"""
Tests for the microscopic car-following layer.

The physics checks here are the ones that matter for validation:
IDM equilibrium is consistent, a dense ring breaks into a backward-moving
jam, and a single FollowerStopper pacer dissipates it.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.simulation.car_following import (
    FollowerStopperController,
    IDMParams,
    OpenRoad,
    RingRoad,
    SmoothedVelocityController,
    estimate_wave_speed,
    idm_acceleration,
    summarize,
)

UNSTABLE = IDMParams(v0=30, T=1.6, a=0.73, b=1.67, s0=2, length=5)


# ---------------------------------------------------------------- IDM core


class TestIDM:
    def test_free_road_accelerates_toward_v0(self):
        acc = idm_acceleration(
            np.array([10.0]), np.array([1e4]), np.array([0.0]),
            np.array([30.0]), np.array([1.5]), 1.0, 2.0, 2.0, 4.0,
        )
        assert acc[0] > 0

    def test_at_v0_free_road_zero_accel(self):
        acc = idm_acceleration(
            np.array([30.0]), np.array([1e4]), np.array([0.0]),
            np.array([30.0]), np.array([1.5]), 1.0, 2.0, 2.0, 4.0,
        )
        assert acc[0] == pytest.approx(0.0, abs=1e-4)

    def test_closing_fast_brakes_hard(self):
        acc = idm_acceleration(
            np.array([30.0]), np.array([20.0]), np.array([30.0]),
            np.array([30.0]), np.array([1.5]), 1.0, 2.0, 2.0, 4.0,
        )
        assert acc[0] < -2.0

    def test_equilibrium_speed_monotone_in_gap(self):
        r = RingRoad(n_vehicles=10, length=1000)
        v_small = r.equilibrium_speed(10.0)
        v_large = r.equilibrium_speed(200.0)
        assert 0 < v_small < v_large <= r.params.v0

    def test_equilibrium_has_zero_accel(self):
        r = RingRoad(n_vehicles=10, length=1000, v0_cv=0.0, T_cv=0.0)
        gap = 40.0
        v = r.equilibrium_speed(gap)
        p = r.params
        acc = idm_acceleration(
            np.array([v]), np.array([gap]), np.array([0.0]),
            np.array([p.v0]), np.array([p.T]), p.a, p.b, p.s0, p.delta,
        )
        assert acc[0] == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------- ring road


class TestRingRoad:
    def test_initial_layout_uniform(self):
        r = RingRoad(n_vehicles=20, length=1000)
        gaps = np.diff(np.append(r.x, r.x[0] + r.length))
        assert np.allclose(gaps, 50.0)

    def test_positions_stay_on_ring(self):
        r = RingRoad(n_vehicles=20, length=1000)
        for _ in range(500):
            r.step()
        assert np.all((r.x >= 0) & (r.x < r.length))

    def test_no_collisions(self):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE, seed=3)
        r.reset(perturbation=5.0)
        for _ in range(6000):
            r.step()
            gap, _ = r._gaps()
            assert gap.min() > 0, "vehicles overlapped"

    def test_homogeneous_unperturbed_stays_uniform(self):
        r = RingRoad(n_vehicles=20, length=1000, v0_cv=0.0, T_cv=0.0)
        tr = r.run(300, perturbation=0.0)
        assert tr.speed_std(after=0) < 1e-6

    def test_dense_ring_develops_stop_and_go(self):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     v0_cv=0.05, T_cv=0.05, seed=1)
        tr = r.run(2400, perturbation=3.0)
        assert tr.speed_std(after=1200) > 3.0
        assert np.nanmin(tr.v[tr.t >= 1200]) < 2.0  # true stops

    def test_wave_moves_upstream_at_realistic_speed(self):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     v0_cv=0.05, T_cv=0.05, seed=1)
        tr = r.run(2400, perturbation=3.0, record_every=0.5)
        w = estimate_wave_speed(tr, after=1200, n_bins=50)
        # Published stop-and-go wave speeds: roughly -10 to -20 km/h.
        assert -22.0 < w < -8.0

    def test_sparse_ring_is_stable(self):
        r = RingRoad(n_vehicles=10, length=1000, params=UNSTABLE,
                     v0_cv=0.05, T_cv=0.05, seed=1)
        tr = r.run(1200, perturbation=3.0)
        assert tr.speed_std(after=600) < 0.5

    def test_pacer_placement_count_and_spacing(self):
        r = RingRoad(n_vehicles=40, length=1000, pacer_fraction=0.1,
                     controller_factory=FollowerStopperController)
        idx = np.flatnonzero(r.is_pacer)
        assert len(idx) == 4
        assert len(r.controllers) == 4
        assert np.all(np.diff(idx) == 10)

    def test_summarize_keys(self):
        r = RingRoad(n_vehicles=10, length=500)
        s = summarize(r.run(60))
        assert set(s) == {
            "mean_speed_mps", "speed_std_mps", "throughput_vph",
            "edie_flow_vph", "edie_density_vpkm",
            "mean_abs_accel", "wave_speed_kmh",
        }

    def test_edie_matches_crossing_count_on_ring(self):
        r = RingRoad(n_vehicles=20, length=1000, v0_cv=0.0, T_cv=0.0)
        tr = r.run(600, perturbation=0.0)
        q, k = tr.edie()
        assert k == pytest.approx(20.0, rel=0.02)
        assert q == pytest.approx(tr.throughput_vph(), rel=0.05)


# ---------------------------------------------------------------- pacers


class TestPacers:
    @pytest.fixture
    def baseline(self):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     v0_cv=0.05, T_cv=0.05, seed=1)
        return summarize(r.run(2400, perturbation=3.0), after=1200)

    def test_single_follower_stopper_dissipates_wave(self, baseline):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     pacer_fraction=1 / 40,
                     controller_factory=lambda: FollowerStopperController(tau=40),
                     v0_cv=0.05, T_cv=0.05, seed=1)
        s = summarize(r.run(2400, perturbation=3.0), after=1200)
        assert s["speed_std_mps"] < 0.1 * baseline["speed_std_mps"]
        assert s["mean_abs_accel"] < 0.1 * baseline["mean_abs_accel"]
        assert s["throughput_vph"] >= baseline["throughput_vph"]

    def test_follower_stopper_never_collides(self):
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     pacer_fraction=0.1,
                     controller_factory=lambda: FollowerStopperController(tau=40),
                     v0_cv=0.05, T_cv=0.05, seed=2)
        r.reset(perturbation=5.0)
        for _ in range(6000):
            r.step()
            gap, _ = r._gaps()
            assert gap.min() > 0

    def test_follower_stopper_command_envelopes(self):
        c = FollowerStopperController()
        c.reset()
        # Tiny gap: command zero regardless of target.
        assert c.command(0.0, 10.0, 1.0, 10.0, 30.0) == 0.0
        # Huge gap: command equals adapted target (initialised to own speed).
        c.reset()
        u = c.command(0.0, 10.0, 500.0, 10.0, 30.0)
        assert u == pytest.approx(10.0, rel=1e-3)

    def test_fast_adaptation_fails_to_dissipate(self, baseline):
        """tau -> 0 makes the pacer a plain follower; the wave survives."""
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     pacer_fraction=1 / 40,
                     controller_factory=lambda: FollowerStopperController(tau=1.0),
                     v0_cv=0.05, T_cv=0.05, seed=1)
        s = summarize(r.run(2400, perturbation=3.0), after=1200)
        assert s["speed_std_mps"] > 0.5 * baseline["speed_std_mps"]

    def test_speed_floor_controller_cannot_dissipate(self, baseline):
        """The PacerProfile-style 20% floor forbids slowing enough to damp."""
        r = RingRoad(n_vehicles=40, length=1000, params=UNSTABLE,
                     pacer_fraction=0.1,
                     controller_factory=lambda: SmoothedVelocityController(tau=40),
                     v0_cv=0.05, T_cv=0.05, seed=1)
        s = summarize(r.run(2400, perturbation=3.0), after=1200)
        assert s["speed_std_mps"] > 0.8 * baseline["speed_std_mps"]


# ---------------------------------------------------------------- open road


class TestOpenRoad:
    def test_vehicles_enter_and_exit(self):
        road = OpenRoad(length=1000, inflow_vph=1200, seed=1)
        tr = road.run(300)
        assert tr.n_vehicles > 20
        assert len(road.exited) > 0

    def test_no_collisions_open_road(self):
        road = OpenRoad(length=1500, inflow_vph=2000, params=UNSTABLE,
                        bottleneck=(900, 1100, 0.5), seed=1)
        for _ in range(4000):
            road.step()
            if road.x.size > 1:
                gaps = road.x[:-1] - road.x[1:] - road.params.length
                assert gaps.min() > 0

    def test_trajectories_padded_with_nan(self):
        road = OpenRoad(length=800, inflow_vph=1000, seed=1)
        tr = road.run(120)
        assert np.isnan(tr.x).any()
        assert tr.x.shape == tr.v.shape
        assert tr.is_pacer.shape == (tr.n_vehicles,)

    def test_pacers_flagged(self):
        road = OpenRoad(length=800, inflow_vph=1500, pacer_fraction=0.5,
                        controller_factory=FollowerStopperController, seed=1)
        tr = road.run(200)
        assert 0 < tr.is_pacer.sum() < tr.n_vehicles

    def test_bottleneck_creates_waves(self):
        road = OpenRoad(length=2000, inflow_vph=2000, params=UNSTABLE,
                        bottleneck=(1200, 1400, 0.4), seed=1)
        tr = road.run(900)
        assert tr.speed_std(after=400) > 3.0
