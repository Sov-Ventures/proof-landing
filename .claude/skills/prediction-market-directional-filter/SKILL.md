---
name: prediction-market-directional-filter
description: |
  Directional filtering rules for binary option trading on prediction markets (Polymarket, Kalshi).
  Use when: (1) analyzing why prediction market trades are losing, (2) building/debugging trading
  bots for binary price predictions, (3) seeing contradictory positions (YES and NO on same strike),
  (4) "cheap" low-probability bets consistently losing, (5) reviewing win rates across YES vs NO
  positions. Key insight: strike price relative to current asset price determines optimal direction.
author: Claude Code
version: 1.0.0
date: 2026-01-27
---

# Prediction Market Directional Filter

## Problem
Binary option trading bots for price predictions often lose money by betting against current
price direction. A bot may show "good edge" mathematically while making systematically losing
trades due to directional bias.

## Context / Trigger Conditions
- Trading binary options like "Will BTC be above $X by date Y?"
- Win rate differs significantly between YES and NO positions
- "Cheap" entries (<15 cents) underperform "expensive" entries
- Bot holds contradictory positions (both YES and NO on same strike)
- Positions on strikes near current price consistently lose

## Root Cause Analysis
From empirical analysis of 38 positions on BTC price prediction markets:

| Pattern | Win Rate | Explanation |
|---------|----------|-------------|
| NO on strikes ABOVE current price | 100% | Betting BTC won't reach higher levels |
| NO on strikes AT/BELOW current price | 0% | Betting BTC will drop (against trend) |
| YES on strikes BELOW current price | 100% | Betting BTC stays above current level |
| YES on strikes ABOVE current price | 0% | Betting BTC will pump (low probability) |

**Key Insight**: Don't bet against current price. If BTC is at $88k:
- NO on $90k+ = good (betting it won't pump)
- NO on $86k = bad (betting it will dump)
- YES on $85k = good (betting it stays above)
- YES on $95k = bad (needs major pump)

## Solution: Directional Filter Rules

```python
def should_trade(strike: float, current_price: float, side: str, buffer_pct: float = 0.02) -> bool:
    """
    Filter trades based on direction relative to current price.

    Args:
        strike: The strike price of the binary option
        current_price: Current asset price
        side: "YES" or "NO"
        buffer_pct: Minimum distance from current price (default 2%)

    Returns:
        True if trade direction is favorable
    """
    distance_pct = (strike - current_price) / current_price

    if side == "NO":
        # Only bet NO when strike is ABOVE current price (betting it won't reach)
        return distance_pct > buffer_pct
    else:  # YES
        # Only bet YES when strike is BELOW current price (betting it stays above)
        return distance_pct < -buffer_pct
```

### Additional Rules

1. **No Contradictory Positions**: Never hold both YES and NO on the same strike
   ```python
   if existing_position_on_strike(strike):
       skip_trade()
   ```

2. **Distance-Based Sizing**: Scale position size by strike distance
   ```python
   distance_pct = abs(strike - current_price) / current_price
   if distance_pct < 0.02:
       return 0  # Too close, skip
   elif distance_pct < 0.05:
       return kelly_size * 0.5  # Half size
   else:
       return kelly_size  # Full size
   ```

3. **Ignore "Cheap Entry" Fallacy**: Low-priced options (<$0.15) are cheap for a reason
   - Don't overweight based on potential payout multiplier
   - Apply same edge requirements regardless of price

## Verification
After implementing directional filter:
- YES win rate should increase (only taking favorable YES bets)
- NO win rate should stay high (already mostly favorable)
- No contradictory positions appear in portfolio
- Average win rate should exceed 60%

## Example

**Before Filter (Actual Results)**:
```
YES positions: 8 total, 25% winning
NO positions:  30 total, 77% winning
Overall: +8.1% return but 13 losing positions
```

**Losses from Ignoring Filter**:
- $86k NO: -$32.23 (BTC was above $86k)
- $88k NO: -$101.66 (BTC was above $88k)
- $90k YES: -$9.79 (BTC didn't reach $90k)
- $92k YES: -$32.35 (BTC didn't reach $92k)

Total preventable losses: **~$176** (2.7% of portfolio)

**After Filter (Expected)**:
- Block all NO bets where strike < current_price
- Block all YES bets where strike > current_price
- Estimated win rate improvement: 25% → 65%+ for YES positions

## Notes

1. **Buffer Zone**: The 2% buffer prevents betting on strikes too close to current price
   where outcome is essentially a coin flip

2. **Trend Consideration**: This filter assumes neutral/ranging markets. In strong trends:
   - Strong uptrend: May relax NO filter slightly
   - Strong downtrend: May relax YES filter slightly

3. **Volatility Adjustment**: Higher volatility = wider buffer zone recommended
   - Normal vol (30-50%): 2% buffer
   - High vol (50-80%): 3-4% buffer
   - Extreme vol (>80%): 5%+ buffer

4. **Time Decay**: Near expiry, filter becomes more critical as price has less time to move

## Related Patterns
- Kelly criterion position sizing
- Black-Scholes binary option pricing
- Prediction market liquidity analysis
