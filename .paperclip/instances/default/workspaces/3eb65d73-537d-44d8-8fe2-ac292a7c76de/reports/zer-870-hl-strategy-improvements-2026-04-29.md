# Hyperliquid Strategy Improvement Analysis — ZER-870

**Date:** 2026-04-29 ~11:30 UTC  
**Analyst:** Gamma (Portfolio Analyst)  
**Issue:** [ZER-870](/ZER/issues/ZER-870)

## Real-Time Strategy Status

| Strategy | Status | Active Position | Key Issue |
|----------|--------|----------------|-----------|
| Grizzly | RIDING | Long BTC @$76,821 (7x, entered 06:24 UTC) | Thesis weakening — conviction 0.33-0.49, funding reversed |
| Vibe OI | WAIT | None | Entry blocked — liquidation risk 87.1% vs 15% threshold |
| Hypergrowth | HALTED | None (emergency close) | Drawdown circuit breaker — halt until 11:43 UTC |
| BTC Weekly | DORMANT | None | DB last modified Apr 14, no trades in 15+ days |

## Strategy-Level Analysis & Recommendations

### 1. Grizzly (BTC Long-Only Swing)

**Current state:** Riding a long from $76,821 at 7x leverage, entered ~5 hours ago. Conviction has dropped from 50% at entry to 33-49% range. Funding rate has reversed (primary weakener). Volume is drying up.

**Config snapshot:**
- Leverage: 7x
- Min conviction: 0.45 (longs), shorts disabled
- Signal convergence: 75% (min 2 non-neutral)
- Trailing stop: 2% from peak
- Max loss/trade: 1.2%
- Grace period: 60 min for signal agreement
- Max weakener groups: 2 before exit

**Recommendation (P1 — config-only):**
- **Tighten trailing stop to 1.5%** — 7x leverage amplifies drawdowns; at current conviction decay rate, the 2% trail may let too much PnL evaporate. A 1.5% trail at 7x = ~10.5% notional move, still generous.
- **Add funding-rate reversal as a standalone exit trigger** — currently it's just a "weakener." When funding flips against the position, it creates persistent drag. Config change: add `funding_reversal_exit: true` or lower the weakener threshold from 2 groups to 1 when funding is the weakener.
- **Consider lowering leverage to 5x** — the 137-trade sample shows net -$7.22 PnL; edge is thin. Lower leverage reduces liquidation risk and gives trades more room.

### 2. Vibe OI (BTC Low-Frequency Volatility Scaling)

**Current state:** Detecting "NUKE" signals with 25-39% confidence but cannot enter because liquidation risk at 87.1% far exceeds the 15% entry threshold. Account has $512 margin.

**Config snapshot:**
- Leverage: 3-5x (capped at 5x)
- Position size: 5% of margin with vol scaling
- Liq risk max: 15% at entry, 10% for active exit
- TP: 3%, SL: 1.5%, Max age: 4h

**Critical finding:** The 87.1% liquidation risk calculation suggests the strategy is computing risk against total account exposure (including Grizzly's 7x BTC long) rather than just its own position. If strategies share margin, Grizzly's large leveraged position makes Vibe OI's entry check permanently fail.

**Recommendation (P0 — needs investigation + possible code change):**
- **Verify margin isolation:** Are Grizzly and Vibe OI on the same Hyperliquid sub-account? If yes, the liq risk check is correctly blocking (the account IS over-leveraged). Solution: move strategies to separate sub-accounts OR implement per-strategy margin accounting.
- **If margin is shared and correct:** the 15% threshold is working as designed safety-net. Don't relax it. Instead, reduce Grizzly leverage to free up margin for Vibe OI entries.
- **If margin is isolated but calculation is wrong:** fix the liq risk calculation to use per-strategy margin, not total account.

### 3. Hypergrowth (Long HYPE / Short ALT Basket)

**Current state:** Emergency drawdown circuit breaker triggered. All positions closed. Halt until 11:43 UTC. HWM equity at $97.28. HYPE allocation was 21.57% (already reduced per prior recommendations). Short basket: W, BERA, ONDO, ASTER, APT.

**Config snapshot:**
- HYPE: 20-40% allocation, 4-6x leverage, RSI max 62, 6% SL
- Short basket: 60-80%, 5-8x leverage, 20% per-alt cap
- Max drawdown: 8% triggers emergency close
- Max gross notional: 10x

**Analysis of the drawdown trigger:**
- Prior analysis showed HYPE long leg lost $99.34 on 451 trades while shorts made +$42
- The emergency close confirms the HYPE long drag is the primary risk — when HYPE drops, the long leg overwhelms short hedge profits
- 812 trades with -$57.22 combined = marginal negative edge with high activity cost

**Recommendation (P0 — config-only):**
- **Cut HYPE base allocation from 21.57% to 15%** — further reduce the losing long leg
- **Tighten HYPE stop loss from 6% to 4%** — faster exits on losing HYPE trades, reduce drawdown accumulation
- **Add HYPE entry cooldown after drawdown halt** — currently 12h reentry cooldown, but after an 8% drawdown halt, consider 24h+ cooldown before HYPE re-entry specifically
- **Prune short basket:** Remove worst-performing shorts (check per-symbol attribution). If APT or BERA are net negative, remove them to improve hedge efficiency.

### 4. BTC Weekly (Pattern-Based Dip Trading)

**Current state:** No trades since at least Apr 14. Database stale. Strategy may not be deployed or has configuration preventing activation.

**Config snapshot:**
- Leverage: 3x, position size: 10% of margin
- Entry: dip below Monday open (max 25% threshold)
- TP: 15%, SL: 3%
- Min margin: $50

**Recommendation (P2 — needs diagnosis):**
- **Diagnose why no trades:** Is the bot process running? Is the $50 min margin check failing? Are dip thresholds too strict for current BTC range?
- **If intended to be dormant:** Document it and disable to avoid confusion in monitoring.
- **If intended to be active:** Check logs, verify wallet connectivity, ensure the entry signal is firing.

## Priority Summary

| Priority | Change | Type | Expected Impact |
|----------|--------|------|-----------------|
| **P0** | Investigate Vibe OI liq risk / margin isolation | Investigation + possible code | Unblock Vibe OI entries entirely |
| **P0** | Cut HYPE allocation 21.57% → 15%, SL 6% → 4% | Config YAML | Reduce drawdown trigger frequency |
| **P1** | Grizzly trailing stop 2% → 1.5% | Config YAML | Preserve more PnL on winning trades |
| **P1** | Add funding reversal as standalone exit trigger | Config YAML or minor code | Avoid riding trades against funding |
| **P2** | Diagnose BTC Weekly inactivity | Investigation | Activate or formally disable strategy |
| **P2** | Prune Hypergrowth short basket underperformers | Config YAML | Improve hedge efficiency |
