"""Tests for portfolio VaR tracking and regime-aware circuit breakers."""

import os
import sqlite3
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.portfolio_var import (
    MetricSnapshotLogger,
    PortfolioVaRTracker,
    RegimeAwareCircuitBreaker,
    RegimeState,
    StrategyExposure,
    VaRMonitoringEngine,
)


def _series(seed: int, mu: float, sigma: float, n: int = 120) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, n)


class TestPortfolioVaRTracker:
    def test_historical_var_computes_positive_value(self):
        tracker = PortfolioVaRTracker(confidence=0.99, method="historical", min_samples=60)
        exposures = [
            StrategyExposure("eth_mm", 0.55),
            StrategyExposure("sol_mm", 0.45),
        ]
        strategy_returns = {
            "eth_mm": _series(11, mu=0.0004, sigma=0.020),
            "sol_mm": _series(22, mu=0.0002, sigma=0.025),
        }
        regime = RegimeState("neutral", confidence=0.8, score=0.1)
        snapshot = tracker.compute(
            strategy_returns=strategy_returns,
            exposures=exposures,
            portfolio_value_usd=1_000_000,
            threshold_pct=0.04,
            regime=regime,
            regime_multiplier=1.0,
            as_of_ts=1_700_000_000.0,
        )
        assert snapshot.var_pct > 0
        assert snapshot.var_usd > 0
        assert snapshot.threshold_pct == 0.04  # explicit override, not default
        assert snapshot.regime == "neutral"

    def test_parametric_var_respects_confidence(self):
        exposures = [StrategyExposure("strat", 1.0)]
        series = _series(33, mu=0.0001, sigma=0.015)
        regime = RegimeState("neutral")

        low = PortfolioVaRTracker(confidence=0.95, method="parametric", min_samples=60).compute(
            strategy_returns={"strat": series},
            exposures=exposures,
            portfolio_value_usd=500_000,
            threshold_pct=0.05,
            regime=regime,
            regime_multiplier=1.0,
        )
        high = PortfolioVaRTracker(confidence=0.99, method="parametric", min_samples=60).compute(
            strategy_returns={"strat": series},
            exposures=exposures,
            portfolio_value_usd=500_000,
            threshold_pct=0.05,
            regime=regime,
            regime_multiplier=1.0,
        )
        assert high.var_pct >= low.var_pct


class TestRegimeAwareCircuitBreaker:
    def test_q2_defaults(self):
        """Q2 2026 defaults: base 3.5%, risk_on 1.10x, risk_off 0.60x."""
        breaker = RegimeAwareCircuitBreaker()
        assert breaker.base_threshold_pct == 0.035
        assert breaker.regime_multipliers["risk_on"] == 1.10
        assert breaker.regime_multipliers["risk_off"] == 0.60

    def test_risk_off_tightens_threshold(self):
        breaker = RegimeAwareCircuitBreaker()
        neutral_threshold, neutral_mult = breaker.threshold_for_regime(RegimeState("neutral"))
        risk_off_threshold, risk_off_mult = breaker.threshold_for_regime(RegimeState("risk_off"))
        assert neutral_mult == 1.0
        assert risk_off_mult < neutral_mult
        assert risk_off_threshold < neutral_threshold

    def test_breach_triggers_halt(self):
        tracker = PortfolioVaRTracker(confidence=0.99, method="historical", min_samples=50)
        breaker = RegimeAwareCircuitBreaker(base_threshold_pct=0.01)
        engine = VaRMonitoringEngine(tracker=tracker, breaker=breaker)

        strategy_returns = {
            "high_vol": _series(44, mu=-0.0005, sigma=0.05, n=200),
        }
        exposures = [StrategyExposure("high_vol", 1.0)]
        snapshot, decision = engine.run(
            strategy_returns=strategy_returns,
            exposures=exposures,
            portfolio_value_usd=2_000_000,
            regime=RegimeState("risk_off", confidence=0.9, score=0.8),
        )
        assert snapshot.breached is True
        assert decision.should_halt_new_risk is True
        assert decision.severity in {"warning", "elevated", "critical"}


class TestMetricSnapshotLogger:
    def test_logs_metric_snapshot_row(self):
        tracker = PortfolioVaRTracker(confidence=0.99, method="historical", min_samples=50)
        breaker = RegimeAwareCircuitBreaker(base_threshold_pct=0.04)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "metrics.sqlite")
            logger = MetricSnapshotLogger(db_path)
            engine = VaRMonitoringEngine(tracker=tracker, breaker=breaker, logger=logger)

            strategy_returns = {
                "eth": _series(55, mu=0.0002, sigma=0.02, n=180),
                "sol": _series(66, mu=0.0001, sigma=0.03, n=180),
            }
            exposures = [
                StrategyExposure("eth", 0.6),
                StrategyExposure("sol", 0.4),
            ]
            snapshot, _ = engine.run(
                strategy_returns=strategy_returns,
                exposures=exposures,
                portfolio_value_usd=1_500_000,
                regime=RegimeState("neutral"),
                as_of_ts=1_700_100_000.0,
            )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT metric_name, value, threshold, unit, regime, captured_at "
                    "FROM metric_snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()

            assert row is not None
            assert row[0] == "portfolio_var_1d"
            assert abs(row[1] - snapshot.var_pct) < 1e-12
            assert abs(row[2] - snapshot.threshold_pct) < 1e-12
            assert row[3] == "fraction"
            assert row[4] == "neutral"
            assert row[5] == 1_700_100_000.0
