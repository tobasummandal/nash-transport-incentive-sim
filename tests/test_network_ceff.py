"""Tests for the microscopically fitted pacer capacity model in Corridor."""

import math

import pytest

from src.simulation.network import Corridor


def make(**kw):
    c = Corridor(corridor_id="c", name="c", length_miles=10, num_lanes=3, **kw)
    return c


class TestEffectiveCapacity:
    def test_default_linear_model_unchanged(self):
        c = make()
        assert c.effective_capacity_multiplier() == 1.0
        c.current_volume = 1000; c.active_pacers = 50
        assert c.effective_capacity_multiplier() == 1.0  # linear model ignores c_eff

    def test_micro_no_pacers_is_identity(self):
        c = make(pacer_model="micro", ceff_kappa=0.1, ceff_p0=0.05)
        c.current_volume = 1000
        assert c.effective_capacity_multiplier() == 1.0

    def test_micro_curve_shape(self):
        c = make(pacer_model="micro", ceff_kappa=0.1, ceff_p0=0.05)
        c.current_volume = 1000
        c.active_pacers = 50  # p = 0.05
        expected = 1.0 + 0.1 * (1 - math.exp(-1.0))
        assert c.effective_capacity_multiplier() == pytest.approx(expected)
        c.active_pacers = 1000  # saturates toward 1 + kappa
        assert c.effective_capacity_multiplier() == pytest.approx(1.1, abs=1e-6)

    def test_micro_reduces_congestion_factor_monotonically(self):
        c = make(pacer_model="micro", ceff_kappa=0.1, ceff_p0=0.05)
        c.current_volume = c._instantaneous_capacity() * 1.1
        cf0 = c.get_congestion_factor()
        prev = cf0
        for n in (10, 30, 60, 120):
            c.active_pacers = n
            cf = c.get_congestion_factor()
            assert cf <= prev
            prev = cf
        assert prev < cf0

    def test_micro_does_not_apply_linear_reduction(self):
        lin = make(pacer_model="linear"); mic = make(pacer_model="micro", ceff_kappa=0.0)
        for c in (lin, mic):
            c.current_volume = c._instantaneous_capacity() * 1.1
            c.active_pacers = 100
        # kappa=0 micro model must equal the no-pacer BPR value, linear must be lower.
        base = make(); base.current_volume = lin.current_volume
        assert mic.get_congestion_factor() == pytest.approx(base.get_congestion_factor())
        assert lin.get_congestion_factor() < base.get_congestion_factor()
