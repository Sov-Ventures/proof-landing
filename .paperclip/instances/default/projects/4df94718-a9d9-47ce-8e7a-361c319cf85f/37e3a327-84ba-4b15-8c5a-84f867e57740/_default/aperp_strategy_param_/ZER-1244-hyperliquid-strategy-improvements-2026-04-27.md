# ZER-1244 Hyperliquid Strategy Improvements (2026-04-27)

## Scope
- Objective: Propose implementation-ready improvements from latest Hyperliquid trading activity.
- Constraint: No production code changes in this task.
- Validation branch: `zer-1122-hl-implementation-ready` (existing strategy validation branch).
- Validation result (last run 2026-04-26): `27 passed, 1 failed` (known: `test_trend_flip_requires_persistence_and_applies_cooldown`).

## Fresh Activity Snapshot (as of 2026-04-27 ~08:00 UTC)

### 14-Day Performance (Apr 13 - Apr 27)
| Strategy | Trades | Wins | Losses | Win Rate | Total PnL (USD) | Avg PnL/Trade (USD) |
|---|---:|---:|---:|---:|---:|---:|
| Grizzly | 39 | 12 | 27 | 30.8% | +$2.33 | +$0.06 |
| Vibe OI | 22 | 9 | 13 | 40.9% | +$0.87 | +$0.04 |
| Hypergrowth | 183 | 90 | 93 | 49.2% | +$52.25 | +$0.29 |

**Key change from ZER-1212 (Apr 26):** All three strategies are now net-positive over 14 days, reversing the 30d negative trend. Hypergrowth flipped strongly positive (+$52.25 vs -$62.73 trailing 30d).

### 30-Day Performance (trailing)
| Strategy | Trades | Wins | Losses | Win Rate | Total PnL (USD) | Avg PnL/Trade (USD) |
|---|---:|---:|---:|---:|---:|---:|
| Grizzly | 132 | 44 | 88 | 33.3% | -$1.96 | -$0.01 |

Grizzly 30d still slightly negative but improving (was -$1.78 at ZER-1212).

### Grizzly Leverage Profile (14d)
| Metric | Value |
|---|---:|
| Avg Leverage | 7.0x |
| Max Leverage | 7.0x |
| Worst Single Trade | -$5.42 |
| Best Single Trade | +$11.57 |

Leverage now capped at 7x (was P95=20x at ZER-1212). This is a material improvement in risk posture.

## Exit-Reason Attribution (14 days)

### Grizzly - Loss Drivers
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| THESIS WEAKENED (4 signals: funding+OI+volume+trend) | 4 | -$8.02 |
| THESIS WEAKENED (2 signals: OI+trend) | 1 | -$0.25 |

**Positive exits:**
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| THESIS WEAKENED (3 signals: funding+volume+trend) | 5 | +$6.38 |
| THESIS KILLED: ETH diverged | 27 | +$3.65 |
| Margin force close | 1 | +$0.48 |

Observation: ETH divergence thesis kills are now net profitable (+$3.65 on 27 trades). The multi-signal weakener group with 4 signals (-$8.02 on 4 trades) is the sole remaining drag.

### Vibe OI - Loss Drivers
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| Max age reached (18.2h) | 1 | -$2.75 |
| SL at -1.5% | 1 | -$1.91 |

**Positive exits:**
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| Max age reached (4.0h) | 14 | +$4.65 |
| Max age reached (4.1h) | 2 | +$0.89 |

Observation: The 4h max-age exit is working well (+$4.65 on 14 trades). The 18.2h outlier (-$2.75) suggests a zombie position slipped through the max age guard.

### Hypergrowth - Loss Drivers
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| auto_reconcile_stale | 1 | -$7.21 |
| drawdown_emergency_close (various tranches) | ~16 | -$14.87 |
| dust_cleanup | 76 | -$1.64 |
| auto_reconcile_orphan | 3 | -$1.00 |

**Positive exits (drawdown closes that captured gains):**
| Exit Reason | Trades | PnL (USD) |
|---|---:|---:|
| drawdown_emergency_close_3of3 | 3 | +$14.45 |
| drawdown_emergency_close_5of7 | 1 | +$10.46 |
| drawdown_emergency_close_4of5 | 6 | +$8.32 |
| drawdown_emergency_close_2of5 | 6 | +$8.00 |

Observation: Drawdown emergency close is now a **net positive contributor** when all tranches are summed. The auto_reconcile_stale (-$7.21) is the single largest loss event.

### Hypergrowth Symbol Concentration (14d)
| Symbol | Trades | Total PnL (USD) | Abs PnL (USD) | Abs PnL Share |
|---|---:|---:|---:|---:|
| W | 20 | +$24.76 | $45.95 | 26.6% |
| HYPE | 10 | -$9.40 | $30.91 | 17.9% |
| SEI | 33 | +$18.68 | $25.32 | 14.7% |
| ZETA | 19 | +$9.19 | $17.63 | 10.2% |
| ONDO | 27 | +$2.82 | $7.84 | 4.5% |
| BERA | 6 | -$1.26 | $6.89 | 4.0% |

W is now the top abs-PnL contributor (26.6%) — below the 30% 96h clamp threshold from ZER-1212 but trending toward it.
HYPE long leg is the largest net loser (-$9.40) while short basket (SEI, W, ZETA) is carrying performance.

---

## Implementation-Ready Improvements

### P0: Hypergrowth - Stale Reconciler Hardening + HYPE Long Leg Guard
**Impact: Recover ~$7-10/14d from stale position losses + reduce HYPE drag**

1. **Stale reconciler max-slippage guard**: The single `auto_reconcile_stale` trade lost -$7.21. Add a maximum slippage threshold (e.g., 0.5%) on stale position close; if slippage exceeds threshold, reduce position in tranches rather than market-close the full amount.
2. **HYPE long conviction decay**: HYPE leg is -$9.40 while short basket is +$55.23. Add a conviction decay factor — if HYPE long PnL trails short basket PnL by >2x over rolling 48h, reduce HYPE allocation by 30% for next 24h.
3. **Concentration clamp activation**: W at 26.6% abs-PnL share is trending toward the 30% threshold. Recommend lowering the 96h clamp trigger from 30% to 25% to catch concentration before it impacts returns.

### P0: Vibe OI - Zombie Position Prevention + Stop Refinement
**Impact: Prevent -$2.75 type outlier losses**

1. **Hard max-age enforcement at 6h**: The 18.2h outlier should never happen. Add a secondary hard-kill at 6h with market order (vs the primary 4h soft exit). This backstops any failure in the primary age check.
2. **Volatility-scaled stops (carry forward from ZER-1212)**: Static -1.5% stop still producing losses. Replace with ATR-scaled stop at 1.5x 15m ATR, floored at -1.0% and capped at -2.5%.
3. **Ghost position reconciliation**: 4 ghost reconcile events (0 PnL) indicate position tracking drift. Add startup reconciliation that verifies all tracked positions exist on-chain before entering new trades.

### P1: Grizzly - 4-Signal Weakener Threshold Refinement
**Impact: Reduce -$8.02 drag from false multi-signal kills**

1. **Raise 4-signal weakener threshold**: Currently kills on 2 groups with 4 signals. The 4-signal weakener group is the *only* net-negative exit path (-$8.02). Require 3 groups (not 2) when 4+ signals fire simultaneously, since multi-signal clustering often indicates noise in choppy markets rather than genuine regime change.
2. **Partial de-risk on first signal cluster**: Instead of full thesis kill, reduce position 50% on first 4-signal cluster, full close only if a second cluster fires within 15 minutes.
3. **Post-kill momentum check**: Before full close, verify price has actually moved >0.3% against position. If price is still within 0.3% of entry, downgrade to partial de-risk.

### P1: Cross-Strategy - Operational Telemetry
1. **Emit structured metrics** for: stale_reconcile_invocations, ghost_position_detections, zombie_age_exits, concentration_clamp_triggers.
2. **Daily PnL attribution summary** per exit-reason category, pushed to Telegram.

## Rollout Sequence
1. **Week 1**: Hypergrowth stale reconciler hardening + HYPE conviction decay (largest single-event loss + systematic HYPE drag)
2. **Week 1**: Vibe OI zombie prevention (simple guard, high impact)
3. **Week 2**: Grizzly 4-signal weakener refinement (requires careful backtesting)
4. **Week 2**: Concentration clamp threshold tightening + telemetry
5. **Week 3**: Vibe OI ATR-scaled stops (needs parameter tuning on historical data)

## Risk Assessment
- All strategies are now 14d net-positive — improvements should preserve this momentum, not disrupt it
- Grizzly leverage capped at 7x (down from P95=20x) — materially safer posture
- Hypergrowth drawdown emergency close system is working as intended (net positive contributor)
- Primary risk: HYPE long leg underperformance vs short basket may indicate fundamental relative value shift

## Evidence Sources
- `/Users/abreckler/Sites/hyperliquid-agent/data/grizzly.db` (queried 2026-04-27)
- `/Users/abreckler/Sites/hyperliquid-agent/data/vibe_oi.db` (queried 2026-04-27)
- `/Users/abreckler/Sites/hyperliquid-agent/data/hypergrowth.db` (queried 2026-04-27)
- `/Users/abreckler/Sites/hyperliquid-agent` (branch: `zer-1122-hl-implementation-ready`)
- Prior analysis: `ZER-1212-hyperliquid-strategy-improvements-2026-04-26.md`
