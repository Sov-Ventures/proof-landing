"""Exchange data fetchers — pull OHLCV into the format Kronos expects.

Each fetcher returns a pd.DataFrame with DatetimeIndex and columns:
  open, high, low, close, volume
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger("kronos_service.data_fetchers")


def fetch_binance_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 500,
) -> pd.DataFrame:
    """Fetch OHLCV candles from Binance spot API."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for candle in raw:
        rows.append({
            "timestamp": pd.Timestamp(candle[0], unit="ms", tz="UTC"),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    df = pd.DataFrame(rows).set_index("timestamp")
    return df


def fetch_coingecko_ohlcv(
    coin_id: str = "bitcoin",
    vs_currency: str = "usd",
    days: int = 30,
) -> pd.DataFrame:
    """Fetch OHLC from CoinGecko (free tier, limited resolution)."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": vs_currency, "days": days}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for candle in raw:
        rows.append({
            "timestamp": pd.Timestamp(candle[0], unit="ms", tz="UTC"),
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": 0.0,
        })

    df = pd.DataFrame(rows).set_index("timestamp")
    return df


def fetch_deribit_ohlcv(
    instrument: str = "BTC-PERPETUAL",
    resolution: str = "60",
    count: int = 500,
) -> pd.DataFrame:
    """Fetch OHLCV from Deribit (crypto derivatives)."""
    import time

    end_ts = int(time.time() * 1000)
    start_ts = end_ts - (count * int(resolution) * 60 * 1000)

    url = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
    params = {
        "instrument_name": instrument,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "resolution": resolution,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("result", {})

    if not data or "ticks" not in data:
        raise ValueError(f"No data returned from Deribit for {instrument}")

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(data["ticks"], unit="ms", utc=True),
        "open": data["open"],
        "high": data["high"],
        "low": data["low"],
        "close": data["close"],
        "volume": data["volume"],
    }).set_index("timestamp")

    return df
