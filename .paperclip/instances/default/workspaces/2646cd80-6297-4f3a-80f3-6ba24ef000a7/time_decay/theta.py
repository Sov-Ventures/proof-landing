"""
Time decay management for prediction market positions.

Calculates theta (θ = −ΔOption Value / ΔTime) and auto-exits positions
when edge < 3% or time remaining < 48 hours.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class DecayAnalysis:
    """Time decay analysis for a single position."""
    market_id: str
    side: str
    current_price: float
    fair_value: float
    edge_pct: float
    theta_per_hour: float
    hours_remaining: float
    should_exit: bool
    exit_reason: Optional[str]
    urgency: str  # "none", "low", "medium", "high", "immediate"


class TimeDecayManager:
    """
    Manages time decay for prediction market positions.

    Monitors theta and triggers exits when:
    - Edge drops below min_edge_pct (default 3%)
    - Time remaining < min_hours_remaining (default 48h)
    - Theta erosion makes holding unprofitable
    """

    def __init__(
        self,
        min_edge_pct: float = 3.0,
        min_hours_remaining: float = 48.0,
        theta_exit_threshold: float = -0.02,  # Exit if theta erodes >2% per hour
    ):
        self.min_edge_pct = min_edge_pct
        self.min_hours_remaining = min_hours_remaining
        self.theta_exit_threshold = theta_exit_threshold
        # Store price history for theta calculation: {market_id: [(timestamp, price)]}
        self._price_history: dict[str, list[tuple[float, float]]] = {}

    def record_price(self, market_id: str, price: float, timestamp: Optional[float] = None):
        """Record a price observation for theta calculation."""
        ts = timestamp or time.time()
        if market_id not in self._price_history:
            self._price_history[market_id] = []
        self._price_history[market_id].append((ts, price))

        # Keep last 48 hours of data
        cutoff = ts - (48 * 3600)
        self._price_history[market_id] = [
            (t, p) for t, p in self._price_history[market_id] if t >= cutoff
        ]

    def compute_theta(self, market_id: str) -> Optional[float]:
        """
        Calculate theta: θ = −ΔOption Value / ΔTime (per hour).

        Uses linear regression on recent price history to estimate
        the rate of time decay.

        Returns:
            Theta in price units per hour, or None if insufficient data
        """
        history = self._price_history.get(market_id, [])
        if len(history) < 2:
            return None

        # Use last N observations (at least 2 hours of data preferred)
        times = [h[0] for h in history]
        prices = [h[1] for h in history]

        # Simple linear regression: price = a + b*time
        n = len(times)
        t0 = times[0]
        # Convert to hours
        t_hours = [(t - t0) / 3600.0 for t in times]

        if t_hours[-1] - t_hours[0] < 0.5:
            # Less than 30 min of data — too noisy
            return None

        mean_t = sum(t_hours) / n
        mean_p = sum(prices) / n

        numerator = sum((t - mean_t) * (p - mean_p) for t, p in zip(t_hours, prices))
        denominator = sum((t - mean_t) ** 2 for t in t_hours)

        if abs(denominator) < 1e-10:
            return None

        slope = numerator / denominator
        # Theta is negative of slope (positive slope = price increasing = negative decay)
        return -slope

    def analyze(
        self,
        market_id: str,
        side: str,
        current_price: float,
        fair_value: float,
        expiry_time: float,
    ) -> DecayAnalysis:
        """
        Analyze time decay for a position and determine if exit is needed.

        Args:
            market_id: Market identifier
            side: "YES" or "NO"
            current_price: Current market price
            fair_value: Our estimated fair value
            expiry_time: Market expiry as Unix timestamp

        Returns:
            DecayAnalysis with exit recommendation
        """
        now = time.time()
        hours_remaining = max(0.0, (expiry_time - now) / 3600.0)

        # Calculate edge
        if side.upper() == "YES":
            edge_pct = (fair_value - current_price) * 100.0
        else:
            edge_pct = ((1.0 - fair_value) - (1.0 - current_price)) * 100.0
            # Simplifies to: edge_pct = (current_price - fair_value) * 100.0

        theta = self.compute_theta(market_id)
        theta_per_hour = theta if theta is not None else 0.0

        # Determine exit signal
        should_exit = False
        exit_reason = None
        urgency = "none"

        if hours_remaining < self.min_hours_remaining:
            should_exit = True
            exit_reason = f"Time remaining ({hours_remaining:.1f}h) < minimum ({self.min_hours_remaining}h)"
            urgency = "immediate" if hours_remaining < 12 else "high"

        elif edge_pct < self.min_edge_pct:
            should_exit = True
            exit_reason = f"Edge ({edge_pct:.1f}%) < minimum ({self.min_edge_pct}%)"
            urgency = "high" if edge_pct < 1.0 else "medium"

        elif theta is not None and theta < self.theta_exit_threshold:
            should_exit = True
            exit_reason = (
                f"Theta ({theta_per_hour:.4f}/hr) exceeds decay threshold "
                f"({self.theta_exit_threshold}/hr)"
            )
            urgency = "medium"

        elif edge_pct < self.min_edge_pct * 1.5:
            urgency = "low"

        return DecayAnalysis(
            market_id=market_id,
            side=side,
            current_price=current_price,
            fair_value=fair_value,
            edge_pct=edge_pct,
            theta_per_hour=theta_per_hour,
            hours_remaining=hours_remaining,
            should_exit=should_exit,
            exit_reason=exit_reason,
            urgency=urgency,
        )

    def scan_positions(
        self,
        positions: list[dict],
    ) -> list[DecayAnalysis]:
        """
        Scan all positions for time decay exits.

        Args:
            positions: List of dicts with keys:
                market_id, side, current_price, fair_value, expiry_time

        Returns:
            List of DecayAnalysis, sorted by urgency (immediate first)
        """
        urgency_order = {"immediate": 0, "high": 1, "medium": 2, "low": 3, "none": 4}

        results = []
        for pos in positions:
            analysis = self.analyze(
                market_id=pos["market_id"],
                side=pos["side"],
                current_price=pos["current_price"],
                fair_value=pos["fair_value"],
                expiry_time=pos["expiry_time"],
            )
            results.append(analysis)

        results.sort(key=lambda a: urgency_order.get(a.urgency, 4))
        return results
