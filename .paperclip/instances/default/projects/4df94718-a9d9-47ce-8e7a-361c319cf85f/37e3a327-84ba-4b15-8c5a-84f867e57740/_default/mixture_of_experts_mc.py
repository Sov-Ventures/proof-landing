#!/usr/bin/env python3
"""
Mixture of Experts — Monte Carlo Simulation (3 Years)
ZER-390: Combines signals from all Zeropoint trading strategies into one model.

Strategies included:
  1. BTC Weekly Pattern (Hyperliquid) — 18/18 win rate, long Thu→Sun when dip < 0.25%
  2. Pair Trading Mean Reversion (Hyperliquid perps) — z-score entry/exit on alt pairs
  3. Certainty Sniper (Polymarket) — buy near-certain outcomes before candle close
  4. Covered Call Coverage (Deribit) — regime-aware BTC covered calls
  5. Copytrader (Polymarket) — mirror high-conviction wallets

Mixture-of-experts approach:
  - Each strategy generates independent signals each week
  - An "expert gate" weights allocation to each strategy based on recent performance
  - Capital is allocated proportionally to expert weights (softmax on trailing Sharpe)
  - Combined portfolio tracks correlated and uncorrelated returns

Usage:
    python mixture_of_experts_mc.py
"""

import math
import random
import statistics
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════
# Strategy Parameters (derived from codebase analysis)
# ═══════════════════════════════════════════════════════════════════════════

# 1. BTC Weekly Pattern
# Historical: 18/18 wins, triggers ~35% of weeks, avg +10.98%, 3x leverage
WP_TRIGGER_PROB = 0.35
WP_WIN_RATE = 1.0
WP_MEAN_WIN = 10.98
WP_MIN_WIN = 1.9
WP_MAX_WIN = 28.8
WP_STDDEV_WIN = 7.0
WP_MEAN_LOSS = -3.0
WP_LEVERAGE = 3
WP_STOP_LOSS = 3.0

# 2. Pair Trading Mean Reversion
# From pair_trading_test_harness.py: z=1.5 entry, TP=18%, SL=12%, ~40-55% win rate
PT_TRADE_PROB = 0.60  # most weeks have at least one z-score breach across 4 pairs
PT_TRADES_PER_WEEK_MEAN = 1.5  # multiple pairs can trigger
PT_WIN_RATE = 0.48
PT_MEAN_WIN = 6.5  # avg win % (sub TP)
PT_STDDEV_WIN = 4.0
PT_MAX_WIN = 18.0  # TP cap
PT_MEAN_LOSS = -5.0  # avg loss (sub SL)
PT_STDDEV_LOSS = 3.0
PT_MAX_LOSS = -12.0  # SL cap
PT_FEE_BPS = 20  # 10bps each side round trip

# 3. Certainty Sniper (Polymarket)
# Buy at 0.97-0.995, resolve at 1.00. Extremely high win rate when direction clear
CS_TRADE_PROB = 0.70  # active 5/7 days, multiple candles per day
CS_TRADES_PER_WEEK_MEAN = 8.0  # multiple opportunities daily
CS_WIN_RATE = 0.985  # only enters when >0.3% move with 30s left — very reliable
CS_MEAN_WIN_PCT = 1.5  # buy at ~0.985, sell at 1.00 → ~1.5% gain
CS_STDDEV_WIN = 0.8
CS_LOSS_FRACTION = 0.97  # lose ~97% of bet on wrong direction
CS_ORDER_SIZE_USD = 500  # fixed per-trade size, not % of allocation

# 4. Covered Call Coverage (Deribit)
# Regime-aware: 40-70% coverage, premium income vs assignment risk
CC_TRADE_PROB = 0.25  # weekly rolls, ~1/month new position
CC_WIN_RATE = 0.75  # most calls expire worthless (premium kept)
CC_MEAN_PREMIUM_PCT = 2.5  # weekly premium as % of covered notional
CC_STDDEV_PREMIUM = 1.0
CC_ASSIGNMENT_LOSS_PCT = -8.0  # if assigned, miss upside above strike
CC_STDDEV_ASSIGNMENT = 3.0

# 5. Copytrader (Polymarket)
# Mirror trades: performance depends on target wallet
CT_TRADE_PROB = 0.55  # target trades ~4 days/week
CT_TRADES_PER_WEEK_MEAN = 3.0
CT_WIN_RATE = 0.58  # slightly above random — following smart money
CT_MEAN_WIN_PCT = 12.0  # binary outcomes can have large swings
CT_STDDEV_WIN = 8.0
CT_MEAN_LOSS_PCT = -15.0
CT_STDDEV_LOSS = 10.0
CT_SLIPPAGE_PCT = 1.5  # delayed execution cost


# ═══════════════════════════════════════════════════════════════════════════
# Simulation Configuration
# ═══════════════════════════════════════════════════════════════════════════

NUM_SIMULATIONS = 10_000
NUM_WEEKS = 156  # 3 years
INITIAL_CAPITAL = 50_000.0

# Per-strategy capital allocation (initial, before expert gating adjusts)
INITIAL_ALLOCATION = {
    "weekly_pattern": 0.25,
    "pair_trading": 0.20,
    "certainty_sniper": 0.20,
    "covered_call": 0.20,
    "copytrader": 0.15,
}

# Expert gate: lookback window for trailing Sharpe calculation
GATE_LOOKBACK_WEEKS = 12
# Minimum allocation floor (no strategy drops below this)
MIN_ALLOCATION = 0.05
# How aggressively the gate re-weights (softmax temperature)
GATE_TEMPERATURE = 2.0


# ═══════════════════════════════════════════════════════════════════════════
# Signal Generators (one per strategy)
# ═══════════════════════════════════════════════════════════════════════════

def gen_weekly_pattern(rng: random.Random, alloc_usd: float = 12500) -> float:
    """BTC Weekly Pattern: fixed $1,000 position at 3x leverage.
    Returns dollar PnL (not fraction)."""
    if rng.random() >= WP_TRIGGER_PROB:
        return 0.0  # no trade this week
    pos_size = 1000.0  # fixed position size per the actual strategy
    if rng.random() < WP_WIN_RATE:
        while True:
            ret = rng.gauss(WP_MEAN_WIN, WP_STDDEV_WIN)
            if WP_MIN_WIN <= ret <= WP_MAX_WIN:
                return pos_size * WP_LEVERAGE * ret / 100.0
    else:
        ret = max(rng.gauss(WP_MEAN_LOSS, 1.5), -WP_STOP_LOSS)
        return pos_size * WP_LEVERAGE * ret / 100.0


def gen_pair_trading(rng: random.Random, alloc_usd: float = 10000) -> float:
    """Pair Trading Mean Reversion: $500 per trade on alt pairs.
    Returns dollar PnL."""
    if rng.random() >= PT_TRADE_PROB:
        return 0.0
    trade_size = 500.0  # per-pair position
    n_trades = max(1, int(rng.gauss(PT_TRADES_PER_WEEK_MEAN, 0.8)))
    total_pnl = 0.0
    for _ in range(n_trades):
        if rng.random() < PT_WIN_RATE:
            ret = min(rng.gauss(PT_MEAN_WIN, PT_STDDEV_WIN), PT_MAX_WIN)
            ret = max(ret, 0.1)
        else:
            ret = max(rng.gauss(PT_MEAN_LOSS, PT_STDDEV_LOSS), PT_MAX_LOSS)
            ret = min(ret, -0.1)
        total_pnl += trade_size * ret / 100.0
    # Subtract fees
    total_pnl -= n_trades * trade_size * PT_FEE_BPS / 10000.0
    return total_pnl


def gen_certainty_sniper(rng: random.Random, alloc_usd: float = 10000) -> float:
    """Certainty Sniper: fixed $500 bets, many small wins, rare total-bet loss.
    Returns dollar PnL."""
    if rng.random() >= CS_TRADE_PROB:
        return 0.0
    n_trades = max(1, int(rng.gauss(CS_TRADES_PER_WEEK_MEAN, 2.0)))
    total_pnl = 0.0
    for _ in range(n_trades):
        if rng.random() < CS_WIN_RATE:
            win_pct = max(0.1, rng.gauss(CS_MEAN_WIN_PCT, CS_STDDEV_WIN))
            total_pnl += CS_ORDER_SIZE_USD * win_pct / 100.0
        else:
            total_pnl -= CS_ORDER_SIZE_USD * CS_LOSS_FRACTION
    return total_pnl


def gen_covered_call(rng: random.Random, alloc_usd: float = 10000) -> float:
    """Covered Call: premium on ~$5,000 BTC notional covered position.
    Returns dollar PnL."""
    if rng.random() >= CC_TRADE_PROB:
        return 0.0
    notional = 5000.0  # covered call notional
    if rng.random() < CC_WIN_RATE:
        ret = max(0.1, rng.gauss(CC_MEAN_PREMIUM_PCT, CC_STDDEV_PREMIUM))
        return notional * ret / 100.0
    else:
        ret = rng.gauss(CC_ASSIGNMENT_LOSS_PCT, CC_STDDEV_ASSIGNMENT)
        ret = min(ret, -0.5)
        return notional * ret / 100.0


def gen_copytrader(rng: random.Random, alloc_usd: float = 7500) -> float:
    """Copytrader: fixed $50 trades following smart money with execution lag.
    Returns dollar PnL."""
    if rng.random() >= CT_TRADE_PROB:
        return 0.0
    n_trades = max(1, int(rng.gauss(CT_TRADES_PER_WEEK_MEAN, 1.0)))
    total_pnl = 0.0
    trade_size = 50.0  # fixed $50 per copy trade
    for _ in range(n_trades):
        if rng.random() < CT_WIN_RATE:
            ret_pct = max(0.5, rng.gauss(CT_MEAN_WIN_PCT, CT_STDDEV_WIN))
        else:
            ret_pct = min(-0.5, rng.gauss(CT_MEAN_LOSS_PCT, CT_STDDEV_LOSS))
        ret_pct -= CT_SLIPPAGE_PCT  # slippage drag
        total_pnl += trade_size * ret_pct / 100.0
    return total_pnl


STRATEGY_GENERATORS = {
    "weekly_pattern": gen_weekly_pattern,
    "pair_trading": gen_pair_trading,
    "certainty_sniper": gen_certainty_sniper,
    "covered_call": gen_covered_call,
    "copytrader": gen_copytrader,
}

STRATEGY_LABELS = {
    "weekly_pattern": "BTC Weekly Pattern (HL)",
    "pair_trading": "Pair Mean Reversion (HL)",
    "certainty_sniper": "Certainty Sniper (PM)",
    "covered_call": "Covered Call (Deribit)",
    "copytrader": "Copytrader (PM)",
}


# ═══════════════════════════════════════════════════════════════════════════
# Expert Gating (Mixture of Experts)
# ═══════════════════════════════════════════════════════════════════════════

def softmax(values: list[float], temperature: float = 1.0) -> list[float]:
    """Softmax with temperature scaling."""
    scaled = [v / temperature for v in values]
    max_v = max(scaled)
    exps = [math.exp(v - max_v) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def compute_expert_weights(
    history: dict[str, list[float]],
    initial_alloc: dict[str, float],
) -> dict[str, float]:
    """
    Compute allocation weights using trailing Sharpe ratio of each strategy.
    Falls back to initial allocation when history is insufficient.
    """
    strategies = list(initial_alloc.keys())

    # Need enough history for meaningful Sharpe
    min_history = max(4, GATE_LOOKBACK_WEEKS // 2)
    has_enough = all(len(history.get(s, [])) >= min_history for s in strategies)

    if not has_enough:
        return dict(initial_alloc)

    sharpe_scores = []
    for s in strategies:
        recent = history[s][-GATE_LOOKBACK_WEEKS:]
        if len(recent) < 2:
            sharpe_scores.append(0.0)
            continue
        mu = statistics.mean(recent)
        sd = statistics.stdev(recent) if len(recent) > 1 else 1e-9
        sd = max(sd, 1e-9)
        sharpe_scores.append(mu / sd)

    weights = softmax(sharpe_scores, GATE_TEMPERATURE)

    # Apply minimum allocation floor
    result = {}
    total_excess = 0.0
    for i, s in enumerate(strategies):
        if weights[i] < MIN_ALLOCATION:
            result[s] = MIN_ALLOCATION
            total_excess += MIN_ALLOCATION - weights[i]
        else:
            result[s] = weights[i]

    # Redistribute excess proportionally from over-min strategies
    if total_excess > 0:
        over_min = {s: w for s, w in result.items() if w > MIN_ALLOCATION}
        over_total = sum(over_min.values())
        if over_total > 0:
            for s in over_min:
                result[s] -= total_excess * (result[s] / over_total)

    # Normalize to sum to 1.0
    total_w = sum(result.values())
    return {s: w / total_w for s, w in result.items()}


# ═══════════════════════════════════════════════════════════════════════════
# Simulation Engine
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SimResult:
    sim_id: int
    final_capital: float
    total_return_pct: float
    max_drawdown_pct: float
    total_pnl: float
    strategy_pnls: dict  # strategy -> total PnL
    strategy_trades: dict  # strategy -> trade count
    final_weights: dict  # final expert gate weights


def run_simulation(sim_id: int, rng: random.Random) -> SimResult:
    """Run a single 3-year simulation with expert gating."""
    capital = INITIAL_CAPITAL
    peak_capital = capital
    max_drawdown_pct = 0.0
    strategy_pnls = {s: 0.0 for s in STRATEGY_GENERATORS}
    strategy_trades = {s: 0 for s in STRATEGY_GENERATORS}
    history = {s: [] for s in STRATEGY_GENERATORS}
    weights = dict(INITIAL_ALLOCATION)

    for week in range(NUM_WEEKS):
        if capital <= 0:
            break

        # Update expert gate weights every 4 weeks after warmup
        if week > 0 and week % 4 == 0:
            weights = compute_expert_weights(history, INITIAL_ALLOCATION)

        week_pnl = 0.0
        for strategy, generator in STRATEGY_GENERATORS.items():
            alloc = weights[strategy] * capital

            # All strategies now return dollar PnL directly
            pnl = generator(rng, alloc_usd=alloc)

            if pnl != 0.0:
                strategy_trades[strategy] += 1

            strategy_pnls[strategy] += pnl
            # Store return as fraction for Sharpe calculation
            ret_frac = pnl / alloc if alloc > 0 else 0.0
            history[strategy].append(ret_frac)
            week_pnl += pnl

        capital += week_pnl

        # Drawdown tracking
        if capital > peak_capital:
            peak_capital = capital
        if peak_capital > 0:
            dd = (peak_capital - capital) / peak_capital * 100
            max_drawdown_pct = max(max_drawdown_pct, dd)

    total_return_pct = ((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
    return SimResult(
        sim_id=sim_id,
        final_capital=capital,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        total_pnl=capital - INITIAL_CAPITAL,
        strategy_pnls=strategy_pnls,
        strategy_trades=strategy_trades,
        final_weights=weights,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════════════

def percentile(data: list[float], p: float) -> float:
    k = (len(data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] * (c - k) + data[c] * (k - f)


def print_report(results: list[SimResult]):
    n = len(results)
    strategies = list(STRATEGY_GENERATORS.keys())

    total_returns = sorted([r.total_return_pct for r in results])
    final_capitals = sorted([r.final_capital for r in results])
    max_drawdowns = sorted([r.max_drawdown_pct for r in results])
    pnls = sorted([r.total_pnl for r in results])

    mean_return = statistics.mean(total_returns)
    median_return = statistics.median(total_returns)
    std_return = statistics.stdev(total_returns)
    mean_pnl = statistics.mean(pnls)
    mean_dd = statistics.mean(max_drawdowns)
    sharpe = mean_return / std_return if std_return > 0 else float("inf")

    profitable = sum(1 for r in results if r.total_pnl > 0)
    ruin = sum(1 for r in results if r.final_capital <= 0)

    print("=" * 78)
    print("  MIXTURE OF EXPERTS — MONTE CARLO SIMULATION (3 YEARS)")
    print("  All Zeropoint Trading Strategies Combined")
    print("=" * 78)
    print()
    print("── Configuration ─────────────────────────────────────────────────────")
    print(f"  Simulations:       {n:,}")
    print(f"  Period:            {NUM_WEEKS} weeks (3 years)")
    print(f"  Initial capital:   ${INITIAL_CAPITAL:,.0f}")
    print(f"  Expert gate:       Softmax on trailing {GATE_LOOKBACK_WEEKS}-week Sharpe")
    print(f"  Gate temperature:  {GATE_TEMPERATURE}")
    print(f"  Min allocation:    {MIN_ALLOCATION*100:.0f}% floor per strategy")
    print()

    # ── Individual Strategy Breakdown ──
    print("── Individual Strategy Performance ────────────────────────────────────")
    print(f"  {'Strategy':<30} {'Mean PnL':>12} {'Med PnL':>12} {'Avg Trades':>12}")
    print(f"  {'─'*30} {'─'*12} {'─'*12} {'─'*12}")

    for s in strategies:
        s_pnls = sorted([r.strategy_pnls[s] for r in results])
        s_trades = [r.strategy_trades[s] for r in results]
        s_mean = statistics.mean(s_pnls)
        s_median = statistics.median(s_pnls)
        s_mean_trades = statistics.mean(s_trades)
        label = STRATEGY_LABELS[s]
        print(f"  {label:<30} ${s_mean:>+10,.0f} ${s_median:>+10,.0f} {s_mean_trades:>10.1f}")

    print()
    print("  Per-strategy return distribution (mean PnL / initial capital):")
    for s in strategies:
        s_pnls = [r.strategy_pnls[s] for r in results]
        s_mean = statistics.mean(s_pnls)
        s_p5 = percentile(sorted(s_pnls), 5)
        s_p95 = percentile(sorted(s_pnls), 95)
        label = STRATEGY_LABELS[s]
        pct = s_mean / INITIAL_CAPITAL * 100
        print(f"  {label:<30}  {pct:>+6.1f}%  (P5: ${s_p5:>+,.0f} | P95: ${s_p95:>+,.0f})")

    # ── Combined Portfolio ──
    print()
    print("── Combined Portfolio (Mixture of Experts) ────────────────────────────")
    print(f"  Mean return:       {mean_return:+.2f}%")
    print(f"  Median return:     {median_return:+.2f}%")
    print(f"  Std deviation:     {std_return:.2f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print()
    print(f"  Mean PnL:          ${mean_pnl:+,.2f}")
    print(f"  Median PnL:        ${statistics.median(pnls):+,.2f}")
    print(f"  Mean max drawdown: {mean_dd:.2f}%")
    print(f"  Profitable sims:   {profitable/n*100:.1f}%  ({profitable:,}/{n:,})")
    print(f"  Ruin probability:  {ruin/n*100:.2f}%  ({ruin:,}/{n:,})")
    print()

    print("── PnL Distribution ──────────────────────────────────────────────────")
    for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        val = percentile(pnls, p)
        ret = val / INITIAL_CAPITAL * 100
        print(f"  P{p:<3}: ${val:>+12,.0f}  ({ret:>+7.1f}%)")

    print()
    print("── Capital Distribution ──────────────────────────────────────────────")
    for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        val = percentile(final_capitals, p)
        print(f"  P{p:<3}: ${val:>12,.0f}")

    print()
    print("── Max Drawdown Distribution ─────────────────────────────────────────")
    print(f"  Mean:  {mean_dd:.2f}%")
    print(f"  P50:   {percentile(max_drawdowns, 50):.2f}%")
    print(f"  P75:   {percentile(max_drawdowns, 75):.2f}%")
    print(f"  P95:   {percentile(max_drawdowns, 95):.2f}%")
    print(f"  P99:   {percentile(max_drawdowns, 99):.2f}%")

    # ── Expert Gate Weights (average final) ──
    print()
    print("── Average Final Expert Gate Weights ──────────────────────────────────")
    avg_weights = {s: statistics.mean([r.final_weights[s] for r in results]) for s in strategies}
    for s in sorted(avg_weights, key=avg_weights.get, reverse=True):
        label = STRATEGY_LABELS[s]
        init_w = INITIAL_ALLOCATION[s] * 100
        final_w = avg_weights[s] * 100
        delta = final_w - init_w
        print(f"  {label:<30}  {final_w:5.1f}%  (initial: {init_w:.0f}%, Δ{delta:+.1f}%)")

    # ── Correlation insight ──
    print()
    print("── Strategy Correlation (PnL) ─────────────────────────────────────────")
    for i, s1 in enumerate(strategies):
        for s2 in strategies[i + 1:]:
            p1 = [r.strategy_pnls[s1] for r in results]
            p2 = [r.strategy_pnls[s2] for r in results]
            n_corr = len(p1)
            m1, m2 = statistics.mean(p1), statistics.mean(p2)
            sd1 = statistics.stdev(p1) or 1e-9
            sd2 = statistics.stdev(p2) or 1e-9
            cov = sum((p1[j] - m1) * (p2[j] - m2) for j in range(n_corr)) / (n_corr - 1)
            corr = cov / (sd1 * sd2)
            l1 = STRATEGY_LABELS[s1][:20]
            l2 = STRATEGY_LABELS[s2][:20]
            print(f"  {l1:<20} × {l2:<20}  ρ = {corr:+.3f}")

    print()
    print("=" * 78)
    print(f"  3-Year Expected PnL: ${mean_pnl:+,.0f} on ${INITIAL_CAPITAL:,.0f} capital")
    ann_ret = ((1 + mean_return / 100) ** (1 / 3) - 1) * 100
    print(f"  Annualized return:   {ann_ret:+.1f}%")
    print(f"  {profitable/n*100:.0f}% of simulations profitable over 3 years")
    print("=" * 78)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    rng = random.Random(42)
    print("Running 10,000 simulations over 156 weeks (3 years)...")
    print()

    results = []
    for i in range(NUM_SIMULATIONS):
        results.append(run_simulation(i, rng))
        if (i + 1) % 2500 == 0:
            print(f"  ... {i+1:,}/{NUM_SIMULATIONS:,} simulations complete")

    print()
    print_report(results)


if __name__ == "__main__":
    main()
