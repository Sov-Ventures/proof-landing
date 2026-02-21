---
name: polymarket-short-collateral-preflight
description: |
  Fix for Polymarket "not enough balance / allowance" errors specifically on SELL orders when
  BUY orders work fine. Use when: (1) SELL orders fail but BUY orders succeed on the same account,
  (2) error occurs on some markets but not others, (3) wallet has USDC but shorts are rejected,
  (4) trading bot over-leveraged with short positions. Root cause: active short positions lock
  collateral, and only ACTIVE (not expired) markets count toward collateral requirements.
author: Claude Code
version: 1.0.0
date: 2026-01-28
---

# Polymarket Short Collateral Pre-flight Check

## Problem

Polymarket API returns `PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]`
specifically for SELL orders, while BUY orders work fine on the same account.

This is confusing because:
- Wallet has USDC balance
- All approvals (USDC and CTF) are set correctly
- BUY orders succeed
- Some SELL orders work, others fail

## Context / Trigger Conditions

**Symptoms:**
- SELL orders fail with "not enough balance / allowance"
- BUY orders work on the same account
- Error is market-specific (some markets accept SELL, others don't)
- Trading bot has been placing short (SELL) positions

**Technical context:**
- Using py-clob-client for Polymarket API
- Bot places both BUY and SELL orders
- Short positions have accumulated over time

**The key insight:**
SELL orders require collateral of `size × (1 - price)` per share. This collateral is locked
until the position is closed or the market expires. Only **ACTIVE** markets lock collateral;
expired markets release it.

## Root Cause

When you place a SELL order (short position):
1. You receive `size × price` as premium upfront
2. But `size × (1 - price)` is locked as collateral
3. Collateral remains locked until market resolves or you buy back

**Example:**
- SELL 100 shares @ $0.90 price
- Premium received: $90 (goes to wallet)
- Collateral locked: $10 (100 × 0.10)
- Net effect: $80 added to wallet, $10 locked

**The problem:** If your trading bot accumulates many short positions, the locked collateral
can exceed your available USDC, causing new SELL orders to fail.

**Critical distinction:** Only positions in **ACTIVE** markets lock collateral. Expired/resolved
markets release collateral (you either win and get $1/share, or lose and get $0).

## Solution

### Step 1: Calculate Active Short Collateral

Query trade history and filter for ACTIVE markets only:

```python
def get_active_short_collateral(client: ClobClient) -> float:
    """Calculate collateral locked in ACTIVE short positions only."""
    trades = client.get_trades()
    if isinstance(trades, dict):
        trades = trades.get('data', [])

    # Aggregate positions by asset
    positions = {}
    for trade in trades:
        asset_id = trade.get('asset_id', '')
        side = trade.get('side', '')
        size = float(trade.get('size', 0))
        price = float(trade.get('price', 0))

        if asset_id not in positions:
            positions[asset_id] = {'bought': 0, 'sold': 0, 'sell_revenue': 0}

        if side == 'BUY':
            positions[asset_id]['bought'] += size
        elif side == 'SELL':
            positions[asset_id]['sold'] += size
            positions[asset_id]['sell_revenue'] += size * price

    # Check each SHORT position against Gamma API for active status
    total_collateral = 0.0
    for asset_id, pos in positions.items():
        net = pos['bought'] - pos['sold']
        if net >= -0.01:  # Not a SHORT position
            continue

        short_size = abs(net)
        avg_sell_price = pos['sell_revenue'] / pos['sold'] if pos['sold'] > 0 else 0
        collateral = short_size * (1 - avg_sell_price)

        # Check if market is still active
        resp = requests.get(
            'https://gamma-api.polymarket.com/markets',
            params={'clob_token_ids': asset_id},
            timeout=5
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                is_active = markets[0].get('active', False) and not markets[0].get('closed', True)
                if is_active:
                    total_collateral += collateral

    return total_collateral
```

### Step 2: Add Pre-flight Check Before SELL Orders

```python
def place_order(client, order, dry_run=True):
    # Pre-flight collateral check for SELL orders
    if order.side == Side.YES_SELL and not dry_run:
        collateral_needed = order.size * (1 - order.price)
        available = get_available_short_collateral(client)

        if collateral_needed > available:
            logger.error(f"SELL order rejected: need ${collateral_needed:.2f} collateral "
                        f"but only ${available:.2f} available.")
            return None

    # ... proceed with order placement
```

### Step 3: Track Available Collateral in Main Loop

```python
# At start of each trading cycle:
exposure.short_collateral = get_active_short_collateral(client)
usdc_balance = get_wallet_usdc_balance()
safety_buffer = usdc_balance * 0.10  # Keep 10% buffer
exposure.available_for_shorts = max(0.0, usdc_balance - exposure.short_collateral - safety_buffer)

logger.info(f"Short collateral: ${exposure.short_collateral:.2f} locked, "
           f"${exposure.available_for_shorts:.2f} available for new shorts")
```

## Verification

1. Check collateral status in logs:
   ```
   Active short collateral: $173.57, available for new shorts: $0.00
   ```

2. SELL orders should now fail gracefully with clear error:
   ```
   SELL order rejected: need $5.00 collateral but only $0.00 available.
   ```

3. BUY orders should continue working normally

## Example

**Before fix:**
```
2026-01-28 12:30:35 | Placing SELL order: 9.3 shares @ $0.74
2026-01-28 12:30:35 | HTTP Request: POST https://clob.polymarket.com/order "HTTP/2 400"
2026-01-28 12:30:35 | Failed to place order: PolyApiException[status_code=400,
                      error_message={'error': 'not enough balance / allowance'}]
```

**After fix:**
```
2026-01-28 13:02:31 | Active short collateral: $173.57, available for new shorts: $0.00
2026-01-28 13:02:35 | SELL order rejected: need $2.41 collateral but only $0.00 available.
                      Redeem winning positions or add USDC.
```

## Notes

1. **Expired positions release collateral**: Positions in resolved markets don't lock collateral.
   The bot should redeem winning positions to free up capital.

2. **Safety buffer**: Keep 10% of USDC as buffer to avoid edge cases where collateral
   calculations differ slightly from the API's internal tracking.

3. **Position sizing integration**: Also limit position sizes in the sizing function,
   not just at order placement time:
   ```python
   if side == Side.YES_SELL:
       max_size = exposure.available_for_shorts / (1 - price)
       size = min(size, max_size)
   ```

4. **This differs from CTF allowance issues**: The `polymarket-ctf-allowance-fix` skill
   covers missing ERC-1155 approvals. This skill covers insufficient collateral even when
   approvals are correct.

5. **Market-specific behavior**: SELL works on markets where you have LONG positions
   (selling owned tokens, no collateral needed) but fails on markets where you'd be
   opening a new SHORT (needs collateral).

## Related Skills

- `polymarket-ctf-allowance-fix` - Missing ERC-1155 approvals causing same error
- `polymarket-negrisk-position-tracking` - Position tracking bugs in neg-risk markets

## References

- [Polymarket CLOB Documentation](https://docs.polymarket.com/)
- [GitHub Issue #109 - Balance/Allowance Errors](https://github.com/Polymarket/py-clob-client/issues/109)
