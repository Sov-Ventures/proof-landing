---
name: polymarket-ctf-allowance-fix
description: |
  Fix for Polymarket "not enough balance / allowance" API error (status_code=400) when placing orders.
  Use when: (1) orders fail with "not enough balance / allowance" despite having USDC in wallet,
  (2) API get_balance_allowance shows Allowance: $0 but Balance is correct, (3) on-chain USDC
  approvals are set but trading still fails, (4) recently added new exchange contracts like
  CTF Exchange V2. Root cause: missing CTF (ERC-1155) setApprovalForAll approvals for exchange
  contracts. Applies to py-clob-client, Polymarket trading bots, and any CLOB API integration.
author: Claude Code
version: 1.0.0
date: 2026-01-28
---

# Polymarket CTF Allowance Fix

## Problem
Polymarket API returns `PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]` when placing orders, even though:
- Wallet has sufficient USDC balance
- On-chain USDC (ERC-20) allowances are set to max for all exchange contracts
- API credentials are valid and API balance shows correct funds

## Context / Trigger Conditions

**Error message:**
```
PolyApiException[status_code=400, error_message={'error': 'not enough balance / allowance'}]
```

**Symptoms:**
- `client.get_balance_allowance()` shows `Allowance: $0.00` but `Balance: $X.XX` is correct
- On-chain USDC allowances are infinite (2^256-1) for all contracts
- Orders fail immediately without being placed on the order book
- Smaller orders ($5) may work while larger orders fail

## Root Cause

Polymarket requires **TWO types of on-chain approvals**:

1. **USDC (ERC-20) approvals** - `approve(spender, amount)` on USDC contract
   - Contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (USDC.e on Polygon)

2. **CTF (ERC-1155) approvals** - `setApprovalForAll(operator, true)` on CTF contract
   - Contract: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` (Conditional Token Framework)

Most setup scripts only configure USDC approvals, missing the CTF approvals entirely.

## Solution

### Step 1: Identify Required Contracts

All these exchange contracts need BOTH USDC and CTF approvals:

```python
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"        # CTF Exchange
CTF_EXCHANGE_V2 = "0xdFE02Eb6733538f8Ea35D585af8DE5958AD99E40"    # CTF Exchange V2
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"  # Neg Risk Exchange
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"      # Neg Risk Adapter
```

### Step 2: Set CTF Approvals

```python
from web3 import Web3

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

ERC1155_ABI = [
    {
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "operator", "type": "address"}
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    }
]

ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI)

# Check if already approved
is_approved = ctf.functions.isApprovedForAll(wallet_address, exchange_address).call()

if not is_approved:
    tx = ctf.functions.setApprovalForAll(exchange_address, True).build_transaction({
        'from': wallet_address,
        'nonce': w3.eth.get_transaction_count(wallet_address),
        'gas': 100000,
        'chainId': 137
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
```

### Step 3: Verify with Test Order

The API "allowance" field may still show $0 after approvals. Test with an actual order:

```python
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

order = OrderArgs(token_id=token_id, price=0.01, size=5.0, side=BUY)
signed = client.create_order(order)
response = client.post_order(signed, OrderType.GTC)
client.cancel(response['orderID'])  # Cancel test order immediately
```

If this succeeds, approvals are correctly set regardless of what the API shows.

## Verification

1. Run `isApprovedForAll()` for each exchange contract - all should return `True`
2. Place and cancel a small test order - should succeed without balance/allowance error
3. Check PolygonScan for approval transactions on the CTF contract

## Example

Complete allowance setup script that handles both USDC and CTF:

```python
# Key contracts
USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

exchanges = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # CTF Exchange
    "0xdFE02Eb6733538f8Ea35D585af8DE5958AD99E40",  # CTF Exchange V2
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg Risk CTF Exchange
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg Risk Adapter
]

for exchange in exchanges:
    # 1. Approve USDC (ERC-20)
    usdc.functions.approve(exchange, 2**256-1).transact()

    # 2. Approve CTF (ERC-1155) - THIS IS THE COMMONLY MISSED STEP
    ctf.functions.setApprovalForAll(exchange, True).transact()
```

## Notes

- The API `allowance` field is misleading - it may show $0 even when on-chain approvals are set
- New exchange contracts (like CTF Exchange V2) require both approval types
- These approvals only need to be set once per wallet per contract
- Use signature_type=0 for EOA wallets when checking balance/allowance via API
- Transaction timeout for approvals should be at least 300 seconds on Polygon during congestion

## References

- [GitHub Issue #109 - Not Enough Balance / Allowance Error](https://github.com/Polymarket/py-clob-client/issues/109)
- [GitHub Issue #95 - No information on how to increase allowance](https://github.com/Polymarket/py-clob-client/issues/95)
- [Poly-rodr Allowance Gist](https://gist.github.com/poly-rodr/44313920481de58d5a3f6d1f8226bd5e)
