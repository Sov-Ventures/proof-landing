# Hyperliquid Strategy Improvement Analysis — ZER-870 Cycle (2026-04-29)

**Analyst:** Gamma (Portfolio Analyst)
**Data window:** 30-day trailing (2026-03-30 to 2026-04-29)
**Strategies covered:** Grizzly, Vibe OI, Hypergrowth, BTC Weekly

---

## Executive Summary

All four Hyperliquid strategies are either losing money or inactive over the trailing 30 days. Combined realized PnL is approximately **-$120** across 663 closed trades. The primary drags are:

1. **Hypergrowth HYPE long leg:** -$99.34 on 451 trades (dominates total loss)
2. **Vibe OI shorts:** -$11.04 on 30 trades (36.7% WR vs 53.3% for longs)
3. **Grizzly 4h trend-flip exits:** -$7.15 on 15 trades (worst exit reason)
4. **BTC Weekly:** completely inactive (0 trades in 30 days)

---

## Strategy-by-Strategy Analysis

### 1. Grizzly (BTC Momentum)

| Metric | Longs | Shorts | Total |
|--------|-------|--------|-------|
| Trades | 80 | 57 | 137 |
| PnL | +$7.57 | -$14.79 | -$7.22 |
| Avg Hold | 163 min | 50 min | — |
| Win Rate | — | — | 33.6% |

**Key findings:**

- **ETH correlation kill is the dominant exit** (51/137 trades = 37%), but its aggregate PnL is near-zero (+$0.37). It's a noise exit — triggering frequently without protecting against real losses, just churning capital.
- **4h trend-flip kills** (-$7.15 on 15 trades, avg -$0.48) are the actual loss driver. These are exiting at the worst time — after holding long enough to accumulate loss but before recovery.
- **Shorts completely disabled** (`allow_shorts: false`) yet longs have been negative for 2 straight weeks (W16: -$2.05, W17: -$4.87). The strategy has no hedge in a ranging/slightly-bearish market.
- **Equity bleeding:** $506.69 -> $488.54 in 14 days (-3.6%).

**Proposed improvements:**

#### 1A. Relax ETH correlation filter (config change)
```yaml
# grizzly.yaml — data section
eth_correlation_min: 0.35     # was 0.5 — too aggressive, killing 37% of trades for near-zero edge
eth_correlation_window: 48    # was 24 — use 48h window for more stable correlation signal
```
**Rationale:** 51 trades killed by ETH divergence with +$0.37 net = pure churn. Relaxing to 0.35 and widening the window should cut false kills by ~60% while still catching genuine decouplings.

#### 1B. Add grace period to 4h trend-flip exit
```yaml
# grizzly.yaml — riding section (new parameter)
trend_flip_grace_sec: 900     # 15-min grace before acting on 4h trend flip
```
**Rationale:** The 4h candle trend flip is the worst-performing exit at -$0.48/trade. A 15-min grace period would filter out wick-driven false flips while still exiting genuine reversals. Existing `thesis_grace_sec` of 3600 applies to other signals but the 4h flip currently fires immediately.

#### 1C. Re-evaluate short leg with tighter conviction
```yaml
# grizzly.yaml — entry section
allow_shorts: true
short_min_conviction: 0.80    # was 0.70; only take high-conviction shorts
short_convergence_threshold: 0.90  # was 0.85; near-unanimity required
```
**Rationale:** Longs-only is bleeding in a range-bound BTC market ($74K-$78K over the last 2 weeks). Selective shorts with very high conviction could hedge the long bleed. The existing `performance_guard` with `guard_shorts: true` adds a safety net.

---

### 2. Vibe OI (BTC Momentum — OI-based)

| Metric | Longs | Shorts | Total |
|--------|-------|--------|-------|
| Trades | 45 | 30 | 75 |
| PnL | -$2.26 | -$11.04 | -$13.31 |
| Win Rate | 53.3% | 36.7% | 46.7% |

**Key findings:**

- **73% of trades exit at max age** (55/75) — TP (3%) and SL (1.5%) rarely hit. The strategy is mostly just holding for 4 hours and taking whatever PnL results.
- **Shorts are the entire drag:** -$11.04 on 30 trades vs -$2.26 on 45 longs. Short win rate is 36.7%.
- **Appears inactive since April 20** — last real trade was 9 days ago. Ghost reconciliation entries on Apr 20 suggest position tracking issues.
- **18.2h zombie position** on Apr 19-20 with -$2.75 PnL despite 4h max age — reconciler didn't catch it promptly.

**Proposed improvements:**

#### 2A. Disable shorts (same pattern as Grizzly)
```yaml
# vibe_oi.yaml — add to entry section
allow_shorts: false           # shorts have -$11.04 on 36.7% WR; longs are near break-even
```
**Rationale:** Shorts account for 83% of total losses with a 36.7% win rate. Disabling them immediately eliminates the main drag.

#### 2B. Reduce TP target and add trailing stop
```yaml
# vibe_oi.yaml — risk section
take_profit_pct: 0.02         # was 0.03; 2% more achievable in 4h window
trailing_stop_enabled: true   # NEW: add trailing stop to capture partial profits
trailing_stop_pct: 0.008      # trail at 0.8% from high
```
**Rationale:** 3% TP in a 4h window at 3-5x leverage is rarely achievable in the current vol regime. 73% of trades just expire. A 2% target + trailing stop would convert more max-age exits into realized winners.

#### 2C. Fix reconciliation gap
```yaml
# vibe_oi.yaml — execution section
onchain_reconcile_interval_sec: 1800  # was 3600; check every 30 min
max_position_age_sec: 14400           # keep at 4h but verify reconciler honors it
```
**Rationale:** The 18.2h zombie position suggests the reconciler missed a stale position. Halving the interval to 30 min would catch ghosts faster.

---

### 3. Hypergrowth (HYPE Long + Alt Short Basket)

| Component | Trades | PnL |
|-----------|--------|-----|
| HYPE Long | 451 | -$99.34 |
| Short Basket | 361 | +$42.12 |
| **Net** | **812** | **-$57.22** |

**Key findings:**

- **HYPE long is a catastrophic drag** at -$99.34 on 451 trades (-$0.22/trade avg). This single leg accounts for 174% of total losses.
- **Short basket is actually working:** W (+$23.61), SEI (+$12.95), BERA (+$4.47), ONDO (+$4.49) are strong performers.
- **Worst short basket names:** JUP (-$2.22), MORPHO (-$1.52), ATOM (-$1.27), STRK (-$1.05) — relatively contained losses.
- The strategy is profitable if you remove the HYPE long entirely.

**Proposed improvements:**

#### 3A. Reduce HYPE allocation to minimum / pause long leg
```yaml
# hypergrowth.yaml — long_leg section
base_allocation: 0.20         # was 0.25; cut to floor
entry_rsi_max: 55             # was 62; much pickier entries
stop_loss_pct: 0.04           # was 0.06; tighter stop to limit per-trade damage
reentry_cooldown_hours: 24    # was 12; slow the cadence
```
**Rationale:** HYPE has been the primary drag for the entire strategy. Cutting allocation to floor, tightening entry filter, tightening stop, and doubling cooldown should halve the long leg's trade count and loss per trade while the short basket continues generating alpha.

#### 3B. Prune underperforming short basket names
```yaml
# hypergrowth.yaml — short_leg.universe: remove JUP, MORPHO, STRK, NEAR
universe:
  - SEI        # +$12.95
  - ASTER      # +$1.75
  - ZETA       # -$0.74 (marginal, keep for diversification)
  - ONDO       # +$4.49
  - ATOM       # -$1.27 (marginal, keep for sector balance)
  - BLUR       # +$0.59
  - OP         # +$0.09
  - PENDLE     # +$0.88
  - W          # +$23.61
  - APT        # -$0.27
  - BERA       # +$4.47
```
Remove: JUP, MORPHO, STRK, NEAR (not currently in universe but may have been traded via residual).

#### 3C. Boost short basket allocation when HYPE is idle
```yaml
# hypergrowth.yaml — risk section
idle_long_short_boost: 1.20   # was 1.00; let short basket run at 120% when HYPE is idle
```
**Rationale:** The short basket is where the edge is. When HYPE long is idle (cooldown or filters blocking entry), let the short basket expand to capture more alpha.

---

### 4. BTC Weekly

**0 trades in 30 days.** Strategy is either not running or conditions never triggered.

**Proposed improvement:**

#### 4A. Investigate whether the bot process is alive
- Check if `run.py` with `btc_weekly` config is actually running
- Verify wallet balance and `min_account_value` threshold
- The `dip_threshold_pct: 0.25` may be too tight — BTC hasn't had a >0.25% dip below Monday open consistently in recent weeks of mostly-sideways action

```yaml
# btc_weekly.yaml — entry section
dip_threshold_pct: 0.50       # was 0.25; widen to catch shallower pullbacks
position_size_pct: 0.08       # was 0.10; slightly smaller given wider entry range
```

---

## Priority Ranking

| Priority | Change | Expected Impact | Risk |
|----------|--------|-----------------|------|
| **P0** | 3A: Reduce HYPE long allocation | Stop $99 bleed | Low — short basket compensates |
| **P0** | 2A: Disable Vibe OI shorts | Stop $11 short drag | Low — longs near break-even |
| **P1** | 1A: Relax Grizzly ETH correlation | Reduce 37% churn exits | Medium — may hold into real losses |
| **P1** | 1B: 4h trend-flip grace period | Reduce -$7.15 4h flip loss | Medium — delayed exits |
| **P2** | 2B: Lower TP + trailing stop | Convert max-age exits to wins | Medium — needs code change |
| **P2** | 3B: Prune short basket | Remove small drags | Low — conservative pruning |
| **P2** | 3C: Idle long boost for shorts | Capture more short alpha | Low |
| **P3** | 1C: Re-enable Grizzly shorts | Hedge long bleed | High — shorts historically weak |
| **P3** | 4A: BTC Weekly activation | Restart dormant strategy | Low — small sizing |

---

## Testing Notes

All config changes are YAML-only and can be tested on a branch without code modifications (except 2B trailing stop which needs implementation). The P0 changes can be deployed immediately to stop the two largest bleed sources.
