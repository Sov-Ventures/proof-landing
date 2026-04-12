#!/usr/bin/env python3
"""Examples: how each ZeroPoint strategy integrates with the Kronos service.

Assumes the Kronos service is running on localhost:8777.
Strategies import KronosClient and call it during their scan cycle.
"""

from kronos_service.client import KronosClient
from kronos_service.data_fetchers import fetch_binance_ohlcv

client = KronosClient()  # reads KRONOS_URL env var, defaults to http://localhost:8777


# ── 1. BS IV Arb: Replace static cached IV with Kronos vol forecast ─────────

def bs_iv_arb_with_kronos():
    """Instead of caching tradfi IV for 5 minutes, use Kronos vol forecast
    as a forward-looking volatility estimate. The vol_forecast field gives
    annualized vol from sample path dispersion — plug this into Black-Scholes
    as the sigma parameter."""
    ohlcv = fetch_binance_ohlcv("BTCUSDT", interval="1h", limit=500)
    result = client.forecast("BTCUSDT", ohlcv, pred_len=24, timeframe="1h", temperature=0.8)

    kronos_vol = result.regime.vol_forecast
    regime = result.regime.regime

    # Use kronos_vol instead of deribit_iv in Black-Scholes N(d2) calculation
    # Skip trades during "volatile" regime (high uncertainty = unreliable arb signal)
    print(f"Kronos vol forecast: {kronos_vol:.4f} (annualized)")
    print(f"Regime: {regime}")
    print(f"Direction confidence: {result.regime.direction_confidence:.2f}")

    if regime == "volatile":
        print("SKIP: volatile regime, arb signals unreliable")
        return None

    return kronos_vol


# ── 2. Pair Trading: Regime filter to skip trending periods ─────────────────

def pair_trading_with_kronos(pair_asset: str = "ARBUSDT"):
    """Mean-reversion only works in mean-reverting regimes. Use Kronos regime
    detection to skip entry when the market is trending."""
    ohlcv = fetch_binance_ohlcv(pair_asset, interval="4h", limit=500)
    regime_info = client.regime(pair_asset, ohlcv, pred_len=12, timeframe="4h")

    print(f"{pair_asset} regime: {regime_info.regime}")

    if regime_info.regime in ("trending_up", "trending_down"):
        print("SKIP: trending regime, mean-reversion signals unreliable")
        return False

    return True  # safe to trade mean-reversion


# ── 3. MoE/Allocation: Forward-looking regime weighting ─────────────────────

def moe_allocation_with_kronos():
    """Replace backward-looking Sharpe-based expert gating with forward regime
    weighting. If Kronos says 'trending', allocate more to trend-following
    strategies (BTC weekly pattern). If 'mean_reverting', allocate to pair trading."""
    ohlcv = fetch_binance_ohlcv("BTCUSDT", interval="1d", limit=200)
    result = client.forecast("BTCUSDT", ohlcv, pred_len=7, timeframe="1d")

    weights = {"btc_weekly_pattern": 0.5, "pair_trading": 0.5}  # default equal

    if result.regime.regime in ("trending_up", "trending_down"):
        weights["btc_weekly_pattern"] = 0.7
        weights["pair_trading"] = 0.3
    elif result.regime.regime == "mean_reverting":
        weights["btc_weekly_pattern"] = 0.3
        weights["pair_trading"] = 0.7
    elif result.regime.regime == "volatile":
        weights["btc_weekly_pattern"] = 0.3
        weights["pair_trading"] = 0.3  # reduce both, hold cash

    print(f"Regime: {result.regime.regime} -> weights: {weights}")
    return weights


# ── 4. FLB Strategies: Directional filter + vol-adjusted sizing ─────────────

def flb_with_kronos(symbol: str = "BTCUSDT"):
    """FLB profits from mispricing, not direction. Use Kronos direction_confidence
    as an additional filter: if direction_confidence > 0.7, there's a strong
    directional move expected — adjust position sizing based on vol forecast."""
    ohlcv = fetch_binance_ohlcv(symbol, interval="1d", limit=200)
    result = client.forecast(symbol, ohlcv, pred_len=3, timeframe="1d")

    base_size = 100  # base position size in dollars
    vol = result.regime.vol_forecast

    # Vol-adjusted sizing: reduce size in high-vol, increase in low-vol
    if vol > 0.8:
        size_multiplier = 0.5
    elif vol > 0.5:
        size_multiplier = 0.75
    else:
        size_multiplier = 1.0

    adjusted_size = base_size * size_multiplier
    print(f"Vol={vol:.4f}, size_multiplier={size_multiplier}, position=${adjusted_size:.0f}")
    return adjusted_size


# ── 5. Certainty Sniper: Low-temp confirmation ─────────────────────────────

def certainty_sniper_with_kronos(symbol: str = "BTCUSDT"):
    """For 5/15-min candle markets near expiry. Low temperature forecast
    for high-confidence directional confirmation before entry."""
    ohlcv = fetch_binance_ohlcv(symbol, interval="5m", limit=100)
    result = client.forecast(symbol, ohlcv, pred_len=3, timeframe="5m", temperature=0.5)

    if result.regime.direction_confidence > 0.85:
        direction = "up" if result.regime.regime == "trending_up" else "down"
        print(f"HIGH CONFIDENCE ({result.regime.direction_confidence:.2f}): {direction}")
        return direction
    else:
        print(f"LOW CONFIDENCE ({result.regime.direction_confidence:.2f}): skip")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("KRONOS STRATEGY INTEGRATION EXAMPLES")
    print("=" * 60)

    print("\n1. BS IV Arb")
    bs_iv_arb_with_kronos()

    print("\n2. Pair Trading")
    pair_trading_with_kronos()

    print("\n3. MoE Allocation")
    moe_allocation_with_kronos()

    print("\n4. FLB Sizing")
    flb_with_kronos()

    print("\n5. Certainty Sniper")
    certainty_sniper_with_kronos()
