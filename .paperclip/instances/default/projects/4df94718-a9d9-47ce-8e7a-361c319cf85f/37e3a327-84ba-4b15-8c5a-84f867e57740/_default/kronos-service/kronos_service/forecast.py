"""Core Kronos forecast service — loads model once, caches predictions, serves all strategies.

Architecture:
  - Single model instance (Kronos-small by default, 24.7M params, CPU-capable)
  - Thread-safe forecast cache with configurable TTL per asset
  - OHLCV input from any exchange (Binance, Deribit, CoinGecko, etc.)
  - Probabilistic output: multiple sample paths for regime detection + vol forecasting
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("kronos_service.forecast")

# Kronos imports are deferred to avoid import-time torch load
_kronos_loaded = False
_KronosModel = None
_KronosTokenizer = None
_KronosPredictor = None


def _ensure_kronos_imports():
    """Lazy-load Kronos model classes from the vendored submodule."""
    global _kronos_loaded, _KronosModel, _KronosTokenizer, _KronosPredictor
    if _kronos_loaded:
        return
    try:
        from model import Kronos as KModel
        from model import KronosTokenizer as KTok
        from model import KronosPredictor as KPred

        _KronosModel = KModel
        _KronosTokenizer = KTok
        _KronosPredictor = KPred
        _kronos_loaded = True
    except ImportError:
        raise ImportError(
            "Kronos model not found. Ensure the Kronos submodule is initialized:\n"
            "  git submodule update --init vendor/Kronos\n"
            "Then install: pip install -r vendor/Kronos/requirements.txt"
        )


# ── Cache ────────────────────────────────────────────────────────────────────

DEFAULT_CACHE_TTL = 300  # 5 minutes — reasonable for 1h+ candle forecasts

@dataclass
class _CacheEntry:
    forecast: pd.DataFrame
    sample_paths: Optional[list[pd.DataFrame]]
    created_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


@dataclass
class ForecastResult:
    """Structured forecast output for strategy consumption."""
    symbol: str
    timeframe: str
    forecast_df: pd.DataFrame          # median forecast: open, high, low, close, volume
    sample_paths: list[pd.DataFrame]   # individual sampled paths for uncertainty
    regime: str                        # "trending_up", "trending_down", "mean_reverting", "volatile"
    vol_forecast: float                # annualized vol forecast from sample dispersion
    direction_confidence: float        # 0-1, how confident the directional signal is
    cached: bool = False
    generated_at: float = 0.0


# ── Service ──────────────────────────────────────────────────────────────────

class KronosForecastService:
    """Singleton-style forecast service. Strategies call .forecast() with OHLCV data."""

    def __init__(
        self,
        model_name: str = "NeoQuasar/Kronos-small",
        tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base",
        max_context: int = 512,
        sample_count: int = 50,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.tokenizer_name = tokenizer_name
        self.max_context = max_context
        self.sample_count = sample_count
        self.cache_ttl = cache_ttl
        self.device = device

        self._predictor = None
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()

    def _ensure_model(self):
        """Lazy-load model on first forecast request."""
        if self._predictor is not None:
            return
        with self._init_lock:
            if self._predictor is not None:
                return
            _ensure_kronos_imports()
            logger.info("Loading Kronos model=%s tokenizer=%s device=%s", self.model_name, self.tokenizer_name, self.device)
            tokenizer = _KronosTokenizer.from_pretrained(self.tokenizer_name)
            model = _KronosModel.from_pretrained(self.model_name)
            if self.device != "cpu":
                model = model.to(self.device)
            self._predictor = _KronosPredictor(model, tokenizer, max_context=self.max_context)
            logger.info("Kronos model loaded successfully")

    def _cache_key(self, symbol: str, timeframe: str, pred_len: int) -> str:
        return f"{symbol}:{timeframe}:{pred_len}"

    def _classify_regime(self, sample_paths: list[pd.DataFrame]) -> tuple[str, float, float]:
        """Classify regime from sample path dispersion and trend.

        Returns: (regime_label, vol_forecast_annualized, direction_confidence)
        """
        if not sample_paths:
            return "unknown", 0.0, 0.0

        # Extract final close prices from all paths
        final_closes = []
        initial_closes = []
        for path in sample_paths:
            if "close" in path.columns and len(path) > 0:
                final_closes.append(path["close"].iloc[-1])
                initial_closes.append(path["close"].iloc[0])

        if not final_closes or not initial_closes:
            return "unknown", 0.0, 0.0

        final_arr = np.array(final_closes)
        initial_arr = np.array(initial_closes)
        returns = (final_arr - initial_arr) / initial_arr

        mean_return = float(np.mean(returns))
        std_return = float(np.std(returns))

        # Annualize vol (assume daily timeframe as default, strategies override)
        vol_annualized = std_return * np.sqrt(252)

        # Direction confidence: fraction of paths agreeing on direction
        up_frac = float(np.mean(returns > 0))
        direction_confidence = max(up_frac, 1 - up_frac)

        # Regime classification
        if std_return > 0.03 and direction_confidence < 0.6:
            regime = "volatile"
        elif abs(mean_return) > 0.01 and direction_confidence > 0.65:
            regime = "trending_up" if mean_return > 0 else "trending_down"
        else:
            regime = "mean_reverting"

        return regime, vol_annualized, direction_confidence

    def forecast(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        pred_len: int = 24,
        timeframe: str = "1h",
        timestamps_future: Optional[list] = None,
        temperature: float = 1.0,
        top_p: float = 0.9,
        cache_ttl: Optional[float] = None,
    ) -> ForecastResult:
        """Generate forecast for a symbol given OHLCV history.

        Args:
            symbol: Asset symbol (e.g. "BTCUSDT", "ETHUSDT", "SOL")
            ohlcv_df: DataFrame with columns [open, high, low, close] (+ optional volume, amount).
                      Index should be DatetimeIndex or have a 'timestamp' column.
            pred_len: Number of future periods to forecast
            timeframe: Candle timeframe ("1h", "4h", "1d", etc.) — used for cache key + vol annualization
            timestamps_future: Optional explicit future timestamps
            temperature: Sampling temperature (higher = more diverse paths)
            top_p: Nucleus sampling threshold
            cache_ttl: Override default cache TTL for this request

        Returns:
            ForecastResult with median forecast, sample paths, regime, vol, and direction confidence
        """
        ttl = cache_ttl if cache_ttl is not None else self.cache_ttl
        cache_key = self._cache_key(symbol, timeframe, pred_len)

        # Check cache
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.expired:
                regime, vol, confidence = self._classify_regime(entry.sample_paths or [])
                return ForecastResult(
                    symbol=symbol,
                    timeframe=timeframe,
                    forecast_df=entry.forecast,
                    sample_paths=entry.sample_paths or [],
                    regime=regime,
                    vol_forecast=vol,
                    direction_confidence=confidence,
                    cached=True,
                    generated_at=entry.created_at,
                )

        # Generate fresh forecast
        self._ensure_model()

        required_cols = {"open", "high", "low", "close"}
        if not required_cols.issubset(set(ohlcv_df.columns)):
            raise ValueError(f"ohlcv_df must have columns {required_cols}, got {set(ohlcv_df.columns)}")

        # Extract timestamps
        if isinstance(ohlcv_df.index, pd.DatetimeIndex):
            x_timestamps = ohlcv_df.index.tolist()
        elif "timestamp" in ohlcv_df.columns:
            x_timestamps = pd.to_datetime(ohlcv_df["timestamp"]).tolist()
        else:
            x_timestamps = list(range(len(ohlcv_df)))

        # Generate future timestamps if not provided
        if timestamps_future is None and isinstance(x_timestamps[0], pd.Timestamp):
            freq = pd.infer_freq(x_timestamps[-10:]) or "h"
            last_ts = x_timestamps[-1]
            timestamps_future = pd.date_range(start=last_ts, periods=pred_len + 1, freq=freq)[1:].tolist()

        logger.info("Generating forecast for %s (%s, pred_len=%d, samples=%d)", symbol, timeframe, pred_len, self.sample_count)

        result_df = self._predictor.predict(
            df=ohlcv_df[list(required_cols)].copy(),
            x_timestamp=x_timestamps,
            y_timestamp=timestamps_future,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=self.sample_count,
        )

        # Generate individual sample paths for uncertainty quantification
        sample_paths = []
        for _ in range(min(self.sample_count, 20)):  # cap stored paths at 20
            path = self._predictor.predict(
                df=ohlcv_df[list(required_cols)].copy(),
                x_timestamp=x_timestamps,
                y_timestamp=timestamps_future,
                pred_len=pred_len,
                T=temperature,
                top_p=top_p,
                sample_count=1,
            )
            sample_paths.append(path)

        # Cache
        now = time.time()
        with self._lock:
            self._cache[cache_key] = _CacheEntry(
                forecast=result_df,
                sample_paths=sample_paths,
                created_at=now,
                ttl=ttl,
            )

        regime, vol, confidence = self._classify_regime(sample_paths)
        logger.info("Forecast complete for %s: regime=%s vol=%.4f confidence=%.2f", symbol, regime, vol, confidence)

        return ForecastResult(
            symbol=symbol,
            timeframe=timeframe,
            forecast_df=result_df,
            sample_paths=sample_paths,
            regime=regime,
            vol_forecast=vol,
            direction_confidence=confidence,
            cached=False,
            generated_at=now,
        )

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear forecast cache, optionally for a specific symbol."""
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache if k.startswith(f"{symbol}:")]
                for k in keys_to_remove:
                    del self._cache[k]

    def cache_stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            total = len(self._cache)
            expired = sum(1 for e in self._cache.values() if e.expired)
            return {"total_entries": total, "expired": expired, "active": total - expired}
