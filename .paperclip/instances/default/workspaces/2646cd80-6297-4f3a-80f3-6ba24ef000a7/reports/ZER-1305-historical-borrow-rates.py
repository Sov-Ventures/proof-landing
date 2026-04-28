#!/usr/bin/env python3
"""
ZER-1305 Follow-up: Fetch historical borrow rates from OKX to make
apples-to-apples comparison with historical funding rates.
Uses /api/v5/finance/savings/lending-rate-history endpoint.
"""

import requests
import time
import json
from datetime import datetime, timedelta

BASE_URL = "https://www.okx.com"

# Top arb candidates from initial analysis
TOP_COINS = [
    "AXS", "BARD", "ONT", "ENJ", "ZIL", "FLOW", "ZORA", "ICP",
    "HUMA", "BLUR", "ZK", "BERA", "POL", "AVNT", "AUCTION",
    "COMP", "IP", "MOVE", "SNX", "OKB", "SUI"
]

def get_lending_rate_history(ccy, days=365):
    """Fetch historical lending/borrow rates. Returns hourly data points."""
    all_rates = []
    after = ""
    cutoff = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

    for _ in range(50):  # Up to 50 pages
        url = f"{BASE_URL}/api/v5/finance/savings/lending-rate-history"
        params = {"ccy": ccy, "limit": "100"}
        if after:
            params["after"] = after

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"  Error: {e}")
            break

        if data.get("code") != "0" or not data.get("data"):
            break

        records = data["data"]
        for r in records:
            ts = int(r.get("ts", 0))
            if ts < cutoff:
                # Add remaining valid records
                valid = [rec for rec in records if int(rec.get("ts", 0)) >= cutoff]
                all_rates.extend(valid)
                return all_rates
            all_rates.append(r)

        after = records[-1].get("ts", "")
        if len(records) < 100:
            break

        time.sleep(0.15)

    return all_rates

def analyze_borrow_rates(rates):
    """Analyze borrow rate history."""
    if not rates:
        return None

    # 'rate' field is the annualized rate as a FRACTION (0.39 = 39% APR)
    # Confirmed by cross-referencing with /api/v5/public/interest-rate-loan-quota
    # which returns daily rate; daily * 365 = this rate value
    annualized_rates = []
    for r in rates:
        rate_val = float(r.get("rate", 0)) * 100  # Convert fraction to percentage
        annualized_rates.append(rate_val)

    if not annualized_rates:
        return None

    avg_rate = sum(annualized_rates) / len(annualized_rates)
    sorted_rates = sorted(annualized_rates)
    mid = len(sorted_rates) // 2
    median_rate = sorted_rates[mid] if len(sorted_rates) % 2 == 1 else (sorted_rates[mid-1] + sorted_rates[mid]) / 2
    max_rate = max(annualized_rates)
    min_rate = min(annualized_rates)

    # Time span
    timestamps = [int(r["ts"]) for r in rates]
    days_covered = (max(timestamps) - min(timestamps)) / (1000 * 86400) if len(timestamps) > 1 else 0

    return {
        "num_samples": len(annualized_rates),
        "days_covered": days_covered,
        "avg_annualized_pct": avg_rate,
        "median_annualized_pct": median_rate,
        "max_annualized_pct": max_rate,
        "min_annualized_pct": min_rate,
        "std_dev": (sum((r - avg_rate)**2 for r in annualized_rates) / len(annualized_rates)) ** 0.5,
    }

def main():
    print("=" * 80)
    print("ZER-1305: Historical Borrow Rate Comparison")
    print(f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    # Load funding rate data from prior analysis
    data_path = "/Users/abreckler/.paperclip/instances/default/workspaces/2646cd80-6297-4f3a-80f3-6ba24ef000a7/reports/ZER-1305-okx-funding-borrow-arb-data.json"
    with open(data_path) as f:
        prior_data = json.load(f)

    # Build lookup for funding APR
    funding_lookup = {}
    for r in prior_data.get("shitcoin_results", []) + prior_data.get("major_results", []):
        funding_lookup[r["coin"]] = r["funding_apr_pct"]

    print(f"\nFetching historical borrow rates for {len(TOP_COINS)} top candidates...")
    print("(Hourly data, paginated, may take a minute)\n")

    results = []

    for i, coin in enumerate(TOP_COINS):
        print(f"  [{i+1}/{len(TOP_COINS)}] {coin}...", end="", flush=True)
        rates = get_lending_rate_history(coin, days=365)
        stats = analyze_borrow_rates(rates)

        if stats:
            funding_apr = funding_lookup.get(coin, 0)
            hist_borrow_apr = stats["avg_annualized_pct"]

            # Recalculate net arb with historical borrow rate
            if funding_apr < 0:
                net_arb = abs(funding_apr) - hist_borrow_apr
                direction = "Long Perp + Short Spot"
            else:
                net_arb = funding_apr - hist_borrow_apr
                direction = "Short Perp + Long Spot"

            results.append({
                "coin": coin,
                "funding_apr": funding_apr,
                "hist_borrow_avg": hist_borrow_apr,
                "hist_borrow_median": stats["median_annualized_pct"],
                "hist_borrow_max": stats["max_annualized_pct"],
                "hist_borrow_min": stats["min_annualized_pct"],
                "borrow_std_dev": stats["std_dev"],
                "net_arb": net_arb,
                "direction": direction,
                "borrow_days": stats["days_covered"],
                "borrow_samples": stats["num_samples"],
            })
            print(f" {stats['num_samples']} samples, {stats['days_covered']:.0f} days, avg borrow: {hist_borrow_apr:.1f}%, median: {stats['median_annualized_pct']:.1f}%")
        else:
            print(f" no historical data")

        time.sleep(0.2)

    # Compare snapshot vs historical
    print("\n" + "=" * 80)
    print("SNAPSHOT vs HISTORICAL BORROW RATE COMPARISON")
    print("=" * 80)

    # Load snapshot rates from prior analysis
    snapshot_lookup = {}
    for r in prior_data.get("shitcoin_results", []):
        snapshot_lookup[r["coin"]] = r["borrow_apr_pct"]

    print(f"\n{'Coin':<8} {'Snapshot':>10} {'Hist Avg':>10} {'Hist Med':>10} {'Hist Min':>10} {'Hist Max':>10} {'Delta':>8}")
    print("-" * 66)

    for r in results:
        snap = snapshot_lookup.get(r["coin"], 0)
        delta = r["hist_borrow_avg"] - snap
        print(f"{r['coin']:<8} {snap:>9.1f}% {r['hist_borrow_avg']:>9.1f}% {r['hist_borrow_median']:>9.1f}% "
              f"{r['hist_borrow_min']:>9.1f}% {r['hist_borrow_max']:>9.1f}% {delta:>+7.1f}%")

    # Revised arb ranking
    print("\n" + "=" * 80)
    print("REVISED ARB RANKING (Using Historical Avg Borrow Rates)")
    print("=" * 80)

    results.sort(key=lambda x: x["net_arb"], reverse=True)

    print(f"\n{'#':<3} {'Coin':<8} {'Direction':<25} {'Fund APR':>9} {'Hist Borr':>10} {'Net Arb':>8} {'Borr Days':>10}")
    print("-" * 80)

    for i, r in enumerate(results, 1):
        print(f"{i:<3} {r['coin']:<8} {r['direction']:<25} {r['funding_apr']:>+8.1f}% {r['hist_borrow_avg']:>9.1f}% "
              f"{r['net_arb']:>+7.1f}% {r['borrow_days']:>9.0f}")

    # Save
    output_path = "/Users/abreckler/.paperclip/instances/default/workspaces/2646cd80-6297-4f3a-80f3-6ba24ef000a7/reports/ZER-1305-historical-borrow-comparison.json"
    with open(output_path, "w") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(),
            "results": results,
        }, f, indent=2)

    print(f"\nData saved to: {output_path}")

    # Summary
    profitable = [r for r in results if r["net_arb"] > 0]
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Coins with positive net arb (historical borrow): {len(profitable)}/{len(results)}")
    if profitable:
        print(f"Top picks:")
        for r in profitable[:5]:
            print(f"  - {r['coin']}: {r['direction']}, Net {r['net_arb']:+.1f}% APR "
                  f"(Funding: {r['funding_apr']:+.1f}%, Hist Borrow Avg: {r['hist_borrow_avg']:.1f}%)")

    return results

if __name__ == "__main__":
    main()
