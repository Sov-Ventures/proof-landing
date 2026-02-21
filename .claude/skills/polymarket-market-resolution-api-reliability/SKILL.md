---
name: polymarket-market-resolution-api-reliability
description: |
  Fix for Polymarket positions incorrectly marked as INVALID when markets actually resolved
  to YES or NO. Use when: (1) database shows market_outcome='INVALID' but market resolved,
  (2) winning tokens remain unredeemed on-chain, (3) PnL shows $0 for positions that should
  have won, (4) Gamma API returns result=null for closed markets. Root cause: Gamma API
  `result` field is unreliable; use CLOB API `tokens[].winner` or on-chain CTF contract
  `payoutNumerators` instead.
author: Claude Code
version: 1.0.0
date: 2026-02-21
---

# Polymarket Market Resolution API Reliability

## Problem

Polymarket trading bots that use the Gamma API to check market resolution may incorrectly
mark winning positions as INVALID because the Gamma API's `result` field is often null
even for resolved markets. This causes:
- Winning positions marked as INVALID with $0 PnL
- Tokens remaining unredeemed on-chain (real money stuck)
- Settlement logic treating resolved markets as "unknown"

## Context / Trigger Conditions

Use this skill when you see:
- Database records with `market_outcome = 'INVALID'` but the market actually resolved
- Positions with `pnl = 0` that should have won
- On-chain token balances remain positive after "settlement"
- Log messages showing `result=unknown` for clearly resolved markets

**Diagnostic check:**
```python
# Compare API responses for a resolved market
import requests

condition_id = '0x...'

# Gamma API - UNRELIABLE for resolution
gamma = requests.get(f'https://gamma-api.polymarket.com/markets?condition_id={condition_id}').json()
print(f"Gamma result: {gamma[0].get('result')}")  # Often returns None!

# CLOB API - RELIABLE for resolution
clob = requests.get(f'https://clob.polymarket.com/markets/{condition_id}').json()
for token in clob.get('tokens', []):
    print(f"{token['outcome']}: winner={token['winner']}")  # Correctly shows True/False
```

## Solution

### Resolution Priority (Most to Least Reliable)

1. **CLOB API** (`tokens[].winner`) - Primary source
2. **On-chain CTF contract** (`payoutNumerators`) - Ultimate source of truth
3. **Gamma API** (`result`) - Fallback only, often unreliable

### Implementation

```python
def get_market_result(self, market_id: str) -> str | None:
    """Check if market resolved. Returns 'yes'/'no' if resolved, None if open."""

    # Primary: CLOB API has reliable winner data
    try:
        resp = requests.get(f"https://clob.polymarket.com/markets/{market_id}", timeout=10)
        if resp.status_code == 200:
            m = resp.json()
            if m.get("closed"):
                for token in m.get("tokens", []):
                    if token.get("winner") is True:
                        outcome = token.get("outcome", "").lower()
                        if outcome in ("yes", "no"):
                            return outcome
                # Closed but no winner - check on-chain
                return self._get_onchain_result(market_id)
            return None  # Still open
    except Exception:
        pass

    # Fallback: On-chain verification
    return self._get_onchain_result(market_id)


def _get_onchain_result(self, condition_id: str) -> str | None:
    """Check CTF contract for resolution (ultimate truth)."""
    CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

    ctf = w3.eth.contract(address=CTF_ADDRESS, abi=[
        {"inputs": [{"name": "", "type": "bytes32"}],
         "name": "payoutDenominator", "outputs": [{"name": "", "type": "uint256"}],
         "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "", "type": "bytes32"}, {"name": "", "type": "uint256"}],
         "name": "payoutNumerators", "outputs": [{"name": "", "type": "uint256"}],
         "stateMutability": "view", "type": "function"},
    ])

    cond_bytes = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)

    denom = ctf.functions.payoutDenominator(cond_bytes).call()
    if denom == 0:
        return None  # Not resolved on-chain

    # Index 0 = YES, Index 1 = NO
    yes_payout = ctf.functions.payoutNumerators(cond_bytes, 0).call()
    no_payout = ctf.functions.payoutNumerators(cond_bytes, 1).call()

    if yes_payout > 0 and no_payout == 0:
        return "yes"
    elif no_payout > 0 and yes_payout == 0:
        return "no"
    return "unknown"
```

## Verification

After implementing the fix:

```python
# Test with a known resolved market
result = exchange.get_market_result("0x...")
assert result in ("yes", "no"), f"Expected yes/no, got {result}"

# Verify on-chain balance is 0 after proper redemption
balance = ctf.functions.balanceOf(wallet, token_id).call()
assert balance == 0, "Tokens should be redeemed"
```

## Example

**Before (broken):**
```
Market: Will SOL be above $80 on Feb 19?
Gamma API: result=None, closed=True
Code returns: "unknown" → marked INVALID
Result: 182 winning tokens stuck unredeemed ($182 lost)
```

**After (fixed):**
```
Market: Will SOL be above $80 on Feb 19?
CLOB API: tokens[0].winner=True, tokens[0].outcome="Yes"
Code returns: "yes"
Result: Tokens properly settled, can be redeemed for USDC
```

## Notes

- The Polymarket Data API (`data-api.polymarket.com/positions`) has a `redeemable` field
  that correctly identifies positions ready for on-chain redemption
- Always verify on-chain balance before attempting redemption (phantom positions exist)
- Add automatic redemption to your worker loop to prevent funds from getting stuck
- The CLOB API endpoint format is `/markets/{condition_id}` (not query params)

## Related Issues

- Positions may be marked "settled" in database but tokens remain on-chain
- Consider adding periodic auto-redemption (every 10 min) to worker loops
- Use `ctf.functions.balanceOf(wallet, token_id)` to verify actual on-chain holdings
