#!/usr/bin/env python3
"""
BTC Weekly Pattern Bot — Hyperliquid

Strategy (18/18 win rate since 2017):
If by Thursday close, BTC's weekly low has NOT dipped more than 0.25% below
Monday's opening price, the week closes green. Every single time.

Logic:
1. Record Monday 00:00 UTC open price
2. Track the weekly low Mon→Thu
3. Thursday ~23:59 UTC: if weekly_low >= monday_open * 0.9975 → enter long
4. Close position Sunday 23:59 UTC (weekly close)

Execution venue: Hyperliquid (perps)

Requires: hyperliquid-python-sdk, requests, python-dotenv
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ── Configuration ────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("btc_weekly_pattern")

# Hyperliquid
HL_PRIVATE_KEY = os.getenv("HL_PRIVATE_KEY", "")
HL_WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS", "")
HL_MAINNET = os.getenv("HL_MAINNET", "true").lower() == "true"

# Strategy parameters
DIP_THRESHOLD_PCT = float(os.getenv("DIP_THRESHOLD_PCT", "0.25"))  # max dip % below open
POSITION_SIZE_USD = float(os.getenv("POSITION_SIZE_USD", "1000"))  # USD notional per trade
LEVERAGE = int(os.getenv("HL_LEVERAGE", "3"))  # leverage multiplier
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "3.0"))  # stop loss % below entry
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "15.0"))  # take profit % above entry
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "300"))  # seconds between checks
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# State file for persistence across restarts
STATE_FILE = Path(__file__).parent / "btc_weekly_state.json"

# Hyperliquid API endpoints
HL_API_URL = "https://api.hyperliquid.xyz" if HL_MAINNET else "https://api.hyperliquid-testnet.xyz"
HL_INFO_URL = f"{HL_API_URL}/info"
HL_EXCHANGE_URL = f"{HL_API_URL}/exchange"

ASSET = "BTC"  # Hyperliquid ticker


# ── Hyperliquid SDK Integration ─────────────────────────────────────────

def get_hl_clients():
    """Initialize Hyperliquid SDK clients."""
    try:
        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants

        base_url = constants.MAINNET_API_URL if HL_MAINNET else constants.TESTNET_API_URL

        info = Info(base_url, skip_ws=True)
        exchange = None
        if HL_PRIVATE_KEY and not DRY_RUN:
            exchange = Exchange(
                wallet=None,  # will use private key
                base_url=base_url,
                account_address=HL_WALLET_ADDRESS or None,
            )
            # Set up wallet from private key
            from eth_account import Account
            wallet = Account.from_key(HL_PRIVATE_KEY)
            exchange = Exchange(
                wallet=wallet,
                base_url=base_url,
                account_address=HL_WALLET_ADDRESS or None,
            )
        return info, exchange
    except ImportError:
        log.warning("hyperliquid-python-sdk not installed, using REST API fallback")
        return None, None


# ── Price Data ───────────────────────────────────────────────────────────

def get_btc_price_rest() -> Optional[float]:
    """Get current BTC mid price from Hyperliquid REST API."""
    try:
        resp = requests.post(
            HL_INFO_URL,
            json={"type": "allMids"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        mids = resp.json()
        if ASSET in mids:
            return float(mids[ASSET])
        log.error(f"{ASSET} not found in Hyperliquid mids response")
        return None
    except Exception as e:
        log.error(f"Failed to fetch BTC price from Hyperliquid: {e}")
        return None


def get_btc_price(info) -> Optional[float]:
    """Get current BTC price, preferring SDK, falling back to REST."""
    if info:
        try:
            mids = info.all_mids()
            if ASSET in mids:
                return float(mids[ASSET])
        except Exception as e:
            log.warning(f"SDK price fetch failed, trying REST: {e}")
    return get_btc_price_rest()


def get_btc_candles_rest(start_ts_ms: int, end_ts_ms: int, interval: str = "1h") -> list:
    """Fetch BTC candle data from Hyperliquid REST API."""
    try:
        resp = requests.post(
            HL_INFO_URL,
            json={
                "type": "candleSnapshot",
                "req": {
                    "coin": ASSET,
                    "interval": interval,
                    "startTime": start_ts_ms,
                    "endTime": end_ts_ms,
                },
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Failed to fetch candles: {e}")
        return []


# ── Weekly Pattern Logic ─────────────────────────────────────────────────

def get_monday_open_utc() -> datetime:
    """Get the most recent Monday 00:00 UTC."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()  # Monday=0
    monday = now - timedelta(days=days_since_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def get_thursday_close_utc() -> datetime:
    """Get this week's Thursday 23:59 UTC."""
    monday = get_monday_open_utc()
    return monday + timedelta(days=3, hours=23, minutes=59, seconds=59)


def get_sunday_close_utc() -> datetime:
    """Get this week's Sunday 23:59 UTC."""
    monday = get_monday_open_utc()
    return monday + timedelta(days=6, hours=23, minutes=59, seconds=59)


def get_weekly_low_from_candles(monday_ts_ms: int, now_ts_ms: int) -> Optional[float]:
    """Get the lowest price from Monday open to now using hourly candles."""
    candles = get_btc_candles_rest(monday_ts_ms, now_ts_ms, interval="1h")
    if not candles:
        return None
    weekly_low = min(float(c["l"]) for c in candles)
    return weekly_low


def check_pattern(monday_open: float, weekly_low: float) -> bool:
    """
    Check if the weekly pattern has triggered.
    Pattern: weekly low has NOT dipped > 0.25% below Monday open.
    """
    threshold = monday_open * (1 - DIP_THRESHOLD_PCT / 100)
    triggered = weekly_low >= threshold
    dip_pct = ((monday_open - weekly_low) / monday_open) * 100

    log.info(
        f"Pattern check: monday_open=${monday_open:,.2f}, "
        f"weekly_low=${weekly_low:,.2f}, dip={dip_pct:.4f}%, "
        f"threshold={DIP_THRESHOLD_PCT}%, triggered={triggered}"
    )
    return triggered


# ── State Persistence ────────────────────────────────────────────────────

def load_state() -> dict:
    """Load bot state from disk."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Failed to load state: {e}")
    return {}


def save_state(state: dict):
    """Save bot state to disk."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        log.error(f"Failed to save state: {e}")


# ── Trading Execution ────────────────────────────────────────────────────

def get_open_position(info) -> Optional[dict]:
    """Check if we have an open BTC position on Hyperliquid."""
    if not HL_WALLET_ADDRESS:
        return None
    try:
        if info:
            user_state = info.user_state(HL_WALLET_ADDRESS)
        else:
            resp = requests.post(
                HL_INFO_URL,
                json={"type": "clearinghouseState", "user": HL_WALLET_ADDRESS},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            user_state = resp.json()

        for pos in user_state.get("assetPositions", []):
            p = pos.get("position", {})
            if p.get("coin") == ASSET and float(p.get("szi", "0")) != 0:
                return {
                    "size": float(p["szi"]),
                    "entry_price": float(p.get("entryPx", "0")),
                    "unrealized_pnl": float(p.get("unrealizedPnl", "0")),
                    "leverage": float(p.get("leverage", {}).get("value", LEVERAGE)),
                }
        return None
    except Exception as e:
        log.error(f"Failed to check position: {e}")
        return None


def set_leverage(exchange, leverage: int):
    """Set leverage for BTC on Hyperliquid."""
    if DRY_RUN or not exchange:
        log.info(f"[DRY RUN] Would set leverage to {leverage}x")
        return
    try:
        exchange.update_leverage(leverage, ASSET, is_cross=True)
        log.info(f"Set {ASSET} leverage to {leverage}x (cross)")
    except Exception as e:
        log.error(f"Failed to set leverage: {e}")


def place_market_order(exchange, is_buy: bool, size_usd: float, price: float):
    """Place a market order on Hyperliquid."""
    # Calculate size in BTC
    size_btc = size_usd / price
    # Round to Hyperliquid's precision (szDecimals for BTC is typically 5)
    size_btc = round(size_btc, 5)

    side = "buy" if is_buy else "sell"

    if DRY_RUN or not exchange:
        log.info(
            f"[DRY RUN] Would {side} {size_btc:.5f} BTC "
            f"(~${size_usd:,.0f}) at market (~${price:,.2f})"
        )
        return {"status": "dry_run", "side": side, "size": size_btc, "price": price}

    try:
        # Use slippage-tolerant price for market orders
        slippage = 0.005  # 0.5%
        limit_price = price * (1 + slippage) if is_buy else price * (1 - slippage)
        # Round price to nearest tick
        limit_price = round(limit_price, 1)

        result = exchange.market_open(
            ASSET,
            is_buy,
            size_btc,
            limit_price,
            slippage=0.005,
        )
        log.info(f"Order result: {result}")
        return result
    except Exception as e:
        log.error(f"Failed to place {side} order: {e}")
        return None


def close_position(exchange, info):
    """Close any open BTC position."""
    pos = get_open_position(info)
    if not pos or pos["size"] == 0:
        log.info("No open position to close")
        return

    is_buy = pos["size"] < 0  # buy to close short, sell to close long
    price = get_btc_price(info)
    if not price:
        log.error("Cannot close position: failed to get price")
        return

    abs_size_usd = abs(pos["size"]) * price
    side = "buy" if is_buy else "sell"

    if DRY_RUN or not exchange:
        log.info(
            f"[DRY RUN] Would close position: {side} {abs(pos['size']):.5f} BTC "
            f"(~${abs_size_usd:,.0f}), PnL: ${pos['unrealized_pnl']:,.2f}"
        )
        return

    try:
        result = exchange.market_close(ASSET)
        log.info(f"Position closed: {result}")
        return result
    except Exception as e:
        log.error(f"Failed to close position: {e}")


# ── Main Loop ────────────────────────────────────────────────────────────

def run_cycle(info, exchange, state: dict) -> dict:
    """Run one check cycle. Returns updated state."""
    now = datetime.now(timezone.utc)
    monday = get_monday_open_utc()
    thursday_close = get_thursday_close_utc()
    sunday_close = get_sunday_close_utc()

    week_key = monday.strftime("%Y-%m-%d")
    log.info(f"Cycle: {now.isoformat()} | Week of {week_key} | Day={now.strftime('%A')}")

    # Reset state on new week
    if state.get("week_key") != week_key:
        log.info(f"New week detected: {week_key}")
        state = {
            "week_key": week_key,
            "monday_open": None,
            "weekly_low": None,
            "pattern_checked": False,
            "pattern_triggered": False,
            "position_opened": False,
            "position_closed": False,
        }

    # Step 1: Get Monday open price
    if state["monday_open"] is None:
        monday_ts_ms = int(monday.timestamp() * 1000)
        # Fetch the first hourly candle of the week
        candles = get_btc_candles_rest(
            monday_ts_ms, monday_ts_ms + 3600_000, interval="1h"
        )
        if candles:
            state["monday_open"] = float(candles[0]["o"])
            log.info(f"Monday open: ${state['monday_open']:,.2f}")
        else:
            # Fallback: use current price if we're early Monday
            if now.weekday() == 0 and now.hour < 1:
                price = get_btc_price(info)
                if price:
                    state["monday_open"] = price
                    log.info(f"Monday open (live): ${price:,.2f}")
            else:
                log.warning("Could not determine Monday open price")
                save_state(state)
                return state

    monday_open = state["monday_open"]

    # Step 2: Track weekly low
    monday_ts_ms = int(monday.timestamp() * 1000)
    now_ts_ms = int(now.timestamp() * 1000)
    weekly_low = get_weekly_low_from_candles(monday_ts_ms, now_ts_ms)

    if weekly_low is not None:
        state["weekly_low"] = weekly_low
        dip_pct = ((monday_open - weekly_low) / monday_open) * 100
        log.info(
            f"Weekly low: ${weekly_low:,.2f} "
            f"(dip from open: {dip_pct:.4f}%, threshold: {DIP_THRESHOLD_PCT}%)"
        )

        # Early exit check: if already dipped too much, no trade this week
        if weekly_low < monday_open * (1 - DIP_THRESHOLD_PCT / 100):
            log.info("Pattern invalidated early — weekly low breached threshold")
            state["pattern_checked"] = True
            state["pattern_triggered"] = False
            save_state(state)
            return state

    # Step 3: Thursday close check — enter trade if pattern triggered
    if now >= thursday_close and not state["pattern_checked"]:
        if weekly_low is not None:
            triggered = check_pattern(monday_open, weekly_low)
            state["pattern_checked"] = True
            state["pattern_triggered"] = triggered

            if triggered:
                log.info("PATTERN TRIGGERED — entering long position")
                price = get_btc_price(info)
                if price:
                    set_leverage(exchange, LEVERAGE)
                    result = place_market_order(exchange, is_buy=True, size_usd=POSITION_SIZE_USD, price=price)
                    if result:
                        state["position_opened"] = True
                        state["entry_price"] = price
                        state["entry_time"] = now.isoformat()
                        log.info(
                            f"Long opened: ${POSITION_SIZE_USD:,.0f} at ${price:,.2f} "
                            f"({LEVERAGE}x leverage)"
                        )
            else:
                log.info("Pattern NOT triggered this week — no trade")
        else:
            log.warning("Cannot check pattern: weekly low unavailable")

    # Step 4: Sunday close — close position
    if now >= sunday_close and state.get("position_opened") and not state.get("position_closed"):
        log.info("Sunday close — closing position")
        pos = get_open_position(info)
        if pos:
            close_position(exchange, info)
            state["position_closed"] = True
            state["exit_time"] = now.isoformat()
            state["exit_pnl"] = pos.get("unrealized_pnl", 0)
            log.info(f"Position closed. PnL: ${pos.get('unrealized_pnl', 0):,.2f}")
        else:
            log.info("No open position found at Sunday close (may have hit SL/TP)")
            state["position_closed"] = True

    # Step 5: Monitor stop loss / take profit for open positions
    if state.get("position_opened") and not state.get("position_closed"):
        price = get_btc_price(info)
        entry = state.get("entry_price", 0)
        if price and entry:
            pnl_pct = ((price - entry) / entry) * 100
            log.info(f"Position monitor: entry=${entry:,.2f}, now=${price:,.2f}, PnL={pnl_pct:+.2f}%")

            if pnl_pct <= -STOP_LOSS_PCT:
                log.warning(f"STOP LOSS hit ({pnl_pct:.2f}%) — closing position")
                close_position(exchange, info)
                state["position_closed"] = True
                state["exit_time"] = now.isoformat()
                state["exit_reason"] = "stop_loss"

            elif pnl_pct >= TAKE_PROFIT_PCT:
                log.info(f"TAKE PROFIT hit ({pnl_pct:.2f}%) — closing position")
                close_position(exchange, info)
                state["position_closed"] = True
                state["exit_time"] = now.isoformat()
                state["exit_reason"] = "take_profit"

    save_state(state)
    return state


def main():
    """Main entry point — runs the weekly pattern bot."""
    log.info("=" * 60)
    log.info("BTC Weekly Pattern Bot — Hyperliquid")
    log.info(f"  Venue: {'Mainnet' if HL_MAINNET else 'Testnet'}")
    log.info(f"  Dry run: {DRY_RUN}")
    log.info(f"  Position size: ${POSITION_SIZE_USD:,.0f}")
    log.info(f"  Leverage: {LEVERAGE}x")
    log.info(f"  Dip threshold: {DIP_THRESHOLD_PCT}%")
    log.info(f"  Stop loss: {STOP_LOSS_PCT}%")
    log.info(f"  Take profit: {TAKE_PROFIT_PCT}%")
    log.info(f"  Check interval: {CHECK_INTERVAL_SEC}s")
    log.info("=" * 60)

    if not HL_PRIVATE_KEY and not DRY_RUN:
        log.error("HL_PRIVATE_KEY required for live trading. Set DRY_RUN=true or provide key.")
        return

    info, exchange = get_hl_clients()
    state = load_state()

    # Verify connectivity
    price = get_btc_price(info)
    if price:
        log.info(f"Connected — BTC price: ${price:,.2f}")
    else:
        log.error("Failed to connect to Hyperliquid. Check network/config.")
        return

    log.info("Starting main loop (Ctrl+C to stop)...")
    try:
        while True:
            try:
                state = run_cycle(info, exchange, state)
            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)

            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        log.info("Shutting down...")


if __name__ == "__main__":
    main()
