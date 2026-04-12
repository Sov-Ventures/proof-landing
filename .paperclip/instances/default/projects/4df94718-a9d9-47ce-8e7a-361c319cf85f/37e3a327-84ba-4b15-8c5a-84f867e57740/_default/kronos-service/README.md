# Kronos Forecast Service

Shared forecast service wrapping the [Kronos](https://github.com/shiyu-coder/Kronos) financial time-series foundation model. Provides a centralized HTTP API so ZeroPoint trading strategies can get forecasts, regime classification, and vol estimates without each loading the model independently.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              Kronos Forecast Service                 │
│  ┌───────────────────┐  ┌────────────────────────┐  │
│  │ KronosForecastSvc │  │  FastAPI Server :8777  │  │
│  │  - Model loading  │──│  POST /forecast        │  │
│  │  - Forecast cache │  │  POST /regime          │  │
│  │  - Regime detect  │  │  GET  /health          │  │
│  └───────────────────┘  └────────────────────────┘  │
│            │ vendor/Kronos (git submodule)           │
└─────────────────────────────────────────────────────┘
        ▲          ▲          ▲           ▲
        │          │          │           │
   BS IV Arb  Pair Trade  MoE/Alloc   FLB Strats
   (vol fcast) (regime)   (weights)  (dir+sizing)
```

## Quick Start

```bash
# 1. Clone and setup
./setup.sh

# 2. Start service
export PYTHONPATH=$(pwd)/vendor/Kronos:$PYTHONPATH
python -m kronos_service

# 3. From any strategy, use the client
from kronos_service.client import KronosClient
client = KronosClient()
result = client.forecast("BTCUSDT", ohlcv_df, pred_len=24)
print(result.regime)  # RegimeInfo(regime='mean_reverting', vol_forecast=0.45, ...)
```

## Strategy Integration

| Strategy | Endpoint | Kronos Use | Config |
|----------|----------|------------|--------|
| BS IV Arb | `/forecast` | `vol_forecast` replaces static cached IV | 1h, pred=24, temp=0.8 |
| Pair Trading | `/regime` | Skip trades during trending regime | 4h, pred=12 |
| MoE/Allocation | `/forecast` | Forward regime weighting vs backward Sharpe | 1d, pred=7 |
| FLB (BTC/ETH/SOL) | `/forecast` | Directional filter + vol-adjusted sizing | 1d, pred=3 |
| Certainty Sniper | `/forecast` | High-confidence directional confirmation | 5m, pred=3, temp=0.5 |
| BTC Weekly | `/forecast` | Pattern confirmation via regime | 1d, pred=7 |
| Market Maker | `/forecast` | Vol-aware spread adjustment | 1h, pred=6, temp=0.8 |

See `examples/strategy_integration.py` for working code.

## API

### `POST /forecast`
Full forecast with OHLCV data. Returns predicted candles + regime + vol.

### `POST /regime`
Lightweight — returns only regime classification (trending/mean-reverting/volatile).

### `GET /health`
Service health + cache stats.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KRONOS_URL` | `http://localhost:8777` | Client: service URL |
| `KRONOS_MODEL` | `NeoQuasar/Kronos-small` | Server: HuggingFace model name |
| `KRONOS_TOKENIZER` | `NeoQuasar/Kronos-Tokenizer-base` | Server: tokenizer name |
| `KRONOS_DEVICE` | `cpu` | Server: `cpu` or `cuda:0` |
| `KRONOS_PORT` | `8777` | Server: listen port |
| `KRONOS_CACHE_TTL` | `300` | Server: cache TTL in seconds |
