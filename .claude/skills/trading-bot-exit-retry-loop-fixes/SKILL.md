---
name: trading-bot-exit-retry-loop-fixes
description: |
  Fix infinite order retry loops in trading bots. Use when: (1) failed orders
  retry every cycle indefinitely (same market appears 6-8+ times per second in
  logs), (2) order API rejects prices outside valid range (e.g., "price (0.999),
  min: 0.01 - max: 0.99"), (3) "not enough balance" errors on phantom positions
  with zero on-chain token balance. Covers price clamping, circuit breaker attempt
  tracking, and on-chain balance verification before order submission.
author: Claude Code
version: 1.0.0
date: 2026-02-21
---

# Trading Bot Exit Retry Loop Fixes

## Problem

Trading bot exit/close loops can get stuck in infinite retries when handling orphan
positions (markets no longer in fetch window). Three interrelated bugs cause cascading
failures: (1) unclamped prices rejected by API, (2) no tracking of failed attempts
causes rapid retries, (3) phantom positions with zero on-chain balance retry forever
because the exchange has them but the blockchain doesn't.

Symptom: Same market IDs appear 6-8+ times per second in logs; bot cannot exit positions;
logs show repeated errors like `Order failed: price (0.999), min: 0.01 - max: 0.99` and
`PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]`.

## Context / Trigger Conditions

**When to apply these fixes:**

1. **Price validation errors**: API returns `"price (X.XXX), min: 0.01 - max: 0.99"`
   because exit prices from order books are submitted unclamped (e.g., 0.999 or 0.001)

2. **Infinite retry loops**: Same position/market retried every cycle with no limit;
   logs show identical exit attempts repeated within seconds with no progress

3. **Phantom positions**: "not enough balance / allowance" errors persist for specific
   positions even though wallet has capital; on-chain token balance is actually 0

4. **Orphan market handling**: Bot attempts to close positions when market is no longer
   in the fetch window; uses fallback order book pricing

**Environment:**
- Polymarket or similar CLOB exchange with price bounds [0.01, 0.99]
- SQLite position tracking with on-chain blockchain verification (Polygon/Ethereum)
- Worker process loop that evaluates exits on every cycle

## Solution

### Fix 1: Price Clamping

Add constants and helper function to enforce API price bounds on all exit order paths:

```python
MIN_PRICE = 0.01
MAX_PRICE = 0.99

def _clamp_price(price: float) -> float:
    """Clamp price to exchange's accepted range."""
    return max(MIN_PRICE, min(MAX_PRICE, round(price, 4)))
```

Apply clamping to:
- Order book prices in orphan exit path (both bids and asks)
- Market order prices (MARKET order type)
- Limit order calculations (before rounding)
- Default fallthrough price

**Key insight:** The LIMIT and LIMIT_CROSS branches may already have inline clamping
(e.g., `min(0.99, price + offset)`), so consolidate all price logic through the helper.

### Fix 2: Circuit Breaker for Failed Attempts

Add in-memory attempt tracking (per-process, resets on restart):

```python
MAX_EXIT_ATTEMPTS = 3
_exit_attempts: dict[int, int] = {}  # position_id -> attempt count

# In exit loop, before evaluating position:
if _exit_attempts.get(pos.id, 0) >= MAX_EXIT_ATTEMPTS:
    continue  # Skip this position

# After submit_order() fails:
else:
    attempts = _exit_attempts.get(pos.id, 0) + 1
    _exit_attempts[pos.id] = attempts
    if attempts >= MAX_EXIT_ATTEMPTS:
        logger.warning(
            "EXIT CIRCUIT BREAKER | market=%s | giving up after %d attempts",
            pos.market_id[:16], attempts,
        )

# After successful exit:
_exit_attempts.pop(pos.id, None)
```

**Why in-memory:** Avoids database schema changes. Resets on process restart, which
is acceptable—a restart is a reset event that can legitimately warrant retrying failed
exits.

**Configurable:** Adjust `MAX_EXIT_ATTEMPTS` based on risk tolerance (3-5 is typical).

### Fix 3: Phantom Position Detection

Add on-chain balance verification before attempting order:

**In exchange adapter (e.g., PolymarketExchange):**

```python
def get_ctf_balance(self, token_id: str) -> int | None:
    """Check on-chain CTF token balance for the wallet.

    Returns raw balance (divide by 1e6 for USDC equivalent), or None on error.
    """
    if self._w3 is None or self._wallet is None:
        return None
    try:
        ctf = self._w3.eth.contract(
            address=Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"),
            abi=[{"inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}],
                  "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
                  "stateMutability": "view", "type": "function"}],
        )
        return ctf.functions.balanceOf(self._wallet, int(token_id)).call()
    except Exception as e:
        logger.debug(f"CTF balance check failed for {token_id[:16]}...: {e}")
        return None
```

**In worker exit loop, before constructing exit order:**

```python
# Phantom position check: verify on-chain balance before attempting exit
if hasattr(exchange, 'get_ctf_balance'):
    ctf_balance = exchange.get_ctf_balance(pos.token_id)
    if ctf_balance is not None and ctf_balance == 0:
        logger.warning(
            "PHANTOM | market=%s | no on-chain balance — closing in DB",
            pos.market_id[:16],
        )
        store.record_exit(pos.id, pos.entry_price, 0.0,
                         exit_reason="phantom_no_balance")
        _exit_attempts.pop(pos.id, None)
        continue
```

**Why this works:**
- Reuses existing Web3 connection and contract patterns from settlement code
- Gracefully handles exchanges without on-chain verification (via `hasattr` guard)
- Closes phantom positions in DB with clear exit_reason for audit trail
- Clears attempt counter so retry budget isn't wasted

**On-chain contract addresses (Polygon):**
- CTF: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- USDC: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`

## Verification

1. **Price clamping**: Confirm no more "price (X.XXX), min: 0.01 - max: 0.99" errors
   - Verify exit prices logged are within [0.01, 0.99] range
   - Test with order book prices at extremes (0.001, 0.999)

2. **Circuit breaker**: Confirm same position/market stops retrying after 3 failures
   - Check logs for `EXIT CIRCUIT BREAKER` message
   - Verify position is skipped in subsequent cycles
   - Confirm orphan positions don't fill 6-8 lines of logs per cycle

3. **Phantom detection**: Confirm phantom positions are closed without order attempts
   - Check logs for `PHANTOM | market=... | no on-chain balance — closing in DB`
   - Verify no `Order failed: ... not enough balance / allowance` follows
   - Confirm DB shows exit_reason='phantom_no_balance' for these positions

## Example

**Before fix:**
```
2026-02-21 18:41:58,345 | INFO | Orphan exit price for 0xc78dbd2... 0.8400 (from order book)
Order failed: PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]
2026-02-21 18:41:59,066 | INFO | Orphan exit price for 0xc78dbd2... 0.8400 (from order book)  # ← retried 1s later
Order failed: PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]
2026-02-21 18:42:00,233 | INFO | Orphan exit price for 0xc78dbd2... 0.8400 (from order book)  # ← retried again
Order failed: PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]
```

**After fix:**
```
2026-02-21 18:41:58,345 | INFO | Orphan exit price for 0xc78dbd2... 0.8400 (from order book)
2026-02-21 18:41:58,350 | WARNING | PHANTOM | market=0xc78dbd2... | no on-chain balance — closing in DB
2026-02-21 18:41:59,066 | (position skipped — circuit breaker, attempt 1/3)
2026-02-21 18:42:00,233 | (position skipped — circuit breaker, attempt 2/3)
```

## Notes

### Edge Cases

1. **Read-only mode**: If exchange is initialized without `PRIVATE_KEY`, `get_ctf_balance()`
   returns None safely (guarded by `hasattr`). Phantom check is skipped.

2. **Non-orphan failures**: Circuit breaker applies to ALL failed exits, not just orphans.
   This is correct—if a normal market exit fails 3 times, something is wrong and we should
   stop retrying.

3. **Stale positions**: If a position becomes phantom months after entry (market resolved,
   tokens redeemed elsewhere), the phantom check catches it. This is a recovery mechanism,
   not a prevention mechanism.

4. **Token count division**: CTF balance is returned as raw integer from contract. For
   human-readable counts, divide by 1e6 (ERC-1155 uses 6 decimals). The check only cares
   if balance == 0, so no division needed.

5. **RPC failures**: If Polygon RPC is down, `get_ctf_balance()` returns None and phantom
   check is skipped. Exit attempt proceeds, likely fails, and circuit breaker increments.

### Configuration

```python
MAX_EXIT_ATTEMPTS = 3  # Adjust per strategy
MIN_PRICE = 0.01       # Exchange-specific, don't change for Polymarket
MAX_PRICE = 0.99       # Exchange-specific, don't change for Polymarket
```

### Performance Impact

- **Price clamping**: O(1), minimal overhead
- **Circuit breaker**: O(1) dict lookup per position per cycle; negligible
- **Phantom check**: O(1) on-chain call per orphan position attempted; ~500ms/call RPC latency
  - Acceptable because it only runs on positions with exit signal, not every position

### Logging

Add clear logging at each step for observability:
- When price is clamped: `"Exit price clamped from %.4f to %.4f"`
- When circuit breaker fires: `"EXIT CIRCUIT BREAKER | market=... | giving up after X attempts"`
- When phantom detected: `"PHANTOM | market=... | no on-chain balance — closing in DB"`

## References

- **Polymarket CLOB API**: Price bounds [0.01, 0.99] enforced at API submission
- **ERC-1155 (Polymarket CTF)**: Used for conditional tokens; `balanceOf(account, id)`
  pattern is standard
- **Polygon RPC**: See environment variables for `POLYGON_RPC` endpoint (default:
  `https://polygon-bor-rpc.publicnode.com`)
- **Similar pattern in codebase**: `settle.py` demonstrates CTF balance checking
  and on-chain payout verification; reuse the same contract interaction patterns

## Related Skills

- **Polymarket CTF Allowance Fix**: For "not enough balance" errors related to missing
  `setApprovalForAll` on CTF contracts (different from phantom positions)
- **Polymarket Silent Redemption Failure**: For redemptions that succeed (tx status=1)
  but transfer no USDC (related phantom position root cause)
