"""Tests for LTV monitor (ZER-1458 P0)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.ltv_monitor import LTVMonitor, LTVSeverity, LTVThresholds


class TestLTVMonitor:
    def test_normal_below_caution(self):
        mon = LTVMonitor()
        snap = mon.evaluate(400, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.NORMAL
        assert snap.should_delever is False
        assert snap.ltv_ratio == pytest.approx(0.40)

    def test_caution_at_52pct(self):
        mon = LTVMonitor()
        snap = mon.evaluate(520, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.CAUTION

    def test_warning_at_57pct(self):
        mon = LTVMonitor()
        snap = mon.evaluate(570, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.WARNING

    def test_critical_at_65pct(self):
        mon = LTVMonitor()
        snap = mon.evaluate(650, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.CRITICAL
        assert snap.should_delever is False

    def test_auto_delever_at_68pct(self):
        mon = LTVMonitor()
        snap = mon.evaluate(680, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.AUTO_DELEVER
        assert snap.should_delever is True

    def test_default_thresholds_match_spec(self):
        t = LTVThresholds()
        assert t.caution == 0.52
        assert t.warning == 0.57
        assert t.critical == 0.65
        assert t.auto_delever == 0.68

    def test_delever_target_below_caution(self):
        mon = LTVMonitor()
        assert mon.delever_target_ltv() == 0.52

    def test_invalid_collateral(self):
        mon = LTVMonitor()
        with pytest.raises(ValueError):
            mon.evaluate(100, 0)

    def test_invalid_threshold_order(self):
        with pytest.raises(ValueError):
            LTVMonitor(LTVThresholds(caution=0.70, warning=0.60, critical=0.50, auto_delever=0.40))

    def test_operating_baseline_is_normal(self):
        """50% operating baseline must NOT trigger CAUTION (was the bug)."""
        mon = LTVMonitor()
        snap = mon.evaluate(500, 1000, as_of_ts=1.0)
        assert snap.severity == LTVSeverity.NORMAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
