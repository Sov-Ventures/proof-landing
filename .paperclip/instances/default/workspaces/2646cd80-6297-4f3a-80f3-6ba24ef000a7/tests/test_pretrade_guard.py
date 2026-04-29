"""Tests for pre-trade portfolio risk guard (ZER-1458 P1)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.pretrade_guard import PreTradeGuard, VenueConcentrationLimits


class TestVenueConcentrationLimits:
    def test_defaults_match_spec(self):
        lim = VenueConcentrationLimits()
        assert lim.polymarket == 1.25
        assert lim.hyperliquid == 1.75
        assert lim.okx == 1.75

    def test_unknown_venue_raises(self):
        lim = VenueConcentrationLimits()
        with pytest.raises(ValueError):
            lim.limit_for("binance")


class TestPreTradeGuard:
    def test_allows_within_limits(self):
        guard = PreTradeGuard()
        result = guard.check(
            venue="polymarket",
            proposed_exposure_usd=100,
            current_venue_exposure_usd=200,
            nav_usd=1000,
        )
        assert result.allowed is True
        assert len(result.rejection_reasons) == 0

    def test_rejects_polymarket_over_125x(self):
        guard = PreTradeGuard()
        result = guard.check(
            venue="polymarket",
            proposed_exposure_usd=500,
            current_venue_exposure_usd=900,
            nav_usd=1000,
        )
        assert result.allowed is False
        assert result.venue_concentration == pytest.approx(1.4)
        assert "polymarket" in result.rejection_reasons[0].lower()

    def test_rejects_high_correlation(self):
        guard = PreTradeGuard()
        result = guard.check(
            venue="hyperliquid",
            proposed_exposure_usd=100,
            current_venue_exposure_usd=100,
            nav_usd=1000,
            portfolio_correlation=0.70,
        )
        assert result.allowed is False
        assert "correlation" in result.rejection_reasons[0].lower()

    def test_correlation_at_limit_passes(self):
        guard = PreTradeGuard()
        result = guard.check(
            venue="okx",
            proposed_exposure_usd=100,
            current_venue_exposure_usd=100,
            nav_usd=1000,
            portfolio_correlation=0.65,
        )
        assert result.allowed is True

    def test_max_portfolio_correlation_default(self):
        guard = PreTradeGuard()
        assert guard.max_portfolio_correlation == 0.65

    def test_invalid_nav(self):
        guard = PreTradeGuard()
        with pytest.raises(ValueError):
            guard.check("polymarket", 100, 0, 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
