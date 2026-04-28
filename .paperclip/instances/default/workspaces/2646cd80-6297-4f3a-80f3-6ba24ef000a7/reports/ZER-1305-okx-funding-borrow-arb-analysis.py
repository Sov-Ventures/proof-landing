#!/usr/bin/env python3
"""
ZER-1305: OKX Perp Funding Rate vs Loan Borrow Rate Arbitrage Analysis
Analyzes 365 days of data to identify arb opportunities on shitcoins
that have both perpetual swap markets AND lending/borrow markets on OKX.
"""

import requests
import time
import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict

BASE_URL = "https://www.okx.com"

def get_all_perp_instruments():
    """Get all perpetual swap instruments on OKX."""
    url = f"{BASE_URL}/api/v5/public/instruments"
    params = {"instType": "SWAP"}
    resp = requests.get(url, params=params)
    data = resp.json()
    if data.get("code") != "0":
        print(f"Error fetching instruments: {data}")
        return []
    return data["data"]

def get_lending_currencies():
    """Get currencies available for lending/borrowing on OKX."""
    # Use the public interest rate and loan quota endpoint
    url = f"{BASE_URL}/api/v5/public/interest-rate-loan-quota"
    resp = requests.get(url)
    data = resp.json()
    if data.get("code") != "0":
        print(f"Error fetching lending currencies: {data}")
        return {}

    # Parse into a dict of currency -> basic rate info
    lending_info = {}
    for item in data.get("data", []):
        for detail in item.get("basic", []):
            ccy = detail.get("ccy", "")
            rate = detail.get("rate", "0")
            quota = detail.get("quota", "0")
            lending_info[ccy] = {
                "daily_rate": float(rate) if rate else 0,
                "annualized_rate": float(rate) * 365 * 100 if rate else 0,  # Convert to APR %
                "quota": float(quota) if quota else 0
            }
    return lending_info

def get_funding_rate_history(inst_id, days=365):
    """Fetch funding rate history for a perpetual swap instrument.
    OKX limits to 100 records per request, need to paginate.
    Funding typically settles every 8 hours = 3 per day = ~1095 for 365 days.
    """
    all_rates = []
    after = ""
    cutoff = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

    for _ in range(15):  # Max 15 pages (1500 records, ~500 days)
        url = f"{BASE_URL}/api/v5/public/funding-rate-history"
        params = {"instId": inst_id, "limit": "100"}
        if after:
            params["after"] = after

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching {inst_id}: {e}")
            break

        if data.get("code") != "0" or not data.get("data"):
            break

        records = data["data"]
        for r in records:
            ts = int(r.get("fundingTime", 0))
            if ts < cutoff:
                all_rates.extend([r for r in records if int(r.get("fundingTime", 0)) >= cutoff])
                return all_rates
            all_rates.append(r)

        # Pagination: use the last record's timestamp as 'after'
        after = records[-1].get("fundingTime", "")
        if len(records) < 100:
            break

        time.sleep(0.15)  # Rate limiting

    return all_rates

def analyze_funding_rates(rates):
    """Analyze funding rate statistics."""
    if not rates:
        return None

    funding_values = [float(r.get("fundingRate", 0)) for r in rates]

    # Per-period stats
    avg_rate = sum(funding_values) / len(funding_values)
    positive_count = sum(1 for f in funding_values if f > 0)
    negative_count = sum(1 for f in funding_values if f < 0)

    # Annualized: OKX settles 3x/day (every 8h) for most, but some settle differently
    # We'll use 3 settlements per day as standard
    periods_per_year = 3 * 365
    annualized_rate = avg_rate * periods_per_year * 100  # As percentage

    # Max/Min
    max_rate = max(funding_values)
    min_rate = min(funding_values)

    # Median
    sorted_rates = sorted(funding_values)
    mid = len(sorted_rates) // 2
    median_rate = sorted_rates[mid] if len(sorted_rates) % 2 == 1 else (sorted_rates[mid-1] + sorted_rates[mid]) / 2

    # Standard deviation
    variance = sum((f - avg_rate) ** 2 for f in funding_values) / len(funding_values)
    std_dev = variance ** 0.5

    return {
        "num_periods": len(funding_values),
        "days_covered": len(funding_values) / 3,
        "avg_per_period": avg_rate,
        "avg_per_period_pct": avg_rate * 100,
        "annualized_pct": annualized_rate,
        "median_per_period": median_rate,
        "median_annualized_pct": median_rate * periods_per_year * 100,
        "max_per_period_pct": max_rate * 100,
        "min_per_period_pct": min_rate * 100,
        "std_dev": std_dev,
        "positive_pct": positive_count / len(funding_values) * 100,
        "negative_pct": negative_count / len(funding_values) * 100,
    }

def classify_coin(symbol):
    """Classify whether a coin is a 'shitcoin' (not BTC/ETH/major stablecoins)."""
    majors = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "AVAX", "MATIC",
              "LINK", "UNI", "ATOM", "LTC", "BCH", "FIL", "APT", "ARB", "OP", "NEAR",
              "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD"}
    return symbol.upper() not in majors

def main():
    print("=" * 80)
    print("ZER-1305: OKX Perp Funding Rate vs Borrow Rate Arbitrage Analysis")
    print(f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    # Step 1: Get all perpetual swap instruments
    print("\n[1/4] Fetching perpetual swap instruments...")
    perps = get_all_perp_instruments()
    print(f"  Found {len(perps)} perpetual swap instruments")

    # Extract USDT-margined perps and their base currencies
    usdt_perps = {}
    for p in perps:
        inst_id = p.get("instId", "")
        if inst_id.endswith("-USDT-SWAP"):
            base_ccy = inst_id.replace("-USDT-SWAP", "")
            usdt_perps[base_ccy] = inst_id

    print(f"  USDT-margined perps: {len(usdt_perps)}")

    # Step 2: Get lending currencies and rates
    print("\n[2/4] Fetching lending/borrow rate information...")
    lending_info = get_lending_currencies()
    print(f"  Found {len(lending_info)} currencies with lending markets")

    # Step 3: Find overlap - coins with BOTH perp AND lending markets
    overlap_coins = set(usdt_perps.keys()) & set(lending_info.keys())
    # Filter to shitcoins
    shitcoins = [c for c in overlap_coins if classify_coin(c)]
    shitcoins.sort()

    print(f"\n  Coins with both perp AND lending markets: {len(overlap_coins)}")
    print(f"  Shitcoins (excluding majors): {len(shitcoins)}")
    print(f"  Shitcoin list: {', '.join(shitcoins[:30])}{'...' if len(shitcoins) > 30 else ''}")

    # Also include majors for context
    majors_in_overlap = [c for c in overlap_coins if not classify_coin(c)]
    majors_in_overlap.sort()
    print(f"  Majors for reference: {', '.join(majors_in_overlap)}")

    # Step 4: Fetch funding rate history for each shitcoin
    print(f"\n[3/4] Fetching 365-day funding rate history for {len(shitcoins)} shitcoins...")
    print("  (This may take a few minutes due to rate limiting...)")

    results = []

    # Process all shitcoins (and a few majors for comparison)
    coins_to_analyze = shitcoins + majors_in_overlap[:5]

    for i, coin in enumerate(coins_to_analyze):
        inst_id = usdt_perps[coin]
        print(f"  [{i+1}/{len(coins_to_analyze)}] Fetching {inst_id}...", end="", flush=True)

        rates = get_funding_rate_history(inst_id, days=365)
        stats = analyze_funding_rates(rates)

        if stats:
            borrow_info = lending_info.get(coin, {})
            borrow_apr = borrow_info.get("annualized_rate", 0)

            # The arb: if funding rate is positive (longs pay shorts),
            # you can short the perp and borrow+hold spot to collect funding.
            # Net arb = funding earned (short) - borrow cost (to hold spot hedge)
            # If funding is negative (shorts pay longs), reverse:
            # go long perp, lend the coin to earn interest

            funding_apr = stats["annualized_pct"]

            # Cash-and-carry arb: short perp + buy spot (funded by borrowing USDT)
            # Earn: funding rate (if positive)
            # Pay: USDT borrow rate (need to check)
            # Simpler view: funding APR vs coin borrow APR

            # For "short perp + long spot" (delta-neutral):
            # If funding > 0: earn funding, cost = borrow rate for USDT margin
            # For "borrow coin, sell spot, long perp":
            # If funding < 0: earn |funding|, cost = coin borrow rate

            net_arb_positive = funding_apr - borrow_apr  # When funding positive
            net_arb_negative = abs(funding_apr) - borrow_apr  # When funding negative

            result = {
                "coin": coin,
                "inst_id": inst_id,
                "is_shitcoin": classify_coin(coin),
                "funding_stats": stats,
                "borrow_apr_pct": borrow_apr,
                "daily_borrow_rate_pct": borrow_info.get("daily_rate", 0) * 100,
                "lending_quota": borrow_info.get("quota", 0),
                "net_arb_if_positive_funding": net_arb_positive,
                "net_arb_if_negative_funding": net_arb_negative,
            }
            results.append(result)
            print(f" {stats['num_periods']} periods, funding APR: {funding_apr:+.1f}%, borrow APR: {borrow_apr:.1f}%")
        else:
            print(f" no data")

        time.sleep(0.2)

    # Step 5: Analysis and ranking
    print("\n" + "=" * 80)
    print("[4/4] ARBITRAGE OPPORTUNITY ANALYSIS")
    print("=" * 80)

    # Sort by absolute arb opportunity
    shitcoin_results = [r for r in results if r["is_shitcoin"]]
    major_results = [r for r in results if not r["is_shitcoin"]]

    # === POSITIVE FUNDING ARB (most common): Short perp + Long spot ===
    print("\n" + "-" * 80)
    print("STRATEGY 1: Short Perp + Long Spot (Positive Funding Arb)")
    print("Earn funding payments by shorting the perp, hedge with spot long")
    print("Net = Funding APR - Coin Borrow APR (to fund spot purchase if needed)")
    print("-" * 80)

    positive_funding = [r for r in shitcoin_results if r["funding_stats"]["annualized_pct"] > 0]
    positive_funding.sort(key=lambda x: x["net_arb_if_positive_funding"], reverse=True)

    print(f"\n{'Coin':<10} {'Funding APR':>12} {'Borrow APR':>12} {'Net Arb':>10} {'Funding +%':>10} {'Days':>6} {'Periods':>8}")
    print("-" * 78)

    for r in positive_funding[:25]:
        s = r["funding_stats"]
        print(f"{r['coin']:<10} {s['annualized_pct']:>+11.1f}% {r['borrow_apr_pct']:>11.1f}% "
              f"{r['net_arb_if_positive_funding']:>+9.1f}% {s['positive_pct']:>9.1f}% "
              f"{s['days_covered']:>5.0f} {s['num_periods']:>7}")

    # === NEGATIVE FUNDING ARB: Long perp + Short/Lend spot ===
    print("\n" + "-" * 80)
    print("STRATEGY 2: Long Perp + Short Spot (Negative Funding Arb)")
    print("Earn funding by going long perp (shorts pay longs), hedge by shorting spot")
    print("Net = |Negative Funding APR| - Borrow APR")
    print("-" * 80)

    negative_funding = [r for r in shitcoin_results if r["funding_stats"]["annualized_pct"] < 0]
    negative_funding.sort(key=lambda x: x["net_arb_if_negative_funding"], reverse=True)

    print(f"\n{'Coin':<10} {'Funding APR':>12} {'Borrow APR':>12} {'Net Arb':>10} {'Funding -%':>10} {'Days':>6} {'Periods':>8}")
    print("-" * 78)

    for r in negative_funding[:25]:
        s = r["funding_stats"]
        print(f"{r['coin']:<10} {s['annualized_pct']:>+11.1f}% {r['borrow_apr_pct']:>11.1f}% "
              f"{r['net_arb_if_negative_funding']:>+9.1f}% {s['negative_pct']:>9.1f}% "
              f"{s['days_covered']:>5.0f} {s['num_periods']:>7}")

    # === TOP OPPORTUNITIES (both directions) ===
    print("\n" + "=" * 80)
    print("TOP 15 ARB OPPORTUNITIES (SHITCOINS) - RANKED BY NET ARB")
    print("=" * 80)

    all_arbs = []
    for r in shitcoin_results:
        s = r["funding_stats"]
        if s["annualized_pct"] > 0:
            all_arbs.append({
                "coin": r["coin"],
                "direction": "Short Perp + Long Spot",
                "funding_apr": s["annualized_pct"],
                "borrow_apr": r["borrow_apr_pct"],
                "net_arb": r["net_arb_if_positive_funding"],
                "consistency": s["positive_pct"],
                "median_funding_apr": s["median_annualized_pct"],
                "std_dev": s["std_dev"],
                "days": s["days_covered"],
            })
        else:
            all_arbs.append({
                "coin": r["coin"],
                "direction": "Long Perp + Short Spot",
                "funding_apr": s["annualized_pct"],
                "borrow_apr": r["borrow_apr_pct"],
                "net_arb": r["net_arb_if_negative_funding"],
                "consistency": s["negative_pct"],
                "median_funding_apr": s["median_annualized_pct"],
                "std_dev": s["std_dev"],
                "days": s["days_covered"],
            })

    all_arbs.sort(key=lambda x: x["net_arb"], reverse=True)

    print(f"\n{'#':<3} {'Coin':<8} {'Direction':<25} {'Fund APR':>9} {'Borr APR':>9} {'Net Arb':>8} {'Consist':>8} {'Med APR':>8} {'Days':>5}")
    print("-" * 93)

    for i, a in enumerate(all_arbs[:15], 1):
        print(f"{i:<3} {a['coin']:<8} {a['direction']:<25} {a['funding_apr']:>+8.1f}% {a['borrow_apr']:>8.1f}% "
              f"{a['net_arb']:>+7.1f}% {a['consistency']:>7.1f}% {a['median_funding_apr']:>+7.1f}% {a['days']:>4.0f}")

    # === RISK-ADJUSTED RANKING ===
    print("\n" + "=" * 80)
    print("RISK-ADJUSTED RANKING (Net Arb / Std Dev of Funding Rate)")
    print("Higher = more consistent arb opportunity")
    print("=" * 80)

    for a in all_arbs:
        if a["std_dev"] > 0:
            a["sharpe_like"] = a["net_arb"] / (a["std_dev"] * 100 * 1095)  # Rough risk-adjusted
        else:
            a["sharpe_like"] = 0

    risk_adj = [a for a in all_arbs if a["net_arb"] > 0]
    risk_adj.sort(key=lambda x: x["sharpe_like"], reverse=True)

    print(f"\n{'#':<3} {'Coin':<8} {'Net Arb':>8} {'Consistency':>11} {'Risk Score':>11}")
    print("-" * 45)

    for i, a in enumerate(risk_adj[:15], 1):
        print(f"{i:<3} {a['coin']:<8} {a['net_arb']:>+7.1f}% {a['consistency']:>10.1f}% {a['sharpe_like']:>10.2f}")

    # === MAJORS COMPARISON ===
    print("\n" + "-" * 80)
    print("MAJORS (for comparison)")
    print("-" * 80)

    print(f"\n{'Coin':<10} {'Funding APR':>12} {'Borrow APR':>12} {'Net Arb':>10} {'Funding +%':>10} {'Days':>6}")
    print("-" * 60)

    for r in major_results:
        s = r["funding_stats"]
        net = r["net_arb_if_positive_funding"] if s["annualized_pct"] > 0 else r["net_arb_if_negative_funding"]
        print(f"{r['coin']:<10} {s['annualized_pct']:>+11.1f}% {r['borrow_apr_pct']:>11.1f}% "
              f"{net:>+9.1f}% {s['positive_pct']:>9.1f}% {s['days_covered']:>5.0f}")

    # === SUMMARY ===
    print("\n" + "=" * 80)
    print("EXECUTIVE SUMMARY")
    print("=" * 80)

    profitable_arbs = [a for a in all_arbs if a["net_arb"] > 5]  # > 5% APR net
    print(f"\nTotal shitcoins analyzed: {len(shitcoin_results)}")
    print(f"Coins with positive net arb (>5% APR): {len(profitable_arbs)}")

    if profitable_arbs:
        avg_net = sum(a["net_arb"] for a in profitable_arbs) / len(profitable_arbs)
        print(f"Average net arb of profitable coins: {avg_net:.1f}%")
        print(f"\nTop 5 opportunities:")
        for i, a in enumerate(all_arbs[:5], 1):
            print(f"  {i}. {a['coin']}: {a['direction']}, Net {a['net_arb']:+.1f}% APR, {a['consistency']:.0f}% directional consistency")

    print(f"\nKey Observations:")
    pos_funding = [r for r in shitcoin_results if r["funding_stats"]["annualized_pct"] > 0]
    neg_funding = [r for r in shitcoin_results if r["funding_stats"]["annualized_pct"] < 0]
    print(f"  - {len(pos_funding)}/{len(shitcoin_results)} shitcoins have avg positive funding (longs pay shorts)")
    print(f"  - {len(neg_funding)}/{len(shitcoin_results)} shitcoins have avg negative funding (shorts pay longs)")

    if pos_funding:
        avg_pos = sum(r["funding_stats"]["annualized_pct"] for r in pos_funding) / len(pos_funding)
        print(f"  - Average positive funding APR: {avg_pos:+.1f}%")
    if neg_funding:
        avg_neg = sum(r["funding_stats"]["annualized_pct"] for r in neg_funding) / len(neg_funding)
        print(f"  - Average negative funding APR: {avg_neg:+.1f}%")

    # Save raw results as JSON
    output_path = "/Users/abreckler/.paperclip/instances/default/workspaces/2646cd80-6297-4f3a-80f3-6ba24ef000a7/reports/ZER-1305-okx-funding-borrow-arb-data.json"
    with open(output_path, "w") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(),
            "shitcoin_results": [{
                "coin": r["coin"],
                "funding_apr_pct": r["funding_stats"]["annualized_pct"],
                "median_funding_apr_pct": r["funding_stats"]["median_annualized_pct"],
                "borrow_apr_pct": r["borrow_apr_pct"],
                "net_arb_pct": r["net_arb_if_positive_funding"] if r["funding_stats"]["annualized_pct"] > 0 else r["net_arb_if_negative_funding"],
                "positive_funding_pct": r["funding_stats"]["positive_pct"],
                "days_covered": r["funding_stats"]["days_covered"],
                "num_periods": r["funding_stats"]["num_periods"],
                "std_dev": r["funding_stats"]["std_dev"],
            } for r in shitcoin_results],
            "major_results": [{
                "coin": r["coin"],
                "funding_apr_pct": r["funding_stats"]["annualized_pct"],
                "borrow_apr_pct": r["borrow_apr_pct"],
                "days_covered": r["funding_stats"]["days_covered"],
            } for r in major_results],
            "top_opportunities": all_arbs[:15],
        }, f, indent=2)

    print(f"\nRaw data saved to: {output_path}")
    print("\n" + "=" * 80)

    return results, all_arbs

if __name__ == "__main__":
    results, all_arbs = main()
