---
name: polymarket-silent-redemption-failure
description: |
  Debugging and PREVENTING Polymarket redemption transactions that succeed (status=1) but transfer
  no USDC. Use when: (1) redeemPositions TX shows SUCCESS but wallet balance unchanged, (2) gas used
  is minimal (~44k) compared to successful redemptions (~80k+), (3) TX has only 2 events instead of
  3+ including USDC Transfer, (4) position tracking shows tokens but on-chain balance is 0,
  (5) "phantom" positions appear redeemable after previous redemption sessions. Root cause: trade
  history tracks ALL historical trades but doesn't account for previous redemptions. Solution:
  verify on-chain balance BEFORE marking positions as redeemable.
author: Claude Code
version: 2.0.0
date: 2026-01-28
---

# Polymarket Silent Redemption Failure

## Problem

When calling `redeemPositions` on the Polymarket CTF (Conditional Tokens Framework) contract,
the transaction can succeed (status=1) but transfer zero USDC. This is extremely confusing
because:
- TX shows "SUCCESS" on-chain
- No error is thrown
- Gas is consumed
- But wallet balance doesn't change

## Context / Trigger Conditions

**Symptoms:**
- `redeemPositions` TX shows status=1 (success)
- Wallet USDC balance unchanged after "successful" redemption
- Gas used is low (~44,000 gas vs ~80,000+ for real redemptions)
- TX logs show only 2 events (no USDC Transfer event)

**Example misleading output:**
```
2026-01-28 13:27:25 | TX sent: 2876577cb22eced6...
2026-01-28 13:27:28 | ✓ Redemption successful! Gas used: 44152
# But wallet balance: $130.80 → $130.80 (no change!)
```

**When this happens:**
- Position tracking shows tokens exist (from trade history)
- But on-chain balance is actually 0
- Common when position tracking has bugs (see `polymarket-negrisk-position-tracking`)

## Root Cause

The CTF `redeemPositions` function does NOT revert when called with zero token balance.
It successfully executes but simply transfers nothing:

```solidity
// Simplified logic
function redeemPositions(collateral, parentId, conditionId, indexSets) {
    for (indexSet in indexSets) {
        uint256 balance = balanceOf(msg.sender, positionId);
        // If balance is 0, this loop does nothing
        if (balance > 0) {
            _burn(msg.sender, positionId, balance);
            collateral.transfer(msg.sender, payout);
        }
    }
    // No revert if nothing happened!
}
```

**Why it doesn't revert:**
- Smart contract design choice - allows batch redemptions where some positions may be empty
- Saves gas on reverts for legitimate "already redeemed" cases
- But creates confusing UX for debugging

## Solution

### Prevention: Verify at Discovery Time (Recommended)

The best fix is to verify on-chain balance when **finding** redeemable positions, not when
redeeming. This prevents phantom positions from ever being marked as redeemable:

```python
def find_redeemable_positions(client: ClobClient) -> list[RedeemablePosition]:
    """Find positions that are ACTUALLY redeemable (verified on-chain)."""
    positions = fetch_positions_from_trades(client)
    redeemable = []

    # Set up CTF contract for balance verification
    CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    CTF_ABI = [{"inputs": [{"name": "account", "type": "address"},
                          {"name": "id", "type": "uint256"}],
               "name": "balanceOf", "outputs": [{"type": "uint256"}],
               "stateMutability": "view", "type": "function"}]
    ctf = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)

    for pos in positions:
        # ... check if market resolved, we won, etc ...

        # CRITICAL: Verify on-chain balance before marking as redeemable
        on_chain_balance = None
        for attempt in range(3):  # Retry for RPC rate limits
            try:
                time.sleep(1.5 + attempt * 2)  # Increasing delay
                raw = ctf.functions.balanceOf(wallet, int(pos.token_id)).call()
                on_chain_balance = raw / 1e6
                break
            except Exception as e:
                if attempt == 2:
                    logger.warning(f"Could not verify {pos.token_id[:20]}...")

        if on_chain_balance is None:
            continue  # Skip unverifiable positions

        if on_chain_balance < 0.5:
            logger.debug(f"Skipping {pos.token_id[:20]}...: on-chain={on_chain_balance:.2f} "
                        f"< tracked={pos.size:.2f} - likely already redeemed")
            continue

        # Use ACTUAL on-chain balance, not tracked position
        redeemable.append(RedeemablePosition(
            position=pos,
            redeemable_value=on_chain_balance,  # Verified balance
            ...
        ))

    return redeemable
```

### Fallback: Verify at Redemption Time

If you can't modify the discovery code, verify before redeeming:

```python
def redeem_position(redeemable: RedeemablePosition, dry_run: bool = True) -> bool:
    # STEP 1: Verify tokens actually exist on-chain
    ctf = web3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
    token_id = int(redeemable.position.token_id)
    on_chain_balance = ctf.functions.balanceOf(wallet, token_id).call()

    if on_chain_balance == 0:
        logger.error(f"Cannot redeem: 0 tokens on-chain for {token_id}")
        logger.error("Position tracking may be incorrect - verify trade data")
        return False

    expected = redeemable.position.size * 1e6  # Convert to raw units
    if abs(on_chain_balance - expected) > 1e4:  # >0.01 token difference
        logger.warning(f"Balance mismatch: tracked={redeemable.position.size}, "
                      f"on-chain={on_chain_balance/1e6}")

    # STEP 2: Proceed with redemption
    if dry_run:
        logger.info(f"[DRY RUN] Would redeem {on_chain_balance/1e6} tokens")
        return True

    # ... actual redemption logic
```

**Verification after redemption:**
```python
# Check USDC balance change
usdc_before = get_usdc_balance(wallet)
tx_receipt = redeem(...)
usdc_after = get_usdc_balance(wallet)

expected_change = redeemable.redeemable_value
actual_change = usdc_after - usdc_before

if actual_change < expected_change * 0.99:  # Allow 1% for fees
    logger.error(f"Redemption may have failed silently!")
    logger.error(f"Expected: ${expected_change:.2f}, Got: ${actual_change:.2f}")
```

## Verification

**How to identify a silent failure:**

1. Check gas used - real redemptions use more gas:
   - Silent failure: ~44,000 gas (just function call overhead)
   - Real redemption: ~80,000+ gas (includes token burn and transfer)

2. Check TX events:
   - Silent failure: 2 events (function call + MATIC fee)
   - Real redemption: 3+ events (includes USDC Transfer)

3. Check wallet balance before/after:
   ```bash
   # Before redemption
   USDC Balance: $130.80

   # After "successful" redemption
   USDC Balance: $130.80  # No change = silent failure
   ```

## Example

**Silent failure (bad):**
```
TX: 0x2876577cb22eced6993329dcb32ec984fd608a1bfec10b1747f2c0d794ddd7f5
Status: SUCCESS
Gas Used: 44,152
Events: 2
  - Log 0: CTF contract event (empty redemption)
  - Log 1: MATIC fee event
USDC Change: $0.00
```

**Real redemption (good):**
```
TX: 0x8f3a2b1c...
Status: SUCCESS
Gas Used: 84,567
Events: 4
  - Log 0: CTF PositionsBurned event
  - Log 1: CTF PayoutRedemption event
  - Log 2: USDC Transfer event ($167.92)
  - Log 3: MATIC fee event
USDC Change: +$167.92
```

## Notes

1. **Trade history ≠ on-chain balance**: Position tracking from `client.get_trades()` shows
   what you traded historically, NOT what you currently hold. Redemptions remove tokens
   without creating sell trades. Always verify on-chain balance.

2. **This is a design feature, not a bug**: The CTF contract intentionally doesn't revert
   on empty redemptions to allow batch operations.

3. **Always check on-chain balance first**: Don't trust position tracking alone.

4. **Common causes of 0 balance:**
   - **Previously redeemed** - Trade history tracks ALL trades forever, but doesn't know
     about redemptions. A position redeemed last week still appears in trade history today.
   - Position tracking bug (see `polymarket-negrisk-position-tracking`)
   - Tokens in different wallet (proxy vs EOA)
   - Lost position (held losing side, tokens burned at $0)

5. **Debugging tip**: Use Polygonscan to inspect TX events. Missing USDC Transfer event
   confirms silent failure.

## Related Skills

- `polymarket-negrisk-position-tracking` - Position tracking bugs causing 0 balance
- `polymarket-ctf-allowance-fix` - Different issue: approvals causing order failures

## References

- [Gnosis Conditional Tokens Framework](https://docs.gnosis.io/conditionaltokens/)
- [Polymarket CTF Contract on Polygonscan](https://polygonscan.com/address/0x4D97DCd97eC945f40cF65F87097ACe5EA0476045)
