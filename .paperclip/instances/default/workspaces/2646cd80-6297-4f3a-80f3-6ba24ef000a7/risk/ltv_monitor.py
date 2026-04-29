"""
Loan-to-Value (LTV) monitor with tiered alert thresholds and auto-delever trigger.

Monitors portfolio LTV ratio against configurable thresholds.
Q2 2026 calibration: operating baseline ~50%, thresholds set above baseline
to avoid false CRITICAL alerts (see ZER-1113, ZER-1458).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class LTVSeverity(Enum):
    NORMAL = "normal"
    CAUTION = "caution"
    WARNING = "warning"
    CRITICAL = "critical"
    AUTO_DELEVER = "auto_delever"


@dataclass(frozen=True)
class LTVThresholds:
    """LTV alert thresholds as fractions (e.g. 0.52 = 52%)."""

    caution: float = 0.52
    warning: float = 0.57
    critical: float = 0.65
    auto_delever: float = 0.68


@dataclass(frozen=True)
class LTVSnapshot:
    """Point-in-time LTV measurement."""

    as_of_ts: float
    total_borrowed_usd: float
    total_collateral_usd: float
    ltv_ratio: float
    severity: LTVSeverity
    thresholds: LTVThresholds
    should_delever: bool
    message: str


class LTVMonitor:
    """
    Monitors loan-to-value ratio and emits tiered alerts.

    LTV = total_borrowed / total_collateral

    Thresholds (Q2 2026, ZER-1458):
      - Caution:     52%  (was 55%)
      - Warning:     57%  (was 60%)
      - Critical:    65%  (was 70%)
      - Auto-delever: 68% (NEW)
    """

    def __init__(self, thresholds: Optional[LTVThresholds] = None):
        self.thresholds = thresholds or LTVThresholds()
        self._validate_thresholds()

    def _validate_thresholds(self) -> None:
        t = self.thresholds
        if not (0 < t.caution < t.warning < t.critical <= t.auto_delever < 1.0):
            raise ValueError(
                f"Thresholds must be ordered: 0 < caution < warning < critical <= auto_delever < 1. "
                f"Got: caution={t.caution}, warning={t.warning}, critical={t.critical}, "
                f"auto_delever={t.auto_delever}"
            )

    def evaluate(
        self,
        total_borrowed_usd: float,
        total_collateral_usd: float,
        as_of_ts: Optional[float] = None,
    ) -> LTVSnapshot:
        """
        Evaluate current LTV ratio against thresholds.

        Args:
            total_borrowed_usd: Total borrowed value across all venues.
            total_collateral_usd: Total collateral value across all venues.
            as_of_ts: Timestamp for the snapshot (defaults to now).

        Returns:
            LTVSnapshot with severity classification and delever flag.
        """
        if total_collateral_usd <= 0:
            raise ValueError("total_collateral_usd must be > 0")
        if total_borrowed_usd < 0:
            raise ValueError("total_borrowed_usd must be >= 0")

        ltv = total_borrowed_usd / total_collateral_usd
        t = self.thresholds

        if ltv >= t.auto_delever:
            severity = LTVSeverity.AUTO_DELEVER
            should_delever = True
            msg = (
                f"AUTO-DELEVER: LTV {ltv:.1%} >= {t.auto_delever:.0%} trigger. "
                f"Reducing positions to restore LTV below {t.warning:.0%}."
            )
        elif ltv >= t.critical:
            severity = LTVSeverity.CRITICAL
            should_delever = False
            msg = f"CRITICAL: LTV {ltv:.1%} >= {t.critical:.0%}. Immediate review required."
        elif ltv >= t.warning:
            severity = LTVSeverity.WARNING
            should_delever = False
            msg = f"WARNING: LTV {ltv:.1%} >= {t.warning:.0%}. Consider reducing exposure."
        elif ltv >= t.caution:
            severity = LTVSeverity.CAUTION
            should_delever = False
            msg = f"CAUTION: LTV {ltv:.1%} >= {t.caution:.0%}. Monitoring closely."
        else:
            severity = LTVSeverity.NORMAL
            should_delever = False
            msg = f"NORMAL: LTV {ltv:.1%} within acceptable range."

        return LTVSnapshot(
            as_of_ts=as_of_ts if as_of_ts is not None else time.time(),
            total_borrowed_usd=total_borrowed_usd,
            total_collateral_usd=total_collateral_usd,
            ltv_ratio=ltv,
            severity=severity,
            thresholds=t,
            should_delever=should_delever,
            message=msg,
        )

    def delever_target_ltv(self) -> float:
        """Target LTV to restore after auto-delever triggers (below warning)."""
        return self.thresholds.caution
