"""Tests for Empirical Kelly Criterion position sizing."""

import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from position_sizing.kelly import KellyCriterion, EmpiricalKelly


class TestKellyCriterion:

    def test_basic_kelly(self):
        """Fair coin with 2:1 odds => f* = (0.5*1 - 0.5)/1 = 0"""
        # p=0.5, b=1 (even money) => 0
        assert KellyCriterion.fraction(0.5, 1.0) == 0.0

    def test_positive_edge(self):
        """60% win rate at even money => f* = 0.2"""
        f = KellyCriterion.fraction(0.6, 1.0)
        assert abs(f - 0.2) < 1e-10

    def test_high_odds(self):
        """30% win at 3:1 odds => f* = (0.3*3 - 0.7)/3 = 0.0667"""
        f = KellyCriterion.fraction(0.3, 3.0)
        assert abs(f - (0.3 * 3 - 0.7) / 3) < 1e-10

    def test_no_edge_returns_zero(self):
        """Negative edge should return 0 (don't bet)."""
        f = KellyCriterion.fraction(0.3, 1.0)
        assert f == 0.0

    def test_invalid_probability(self):
        with pytest.raises(ValueError):
            KellyCriterion.fraction(0.0, 1.0)
        with pytest.raises(ValueError):
            KellyCriterion.fraction(1.0, 1.0)

    def test_from_market_yes(self):
        """Fair value 0.7, market 0.5 YES => positive Kelly."""
        f = KellyCriterion.fraction_from_market(0.7, 0.5, "YES")
        # b = 1/0.5 - 1 = 1.0, f = (0.7*1 - 0.3)/1 = 0.4
        assert abs(f - 0.4) < 1e-10

    def test_from_market_no(self):
        """Fair value 0.3, market 0.5 NO => positive Kelly."""
        f = KellyCriterion.fraction_from_market(0.3, 0.5, "NO")
        # p = 0.7, b = 1/0.5 - 1 = 1.0, f = (0.7*1 - 0.3)/1 = 0.4
        assert abs(f - 0.4) < 1e-10


class TestEmpiricalKelly:

    def test_cv_edge_with_consistent_returns(self):
        """Consistent positive returns should have low CV."""
        ek = EmpiricalKelly(n_simulations=5000, seed=42)
        returns = np.array([0.05] * 50 + [0.06] * 50)  # Very consistent
        cv, mean, std = ek.compute_cv_edge(returns)
        assert cv < 0.1  # Low CV
        assert mean > 0.04

    def test_cv_edge_with_noisy_returns(self):
        """Noisy returns should have higher CV."""
        ek = EmpiricalKelly(n_simulations=5000, seed=42)
        rng = np.random.default_rng(123)
        returns = rng.normal(0.02, 0.15, 100)  # High variance
        cv, mean, std = ek.compute_cv_edge(returns)
        assert cv > 0.2  # Higher uncertainty

    def test_insufficient_data(self):
        """Too few trades => CV = 1.0 (maximum conservatism)."""
        ek = EmpiricalKelly(min_trades_required=20, seed=42)
        returns = np.array([0.05, 0.03, 0.04])
        cv, _, _ = ek.compute_cv_edge(returns)
        assert cv == 1.0

    def test_empirical_smaller_than_kelly(self):
        """Empirical Kelly should always be <= raw Kelly."""
        ek = EmpiricalKelly(seed=42)
        returns = np.random.default_rng(42).normal(0.05, 0.10, 50)
        result = ek.size(
            fair_value=0.65,
            market_price=0.50,
            side="YES",
            bankroll=10000,
            historical_returns=returns,
        )
        assert result.empirical_fraction <= result.kelly_fraction

    def test_max_fraction_cap(self):
        """Position size should never exceed max_fraction."""
        ek = EmpiricalKelly(max_fraction=0.10, seed=42)
        returns = np.array([0.20] * 100)  # Extremely consistent high returns
        result = ek.size(
            fair_value=0.90,
            market_price=0.50,
            side="YES",
            bankroll=10000,
            historical_returns=returns,
        )
        assert result.empirical_fraction <= 0.10

    def test_no_edge_no_bet(self):
        """No edge => zero position."""
        ek = EmpiricalKelly(seed=42)
        result = ek.size(
            fair_value=0.50,
            market_price=0.50,
            side="YES",
            bankroll=10000,
        )
        assert result.suggested_position_pct == 0.0

    def test_no_history_uses_half_kelly(self):
        """Without history, CV defaults to 0.5 (effectively half-Kelly)."""
        ek = EmpiricalKelly(max_fraction=1.0, seed=42)
        result = ek.size(
            fair_value=0.70,
            market_price=0.50,
            side="YES",
            bankroll=10000,
        )
        assert result.cv_edge == 0.5
        expected = result.kelly_fraction * 0.5
        assert abs(result.empirical_fraction - expected) < 1e-10


class TestVWAPExecutor:

    def test_plan_creation(self):
        from execution.vwap import VWAPExecutor, OrderbookTracker

        ob = OrderbookTracker()
        ob.update(
            bids=[{"price": 0.49, "size": 500}, {"price": 0.48, "size": 1000}],
            asks=[{"price": 0.51, "size": 500}, {"price": 0.52, "size": 1000}],
            sequence=1,
        )
        executor = VWAPExecutor()
        plan = executor.create_plan(1000, "buy", 0.51, ob)
        assert len(plan.slices) >= 3
        assert abs(plan.total_size - 1000) < 1e-10

    def test_orderbook_sequence_gap(self):
        from execution.vwap import OrderbookTracker

        ob = OrderbookTracker()
        ob.update([], [], 1)
        assert ob.update([], [], 2) is True
        assert ob.update([], [], 5) is False  # Gap
        assert ob.gap_count == 1


class TestTimeDecay:

    def test_exit_on_low_edge(self):
        from time_decay.theta import TimeDecayManager
        import time as _time

        mgr = TimeDecayManager(min_edge_pct=3.0)
        future = _time.time() + 7 * 24 * 3600  # 7 days out
        result = mgr.analyze("mkt1", "YES", 0.50, 0.51, future)
        # Edge = 1% < 3% minimum
        assert result.should_exit is True
        assert "Edge" in result.exit_reason

    def test_exit_on_time(self):
        from time_decay.theta import TimeDecayManager
        import time as _time

        mgr = TimeDecayManager(min_hours_remaining=48.0)
        soon = _time.time() + 24 * 3600  # 24h out
        result = mgr.analyze("mkt2", "YES", 0.50, 0.70, soon)
        # Good edge but too close to expiry
        assert result.should_exit is True
        assert "Time remaining" in result.exit_reason

    def test_no_exit_healthy_position(self):
        from time_decay.theta import TimeDecayManager
        import time as _time

        mgr = TimeDecayManager()
        future = _time.time() + 14 * 24 * 3600  # 14 days
        result = mgr.analyze("mkt3", "YES", 0.50, 0.60, future)
        # Edge = 10%, plenty of time
        assert result.should_exit is False
        assert result.urgency == "none"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
