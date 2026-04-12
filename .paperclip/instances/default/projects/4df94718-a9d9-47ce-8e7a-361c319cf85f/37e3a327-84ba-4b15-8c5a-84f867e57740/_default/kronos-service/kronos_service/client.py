"""Lightweight HTTP client for strategies to call the Kronos forecast service.

Strategies import this instead of loading the Kronos model directly:

    from kronos_service.client import KronosClient

    client = KronosClient()  # defaults to http://localhost:8777
    result = client.forecast("BTCUSDT", ohlcv_df, pred_len=24, timeframe="1h")
    print(result.regime, result.vol_forecast, result.direction_confidence)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger("kronos_service.client")

DEFAULT_URL = "http://localhost:8777"


@dataclass
class RegimeInfo:
    regime: str                  # "trending_up", "trending_down", "mean_reverting", "volatile"
    vol_forecast: float          # annualized vol
    direction_confidence: float  # 0-1


@dataclass
class ForecastResult:
    symbol: str
    timeframe: str
    regime: RegimeInfo
    forecast_df: pd.DataFrame    # columns: open, high, low, close (+ volume if available)
    sample_count: int
    cached: bool
    generated_at: float


class KronosClient:
    """HTTP client for the Kronos forecast service."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base_url = (base_url or os.getenv("KRONOS_URL", DEFAULT_URL)).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def health(self) -> dict:
        resp = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def forecast(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        pred_len: int = 24,
        timeframe: str = "1h",
        temperature: float = 1.0,
        top_p: float = 0.9,
        cache_ttl: Optional[float] = None,
    ) -> ForecastResult:
        """Request forecast from the Kronos service.

        Args:
            symbol: Asset symbol (e.g. "BTCUSDT")
            ohlcv_df: DataFrame with DatetimeIndex and columns [open, high, low, close]
            pred_len: Forecast horizon in candles
            timeframe: Candle timeframe
            temperature: Sampling temperature
            top_p: Nucleus sampling threshold
            cache_ttl: Optional cache TTL override

        Returns:
            ForecastResult with forecast DataFrame and regime classification
        """
        # Serialize OHLCV to list of dicts
        ohlcv_records = []
        for idx, row in ohlcv_df.iterrows():
            record = {
                "timestamp": str(idx),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            if "volume" in row:
                record["volume"] = float(row["volume"])
            ohlcv_records.append(record)

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "ohlcv": ohlcv_records,
            "pred_len": pred_len,
            "temperature": temperature,
            "top_p": top_p,
        }
        if cache_ttl is not None:
            payload["cache_ttl"] = cache_ttl

        resp = self._session.post(
            f"{self.base_url}/forecast",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse forecast back to DataFrame
        forecast_records = data["forecast"]
        forecast_df = pd.DataFrame(forecast_records)
        if "timestamp" in forecast_df.columns:
            forecast_df["timestamp"] = pd.to_datetime(forecast_df["timestamp"])
            forecast_df = forecast_df.set_index("timestamp")

        regime_data = data["regime"]

        return ForecastResult(
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            regime=RegimeInfo(
                regime=regime_data["regime"],
                vol_forecast=regime_data["vol_forecast"],
                direction_confidence=regime_data["direction_confidence"],
            ),
            forecast_df=forecast_df,
            sample_count=data["sample_count"],
            cached=data["cached"],
            generated_at=data["generated_at"],
        )

    def regime(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        pred_len: int = 24,
        timeframe: str = "1h",
    ) -> RegimeInfo:
        """Lightweight call — returns only regime classification."""
        ohlcv_records = []
        for idx, row in ohlcv_df.iterrows():
            record = {
                "timestamp": str(idx),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            ohlcv_records.append(record)

        resp = self._session.post(
            f"{self.base_url}/regime",
            json={
                "symbol": symbol,
                "timeframe": timeframe,
                "ohlcv": ohlcv_records,
                "pred_len": pred_len,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        r = data["regime"]
        return RegimeInfo(
            regime=r["regime"],
            vol_forecast=r["vol_forecast"],
            direction_confidence=r["direction_confidence"],
        )

    def clear_cache(self, symbol: Optional[str] = None):
        params = {"symbol": symbol} if symbol else {}
        resp = self._session.post(f"{self.base_url}/cache/clear", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
