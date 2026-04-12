"""Unit tests for regime classification logic (no model required)."""

import numpy as np
import pandas as pd
import pytest

from kronos_service.forecast import KronosForecastService


def _make_sample_paths(final_returns: list[float]) -> list[pd.DataFrame]:
    """Create mock sample paths with specified final returns."""
    paths = []
    base_close = 100.0
    for ret in final_returns:
        df = pd.DataFrame({
            "open": [base_close, base_close * (1 + ret * 0.5)],
            "high": [base_close * 1.01, base_close * (1 + ret) * 1.01],
            "low": [base_close * 0.99, base_close * (1 + ret) * 0.99],
            "close": [base_close, base_close * (1 + ret)],
        })
        paths.append(df)
    return paths


class TestRegimeClassification:
    """Test _classify_regime on the KronosForecastService."""

    def setup_method(self):
        # Create service without loading model (we only test _classify_regime)
        self.svc = KronosForecastService.__new__(KronosForecastService)

    def test_trending_up(self):
        # 80% of paths go up significantly
        returns = [0.03] * 16 + [-0.01] * 4
        paths = _make_sample_paths(returns)
        regime, vol, confidence = self.svc._classify_regime(paths)
        assert regime == "trending_up"
        assert confidence > 0.65

    def test_trending_down(self):
        returns = [-0.03] * 16 + [0.01] * 4
        paths = _make_sample_paths(returns)
        regime, vol, confidence = self.svc._classify_regime(paths)
        assert regime == "trending_down"
        assert confidence > 0.65

    def test_mean_reverting(self):
        # Small returns, no clear direction
        returns = [0.002, -0.001, 0.003, -0.002, 0.001, -0.003, 0.002, -0.001,
                   0.001, -0.002, 0.003, -0.001, 0.002, -0.002, 0.001, -0.003,
                   0.002, -0.001, 0.001, -0.002]
        paths = _make_sample_paths(returns)
        regime, vol, confidence = self.svc._classify_regime(paths)
        assert regime == "mean_reverting"

    def test_volatile(self):
        # High dispersion, no clear direction
        returns = [0.05, -0.06, 0.07, -0.04, 0.08, -0.05, 0.06, -0.07,
                   0.04, -0.08, 0.05, -0.06, 0.07, -0.04, 0.08, -0.05,
                   0.06, -0.07, 0.04, -0.08]
        paths = _make_sample_paths(returns)
        regime, vol, confidence = self.svc._classify_regime(paths)
        assert regime == "volatile"

    def test_empty_paths(self):
        regime, vol, confidence = self.svc._classify_regime([])
        assert regime == "unknown"
        assert vol == 0.0
        assert confidence == 0.0
