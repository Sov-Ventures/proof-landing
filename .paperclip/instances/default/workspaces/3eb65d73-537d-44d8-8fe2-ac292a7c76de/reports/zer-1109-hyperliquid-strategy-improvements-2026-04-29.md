# ZER-1109: Hyperliquid Strategy Improvements — 2026-04-29

## Scope
- 14-day window: April 15–29, 2026
- Databases: `grizzly.db`, `vibe_oi.db`, `hypergrowth.db`
- Configs: `grizzly.yaml`, `vibe_oi.yaml`, `hypergrowth.yaml`
- Compared against prior analysis (ZER-745, April 27)

---

## Portfolio Summary (14-day)

| Strategy | Trades | Win Rate | Net PnL | Δ vs Apr 27 | Status |
|-----------|--------|----------|---------|-------------|--------|
| Grizzly | 39 | 30.8% | **-$5.61** | -$8.21 | ⚠️ Net negative, deteriorating |
| Vibe OI | 12 | 41.7% | **-$1.28** | -$2.15 | ⚠️ Stalled — zero trades in 10 days |
| Hypergrowth | 191 | 49.2% | **+$56.99** | +$4.74 | ✅ Still strong, trend weakening |
| **Total** | **242** | — | **+$50.10** | **-$5.62** | Overall positive but decaying |

**Key headline:** Portfolio PnL dropped from +$55.72 to +$50.10 since Apr 27. Grizzly flipped negative. Vibe OI inactive. Only Hypergrowth is carrying the portfolio.

---

## 1. Grizzly — Significant Deterioration

### 1a. Performance flipped negative
Since Apr 27 analysis: **5 new trades, all losses, -$5.26 PnL.**

| Period | Trades | PnL | Note |
|--------|--------|-----|------|
| Apr 15–27 (prior report) | 40 | +$2.60 | Fragile positive |
| Apr 27–29 (new) | 5 | **-$5.26** | All losers |
| Full 14-day | 39 | **-$5.61** | Net negative |

Biggest single loss: -$4.95 on Apr 27 14:36 (ETH correlation divergence exit after just 30 minutes hold).

### 1b. Sub-1-hour trades are catastrophic
**NEW FINDING:** Hold time analysis reveals a severe short-duration loss pattern:

| Hold Bucket | Trades | PnL | Avg PnL |
|-------------|--------|-----|---------|
| <1h | 14 | **-$13.92** | -$0.99 |
| 1–4h | 13 | -$8.52 | -$0.66 |
| 4–12h | 10 | +$4.87 | +$0.49 |
| >12h | 2 | +$11.96 | +$5.98 |

**36% of all trades exit within 1 hour, accounting for -$13.92 in losses.** The strategy has positive expectancy only when positions are held >4 hours. Sub-1h exits are rapid thesis-kills in noisy conditions.

### 1c. ETH correlation still dominates exit flow
- ETH correlation exits: 27 trades (69%), -$5.06 PnL, avg hold 4.1h
- Other exits: 12 trades, -$0.54 PnL, avg hold 1.3h

The ETH correlation signal triggers fast exits but isn't capturing alpha. It mainly churns capital in choppy ETH/BTC regimes.

### 1d. Currently active
Grizzly is RIDING a long position as of 07:40 UTC (7,473 signal logs in last 48h). No open trade in DB — may be in the entry-to-write pipeline.

---

## 2. Vibe OI — Effectively Offline

### 2a. Zero new trades in 10 days
Last trade: Apr 19. Since then, the strategy has logged **1,010 signal scans in 48h** — all returning `WAIT/HOLD`. The signals are not converging.

### 2b. The 18.2h zombie remains the biggest historical loss
The -$2.75 zombie trade (identified in Apr 27 report) is still the dominant loss. No new trades to evaluate, so the P0-B hard-kill proposal from Apr 27 remains valid but lower urgency.

### 2c. 10-day entry drought is the new problem
With current thresholds (`price_change_threshold: 0.003`, `oi_change_threshold: 0.01`), the strategy is too selective for the current BTC regime. The strategy is effectively paused without anyone deciding to pause it.

---

## 3. Hypergrowth — Strong but Weakening

### 3a. Still the only profitable strategy
- 27 new trades since Apr 27, +$3.53 (positive but decelerating)
- Short basket remains the edge: W +$24.49, SEI +$19.08, ZETA +$8.05

### 3b. W concentration improved
**W dropped from 26.6% → 15.7% of abs PnL** — the concern from Apr 27 has resolved naturally as other symbols contributed more.

### 3c. HYPE long drag reduced
- HYPE realized PnL improved from -$9.40 → -$2.19 (9 trades, 55.6% WR in this window)
- Still the only net-negative symbol, but less severe

### 3d. NEW: Drawdown emergency close trend is turning negative
**4 drawdown rounds since Apr 27, with the last 2 net negative:**

| Timestamp | Round | Net PnL | Trend |
|-----------|-------|---------|-------|
| Apr 27 13:20 | 4-position close | +$5.44 | ✅ Profitable |
| Apr 27 21:53 | 5-position close | +$1.16 | ✅ Marginal |
| Apr 28 06:26 | 5-position close | +$2.29 | ✅ Profitable |
| Apr 28 17:26 | 5-position close | **-$4.29** | ⚠️ Net loss |
| Apr 29 01:50 | 3-position close | **-$1.30** | ⚠️ Net loss |

The last two emergency close rounds (9 trades combined) lost -$5.59. This may signal fading short-basket edge in the current alt market regime (alts recovering relative to HYPE).

### 3e. Core positions are 15 days old
All 10 open positions (1 HYPE long + 9 alt shorts) were entered Apr 14. At 14.9 days, these are approaching a 3-week hold without rebalancing.

### 3f. APT showing persistent weakness
APT: 12 trades, -$1.91 total PnL, 33.3% WR — worst short basket performer. Last 3 trades were all $0.00 dust cleanup. Consider removal from universe or temporary exclusion.

---

## Proposed Improvements

### P0 — Immediate

#### A) Grizzly: Minimum hold time guard for thesis-kill exits
**Why:** Sub-1h exits are -$13.92 on 14 trades (avg -$0.99/trade). Thesis-kills within the first hour are predominantly noise, not signal. The existing `min_hold_sec: 1200` (20 min) is not enough.

**Proposed change:** Increase `min_hold_sec` from 1200 → 3600 (1 hour). Alternatively, for exits between 20–60 min, require 3+ weakener groups instead of 2. The hard stop (`max_loss_per_trade_pct: 0.012`) still provides downside protection during this window.

**Expected impact:** Avoid ~$10/14d in premature exit losses. Trades held >4h are net positive.

**Target:** `configs/grizzly.yaml` → `riding.min_hold_sec`

#### B) Grizzly: ETH correlation sensitivity reduction
**Why:** ETH correlation exits account for 69% of all exits but produce -$5.06 PnL. The signal is too trigger-happy.

**Proposed change:** Raise `eth_correlation_min` from 0.5 → 0.4 (i.e., require a stronger divergence before killing thesis). Also consider increasing `eth_correlation_window` from 24h → 48h to smooth out short-term noise.

**Target:** `configs/grizzly.yaml` → `data.eth_correlation_min`, `data.eth_correlation_window`

**Expected impact:** Reduce ETH-triggered churn by ~30%, allowing more trades to reach the profitable >4h hold window.

#### C) Vibe OI: Threshold relaxation to resume trading
**Why:** Zero entries in 10 days means the strategy contributes nothing to portfolio PnL. The entry thresholds are too strict for the current low-vol BTC regime.

**Proposed change:**
- `price_change_threshold`: 0.003 → 0.002
- `oi_change_threshold`: 0.01 → 0.005
- `volume_spike_threshold`: 1.3 → 1.15

Consider also adding a `max_idle_hours: 48` parameter that auto-relaxes thresholds by 20% if no entry occurs within 48h, with a floor to prevent trading in truly dead markets.

**Target:** `configs/vibe_oi.yaml` → `signals.*`

**Expected impact:** Resume trade generation. Even at reduced conviction, the 4h max-age exit provides natural loss-capping.

### P1 — Next Sprint

#### D) Hypergrowth: Drawdown emergency close trend monitor
**Why:** Last 2 of 4 drawdown rounds were net negative (-$5.59 combined). If short basket alpha is fading, continued emergency closes will drain capital.

**Proposed change:** Track rolling PnL of the last 3 drawdown emergency close rounds. If net PnL of the last 3 rounds is negative, reduce short basket allocation by 20% for the next 24h and alert via Telegram. This creates an auto-defensive posture without shutting down the strategy.

**Target:** `src/core/hypergrowth_runner.py` → drawdown emergency close logic

#### E) Hypergrowth: Remove APT from short universe
**Why:** APT has the worst short performance (-$1.91, 33.3% WR) and the last 3 trades were all dust cleanup at $0. It's generating churn without edge.

**Proposed change:** Remove APT from `short_leg.universe` and `short_leg.sectors.l1`. Redistribute allocation to SEI (highest WR at 58.1%) and ZETA (55.6%).

**Target:** `configs/hypergrowth.yaml` → `short_leg.universe`, `short_leg.sectors`

#### F) Hypergrowth: Position age alert at 21 days
**Why:** All 10 open positions are 14.9 days old. Long-held pair positions accumulate funding costs and may drift from original thesis.

**Proposed change:** Add alert when any position exceeds 21 days. Trigger a manual rebalance review rather than auto-close — the positions may still be intentional.

### P2 — Monitor (carried from Apr 27)

#### G) Vibe OI: 6h hard kill (P0-B from Apr 27)
Still valid but lower priority since no new trades are being generated. Implement when entry thresholds are relaxed (P0-C above).

#### H) Hypergrowth: Stale reconciler slippage cap (P0-C from Apr 27)
No new auto_reconcile_stale trades since Apr 27. Still valid for the next occurrence. 0.5% max slippage cap with tranche splitting.

---

## Config Diff vs April 27 Report

| Item | Apr 27 State | Apr 29 State | Change |
|------|-------------|-------------|--------|
| Grizzly `allow_shorts` | `false` | `false` | No change |
| Grizzly 4-signal weakener guard | Proposed P0-A | **Not implemented** | ⚠️ Strategy lost -$5.26 since |
| Vibe OI 6h hard kill | Proposed P0-B | **Not implemented** | Lower priority (no trades) |
| Hypergrowth stale reconciler cap | Proposed P0-C | **Not implemented** | No new occurrences |
| Vibe OI entry thresholds | Unchanged | Unchanged | ⚠️ 10 days idle |

**None of the Apr 27 P0 proposals were implemented.** Grizzly losses have worsened. Prioritizing threshold/hold-time changes (P0-A, P0-C in this report) that are config-only and require no code changes.

---

## Risk Dashboard Snapshot

| Metric | Value | Status |
|--------|-------|--------|
| Portfolio 14d PnL | +$50.10 | ⚠️ Down from +$55.72 |
| Active strategies | 2 of 3 | ⚠️ Vibe OI effectively offline |
| Grizzly 14d PnL | -$5.61 | ⚠️ Net negative |
| Hypergrowth open position age | 14.9 days | Approaching 3-week threshold |
| Drawdown emergency close trend | 2 consecutive net-negative rounds | ⚠️ Monitor |
| Worst single-trade loss (14d) | -$7.74 (HYPE drawdown) | Within bounds |

---

## Notes
- No source files were modified. All proposals are ready-to-implement specifications.
- Evidence is from local DBs through ~2026-04-29 07:40 UTC.
- Prior analysis: `reports/zer-745-hyperliquid-strategy-improvements-2026-04-27.md`
- P0-A and P0-B are config-only changes (no code needed). P0-C may require signal logic review.
