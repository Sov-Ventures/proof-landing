#!/usr/bin/env python3
"""
ZER-1305 / ZER-1422: OKX Funding Rate Arb Position Monitor
with Borrow Rate Circuit Breaker.

Monitors active funding-rate arb positions on OKX and triggers
an automatic exit when borrow rates spike above the configured
circuit breaker threshold (default: 50% APR).

Usage:
    python3 ZER-1305-position-monitor.py [--dry-run] [--config CONFIG_PATH]

Designed to run on an 8-hour schedule aligned with OKX funding settlements.
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(WORKSPACE, "ZER-1305-funding-arb-config.json")
OKX_BASE = "https://www.okx.com"

# Paperclip alert settings (read from env or config)
PAPERCLIP_API_URL = os.environ.get("PAPERCLIP_API_URL", "")
PAPERCLIP_API_KEY = os.environ.get("PAPERCLIP_API_KEY", "")
PAPERCLIP_COMPANY_ID = os.environ.get("PAPERCLIP_COMPANY_ID", "")

# ---------------------------------------------------------------------------
# OKX Public API helpers (no auth needed for public endpoints)
# ---------------------------------------------------------------------------

def get_current_borrow_rate(currency: str) -> dict:
    """Fetch the current lending/borrow rate for a currency on OKX.

    Returns dict with daily_rate, apr_pct, and quota.
    Uses the public interest-rate-loan-quota endpoint.
    """
    url = f"{OKX_BASE}/api/v5/public/interest-rate-loan-quota"
    resp = requests.get(url, timeout=10)
    data = resp.json()

    if data.get("code") != "0":
        raise RuntimeError(f"OKX API error: {data}")

    for item in data.get("data", []):
        for detail in item.get("basic", []):
            if detail.get("ccy", "").upper() == currency.upper():
                daily_rate = float(detail.get("rate", 0))
                return {
                    "currency": currency.upper(),
                    "daily_rate": daily_rate,
                    "apr_pct": daily_rate * 365 * 100,
                    "quota": float(detail.get("quota", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

    return {
        "currency": currency.upper(),
        "daily_rate": 0,
        "apr_pct": 0,
        "quota": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": f"Currency {currency} not found in lending markets",
    }


def get_current_funding_rate(inst_id: str) -> dict:
    """Fetch the current and next funding rate for an instrument."""
    url = f"{OKX_BASE}/api/v5/public/funding-rate"
    params = {"instId": inst_id}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    if data.get("code") != "0" or not data.get("data"):
        raise RuntimeError(f"OKX funding rate error for {inst_id}: {data}")

    rec = data["data"][0]
    raw_current = rec.get("fundingRate", "") or "0"
    raw_next = rec.get("nextFundingRate", "") or "0"
    current_rate = float(raw_current)
    next_rate = float(raw_next)

    return {
        "inst_id": inst_id,
        "current_rate_8h": current_rate,
        "current_apr_pct": current_rate * 3 * 365 * 100,
        "next_rate_8h": next_rate,
        "next_apr_pct": next_rate * 3 * 365 * 100,
        "funding_time": rec.get("fundingTime", ""),
        "next_funding_time": rec.get("nextFundingTime", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Circuit breaker evaluation
# ---------------------------------------------------------------------------

def evaluate_circuit_breaker(
    borrow_data: dict,
    funding_data: dict,
    config: dict,
) -> dict:
    """Check if any circuit breaker conditions are met.

    Returns dict with 'triggered' bool, 'reason', and 'details'.
    """
    cb_config = config.get("circuit_breakers", {})

    # --- Borrow rate circuit breaker ---
    borrow_cb = cb_config.get("borrow_rate", {})
    threshold = borrow_cb.get("threshold_apr_pct", 50.0)
    current_apr = borrow_data.get("apr_pct", 0)

    if current_apr > threshold:
        return {
            "triggered": True,
            "breaker": "borrow_rate",
            "reason": (
                f"Borrow rate {current_apr:.1f}% APR exceeds "
                f"circuit breaker threshold {threshold:.1f}% APR"
            ),
            "details": {
                "current_borrow_apr_pct": current_apr,
                "threshold_apr_pct": threshold,
                "borrow_data": borrow_data,
                "funding_data": funding_data,
            },
        }

    # --- (Future) Funding flip circuit breaker ---
    # This requires tracking consecutive periods — stateful, not yet implemented.
    # Placeholder for ZER-1422 follow-up.

    return {
        "triggered": False,
        "breaker": None,
        "reason": "All circuit breakers clear",
        "details": {
            "current_borrow_apr_pct": current_apr,
            "threshold_apr_pct": threshold,
            "headroom_pct": threshold - current_apr,
            "borrow_data": borrow_data,
            "funding_data": funding_data,
        },
    }


# ---------------------------------------------------------------------------
# Paperclip alert (post comment to ZER-1305 when CB triggers)
# ---------------------------------------------------------------------------

def post_circuit_breaker_alert(
    issue_identifier: str,
    cb_result: dict,
    asset: str,
    dry_run: bool = False,
) -> bool:
    """Post a comment on the specified issue when the circuit breaker fires.

    Returns True if comment posted (or dry-run).
    """
    borrow_apr = cb_result["details"]["current_borrow_apr_pct"]
    threshold = cb_result["details"]["threshold_apr_pct"]
    funding = cb_result["details"].get("funding_data", {})
    funding_apr = funding.get("current_apr_pct", 0)

    comment_body = (
        f"## Circuit Breaker Triggered: {asset}\n\n"
        f"**Borrow rate circuit breaker fired** — exiting position.\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Asset | {asset} |\n"
        f"| Current borrow APR | {borrow_apr:.1f}% |\n"
        f"| CB threshold | {threshold:.1f}% |\n"
        f"| Current funding APR | {funding_apr:.1f}% |\n"
        f"| Time (UTC) | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} |\n\n"
        f"**Action:** Close short perp, repay loan, unwind spot hedge.\n\n"
        f"Rationale: Stressed-regime borrow spikes wipe out funding income. "
        f"V2 Monte Carlo shows ~80% APR mean borrow in stressed regimes "
        f"(see `reports/ZER-1305-monte-carlo-v2-regime-switching-2026-04-29.md`).\n\n"
        f"_Triggered by [ZER-1422](/ZER/issues/ZER-1422) borrow rate circuit breaker._"
    )

    if dry_run:
        print(f"\n[DRY RUN] Would post to {issue_identifier}:\n")
        print(comment_body)
        return True

    if not (PAPERCLIP_API_URL and PAPERCLIP_API_KEY and PAPERCLIP_COMPANY_ID):
        print("[WARN] Paperclip env vars not set — cannot post alert comment.")
        print(f"[WARN] Alert body:\n{comment_body}")
        return False

    # Search for issue by identifier to get its ID
    try:
        search_resp = requests.get(
            f"{PAPERCLIP_API_URL}/api/companies/{PAPERCLIP_COMPANY_ID}/issues",
            params={"q": issue_identifier},
            headers={"Authorization": f"Bearer {PAPERCLIP_API_KEY}"},
            timeout=10,
        )
        issues = search_resp.json().get("issues", [])
        target = next(
            (i for i in issues if i.get("identifier") == issue_identifier), None
        )
        if not target:
            print(f"[WARN] Could not find issue {issue_identifier}")
            return False

        issue_id = target["id"]
        comment_resp = requests.post(
            f"{PAPERCLIP_API_URL}/api/issues/{issue_id}/comments",
            headers={
                "Authorization": f"Bearer {PAPERCLIP_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"body": comment_body},
            timeout=10,
        )
        if comment_resp.status_code in (200, 201):
            print(f"[OK] Alert posted to {issue_identifier}")
            return True
        else:
            print(f"[WARN] Failed to post alert: {comment_resp.status_code}")
            return False
    except Exception as e:
        print(f"[ERROR] Alert post failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main monitor loop (single check — designed for cron/scheduled execution)
# ---------------------------------------------------------------------------

def run_monitor(config_path: str, dry_run: bool = False) -> dict:
    """Run a single monitoring check for all configured assets.

    Returns a summary dict with per-asset results.
    """
    with open(config_path) as f:
        config = json.load(f)

    assets = config.get("constraints", {}).get("allowed_assets", [])
    alert_issue = config.get("monitoring", {}).get("alert_issue_id", "ZER-1305")
    results = {}

    print("=" * 70)
    print(f"OKX Funding Arb Position Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Config: {config_path}")
    print(f"Assets: {', '.join(assets)}")
    print(f"Borrow CB threshold: {config['circuit_breakers']['borrow_rate']['threshold_apr_pct']}% APR")
    print("=" * 70)

    for asset in assets:
        inst_id = f"{asset}-USDT-SWAP"
        print(f"\n--- {asset} ({inst_id}) ---")

        try:
            borrow = get_current_borrow_rate(asset)
            print(f"  Borrow rate: {borrow['apr_pct']:.1f}% APR (daily: {borrow['daily_rate']*100:.4f}%)")
            if borrow.get("error"):
                print(f"  [WARN] {borrow['error']}")
        except Exception as e:
            print(f"  [ERROR] Failed to fetch borrow rate: {e}")
            results[asset] = {"error": str(e)}
            continue

        try:
            funding = get_current_funding_rate(inst_id)
            print(f"  Funding rate: {funding['current_apr_pct']:.1f}% APR ({funding['current_rate_8h']*100:.4f}%/8h)")
            print(f"  Next funding: {funding['next_apr_pct']:.1f}% APR ({funding['next_rate_8h']*100:.4f}%/8h)")
        except Exception as e:
            print(f"  [ERROR] Failed to fetch funding rate: {e}")
            results[asset] = {"error": str(e)}
            continue

        # Evaluate circuit breaker
        cb = evaluate_circuit_breaker(borrow, funding, config)
        results[asset] = cb

        if cb["triggered"]:
            print(f"\n  *** CIRCUIT BREAKER TRIGGERED: {cb['reason']} ***")
            print(f"  Action: EXIT POSITION (close short, repay loan)")
            post_circuit_breaker_alert(alert_issue, cb, asset, dry_run=dry_run)
        else:
            headroom = cb["details"]["headroom_pct"]
            print(f"  Status: CLEAR (headroom: {headroom:.1f}% APR to CB threshold)")

        # Net arb calculation
        net_arb = abs(funding["current_apr_pct"]) - borrow["apr_pct"]
        print(f"  Net arb: {net_arb:+.1f}% APR")

    # Summary
    print("\n" + "=" * 70)
    triggered = [a for a, r in results.items() if r.get("triggered")]
    if triggered:
        print(f"ALERT: Circuit breaker triggered for: {', '.join(triggered)}")
    else:
        print("All positions clear — no circuit breaker triggered.")
    print("=" * 70)

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OKX Funding Rate Arb Position Monitor with Borrow Rate Circuit Breaker"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Path to strategy config JSON (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run checks but don't post alerts or execute exits",
    )
    args = parser.parse_args()

    results = run_monitor(args.config, dry_run=args.dry_run)

    # Exit code: 1 if any circuit breaker triggered (useful for cron alerting)
    any_triggered = any(r.get("triggered") for r in results.values())
    sys.exit(1 if any_triggered else 0)
