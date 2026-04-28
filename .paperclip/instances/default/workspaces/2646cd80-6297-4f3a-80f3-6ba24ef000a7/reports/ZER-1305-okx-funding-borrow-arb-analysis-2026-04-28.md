# ZER-1305: OKX Perp Funding Rate vs Loan Borrow Rate Arbitrage Analysis

**Date:** 2026-04-28
**Analyst:** Lambda (Quantitative Analyst)
**Data Period:** 365 days (where available), sourced from OKX public API

---

## Methodology

Compared annualized perpetual swap funding rates against OKX margin lending/borrow rates for 146 shitcoins (excluding BTC, ETH, SOL, and other top-20 majors) that have **both** a USDT-margined perpetual swap **and** a lending market on OKX.

**Arb mechanics:**
- **Positive funding (longs pay shorts):** Short the perp + buy spot = collect funding payments delta-neutral. Cost = borrow rate if leveraging.
- **Negative funding (shorts pay longs):** Long the perp + borrow & sell spot = collect funding. Cost = coin borrow rate for the spot short leg.

Net arb = |Funding APR| - Borrow APR

---

## Key Finding: Negative Funding Dominates Shitcoins

- **97/146 shitcoins** (66%) have average **negative** funding rates (shorts pay longs)
- Average negative funding APR: **-16.3%**
- Only 49 coins have positive avg funding, at a mild **+2.5%** APR
- This means the dominant arb is: **Long perp + Short spot** (borrow coin, sell spot, go long perp)

---

## Top 15 Arbitrage Opportunities

Ranked by net arb (|Funding APR| minus Borrow APR):

| # | Coin | Direction | Funding APR | Borrow APR | Net Arb | Consistency | Days |
|---|------|-----------|------------|------------|---------|-------------|------|
| 1 | **AXS** | Long Perp + Short Spot | -117.9% | 39.0% | **+78.9%** | 86.3% | 188 |
| 2 | **BARD** | Long Perp + Short Spot | -101.1% | 29.0% | **+72.1%** | 80.5% | 499 |
| 3 | **ONT** | Long Perp + Short Spot | -97.4% | 40.0% | **+57.4%** | 59.2% | 218 |
| 4 | **ENJ** | Long Perp + Short Spot | -101.3% | 50.0% | **+51.3%** | 66.9% | 318 |
| 5 | **ZIL** | Long Perp + Short Spot | -58.1% | 8.0% | **+50.1%** | 62.9% | 314 |
| 6 | **FLOW** | Long Perp + Short Spot | -44.7% | 1.0% | **+43.6%** | 34.6% | 297 |
| 7 | **ZORA** | Long Perp + Short Spot | -31.5% | 8.0% | **+23.5%** | 55.0% | 328 |
| 8 | **ICP** | Long Perp + Short Spot | -21.3% | 1.0% | **+20.3%** | 67.2% | 90 |
| 9 | **HUMA** | Long Perp + Short Spot | -35.0% | 15.0% | **+20.0%** | 22.3% | 181 |
| 10 | **BLUR** | Long Perp + Short Spot | -51.5% | 38.0% | **+13.5%** | 38.0% | 202 |
| 11 | **ZK** | Long Perp + Short Spot | -23.3% | 10.0% | **+13.3%** | 40.5% | 326 |
| 12 | **BERA** | Long Perp + Short Spot | -53.3% | 40.0% | **+13.3%** | 75.0% | 263 |
| 13 | **POL** | Long Perp + Short Spot | -11.6% | 1.0% | **+10.6%** | 63.9% | 181 |
| 14 | **AVNT** | Long Perp + Short Spot | -14.6% | 4.0% | **+10.6%** | 46.8% | 188 |
| 15 | **AUCTION** | Long Perp + Short Spot | -21.8% | 13.0% | **+8.8%** | 40.2% | 188 |

---

## Risk-Adjusted Top Picks

Factoring in consistency and volatility of funding rates:

| # | Coin | Net Arb | Directional Consistency | Risk Score |
|---|------|---------|------------------------|------------|
| 1 | **POL** | +10.6% | 63.9% | 0.51 |
| 2 | **OKB** | +2.0% | 79.7% | 0.47 |
| 3 | **AXS** | +78.9% | 86.3% | 0.40 |
| 4 | **BARD** | +72.1% | 80.5% | 0.35 |
| 5 | **FLOW** | +43.6% | 34.6% | 0.33 |
| 6 | **ICP** | +20.3% | 67.2% | 0.33 |
| 7 | **HBAR** | +3.7% | 55.7% | 0.29 |
| 8 | **ZIL** | +50.1% | 62.9% | 0.26 |
| 9 | **ONT** | +57.4% | 59.2% | 0.25 |
| 10 | **ZORA** | +23.5% | 55.0% | 0.25 |

---

## Tier-1 Recommendations (High Conviction)

These coins offer the best combination of high net arb, reasonable consistency, and sufficient liquidity:

### 1. AXS (Axie Infinity) -- Net +78.9% APR
- Funding: -117.9% annualized (86% of periods negative)
- Borrow: 39.0% APR
- Strategy: Long perp + borrow & sell spot
- Risk: Extreme funding rate swings, but very high consistency

### 2. ZIL (Zilliqa) -- Net +50.1% APR
- Funding: -58.1% annualized (63% negative)
- Borrow: 8.0% APR (very low cost)
- Strategy: Long perp + borrow & sell spot
- Risk: Moderate consistency, but exceptional borrow-to-funding spread

### 3. FLOW -- Net +43.6% APR
- Funding: -44.7% annualized
- Borrow: 1.0% APR (lowest borrow cost in the set)
- Strategy: Long perp + borrow & sell spot
- Risk: Only 34.6% consistency -- funding flips positive frequently

### 4. ICP -- Net +20.3% APR
- Funding: -21.3% annualized (67% negative)
- Borrow: 1.0% APR
- Strategy: Long perp + borrow & sell spot
- Risk: Only 90 days of data; needs monitoring

### 5. POL (Polygon) -- Net +10.6% APR
- Funding: -11.6% annualized (64% negative)
- Borrow: 1.0% APR
- Best risk-adjusted score (0.51) -- most stable spread
- Strategy: Long perp + borrow & sell spot

---

## Positive Funding Side (Short Perp + Long Spot)

Much weaker opportunities. Only 2 shitcoins have positive net arb:

| Coin | Funding APR | Borrow APR | Net Arb | Consistency |
|------|------------|------------|---------|-------------|
| OKB | +3.0% | 1.0% | +2.0% | 79.7% |
| SUI | +2.8% | 1.0% | +1.8% | 67.5% |

These are very thin margins -- not actionable for active trading.

---

## Structural Observations

1. **Shitcoins skew heavily negative on funding.** The market is structurally short these coins via perps, paying longs to hold. This likely reflects hedging demand and bearish positioning.

2. **Borrow rates are often the binding constraint.** Many coins with extreme negative funding (e.g., API3 at -32.9%) have even more extreme borrow rates (API3: 203%), making the arb underwater.

3. **The best arbs are where borrow rates are low but funding is deeply negative.** ZIL (8% borrow, -58% funding), FLOW (1% borrow, -45% funding), and POL (1% borrow, -12% funding) exemplify this pattern.

4. **OKX lending rates are snapshot rates**, not time-weighted averages. Actual borrow costs fluctuate and may be higher during execution. This analysis uses current borrow rates -- historical borrow rates would give a more accurate picture.

5. **Execution risks:** Liquidation risk on the perp leg if the coin pumps (even though delta-neutral, the perp requires margin), borrow recall risk on the spot short leg, and funding rate regime changes.

---

---

## REVISION: Apples-to-Apples Historical Borrow Rate Comparison

**Important correction:** The initial analysis used snapshot borrow rates from `/api/v5/public/interest-rate-loan-quota` (a single point-in-time daily rate extrapolated to annual). This was not apples-to-apples with the 365-day historical funding rate averages.

**Fix:** Used `/api/v5/finance/savings/lending-rate-history` to fetch ~5,000 hourly borrow rate samples per coin (~208 days of history), then computed the true historical average borrow APR.

### Key Finding: Snapshot Rates Understate Historical Borrow Costs

Many coins' snapshot borrow rates were LOWER than their historical average, meaning the initial analysis was **too optimistic** for some coins:

| Coin | Snapshot APR | Hist Avg APR | Hist Median APR | Delta |
|------|-------------|-------------|-----------------|-------|
| AXS | 39.0% | **64.2%** | 35.0% | +25.2% |
| BARD | 29.0% | **51.8%** | 1.0% | +22.8% |
| ONT | 40.0% | **68.8%** | 34.0% | +28.8% |
| FLOW | 1.0% | **3.1%** | 1.0% | +2.1% |
| ZIL | 8.0% | **20.8%** | 1.0% | +12.8% |
| ZORA | 8.0% | **81.5%** | 39.0% | +73.5% |
| MOVE | 27.0% | **64.1%** | 47.0% | +37.1% |
| COMP | 29.0% | **13.5%** | 1.0% | -15.5% |
| BLUR | 38.0% | **25.3%** | 1.0% | -12.7% |
| POL | 1.0% | **6.5%** | 1.0% | +5.5% |

Borrow rates are extremely bimodal — most coins show median ~1% (no demand) but avg far higher due to sporadic spikes (some hitting 365% during squeeze events).

### Revised Arb Ranking (Historical Borrow Rates)

| # | Coin | Direction | Funding APR | Hist Borrow APR | **Net Arb** |
|---|------|-----------|------------|----------------|-------------|
| 1 | **AXS** | Long Perp + Short Spot | -117.9% | 64.2% | **+53.8%** |
| 2 | **BARD** | Long Perp + Short Spot | -101.1% | 51.8% | **+49.3%** |
| 3 | **ENJ** | Long Perp + Short Spot | -101.3% | 53.5% | **+47.8%** |
| 4 | **FLOW** | Long Perp + Short Spot | -44.7% | 3.1% | **+41.6%** |
| 5 | **ZIL** | Long Perp + Short Spot | -58.1% | 20.8% | **+37.3%** |
| 6 | **ONT** | Long Perp + Short Spot | -97.4% | 68.8% | **+28.6%** |
| 7 | **BLUR** | Long Perp + Short Spot | -51.5% | 25.3% | **+26.2%** |
| 8 | **COMP** | Long Perp + Short Spot | -35.4% | 13.5% | **+21.9%** |
| 9 | **ZK** | Long Perp + Short Spot | -23.3% | 7.8% | **+15.5%** |
| 10 | **HUMA** | Long Perp + Short Spot | -35.0% | 23.6% | **+11.4%** |
| 11 | **ICP** | Long Perp + Short Spot | -21.3% | 11.1% | **+10.2%** |
| 12 | **SNX** | Long Perp + Short Spot | -21.8% | 15.1% | **+6.7%** |
| 13 | **POL** | Long Perp + Short Spot | -11.6% | 6.5% | **+5.1%** |

**Eliminated (negative net arb with historical borrow):** BERA (-1.7%), AUCTION (-7.0%), IP (-17.5%), AVNT (-19.8%), MOVE (-32.0%), ZORA (-50.0%)

### Revised Tier-1 Recommendations

1. **FLOW** — Net +41.6% APR, lowest borrow cost (3.1% avg), most executable
2. **ZIL** — Net +37.3% APR, borrow bimodal (median 1%, avg 20.8%) — profitable when timed right
3. **AXS** — Net +53.8% APR largest spread, but 64% borrow cost means large capital at risk
4. **COMP** — Net +21.9% APR, lower volatility profile, 13.5% avg borrow
5. **ZK** — Net +15.5% APR, 7.8% avg borrow, clean risk profile

### Borrow Rate Regime Risk

The bimodal nature of borrow rates is the key risk. Most coins show:
- **Baseline**: 1% APR (no borrowing demand)
- **Spike regime**: 100-365% APR (during short squeezes, liquidation cascades)

Funding rates may be correlated with borrow rate spikes (both reflect short demand). The arb is most profitable when funding is deeply negative BUT borrow rates stay low — which may not always co-occur.

---

## Next Steps

1. **Correlation analysis** — measure how borrow rate spikes correlate with funding rate extremes (the arb breaks if they spike simultaneously)
2. **Size the opportunity** — check OKX lending quota and perp open interest/liquidity for top picks
3. **Build a monitoring system** to alert when funding-borrow spread exceeds threshold
4. **Prototype a delta-neutral bot** for FLOW and ZK (lowest borrow cost, cleanest spreads)
5. **Cross-venue comparison** — check if same arb exists on Binance/Bybit with different borrow rates

---

## Data Files

- Analysis script: `reports/ZER-1305-okx-funding-borrow-arb-analysis.py`
- Historical borrow comparison script: `reports/ZER-1305-historical-borrow-rates.py`
- Raw JSON data: `reports/ZER-1305-okx-funding-borrow-arb-data.json`
- Historical borrow comparison data: `reports/ZER-1305-historical-borrow-comparison.json`
- This report: `reports/ZER-1305-okx-funding-borrow-arb-analysis-2026-04-28.md`
