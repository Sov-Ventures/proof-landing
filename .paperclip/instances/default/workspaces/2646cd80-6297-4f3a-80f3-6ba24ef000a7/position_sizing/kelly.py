"""
Empirical Kelly Criterion position sizing with Monte Carlo adjustment.

Standard Kelly: f* = (p * b - q) / b
Empirical Kelly: f_empirical = f_kelly * (1 - CV_edge)

Where CV_edge is the coefficient of variation of the edge,
computed from Monte Carlo simulations of historical return paths.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class KellyResult:
    """Result of a Kelly criterion calculation."""
    kelly_fraction: float          # Raw Kelly fraction
    empirical_fraction: float      # Adjusted fraction after MC
    cv_edge: float                 # Coefficient of variation of edge
    suggested_position_pct: float  # Final position size as % of bankroll
    half_kelly_pct: float          # Conservative half-Kelly size
    mc_mean_edge: float            # Mean edge from MC simulations
    mc_std_edge: float             # Std dev of edge from MC


class KellyCriterion:
    """Standard Kelly Criterion calculator for binary prediction markets."""

    @staticmethod
    def fraction(p: float, b: float) -> float:
        """
        Calculate the Kelly fraction for a binary bet.

        Args:
            p: Probability of winning (0 < p < 1)
            b: Net odds received on the bet (payout / stake - 1).
               For a market at price c, b = (1/c) - 1 for YES,
               or b = (1/(1-c)) - 1 for NO.

        Returns:
            Kelly fraction f* = (p*b - q) / b
        """
        if not 0 < p < 1:
            raise ValueError(f"p must be in (0, 1), got {p}")
        if b <= 0:
            raise ValueError(f"b must be positive, got {b}")

        q = 1 - p
        f = (p * b - q) / b
        return max(f, 0.0)  # Never go negative (don't bet)

    @staticmethod
    def fraction_from_market(fair_value: float, market_price: float, side: str = "YES") -> float:
        """
        Calculate Kelly fraction from fair value estimate vs market price.

        Args:
            fair_value: Our estimated true probability
            market_price: Current market price (0 < price < 1)
            side: "YES" or "NO"

        Returns:
            Kelly fraction for the given side
        """
        if side.upper() == "YES":
            p = fair_value
            b = (1.0 / market_price) - 1.0
        else:
            p = 1.0 - fair_value
            b = (1.0 / (1.0 - market_price)) - 1.0

        if b <= 0:
            return 0.0

        return KellyCriterion.fraction(p, b)


class EmpiricalKelly:
    """
    Empirical Kelly with Monte Carlo adjustment.

    Uses historical returns to estimate the coefficient of variation (CV)
    of the edge via Monte Carlo simulation, then adjusts the Kelly fraction
    downward to account for estimation uncertainty.

    f_empirical = f_kelly * (1 - CV_edge)
    """

    def __init__(
        self,
        n_simulations: int = 10_000,
        lookback_trades: int = 100,
        max_fraction: float = 0.20,
        min_trades_required: int = 30,
        seed: Optional[int] = None,
    ):
        """
        Args:
            n_simulations: Number of Monte Carlo paths to simulate
            lookback_trades: Number of recent trades to use for MC
            max_fraction: Maximum position size cap (safety)
            min_trades_required: Minimum trades needed before using empirical adjustment
            seed: Random seed for reproducibility
        """
        self.n_simulations = n_simulations
        self.lookback_trades = lookback_trades
        self.max_fraction = max_fraction
        self.min_trades_required = min_trades_required
        self.rng = np.random.default_rng(seed)

    def compute_cv_edge(self, historical_returns: np.ndarray) -> tuple[float, float, float]:
        """
        Compute coefficient of variation of edge via Monte Carlo.

        Bootstraps n_simulations samples from historical returns,
        computes the mean return (edge) of each sample, then
        returns CV = std(edges) / mean(edges).

        Args:
            historical_returns: Array of per-trade returns (e.g., +0.15, -0.08, ...)

        Returns:
            (cv_edge, mean_edge, std_edge)
        """
        n = len(historical_returns)
        if n < self.min_trades_required:
            # Not enough data — return high CV to be conservative
            mean_edge = float(np.mean(historical_returns)) if n > 0 else 0.0
            return 1.0, mean_edge, 0.0

        sample_size = min(n, self.lookback_trades)
        recent = historical_returns[-sample_size:]

        # Bootstrap: resample with replacement, compute mean of each sample
        edges = np.empty(self.n_simulations)
        for i in range(self.n_simulations):
            sample = self.rng.choice(recent, size=sample_size, replace=True)
            edges[i] = np.mean(sample)

        mean_edge = float(np.mean(edges))
        std_edge = float(np.std(edges, ddof=1))

        if abs(mean_edge) < 1e-10:
            return 1.0, mean_edge, std_edge

        cv_edge = std_edge / abs(mean_edge)
        return float(np.clip(cv_edge, 0.0, 1.0)), mean_edge, std_edge

    def size(
        self,
        fair_value: float,
        market_price: float,
        side: str,
        bankroll: float,
        historical_returns: Optional[np.ndarray] = None,
        regime: Optional[str] = None,
    ) -> KellyResult:
        """
        Calculate empirical Kelly position size.

        Args:
            fair_value: Our estimated true probability
            market_price: Current market price
            side: "YES" or "NO"
            bankroll: Total available capital
            historical_returns: Array of past trade returns for this strategy

        Returns:
            KellyResult with sizing details
        """
        kelly_f = KellyCriterion.fraction_from_market(fair_value, market_price, side)

        if kelly_f <= 0:
            return KellyResult(
                kelly_fraction=0.0,
                empirical_fraction=0.0,
                cv_edge=0.0,
                suggested_position_pct=0.0,
                half_kelly_pct=0.0,
                mc_mean_edge=0.0,
                mc_std_edge=0.0,
            )

        # If we have historical data, compute empirical adjustment
        if historical_returns is not None and len(historical_returns) > 0:
            cv_edge, mc_mean, mc_std = self.compute_cv_edge(historical_returns)
        else:
            # No history — use half Kelly as default conservative sizing
            cv_edge, mc_mean, mc_std = 0.5, 0.0, 0.0

        empirical_f = kelly_f * (1.0 - cv_edge)
        empirical_f = max(empirical_f, 0.0)

        # Apply max fraction cap; tighter in risk-off regime (12%)
        effective_max = self.max_fraction
        if regime == "risk_off":
            effective_max = min(effective_max, 0.12)
        capped_f = min(empirical_f, effective_max)

        return KellyResult(
            kelly_fraction=kelly_f,
            empirical_fraction=capped_f,
            cv_edge=cv_edge,
            suggested_position_pct=capped_f * 100.0,
            half_kelly_pct=(kelly_f / 2.0) * 100.0,
            mc_mean_edge=mc_mean,
            mc_std_edge=mc_std,
        )
