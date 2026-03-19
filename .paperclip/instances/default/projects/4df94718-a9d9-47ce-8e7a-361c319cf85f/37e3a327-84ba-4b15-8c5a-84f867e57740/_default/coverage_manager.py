"""
Coverage Manager — Regime-Aware Covered Call Coverage Ratios

Shared infrastructure module that maps market regime classifications to
BTC covered call coverage ratios. Loads Sigma's regime_coverage_config.json
and provides a single entry point for the cc_strategy to determine how much
of the BTC holdings to cover.

Features:
- 6 regimes → coverage ratios (40%–70%)
- IV (DVOL) overrides when implied vol diverges from price regime
- Circuit breakers for rapid rallies, consecutive assignments, monthly P&L
- Static/default regime fallback when live model is unavailable

Author: Zeta (Trading Engineer) | ZER-121
Config: Sigma (Head of Research) | ZER-116
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default config path ──────────────────────────────────────────────────────
_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "Sites"
    / "zeropoint-os"
    / "agents"
    / "Sigma - Head of Research"
    / "research"
    / "regime_coverage_config.json"
)

# Also check relative to zeropoint-os repo root
_REPO_CONFIG_PATH = (
    Path("/Users/abreckler/Sites/zeropoint-os")
    / "agents"
    / "Sigma - Head of Research"
    / "research"
    / "regime_coverage_config.json"
)


@dataclass
class CircuitBreakerState:
    """Tracks circuit breaker conditions across cycles."""

    pause_writes_until: float = 0.0  # unix timestamp
    consecutive_assignments: int = 0
    pause_cycles_remaining: int = 0
    monthly_pnl_btc: float = 0.0
    needs_parameter_review: bool = False


@dataclass
class CoverageDecision:
    """Result of a coverage calculation."""

    coverage_ratio: float
    regime: str
    source: str  # "regime_map", "iv_override", "circuit_breaker", "default"
    reason: str
    paused: bool = False


class CoverageManager:
    """
    Determines covered call coverage ratio based on market regime,
    IV conditions, and circuit breaker state.

    Usage:
        mgr = CoverageManager()
        # or: mgr = CoverageManager(config_path="/path/to/config.json")

        decision = mgr.get_coverage(regime="neutral")
        # decision.coverage_ratio -> 0.60

        decision = mgr.get_coverage(regime="trending_up", dvol=85.0)
        # decision.coverage_ratio -> 0.70 (IV override)

        decision = mgr.get_coverage(regime="neutral", btc_24h_change_pct=9.0)
        # decision.paused -> True (circuit breaker)
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config = self._load_config(config_path)
        self._regime_map: dict[str, float] = {
            k: v["coverage_ratio"]
            for k, v in self._config["regime_coverage_map"].items()
        }
        self._iv_overrides = self._config.get("iv_regime_overrides", {})
        self._circuit_breakers = self._config.get("circuit_breakers", {})
        self._defaults = self._config.get("defaults", {})
        self._cb_state = CircuitBreakerState()

    def _load_config(self, config_path: Optional[str]) -> dict:
        """Load regime coverage config from JSON file."""
        paths_to_try = []
        if config_path:
            paths_to_try.append(Path(config_path))
        paths_to_try.extend([_REPO_CONFIG_PATH, _DEFAULT_CONFIG_PATH])

        for path in paths_to_try:
            if path.exists():
                with open(path) as f:
                    config = json.load(f)
                logger.info("Loaded regime coverage config from %s", path)
                return config

        logger.warning("No config found, using hardcoded defaults")
        return self._hardcoded_defaults()

    @staticmethod
    def _hardcoded_defaults() -> dict:
        """Fallback config if JSON file is unavailable."""
        return {
            "regime_coverage_map": {
                "trending_up": {"coverage_ratio": 0.40},
                "high_vol": {"coverage_ratio": 0.60},
                "low_vol": {"coverage_ratio": 0.60},
                "neutral": {"coverage_ratio": 0.60},
                "trending_down": {"coverage_ratio": 0.70},
                "crisis": {"coverage_ratio": 0.70},
            },
            "iv_regime_overrides": {
                "dvol_above_80": {"coverage_ratio": 0.70},
                "dvol_below_30": {"coverage_ratio": 0.00},
            },
            "circuit_breakers": {
                "btc_24h_rally_pct": 8.0,
                "btc_24h_rally_action": "pause_new_writes_48h",
                "consecutive_assignments_max": 3,
                "consecutive_assignments_action": "pause_1_cycle",
                "monthly_pnl_negative_btc": True,
                "monthly_pnl_negative_action": "review_parameters",
            },
            "defaults": {
                "base_coverage_ratio": 0.60,
                "fallback_on_model_failure": 0.60,
                "min_coverage_ratio": 0.0,
                "max_coverage_ratio": 0.70,
            },
        }

    @property
    def base_coverage(self) -> float:
        return self._defaults.get("base_coverage_ratio", 0.60)

    @property
    def fallback_coverage(self) -> float:
        return self._defaults.get("fallback_on_model_failure", 0.60)

    @property
    def min_coverage(self) -> float:
        return self._defaults.get("min_coverage_ratio", 0.0)

    @property
    def max_coverage(self) -> float:
        return self._defaults.get("max_coverage_ratio", 0.70)

    def get_coverage(
        self,
        regime: Optional[str] = None,
        dvol: Optional[float] = None,
        btc_24h_change_pct: Optional[float] = None,
    ) -> CoverageDecision:
        """
        Determine coverage ratio based on regime, IV, and circuit breakers.

        Args:
            regime: Market regime from classify_regime(). None = use default.
            dvol: Current Deribit DVOL index value. None = skip IV overrides.
            btc_24h_change_pct: BTC price change over last 24h (%). None = skip rally check.

        Returns:
            CoverageDecision with ratio, source, and whether overlay is paused.
        """
        # Step 1: Check circuit breakers first (they can pause everything)
        cb_decision = self._check_circuit_breakers(btc_24h_change_pct)
        if cb_decision is not None:
            return cb_decision

        # Step 2: IV overrides take precedence over regime map
        if dvol is not None:
            iv_decision = self._check_iv_overrides(dvol, regime)
            if iv_decision is not None:
                return iv_decision

        # Step 3: Regime-based coverage
        if regime and regime in self._regime_map:
            ratio = self._regime_map[regime]
            ratio = self._clamp(ratio)
            return CoverageDecision(
                coverage_ratio=ratio,
                regime=regime,
                source="regime_map",
                reason=f"Regime '{regime}' maps to {ratio:.0%} coverage",
            )

        # Step 4: Default/fallback
        fallback = self.fallback_coverage if regime is not None else self.base_coverage
        return CoverageDecision(
            coverage_ratio=fallback,
            regime=regime or "unknown",
            source="default",
            reason=f"Using {'fallback' if regime else 'base'} coverage {fallback:.0%}",
        )

    def _check_iv_overrides(
        self, dvol: float, regime: Optional[str]
    ) -> Optional[CoverageDecision]:
        """Check if DVOL triggers an IV-based override."""
        dvol_above = self._iv_overrides.get("dvol_above_80", {})
        dvol_below = self._iv_overrides.get("dvol_below_30", {})

        if dvol >= 80 and dvol_above:
            ratio = self._clamp(dvol_above["coverage_ratio"])
            if ratio == 0.0:
                return CoverageDecision(
                    coverage_ratio=0.0,
                    regime=regime or "unknown",
                    source="iv_override",
                    reason=f"DVOL {dvol:.1f} >= 80: overlay suspended",
                    paused=True,
                )
            return CoverageDecision(
                coverage_ratio=ratio,
                regime=regime or "unknown",
                source="iv_override",
                reason=f"DVOL {dvol:.1f} >= 80: override to {ratio:.0%}",
            )

        if dvol <= 30 and dvol_below:
            ratio = dvol_below["coverage_ratio"]
            return CoverageDecision(
                coverage_ratio=0.0,
                regime=regime or "unknown",
                source="iv_override",
                reason=f"DVOL {dvol:.1f} <= 30: premiums too thin, overlay suspended",
                paused=True,
            )

        return None

    def _check_circuit_breakers(
        self, btc_24h_change_pct: Optional[float]
    ) -> Optional[CoverageDecision]:
        """Check circuit breaker conditions."""
        now = time.time()

        # Check if we're in a pause-writes window
        if self._cb_state.pause_writes_until > now:
            remaining_hours = (self._cb_state.pause_writes_until - now) / 3600
            return CoverageDecision(
                coverage_ratio=0.0,
                regime="circuit_breaker",
                source="circuit_breaker",
                reason=f"Writes paused for {remaining_hours:.1f}h more (24h rally breaker)",
                paused=True,
            )

        # Check pause cycles from consecutive assignments
        if self._cb_state.pause_cycles_remaining > 0:
            self._cb_state.pause_cycles_remaining -= 1
            return CoverageDecision(
                coverage_ratio=0.0,
                regime="circuit_breaker",
                source="circuit_breaker",
                reason=f"Paused for {self._cb_state.pause_cycles_remaining + 1} cycle(s) (consecutive assignments)",
                paused=True,
            )

        # Check 24h rally
        rally_threshold = self._circuit_breakers.get("btc_24h_rally_pct", 8.0)
        if btc_24h_change_pct is not None and btc_24h_change_pct >= rally_threshold:
            self._cb_state.pause_writes_until = now + 48 * 3600  # 48h pause
            logger.warning(
                "Circuit breaker: BTC 24h rally %.1f%% >= %.1f%% threshold, pausing 48h",
                btc_24h_change_pct,
                rally_threshold,
            )
            return CoverageDecision(
                coverage_ratio=0.0,
                regime="circuit_breaker",
                source="circuit_breaker",
                reason=f"BTC rallied {btc_24h_change_pct:.1f}% in 24h (>= {rally_threshold}%), pausing 48h",
                paused=True,
            )

        return None

    def record_assignment(self) -> Optional[CoverageDecision]:
        """
        Record a call assignment event. Returns a pause decision if
        consecutive assignment limit is hit.
        """
        self._cb_state.consecutive_assignments += 1
        max_consecutive = self._circuit_breakers.get("consecutive_assignments_max", 3)

        if self._cb_state.consecutive_assignments >= max_consecutive:
            self._cb_state.pause_cycles_remaining = 1
            logger.warning(
                "Circuit breaker: %d consecutive assignments (max %d), pausing 1 cycle",
                self._cb_state.consecutive_assignments,
                max_consecutive,
            )
            return CoverageDecision(
                coverage_ratio=0.0,
                regime="circuit_breaker",
                source="circuit_breaker",
                reason=f"{self._cb_state.consecutive_assignments} consecutive assignments, pausing 1 cycle",
                paused=True,
            )
        return None

    def record_expiry_no_assignment(self):
        """Record a call expiry without assignment (resets consecutive counter)."""
        self._cb_state.consecutive_assignments = 0

    def record_monthly_pnl(self, pnl_btc: float):
        """
        Record monthly P&L. Flags for parameter review if negative.
        """
        self._cb_state.monthly_pnl_btc = pnl_btc
        check_negative = self._circuit_breakers.get("monthly_pnl_negative_btc", True)
        if check_negative and pnl_btc < 0:
            self._cb_state.needs_parameter_review = True
            logger.warning(
                "Monthly P&L negative (%.6f BTC), flagging for parameter review",
                pnl_btc,
            )

    @property
    def needs_parameter_review(self) -> bool:
        return self._cb_state.needs_parameter_review

    def clear_parameter_review(self):
        self._cb_state.needs_parameter_review = False

    def reset_circuit_breakers(self):
        """Reset all circuit breaker state (for testing or manual override)."""
        self._cb_state = CircuitBreakerState()

    def _clamp(self, ratio: float) -> float:
        """Clamp coverage ratio to configured min/max bounds."""
        return max(self.min_coverage, min(self.max_coverage, ratio))

    def get_regime_map(self) -> dict[str, float]:
        """Return the full regime → coverage ratio map (for logging/display)."""
        return dict(self._regime_map)

    def __repr__(self) -> str:
        return (
            f"CoverageManager(base={self.base_coverage:.0%}, "
            f"regimes={len(self._regime_map)}, "
            f"review_needed={self.needs_parameter_review})"
        )
