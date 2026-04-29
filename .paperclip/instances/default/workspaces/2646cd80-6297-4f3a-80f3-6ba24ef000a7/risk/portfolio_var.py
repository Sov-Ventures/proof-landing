"""
Portfolio-level VaR tracking with regime-aware circuit breakers.

This module supports:
1. Daily portfolio VaR estimation across active strategies
2. Regime-aware risk limits (risk-off => tighter limits)
3. Breach alerts when VaR exceeds limit
4. Logging snapshots into metric_snapshots for dashboarding
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np


@dataclass(frozen=True)
class StrategyExposure:
    """A strategy exposure as weight/fraction of total NAV."""

    name: str
    weight: float


@dataclass(frozen=True)
class RegimeState:
    """
    Market regime information from upstream detection logic.

    `regime` should be one of: risk_on, neutral, risk_off.
    """

    regime: str
    confidence: float = 0.0
    score: float = 0.0


@dataclass(frozen=True)
class VaRSnapshot:
    """Computed portfolio VaR at a point in time."""

    as_of_ts: float
    confidence: float
    method: str
    portfolio_value_usd: float
    var_pct: float
    var_usd: float
    threshold_pct: float
    threshold_usd: float
    regime: str
    regime_multiplier: float
    breached: bool


@dataclass(frozen=True)
class CircuitBreakerDecision:
    """Decision output for downstream execution/risk controls."""

    should_halt_new_risk: bool
    risk_reduction_target_pct: float
    severity: str
    message: str


class PortfolioVaRTracker:
    """
    Computes 1-day portfolio VaR from strategy-level return series.

    Supports:
    - Parametric VaR (normal assumption)
    - Historical VaR (empirical quantile)
    """

    def __init__(
        self,
        confidence: float = 0.99,
        method: str = "historical",
        min_samples: int = 30,
    ):
        if not 0.0 < confidence < 1.0:
            raise ValueError(f"confidence must be in (0, 1), got {confidence}")
        if method not in {"historical", "parametric"}:
            raise ValueError(f"method must be 'historical' or 'parametric', got {method}")
        self.confidence = confidence
        self.method = method
        self.min_samples = min_samples

    def _portfolio_returns(
        self,
        strategy_returns: dict[str, Iterable[float]],
        exposures: list[StrategyExposure],
    ) -> np.ndarray:
        if not exposures:
            raise ValueError("exposures cannot be empty")

        series = []
        weights = []
        for exp in exposures:
            if exp.name not in strategy_returns:
                raise ValueError(f"missing return series for strategy {exp.name}")
            values = np.asarray(list(strategy_returns[exp.name]), dtype=float)
            if values.size == 0:
                raise ValueError(f"empty return series for strategy {exp.name}")
            series.append(values)
            weights.append(exp.weight)

        min_len = min(len(s) for s in series)
        if min_len < self.min_samples:
            raise ValueError(
                f"not enough samples for VaR: {min_len} < min_samples({self.min_samples})"
            )

        clipped = np.vstack([s[-min_len:] for s in series])
        weight_vec = np.asarray(weights, dtype=float)
        if np.allclose(weight_vec.sum(), 0.0):
            raise ValueError("exposure weights sum to zero")

        normalized = weight_vec / weight_vec.sum()
        return normalized @ clipped

    def _z_score(self) -> float:
        # Fixed z values for common confidence levels to avoid scipy dependency.
        if abs(self.confidence - 0.95) < 1e-6:
            return 1.6448536269514722
        if abs(self.confidence - 0.99) < 1e-6:
            return 2.3263478740408408
        # Linear interpolation between 95% and 99% for nearby values.
        low_c, high_c = 0.95, 0.99
        low_z, high_z = 1.6448536269514722, 2.3263478740408408
        c = float(np.clip(self.confidence, low_c, high_c))
        alpha = (c - low_c) / (high_c - low_c)
        return low_z + alpha * (high_z - low_z)

    def compute(
        self,
        strategy_returns: dict[str, Iterable[float]],
        exposures: list[StrategyExposure],
        portfolio_value_usd: float,
        threshold_pct: float,
        regime: RegimeState,
        regime_multiplier: float,
        as_of_ts: Optional[float] = None,
    ) -> VaRSnapshot:
        if portfolio_value_usd <= 0:
            raise ValueError("portfolio_value_usd must be > 0")
        if threshold_pct <= 0:
            raise ValueError("threshold_pct must be > 0")
        if regime_multiplier <= 0:
            raise ValueError("regime_multiplier must be > 0")

        returns = self._portfolio_returns(strategy_returns, exposures)

        if self.method == "historical":
            percentile = (1.0 - self.confidence) * 100.0
            left_tail = np.percentile(returns, percentile)
            var_pct = max(0.0, -float(left_tail))
        else:
            mu = float(np.mean(returns))
            sigma = float(np.std(returns, ddof=1))
            z = self._z_score()
            var_pct = max(0.0, z * sigma - mu)

        threshold = threshold_pct * regime_multiplier
        var_usd = var_pct * portfolio_value_usd
        threshold_usd = threshold * portfolio_value_usd
        breached = var_pct > threshold

        return VaRSnapshot(
            as_of_ts=as_of_ts if as_of_ts is not None else time.time(),
            confidence=self.confidence,
            method=self.method,
            portfolio_value_usd=portfolio_value_usd,
            var_pct=var_pct,
            var_usd=var_usd,
            threshold_pct=threshold,
            threshold_usd=threshold_usd,
            regime=regime.regime,
            regime_multiplier=regime_multiplier,
            breached=breached,
        )


class RegimeAwareCircuitBreaker:
    """
    Regime-aware circuit breaker for portfolio-level VaR.

    Lower multipliers tighten limits in stressed regimes.
    """

    def __init__(
        self,
        base_threshold_pct: float = 0.035,
        regime_multipliers: Optional[dict[str, float]] = None,
    ):
        if base_threshold_pct <= 0:
            raise ValueError("base_threshold_pct must be > 0")
        self.base_threshold_pct = base_threshold_pct
        self.regime_multipliers = regime_multipliers or {
            "risk_on": 1.10,
            "neutral": 1.00,
            "risk_off": 0.60,
        }

    def threshold_for_regime(self, regime: RegimeState) -> tuple[float, float]:
        multiplier = self.regime_multipliers.get(regime.regime, 1.0)
        return self.base_threshold_pct * multiplier, multiplier

    def evaluate(self, snapshot: VaRSnapshot) -> CircuitBreakerDecision:
        if not snapshot.breached:
            return CircuitBreakerDecision(
                should_halt_new_risk=False,
                risk_reduction_target_pct=0.0,
                severity="none",
                message="VaR within limit; no circuit breaker action required.",
            )

        overage = snapshot.var_pct - snapshot.threshold_pct
        overage_ratio = overage / max(snapshot.threshold_pct, 1e-12)

        if overage_ratio < 0.10:
            severity = "warning"
            cut = 0.20
        elif overage_ratio < 0.40:
            severity = "elevated"
            cut = 0.35
        else:
            severity = "critical"
            cut = 0.60

        return CircuitBreakerDecision(
            should_halt_new_risk=True,
            risk_reduction_target_pct=cut,
            severity=severity,
            message=(
                f"Circuit breaker triggered ({severity}): VaR {snapshot.var_pct:.2%} "
                f"> limit {snapshot.threshold_pct:.2%} in {snapshot.regime} regime."
            ),
        )


class MetricSnapshotLogger:
    """Writes VaR snapshots into a metric_snapshots SQL table."""

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS metric_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      metric_name TEXT NOT NULL,
      value REAL NOT NULL,
      threshold REAL,
      unit TEXT NOT NULL,
      regime TEXT,
      tags_json TEXT,
      captured_at REAL NOT NULL
    )
    """

    INSERT_SQL = """
    INSERT INTO metric_snapshots (
      metric_name, value, threshold, unit, regime, tags_json, captured_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.commit()

    def log_var_snapshot(self, snapshot: VaRSnapshot, tags_json: str = "{}") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                self.INSERT_SQL,
                (
                    "portfolio_var_1d",
                    snapshot.var_pct,
                    snapshot.threshold_pct,
                    "fraction",
                    snapshot.regime,
                    tags_json,
                    snapshot.as_of_ts,
                ),
            )
            conn.commit()


class VaRMonitoringEngine:
    """High-level orchestration helper for tracking + breaker + logging."""

    def __init__(
        self,
        tracker: PortfolioVaRTracker,
        breaker: RegimeAwareCircuitBreaker,
        logger: Optional[MetricSnapshotLogger] = None,
    ):
        self.tracker = tracker
        self.breaker = breaker
        self.logger = logger

    def run(
        self,
        strategy_returns: dict[str, Iterable[float]],
        exposures: list[StrategyExposure],
        portfolio_value_usd: float,
        regime: RegimeState,
        as_of_ts: Optional[float] = None,
    ) -> tuple[VaRSnapshot, CircuitBreakerDecision]:
        threshold, multiplier = self.breaker.threshold_for_regime(regime)
        snapshot = self.tracker.compute(
            strategy_returns=strategy_returns,
            exposures=exposures,
            portfolio_value_usd=portfolio_value_usd,
            threshold_pct=self.breaker.base_threshold_pct,
            regime=regime,
            regime_multiplier=multiplier,
            as_of_ts=as_of_ts,
        )
        decision = self.breaker.evaluate(snapshot)
        if self.logger is not None:
            self.logger.log_var_snapshot(snapshot)
        return snapshot, decision
