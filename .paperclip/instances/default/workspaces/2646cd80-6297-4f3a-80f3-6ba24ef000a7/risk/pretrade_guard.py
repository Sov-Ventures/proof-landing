"""
Pre-trade portfolio risk guard.

Blocks new trades that would push venue concentration or total portfolio
concentration beyond configured limits.

Q2 2026 thresholds (ZER-1458):
  - Polymarket max concentration: 1.25 (was 1.50)
  - Hyperliquid max concentration: 1.75 (was 2.00)
  - OKX max concentration: 1.75 (was 2.00)
  - Max portfolio correlation: 0.65 (was 0.75)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PreTradeCheck:
    """Result of a pre-trade risk check."""

    allowed: bool
    venue: str
    proposed_exposure_usd: float
    current_venue_exposure_usd: float
    nav_usd: float
    venue_concentration: float
    venue_limit: float
    portfolio_correlation: Optional[float]
    correlation_limit: float
    rejection_reasons: tuple[str, ...]


@dataclass
class VenueConcentrationLimits:
    """Maximum venue exposure as a multiple of NAV."""

    polymarket: float = 1.25
    hyperliquid: float = 1.75
    okx: float = 1.75

    def limit_for(self, venue: str) -> float:
        venue_lower = venue.lower().replace("-", "").replace("_", "")
        limits = {
            "polymarket": self.polymarket,
            "hyperliquid": self.hyperliquid,
            "okx": self.okx,
        }
        if venue_lower not in limits:
            raise ValueError(
                f"Unknown venue '{venue}'. Supported: {list(limits.keys())}"
            )
        return limits[venue_lower]


class PreTradeGuard:
    """
    Pre-trade portfolio risk guard.

    Rejects proposed trades that would:
    1. Push venue concentration above venue-specific limits
    2. Push portfolio correlation above the max allowed threshold
    """

    def __init__(
        self,
        venue_limits: Optional[VenueConcentrationLimits] = None,
        max_portfolio_correlation: float = 0.65,
    ):
        self.venue_limits = venue_limits or VenueConcentrationLimits()
        self.max_portfolio_correlation = max_portfolio_correlation

    def check(
        self,
        venue: str,
        proposed_exposure_usd: float,
        current_venue_exposure_usd: float,
        nav_usd: float,
        portfolio_correlation: Optional[float] = None,
    ) -> PreTradeCheck:
        """
        Check whether a proposed trade passes pre-trade risk limits.

        Args:
            venue: Trading venue name (polymarket, hyperliquid, okx).
            proposed_exposure_usd: Additional exposure this trade would add.
            current_venue_exposure_usd: Existing exposure on this venue.
            nav_usd: Current portfolio NAV.
            portfolio_correlation: Current portfolio-wide pairwise correlation
                                   (optional; skipped if None).

        Returns:
            PreTradeCheck with allowed=True if all checks pass.
        """
        if nav_usd <= 0:
            raise ValueError("nav_usd must be > 0")
        if proposed_exposure_usd < 0:
            raise ValueError("proposed_exposure_usd must be >= 0")

        reasons: list[str] = []

        venue_limit = self.venue_limits.limit_for(venue)
        new_venue_exposure = current_venue_exposure_usd + proposed_exposure_usd
        venue_concentration = new_venue_exposure / nav_usd

        if venue_concentration > venue_limit:
            reasons.append(
                f"Venue concentration {venue_concentration:.2f}x would exceed "
                f"{venue} limit of {venue_limit:.2f}x NAV."
            )

        if portfolio_correlation is not None and portfolio_correlation > self.max_portfolio_correlation:
            reasons.append(
                f"Portfolio correlation {portfolio_correlation:.2f} exceeds "
                f"max {self.max_portfolio_correlation:.2f}."
            )

        return PreTradeCheck(
            allowed=len(reasons) == 0,
            venue=venue,
            proposed_exposure_usd=proposed_exposure_usd,
            current_venue_exposure_usd=current_venue_exposure_usd,
            nav_usd=nav_usd,
            venue_concentration=venue_concentration,
            venue_limit=venue_limit,
            portfolio_correlation=portfolio_correlation,
            correlation_limit=self.max_portfolio_correlation,
            rejection_reasons=tuple(reasons),
        )
