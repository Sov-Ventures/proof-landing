#!/usr/bin/env python3
"""
Polymarket Copytrader — mirrors trades from a target wallet.

Monitors a target trader's activity via the Polymarket Data API and
replicates their trades on your account using the CLOB API.

Usage:
    python copytrader.py                    # uses .env config
    python copytrader.py --dry-run          # force dry run
    python copytrader.py --target 0x...     # override target wallet

Requires: py-clob-client, python-dotenv, requests
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

# ── Configuration ────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("copytrader")

# API endpoints
CLOB_HOST = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
GAMMA_HOST = os.getenv("GAMMA_HOST", "https://gamma-api.polymarket.com")
DATA_API_HOST = os.getenv("DATA_API_HOST", "https://data-api.polymarket.com")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))

# Wallet
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# Target trader
TARGET_WALLET = os.getenv("TARGET_WALLET", "")

# Copy parameters
COPY_MODE = os.getenv("COPY_MODE", "fixed")  # "fixed" or "proportional"
FIXED_ORDER_SIZE_USD = float(os.getenv("FIXED_ORDER_SIZE_USD", "50"))
PROPORTIONAL_FACTOR = float(os.getenv("PROPORTIONAL_FACTOR", "0.1"))  # 10% of target's size
MAX_ORDER_SIZE_USD = float(os.getenv("MAX_ORDER_SIZE_USD", "500"))
MIN_ORDER_SIZE_USD = float(os.getenv("MIN_ORDER_SIZE_USD", "5"))
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.03"))  # 3 cents max slippage from target price

# Timing
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "15"))
TRADE_STALENESS_SEC = int(os.getenv("TRADE_STALENESS_SEC", "300"))  # ignore trades older than 5 min

# Safety
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# State file to persist last-seen trade ID across restarts
STATE_FILE = Path(__file__).parent / ".copytrader_state.json"


# ── Data Types ───────────────────────────────────────────────────────────

@dataclass
class TargetTrade:
    """A trade made by the target wallet."""
    trade_id: str
    timestamp: str  # ISO format
    asset_id: str  # token_id
    condition_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float  # number of shares
    market_slug: str
    outcome: str  # "Yes" or "No"
    title: str  # market question


@dataclass
class Stats:
    """Runtime statistics."""
    polls: int = 0
    new_trades_seen: int = 0
    trades_copied: int = 0
    trades_skipped: int = 0
    total_volume_usd: float = 0.0
    errors: int = 0
    start_time: float = field(default_factory=time.time)


# ── Target Trader Monitor ────────────────────────────────────────────────

class TraderMonitor:
    """Monitors a target wallet's trades via the Polymarket Data API."""

    def __init__(self, wallet: str):
        self.wallet = wallet.lower()
        self._last_seen_id: Optional[str] = None
        self._load_state()

    def _load_state(self):
        """Load last-seen trade ID from state file."""
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                self._last_seen_id = state.get(self.wallet)
                if self._last_seen_id:
                    log.info(f"Resumed from trade ID: {self._last_seen_id}")
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_state(self):
        """Persist last-seen trade ID."""
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
            except json.JSONDecodeError:
                pass
        state[self.wallet] = self._last_seen_id
        STATE_FILE.write_text(json.dumps(state, indent=2))

    def fetch_recent_trades(self, limit: int = 50) -> list[TargetTrade]:
        """Fetch recent trades for the target wallet."""
        try:
            resp = requests.get(
                f"{DATA_API_HOST}/trades",
                params={"user": self.wallet, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            raw_trades = resp.json()
        except Exception as e:
            log.error(f"Failed to fetch trades for {self.wallet}: {e}")
            return []

        trades = []
        for t in raw_trades:
            try:
                trades.append(TargetTrade(
                    trade_id=str(t.get("id", t.get("tradeId", ""))),
                    timestamp=t.get("timestamp", t.get("matchTime", "")),
                    asset_id=t.get("asset_id", t.get("assetId", "")),
                    condition_id=t.get("conditionId", t.get("market", "")),
                    side=t.get("side", "BUY").upper(),
                    price=float(t.get("price", 0)),
                    size=float(t.get("size", 0)),
                    market_slug=t.get("market_slug", t.get("slug", "")),
                    outcome=t.get("outcome", t.get("outcomeName", "")),
                    title=t.get("title", t.get("question", "")),
                ))
            except (ValueError, TypeError) as e:
                log.warning(f"Skipping malformed trade: {e}")
                continue

        return trades

    def get_new_trades(self) -> list[TargetTrade]:
        """Return only trades we haven't seen yet, newest first."""
        all_trades = self.fetch_recent_trades()
        if not all_trades:
            return []

        new_trades = []
        for trade in all_trades:
            if trade.trade_id == self._last_seen_id:
                break
            new_trades.append(trade)

        if new_trades:
            self._last_seen_id = new_trades[0].trade_id
            self._save_state()
            log.info(f"Found {len(new_trades)} new trade(s) from target")

        # Return oldest-first so we replay in order
        return list(reversed(new_trades))

    def initialize_cursor(self):
        """Set the cursor to the most recent trade so we only copy future trades."""
        trades = self.fetch_recent_trades(limit=1)
        if trades:
            self._last_seen_id = trades[0].trade_id
            self._save_state()
            log.info(
                f"Initialized cursor at trade {self._last_seen_id} "
                f"— will only copy future trades"
            )
        else:
            log.info("No existing trades found for target — will copy from first trade")


# ── Order Execution ──────────────────────────────────────────────────────

class CopyExecutor:
    """Executes copy trades on Polymarket CLOB."""

    def __init__(self, client: ClobClient):
        self.client = client

    def get_market_price(self, token_id: str, side: str) -> Optional[float]:
        """Get current best price for a token."""
        try:
            book = self.client.get_order_book(token_id)
            if side == "BUY":
                asks = book.asks if hasattr(book, "asks") else []
                if asks:
                    return float(min(a.price for a in asks))
            else:
                bids = book.bids if hasattr(book, "bids") else []
                if bids:
                    return float(max(b.price for b in bids))
        except Exception as e:
            log.warning(f"Failed to get order book for {token_id}: {e}")
        return None

    def calculate_copy_size(self, target_trade: TargetTrade) -> float:
        """Calculate our order size based on copy mode."""
        target_usd = target_trade.size * target_trade.price

        if COPY_MODE == "proportional":
            size_usd = target_usd * PROPORTIONAL_FACTOR
        else:
            size_usd = FIXED_ORDER_SIZE_USD

        # Clamp to limits
        size_usd = max(MIN_ORDER_SIZE_USD, min(MAX_ORDER_SIZE_USD, size_usd))
        return size_usd

    def execute_copy(self, trade: TargetTrade) -> Optional[dict]:
        """Execute a copy of the target's trade."""
        side = BUY if trade.side == "BUY" else SELL
        size_usd = self.calculate_copy_size(trade)

        # Get current market price
        current_price = self.get_market_price(trade.asset_id, trade.side)
        if current_price is None:
            log.warning(f"Cannot get price for {trade.asset_id} — skipping")
            return None

        # Check slippage
        slippage = abs(current_price - trade.price)
        if slippage > MAX_SLIPPAGE:
            log.warning(
                f"Slippage too high: target @ ${trade.price:.4f}, "
                f"current @ ${current_price:.4f} (diff ${slippage:.4f}) — skipping"
            )
            return None

        # Use current market price for our order
        order_price = current_price
        # Clamp price to valid range
        order_price = max(0.01, min(0.99, round(order_price, 2)))

        # Calculate shares from USD amount
        shares = size_usd / order_price

        if DRY_RUN:
            log.info(
                f"[DRY RUN] Would {trade.side} {shares:.2f} shares @ "
                f"${order_price:.4f} (${size_usd:.2f}) — "
                f"{trade.title} [{trade.outcome}]"
            )
            return {"dry_run": True, "price": order_price, "size": shares, "side": trade.side}

        try:
            order_args = OrderArgs(
                token_id=trade.asset_id,
                price=order_price,
                size=shares,
                side=side,
            )
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order, OrderType.GTC)
            log.info(
                f"Order placed: {trade.side} {shares:.2f} @ ${order_price:.4f} "
                f"(${size_usd:.2f}) — {trade.title} [{trade.outcome}] → {resp}"
            )
            return resp
        except Exception as e:
            log.error(f"Order failed: {e}")
            return None


# ── Main Bot ─────────────────────────────────────────────────────────────

class CopyTraderBot:
    """
    Main bot: poll target wallet, detect new trades, mirror them.
    """

    def __init__(self, target_wallet: str, dry_run: bool = True):
        self.target_wallet = target_wallet
        self.dry_run = dry_run
        self.monitor = TraderMonitor(target_wallet)
        self.stats = Stats()
        self.client: Optional[ClobClient] = None
        self.executor: Optional[CopyExecutor] = None

    def init_client(self):
        """Initialize Polymarket CLOB client."""
        if not PRIVATE_KEY:
            log.warning("No PRIVATE_KEY set — running in monitor-only mode")
            return

        self.client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=PRIVATE_KEY,
            signature_type=0,
        )

        # Load or derive API credentials
        creds_path = Path(__file__).parent / ".api_credentials.json"
        if creds_path.exists():
            with open(creds_path) as f:
                creds = json.load(f)
            self.client.set_api_creds(ApiCreds(
                api_key=creds["apiKey"],
                api_secret=creds["secret"],
                api_passphrase=creds["passphrase"],
            ))
            log.info("Loaded API credentials from file")
        else:
            try:
                creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(creds)
                log.info("Derived API credentials")
            except Exception as e:
                log.error(f"Failed to derive API creds: {e}")
                return

        self.executor = CopyExecutor(self.client)
        log.info("CLOB client initialized")

    def is_trade_fresh(self, trade: TargetTrade) -> bool:
        """Check if a trade is recent enough to copy."""
        try:
            trade_time = datetime.fromisoformat(
                trade.timestamp.replace("Z", "+00:00")
            )
            age_sec = (datetime.now(timezone.utc) - trade_time).total_seconds()
            return age_sec < TRADE_STALENESS_SEC
        except (ValueError, TypeError):
            # If we can't parse timestamp, accept it (it was new to us)
            return True

    def process_new_trades(self):
        """Poll for new trades and copy them."""
        self.stats.polls += 1
        new_trades = self.monitor.get_new_trades()

        for trade in new_trades:
            self.stats.new_trades_seen += 1

            # Skip stale trades
            if not self.is_trade_fresh(trade):
                log.info(f"Skipping stale trade: {trade.trade_id}")
                self.stats.trades_skipped += 1
                continue

            log.info(
                f"Copying: {trade.side} {trade.size:.2f} @ ${trade.price:.4f} "
                f"— {trade.title} [{trade.outcome}]"
            )

            if not self.executor:
                log.info("[MONITOR] No executor — trade logged only")
                self.stats.trades_skipped += 1
                continue

            result = self.executor.execute_copy(trade)
            if result:
                self.stats.trades_copied += 1
                size_usd = self.executor.calculate_copy_size(trade)
                self.stats.total_volume_usd += size_usd
            else:
                self.stats.trades_skipped += 1

    def print_stats(self):
        """Print runtime statistics."""
        elapsed = time.time() - self.stats.start_time
        log.info(
            f"Stats: {elapsed:.0f}s | "
            f"{self.stats.polls} polls | "
            f"{self.stats.new_trades_seen} seen | "
            f"{self.stats.trades_copied} copied | "
            f"{self.stats.trades_skipped} skipped | "
            f"${self.stats.total_volume_usd:.2f} volume"
        )

    def run(self):
        """Main bot loop."""
        log.info("=" * 60)
        log.info("Polymarket Copytrader starting")
        log.info(f"  Target: {self.target_wallet}")
        log.info(f"  DRY_RUN: {self.dry_run}")
        log.info(f"  Copy mode: {COPY_MODE}")
        if COPY_MODE == "fixed":
            log.info(f"  Fixed size: ${FIXED_ORDER_SIZE_USD}")
        else:
            log.info(f"  Proportional factor: {PROPORTIONAL_FACTOR}")
        log.info(f"  Max order: ${MAX_ORDER_SIZE_USD}")
        log.info(f"  Max slippage: ${MAX_SLIPPAGE}")
        log.info(f"  Poll interval: {POLL_INTERVAL_SEC}s")
        log.info(f"  Staleness window: {TRADE_STALENESS_SEC}s")
        log.info("=" * 60)

        self.init_client()

        # Initialize cursor to only copy future trades
        self.monitor.initialize_cursor()

        cycle = 0
        try:
            while True:
                cycle += 1
                self.process_new_trades()

                if cycle % 20 == 0:
                    self.print_stats()

                time.sleep(POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            self.print_stats()


# ── Wallet Resolution Helper ────────────────────────────────────────────

def resolve_wallet_from_profile(username: str) -> Optional[str]:
    """
    Attempt to resolve a Polymarket username to a wallet address.
    Uses the Gamma API profile endpoint.
    """
    # Try profile API
    try:
        resp = requests.get(
            f"{GAMMA_HOST}/profiles",
            params={"username": username.lstrip("@")},
            timeout=10,
        )
        if resp.status_code == 200:
            profiles = resp.json()
            if profiles and isinstance(profiles, list) and len(profiles) > 0:
                addr = profiles[0].get("address") or profiles[0].get("proxyWallet")
                if addr:
                    log.info(f"Resolved @{username} → {addr}")
                    return addr
    except Exception as e:
        log.warning(f"Profile resolution failed: {e}")

    # Try direct user search
    try:
        resp = requests.get(
            f"https://polymarket.com/api/profile/{username.lstrip('@')}",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get("address") or data.get("proxyWallet")
            if addr:
                log.info(f"Resolved @{username} → {addr}")
                return addr
    except Exception as e:
        log.debug(f"Direct profile lookup failed: {e}")

    return None


# ── Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Polymarket Copytrader")
    parser.add_argument("--target", help="Target wallet address or @username")
    parser.add_argument("--dry-run", action="store_true", help="Force dry run mode")
    parser.add_argument(
        "--resolve-only", action="store_true",
        help="Just resolve username to wallet and exit",
    )
    args = parser.parse_args()

    target = args.target or TARGET_WALLET
    if not target:
        log.error(
            "No target wallet specified. Set TARGET_WALLET in .env "
            "or use --target 0x... or --target @username"
        )
        return

    # Resolve username to wallet if needed
    if target.startswith("@") or not target.startswith("0x"):
        log.info(f"Resolving username: {target}")
        wallet = resolve_wallet_from_profile(target)
        if not wallet:
            log.error(
                f"Could not resolve '{target}' to a wallet address. "
                f"Please provide the wallet address directly with --target 0x..."
            )
            return
        target = wallet

    if args.resolve_only:
        print(f"Resolved wallet: {target}")
        return

    global DRY_RUN
    if args.dry_run:
        DRY_RUN = True

    bot = CopyTraderBot(target_wallet=target, dry_run=DRY_RUN)
    bot.run()


if __name__ == "__main__":
    main()
