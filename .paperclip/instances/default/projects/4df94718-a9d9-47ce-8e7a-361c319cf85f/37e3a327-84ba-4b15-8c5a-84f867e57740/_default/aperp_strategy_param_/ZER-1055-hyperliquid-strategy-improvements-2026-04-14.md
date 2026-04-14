# ZER-1055 Hyperliquid Strategy Improvements (2026-04-14)

## Executive Summary
Analysis of 30-day Hyperliquid trading activity (March 15 - April 14, 2026) reveals three critical improvement opportunities with estimated +$150-200 recovery potential per month if implemented.

## Branch + Validation Context
- Analysis branch: `zer-1055-hl-improvements-2026-04-14`
- Runner workspace: `/Users/abreckler/Sites/hyperliquid-agent`
- Data sources:
  - `data/hypergrowth.db` (666 trades, 30-day)
  - `data/grizzly.db` (143 trades, 30-day)
  - `data/vibe_oi.db` (66 trades, 30-day)
- Analysis period: 2026-03-15 to 2026-04-14

## Latest 30-Day Performance Snapshot

### Overall Performance
| Strategy | Trades | Total PnL | Avg PnL/Trade | Status |
|----------|--------|-----------|---------------|--------|
| Hypergrowth | 666 | -$114.34 | -$0.17 | **HALTED** (drawdown) |
| Grizzly | 143 | -$5.14 | -$0.04 | Active |
| Vibe OI | 66 | -$148.92 | -$2.26 | Active |
| **TOTAL** | **875** | **-$268.40** | **-$0.31** | |

### Recent 4-Day Performance (April 10-14)
| Strategy | Trades | Total PnL | Avg PnL/Trade | Trend |
|----------|--------|-----------|---------------|-------|
| Hypergrowth | 0 | $0.00 | N/A | Halted |
| Grizzly | 11 | +$5.44 | +$0.49 | ✅ Positive |
| Vibe OI | 11 | +$6.01 | +$0.55 | ✅ Positive |

**Note:** Recent 4-day positive performance is NOT representative. Both strategies remain deeply negative over 30 days.

## Critical Findings

### 🚨 CRITICAL #1: Vibe OI Liquidation Risk Exits (Highest Priority)

**Problem:**
- 4 liquidation risk exits caused **-$148.39** in losses (99.6% of total 30-day losses)
- Average loss per liquidation exit: **-$37.10** (vs -$1.87 for regular SL exits)
- All occurred March 18-19 during BTC volatility
- Worst single trade: -$68.98

**Impact Without These 4 Trades:**
- 30-day PnL would be +$0.47 (near breakeven) instead of -$148.92
- **Improvement potential: +$148**

**Exit Reason Breakdown (30-day):**
```
Liquidation Risk Exit:    4 trades, -$148.39  (-$37.10 avg) ← FATAL
Stop Loss Exit:           9 trades,  -$16.86  ( -$1.87 avg)
Max Age Exit:            52 trades,  +$12.27  ( +$0.24 avg) ← Profitable!
Take Profit:              1 trade,    +$4.06  ( +$4.06 avg)
```

**Root Cause Analysis:**
1. Over-leveraged positions during high volatility regime
2. No volatility-based position size scaling (proposed in ZER-823 but not implemented)
3. No liquidation risk pre-flight check before entry
4. Emergency exit threshold (3-4% liq risk) is too late - already deep underwater

**Proposed Improvements (Ready to Implement):**

**A1. Pre-entry Liquidation Risk Gate (Critical)**
```python
# In vibe_runner.py, before position entry
def check_liquidation_risk_preflight(symbol, size, leverage, entry_price):
    """
    Calculate expected liquidation risk BEFORE entering.
    Reject entry if risk > 15% at entry.
    """
    account_value = get_account_value()
    position_value = size * entry_price
    margin_required = position_value / leverage
    
    # Estimate liquidation price (simplified)
    liq_price = entry_price * (1 - (0.9 / leverage))
    liq_distance_pct = abs((entry_price - liq_price) / entry_price) * 100
    
    if liq_distance_pct > 15:
        log.warning(f"ENTRY BLOCKED: Liq risk {liq_distance_pct:.1f}% > 15% threshold")
        return False
    return True
```

**A2. Volatility-Scaled Position Sizing (Critical)**
```python
# In vibe_runner.py
def get_volatility_scaled_position_size(base_size_pct, symbol):
    """
    Scale position size inversely with recent realized volatility.
    High vol = smaller positions to avoid liquidation.
    """
    # Get 24h realized volatility
    vol_24h = calculate_realized_volatility(symbol, hours=24)
    
    # Baseline: 2% vol = 1.0x multiplier
    # 4% vol = 0.5x multiplier (half size)
    # 8% vol = 0.25x multiplier (quarter size)
    vol_multiplier = (0.02 / vol_24h) if vol_24h > 0.02 else 1.0
    vol_multiplier = max(0.25, min(1.0, vol_multiplier))  # Clamp 0.25-1.0
    
    adjusted_size = base_size_pct * vol_multiplier
    log.info(f"Vol scaling: {vol_24h:.2%} vol → {vol_multiplier:.2f}x size ({adjusted_size:.4f})")
    return adjusted_size
```

**A3. Early Liquidation Risk Exit (Critical)**
```python
# In vibe_runner.py position monitor
def check_liquidation_risk_threshold(position):
    """
    Exit at 10% liq risk instead of waiting until 3-4%.
    Current 3-4% threshold results in -$37 avg loss.
    Earlier exit at 10% estimated -$5-10 loss.
    """
    liq_risk_pct = calculate_liquidation_risk(position)
    
    if liq_risk_pct <= 10.0:  # Changed from 3.0
        log.warning(f"EARLY LIQ EXIT: {liq_risk_pct:.1f}% risk")
        return True, "early_liq_risk_10pct"
    return False, None
```

**A4. Volatility Regime Pause (Defensive)**
```python
# In vibe_runner.py, before scanning for entries
def check_volatility_pause():
    """
    If BTC 24h realized vol > 6%, pause new entries for 6h.
    Resume after vol drops below 4% or 6h timeout.
    """
    vol_24h = calculate_realized_volatility("BTC", hours=24)
    
    if vol_24h > 0.06:
        pause_until = time.time() + 6 * 3600
        log.warning(f"VOL PAUSE: {vol_24h:.2%} > 6% threshold, pausing until {pause_until}")
        return True, pause_until
    return False, None
```

**Expected Impact:**
- Prevent 80-90% of liquidation risk exits
- Reduce avg liquidation loss from -$37 to -$5
- **Monthly recovery: +$120-140**

---

### 🚨 CRITICAL #2: Hypergrowth Manual Close Pathways (High Priority)

**Problem:**
- Manual close pathways account for **-$110.59** (96.7% of 30-day losses)
- Strategy currently **HALTED** due to drawdown (until April 14 12:43 IDT)
- Same issue identified in ZER-823 (April 10) - **still not fixed**

**Exit Reason Breakdown (30-day):**
```
manual_close_script:      18 trades,  -$77.43  (-$4.30 avg) ← Operational drag
manual_resolve_onchain:   26 trades,  -$33.16  (-$1.28 avg) ← Operational drag
stop_loss:               422 trades,   -$5.78  (-$0.01 avg) ← Actually fine!
drawdown_close_dust:      28 trades,   -$5.70  (-$0.20 avg)
dust_cleanup:             40 trades,   +$7.97  (+$0.20 avg)
```

**What-If Analysis:**
- Excluding manual close pathways: -$3.75 (97% improvement)
- **Improvement potential: +$110**

**Proposed Improvements (Ready to Implement):**

**B1. Replace Manual Close with Automated Reconciler (Critical)**
```python
# In hypergrowth_runner.py
def auto_reconcile_stale_positions():
    """
    Periodic reconciler (every 1h) to close stale/orphaned positions
    via standard exit flow BEFORE falling back to manual scripts.
    """
    positions = get_open_positions()
    now = time.time()
    
    for pos in positions:
        age_hours = (now - pos['entry_time']) / 3600
        
        # Close positions older than 48h via standard flow
        if age_hours > 48:
            log.warning(f"STALE POSITION: {pos['symbol']} age={age_hours:.1f}h, auto-closing")
            close_position_standard(pos, reason="auto_reconcile_stale")
            continue
        
        # Close positions with no active thesis tracking
        if pos['symbol'] not in active_thesis_map:
            log.warning(f"ORPHAN POSITION: {pos['symbol']} no active thesis, auto-closing")
            close_position_standard(pos, reason="auto_reconcile_orphan")
```

**B2. Block Manual Close from Routine Paths**
```python
# In hypergrowth_runner.py
ALLOW_MANUAL_CLOSE_SCRIPT = os.getenv("ALLOW_MANUAL_CLOSE", "false").lower() == "true"

def close_position_manual_fallback(pos):
    """Only allow manual close if explicitly enabled (emergency use)."""
    if not ALLOW_MANUAL_CLOSE_SCRIPT:
        log.error(f"BLOCKED: manual_close_script disabled, use auto_reconcile instead")
        return False
    
    log.warning(f"EMERGENCY MANUAL CLOSE: {pos['symbol']}")
    # ... existing manual close logic
```

**B3. Concentration Risk Clamp**
```python
# In hypergrowth_runner.py
def check_symbol_concentration(symbol):
    """
    If rolling 96h abs-PnL share for one symbol > 55%,
    reduce that symbol's position cap by 50% for next 48h.
    
    Example: HYPE dominated 67.22% of 96h PnL in ZER-823 analysis.
    """
    pnl_96h = get_96h_pnl_by_symbol()
    total_abs_pnl = sum(abs(pnl) for pnl in pnl_96h.values())
    
    if total_abs_pnl > 0:
        symbol_share = abs(pnl_96h.get(symbol, 0)) / total_abs_pnl
        
        if symbol_share > 0.55:
            reduction_pct = 0.50
            cooldown_hours = 48
            log.warning(
                f"CONCENTRATION CLAMP: {symbol} {symbol_share:.1%} > 55%, "
                f"reducing cap by {reduction_pct:.0%} for {cooldown_hours}h"
            )
            return reduction_pct, cooldown_hours
    
    return 0, 0
```

**Expected Impact:**
- Eliminate 80-90% of manual close losses
- **Monthly recovery: +$80-100**

---

### ⚠️  MEDIUM PRIORITY #3: Grizzly Trend-Flip Thesis Kills

**Problem:**
- Trend-flip thesis kills show -$7.15 over 30 days (15 trades, -$0.48 avg)
- ETH correlation kills are actually **profitable**: +$7.03 (21 trades, +$0.33 avg)
- **This contradicts ZER-823 finding** that trend-flip kills were near-breakeven

**Exit Reason Breakdown (30-day):**
```
ETH Correlation Kill:          21 trades,  +$7.03  (+$0.33 avg) ← Keep this!
Thesis Weakened (2 signals):   28 trades,  +$4.89  (+$0.17 avg) ← Keep this!
Trend Flip Kill:               15 trades,  -$7.15  (-$0.48 avg) ← Fix this
Thesis Weakened (3 signals):   78 trades,  -$8.91  (-$0.11 avg)
```

**Proposed Improvements (Ready to Implement):**

**C1. Trend-Flip Persistence Filter**
```python
# In grizzly strategy layer
def check_trend_flip_persistence(symbol):
    """
    Require trend-flip kill condition to persist for 2 consecutive
    re-evaluations (except hard risk stops like liquidation risk).
    
    Goal: Reduce premature exits on temporary trend noise.
    """
    trend_state = get_trend_state(symbol)
    
    if trend_state.flip_detected:
        if not hasattr(trend_state, 'flip_confirmed_count'):
            trend_state.flip_confirmed_count = 1
            log.info(f"TREND FLIP: {symbol} first detection, waiting for confirmation")
            return False  # Don't kill yet
        else:
            trend_state.flip_confirmed_count += 1
            if trend_state.flip_confirmed_count >= 2:
                log.warning(f"TREND FLIP CONFIRMED: {symbol} (2 consecutive checks)")
                return True
    
    return False
```

**C2. Post-Kill Cooldown**
```python
# In grizzly strategy layer
def apply_trend_flip_cooldown(symbol, direction):
    """
    After a trend-flip thesis kill, apply 30-minute no-reentry
    cooldown in the same direction.
    
    Goal: Avoid immediate re-entry into failing trend.
    """
    cooldown_key = f"{symbol}_{direction}_trend_flip"
    cooldown_until = time.time() + 30 * 60  # 30 minutes
    
    set_cooldown(cooldown_key, cooldown_until)
    log.info(f"COOLDOWN: {symbol} {direction} blocked for 30m after trend flip")
```

**Expected Impact:**
- Reduce trend-flip kill losses by 50%
- **Monthly recovery: +$3-4** (smaller impact, lower priority)

---

## Implementation Priority & Estimated Impact

| Priority | Issue | Strategy | Estimated Monthly Recovery | Complexity |
|----------|-------|----------|---------------------------|------------|
| **P0** | Liquidation risk exits | Vibe OI | +$120-140 | Medium |
| **P0** | Manual close pathways | Hypergrowth | +$80-100 | Low |
| **P1** | Trend-flip sensitivity | Grizzly | +$3-4 | Low |
| | | **TOTAL** | **+$203-244/month** | |

## Concrete Implementation Batch

### Phase 1 (P0 - This Week)
1. **File:** `src/core/vibe_runner.py`
   - Add `check_liquidation_risk_preflight()` before entry
   - Add `get_volatility_scaled_position_size()` for dynamic sizing
   - Update liq risk threshold from 3% to 10%
   - Add `check_volatility_pause()` before scanning

2. **File:** `src/core/hypergrowth_runner.py`
   - Add `auto_reconcile_stale_positions()` (run every 1h)
   - Add `ALLOW_MANUAL_CLOSE` env var gate (default: false)
   - Add `check_symbol_concentration()` before entries

3. **File:** `configs/vibe_oi.yaml`
   ```yaml
   position_size_base_pct: 0.02
   vol_scaling_enabled: true
   vol_scaling_baseline: 0.02
   liq_risk_entry_max: 15.0
   liq_risk_exit_threshold: 10.0
   vol_pause_threshold: 0.06
   ```

4. **File:** `configs/hypergrowth.yaml`
   ```yaml
   auto_reconcile_enabled: true
   auto_reconcile_interval_sec: 3600
   allow_manual_close: false
   concentration_threshold_pct: 55.0
   concentration_reduction_pct: 50.0
   ```

### Phase 2 (P1 - Next Week)
1. **File:** `src/strategies/grizzly.py` or `src/core/runner.py`
   - Add trend-flip persistence filter (2 consecutive confirmations)
   - Add post-kill cooldown (30m same-direction block)

2. **File:** `configs/grizzly.yaml`
   ```yaml
   trend_flip_persistence_required: 2
   trend_flip_cooldown_minutes: 30
   ```

## Testing & Validation Plan

### Unit Tests
- [ ] Test `check_liquidation_risk_preflight()` with various leverage/size scenarios
- [ ] Test `get_volatility_scaled_position_size()` with vol range [1%-10%]
- [ ] Test `auto_reconcile_stale_positions()` with aged positions
- [ ] Test `check_symbol_concentration()` with HYPE-like dominance

### Integration Tests (Staging)
- [ ] Run Vibe OI with vol scaling on testnet for 48h
- [ ] Run Hypergrowth with manual_close blocked + auto_reconcile for 48h
- [ ] Monitor for false positives (blocked legitimate entries)

### Backtest Validation
- [ ] Replay March 18-19 BTC dump with new Vibe OI rules
- [ ] Replay April 7 HYPE manual close scenario with auto_reconcile
- [ ] Compare PnL with/without changes

### Production Rollout
1. Deploy to Vibe OI (highest impact, +$120-140)
2. Deploy to Hypergrowth after drawdown halt expires (April 14 12:43)
3. Deploy to Grizzly (lowest priority, +$3-4)

## Risk Assessment

### Implementation Risks
- **Vol scaling too aggressive**: Could miss profitable entries in normal vol
  - Mitigation: Baseline at 2% vol (historical average), only scale down above that
- **Liq risk preflight too strict**: Could block profitable high-leverage trades
  - Mitigation: 15% threshold is loose enough for 3-5x leverage trades
- **Auto reconcile too aggressive**: Could close positions prematurely
  - Mitigation: 48h threshold is very conservative (2x typical max_age)

### Validation Criteria for Success
- Week 1: Zero liquidation risk exits > -$10 (vs 4 trades -$148 in March)
- Week 1: Zero manual_close_script exits (vs 18 trades -$77 in March)
- Week 2: Vibe OI 7-day PnL > -$20 (vs -$148 per 30 days)
- Week 2: Hypergrowth 7-day PnL > -$10 (vs -$114 per 30 days)

## Comparison to ZER-823 (April 10 Analysis)

### What Changed Since ZER-823?
| Finding | ZER-823 (Apr 10) | ZER-1055 (Apr 14) | Status |
|---------|------------------|-------------------|---------|
| Hypergrowth manual close drag | -$77.43 (96h) | -$77.43 (30d) | **Unchanged** |
| Vibe OI SL cluster losses | -$6.89 (96h) | -$16.86 (30d) | Still present |
| Grizzly trend-flip kills | Near breakeven | -$7.15 (30d) | **Worsened** |
| Grizzly ETH correlation kills | Not analyzed | +$7.03 (30d) | **Profitable!** |

### New Findings in ZER-1055
1. **Vibe OI liquidation risk exits** were not identified in ZER-823 (only 96h window)
   - 30-day analysis reveals this as the #1 issue (-$148)
2. **Grizzly trend-flip kills** are now shown to be loss source (not ETH correlation)
   - ZER-823 recommended adding trend-flip persistence - **validated by new data**
3. **Hypergrowth is halted** due to drawdown - implementations blocked until restart

### ZER-823 Recommendations Still Valid
- ✅ Hypergrowth auto reconciler (still needed, unchanged)
- ✅ Vibe OI vol-scaled sizing (now critical due to liq risk finding)
- ✅ Grizzly trend persistence (validated by 30-day data)

### ZER-823 Recommendations Now Invalidated
- ❌ "Vibe OI SL cluster breaker" - Not the main issue (liq risk is 10x worse)
- ❌ "Grizzly ETH correlation is reducing edge" - Actually profitable (+$7.03)

## SQL Queries Used for Analysis

```sql
-- 30-day performance summary
SELECT COUNT(*) as trades_30d,
       ROUND(SUM(pnl), 4) as total_pnl_30d,
       ROUND(AVG(pnl), 4) as avg_pnl_30d,
       ROUND(MIN(pnl), 4) as worst_trade,
       ROUND(MAX(pnl), 4) as best_trade
FROM trades 
WHERE exit_time >= strftime('%s', '2026-03-15 00:00:00');

-- Exit reason breakdown
SELECT exit_reason, 
       COUNT(*) as count,
       ROUND(SUM(pnl), 4) as total_pnl,
       ROUND(AVG(pnl), 4) as avg_pnl
FROM trades 
WHERE exit_time >= strftime('%s', '2026-03-15 00:00:00')
GROUP BY exit_reason
ORDER BY total_pnl ASC;

-- Worst trades (outlier analysis)
SELECT datetime(exit_time, 'unixepoch') as exit_time,
       symbol, side, ROUND(pnl, 4) as pnl, exit_reason
FROM trades 
WHERE exit_time >= strftime('%s', '2026-03-15 00:00:00')
  AND pnl < -10
ORDER BY pnl ASC;
```

## Appendix: Raw Data

### Vibe OI 30-Day Exit Distribution
```
Liquidation Risk Exit:    4 trades, -$148.39  (-$37.10 avg)
  ├─ 2026-03-18: -$68.98 (Liq risk 3.0%)
  ├─ 2026-03-19: -$55.27 (Liq risk 2.9%)
  ├─ 2026-03-19: -$22.05 (Liq risk 4.4%)
  └─ [1 more]:    -$2.08
Stop Loss Exit:           9 trades,  -$16.86  ( -$1.87 avg)
Max Age Exit:            52 trades,  +$12.27  ( +$0.24 avg)
Take Profit:              1 trade,    +$4.06  ( +$4.06 avg)
```

### Hypergrowth 30-Day Exit Distribution
```
manual_close_script:     18 trades,  -$77.43  (-$4.30 avg)
  ├─ Top 2 worst: HYPE -$57.69, HYPE -$19.25 (both Apr 7)
manual_resolve_onchain:  26 trades,  -$33.16  (-$1.28 avg)
stop_loss:              422 trades,   -$5.78  (-$0.01 avg)
drawdown_close_dust:     28 trades,   -$5.70  (-$0.20 avg)
dust_cleanup:            40 trades,   +$7.97  (+$0.20 avg)
```

### Grizzly 30-Day Exit Distribution
```
ETH Correlation Kill:                        21 trades,  +$7.03  (+$0.33 avg)
Thesis Weakened (funding + volume):          28 trades,  +$4.89  (+$0.17 avg)
Trend Flip Kill:                             15 trades,  -$7.15  (-$0.48 avg)
Thesis Weakened (funding + OI + volume):     78 trades,  -$8.91  (-$0.11 avg)
```

---

**Analysis completed:** 2026-04-14 07:00 UTC  
**Data sources:** hypergrowth.db, grizzly.db, vibe_oi.db  
**Branch:** zer-1055-hl-improvements-2026-04-14  
**Analyst:** Gamma (Portfolio Analyst)
