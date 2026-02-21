---
name: polymarket-negrisk-position-tracking
description: |
  Fix for incorrect position tracking in Polymarket trading bots when using neg-risk markets
  and MAKER trades. Use when: (1) on-chain token balances don't match tracked positions,
  (2) redemption transactions succeed but no USDC received, (3) position shows NO tokens
  but you actually hold YES tokens (or vice versa), (4) trade.asset_id differs from
  maker_order.asset_id, (5) "not enough balance / allowance" errors despite having USDC
  (due to incorrect short collateral calculation). Root cause: for MAKER trades, must use
  maker_order.asset_id and maker_order.side, NOT trade values which show counterparty's
  perspective. CRITICAL: This fix must be applied to EVERY function that aggregates trades.
author: Claude Code
version: 2.1.0
date: 2026-01-28
---

# Polymarket Neg-Risk Position Tracking Bug (MAKER Trades)

## Problem

When tracking positions from Polymarket trade history, using `trade.asset_id` and `trade.side`
for MAKER trades causes positions to be tracked under the WRONG token ID. This results in:
- Position tracking shows NO tokens when you actually hold YES tokens
- On-chain balances show 0 for tracked positions
- Redemption transactions "succeed" but transfer no USDC (because 0 tokens exist)
- Massive mismatch between expected and actual redeemable value

## Context / Trigger Conditions

**Symptoms:**
- On-chain token balance is 0 for positions that trade history says exist
- `redeemPositions` TX succeeds (status=1) but wallet balance doesn't increase
- Position tracking shows wrong outcome (YES vs NO)
- BUY trades being recorded as SELLs (or vice versa)

**Verification command:**
```python
# Check if trade.asset_id differs from maker_order.asset_id
for trade in trades:
    if trade.get('trader_side') == 'MAKER':
        maker_asset = trade.get('maker_orders', [{}])[0].get('asset_id')
        trade_asset = trade.get('asset_id')
        if maker_asset != trade_asset:
            print(f"MISMATCH: trade={trade_asset[:20]} vs maker={maker_asset[:20]}")
```

**Technical context:**
- Using py-clob-client to fetch trade history via `client.get_trades()`
- Trading in neg-risk markets (Polymarket price prediction markets)
- Mix of MAKER and TAKER trades

## Root Cause

In Polymarket neg-risk markets, when you're a MAKER, the trade data shows the **counterparty's
perspective**, not yours:

**Example trade data:**
```python
trade = {
    'side': 'SELL',           # Counterparty sold to you
    'outcome': 'Yes',         # Counterparty's token
    'asset_id': '30562...',   # WRONG - counterparty's token ID
    'trader_side': 'MAKER',
    'maker_orders': [{
        'side': 'BUY',        # YOUR action - you bought
        'outcome': 'Yes',     # What YOU hold
        'asset_id': '93270...'  # CORRECT - your actual token ID
    }]
}
```

**The key insight:** For MAKER trades:
- `trade.asset_id` = counterparty's token (WRONG for tracking your position)
- `maker_order.asset_id` = your actual token (CORRECT)
- `trade.side` = counterparty's action (WRONG)
- `maker_order.side` = your action (CORRECT)

**Verified on-chain:**
```
trade.asset_id (30562...):  On-chain balance = 0.00 shares
maker.asset_id (93270...):  On-chain balance = 62.55 shares  ← ACTUAL TOKENS
```

## Solution

**For MAKER trades, use maker_order values. For TAKER trades, use trade values:**

```python
def fetch_positions_from_trades(client: ClobClient) -> list[Position]:
    trades = client.get_trades()  # With pagination
    positions = {}

    for trade in trades:
        trader_side = trade.get('trader_side', 'TAKER')

        if trader_side == 'MAKER':
            # Use maker order's values (what we actually hold)
            maker_orders = trade.get('maker_orders', [])
            if maker_orders:
                user_order = maker_orders[0]
                asset_id = user_order.get('asset_id', trade.get('asset_id', ''))
                outcome = user_order.get('outcome', trade.get('outcome', 'Unknown'))
                side = user_order.get('side', trade.get('side', ''))  # CRITICAL!
                price = float(user_order.get('price', trade.get('price', 0)))
            else:
                asset_id = trade.get('asset_id', '')
                outcome = trade.get('outcome', 'Unknown')
                side = trade.get('side', '')
                price = float(trade.get('price', 0))
        else:
            # TAKER: use trade's values directly
            asset_id = trade.get('asset_id', '')
            outcome = trade.get('outcome', 'Unknown')
            side = trade.get('side', '')
            price = float(trade.get('price', 0))

        size = float(trade.get('size', 0))

        if not asset_id:
            continue

        if asset_id not in positions:
            positions[asset_id] = {
                'asset_id': asset_id,
                'outcome': outcome,
                'total_bought': 0,
                'total_sold': 0,
            }

        if side == 'BUY':
            positions[asset_id]['total_bought'] += size
        elif side == 'SELL':
            positions[asset_id]['total_sold'] += size

    # Filter for open positions
    return [p for p in positions.values()
            if p['total_bought'] - p['total_sold'] > 0.01]
```

## Verification

**1. Compare tracked positions to on-chain balances:**
```python
for pos in positions:
    on_chain = ctf.functions.balanceOf(wallet, int(pos.token_id)).call() / 1e6
    if abs(on_chain - pos.size) > 0.1:
        print(f"MISMATCH: tracked={pos.size}, on-chain={on_chain}")
```

**2. After fix, on-chain should match tracked:**
```
✓ MATCH | Yes | Track:    50.13 | Chain:    50.13
✓ MATCH | Yes | Track:    62.55 | Chain:    62.55
```

## Example

**Before fix (using trade.asset_id):**
```
Tracked: 167.92 NO tokens
On-chain: 0.00 NO tokens  ← WRONG TOKEN ID
Redemption: TX succeeds, $0 received
```

**After fix (using maker_order.asset_id):**
```
Tracked: 62.55 YES tokens
On-chain: 62.55 YES tokens  ← CORRECT
Redemption: TX succeeds, $62.55 received
```

## Notes

1. **Both asset_id AND side must come from maker_order**: If you only fix asset_id but
   still use trade.side, BUY trades get recorded as SELLs.

2. **Not all MAKER trades have mismatched IDs**: Some trades have matching asset_ids.
   The code handles both cases.

3. **TAKER trades are correct**: Only MAKER trades in neg-risk markets have this issue.

4. **Silent redemption failure**: If you track the wrong token ID and call
   `redeemPositions`, the TX succeeds but nothing happens (no revert, no transfer).
   This is extremely confusing - always verify on-chain balances first.

5. **Price can still come from maker_order**: For accurate entry prices, use
   `maker_order.price` (your actual fill price).

6. **CRITICAL: Apply this fix EVERYWHERE you aggregate trades**: This bug will recur
   in any code that loops through trades and uses `trade.side` or `trade.asset_id`.
   Common places that need this fix:
   - Position tracking (`fetch_positions_from_trades`)
   - Short collateral calculation (`get_active_short_collateral`)
   - P&L calculation
   - Trade history analysis

   **Real example**: `get_active_short_collateral()` was incorrectly tracking LONG
   positions as SHORTs, showing $190 collateral locked when actual was $8.73. This
   caused "not enough balance / allowance" errors despite having $89 USDC in wallet.

7. **Symptoms of unfixed code in collateral tracking**:
   - "not enough balance / allowance" errors on SELL orders
   - Short collateral exceeds wallet balance (mathematically impossible)
   - SELL orders blocked despite sufficient USDC

## Related Skills

- `polymarket-ctf-allowance-fix` - Missing ERC-1155 approvals
- `polymarket-short-collateral-preflight` - Short position collateral tracking

## References

- [Polymarket CLOB Documentation](https://docs.polymarket.com/)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
