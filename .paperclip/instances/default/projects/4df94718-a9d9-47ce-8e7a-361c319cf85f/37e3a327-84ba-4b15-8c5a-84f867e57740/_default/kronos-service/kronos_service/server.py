"""FastAPI server — runs KronosForecastService as an HTTP endpoint.

Strategies POST OHLCV data and receive forecasts back without loading the model themselves.

Usage:
    python -m kronos_service.server
    # or
    uvicorn kronos_service.server:app --host 0.0.0.0 --port 8777
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from kronos_service.forecast import KronosForecastService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("kronos_service.server")

app = FastAPI(title="Kronos Forecast Service", version="0.1.0")

# Service singleton — initialized on first request
_service: Optional[KronosForecastService] = None


def _get_service() -> KronosForecastService:
    global _service
    if _service is None:
        _service = KronosForecastService(
            model_name=os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-small"),
            tokenizer_name=os.getenv("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base"),
            cache_ttl=float(os.getenv("KRONOS_CACHE_TTL", "300")),
            device=os.getenv("KRONOS_DEVICE", "cpu"),
        )
    return _service


# ── Request/Response models ──────────────────────────────────────────────────

class OHLCVRow(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class ForecastRequest(BaseModel):
    symbol: str = Field(..., description="Asset symbol, e.g. BTCUSDT")
    timeframe: str = Field(default="1h", description="Candle timeframe: 1h, 4h, 1d")
    ohlcv: list[OHLCVRow] = Field(..., description="Historical OHLCV data")
    pred_len: int = Field(default=24, ge=1, le=168, description="Forecast horizon in candles")
    temperature: float = Field(default=1.0, ge=0.1, le=2.0)
    top_p: float = Field(default=0.9, ge=0.1, le=1.0)
    cache_ttl: Optional[float] = Field(default=None, description="Override cache TTL in seconds")


class RegimeResponse(BaseModel):
    regime: str
    vol_forecast: float
    direction_confidence: float


class ForecastResponse(BaseModel):
    symbol: str
    timeframe: str
    regime: RegimeResponse
    forecast: list[dict]  # list of {timestamp, open, high, low, close, volume}
    sample_count: int
    cached: bool
    generated_at: float


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    svc = _get_service()
    return {"status": "ok", "cache": svc.cache_stats()}


@app.post("/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest):
    svc = _get_service()

    try:
        df = pd.DataFrame([r.model_dump() for r in req.ohlcv])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid OHLCV data: {e}")

    if len(df) < 10:
        raise HTTPException(status_code=400, detail="Need at least 10 OHLCV rows")

    try:
        result = svc.forecast(
            symbol=req.symbol,
            ohlcv_df=df,
            pred_len=req.pred_len,
            timeframe=req.timeframe,
            temperature=req.temperature,
            top_p=req.top_p,
            cache_ttl=req.cache_ttl,
        )
    except Exception as e:
        logger.exception("Forecast failed for %s", req.symbol)
        raise HTTPException(status_code=500, detail=str(e))

    # Serialize forecast DataFrame
    forecast_records = []
    for idx, row in result.forecast_df.iterrows():
        record = {"timestamp": str(idx)}
        record.update(row.to_dict())
        forecast_records.append(record)

    return ForecastResponse(
        symbol=result.symbol,
        timeframe=result.timeframe,
        regime=RegimeResponse(
            regime=result.regime,
            vol_forecast=result.vol_forecast,
            direction_confidence=result.direction_confidence,
        ),
        forecast=forecast_records,
        sample_count=len(result.sample_paths),
        cached=result.cached,
        generated_at=result.generated_at,
    )


@app.post("/regime")
def regime_only(req: ForecastRequest):
    """Lightweight endpoint — returns only regime classification, no full forecast data."""
    resp = forecast(req)
    return {
        "symbol": resp.symbol,
        "regime": resp.regime,
        "cached": resp.cached,
    }


@app.post("/cache/clear")
def clear_cache(symbol: Optional[str] = None):
    svc = _get_service()
    svc.clear_cache(symbol)
    return {"status": "cleared", "symbol": symbol or "all"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("KRONOS_PORT", "8777"))
    uvicorn.run(app, host="0.0.0.0", port=port)
