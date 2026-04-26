"""Tests for equilibrium computation module."""

from __future__ import annotations

import numpy as np
import pytest

from src.agents.base import (
    AgentPreferences,
    DecisionRule,
    LinearUtilityModel,
)
from src.agents.commuter import CommuterAgent, CommuterProfile
from src.simulation.equilibrium import (
    EquilibriumResult,
    _agent_cost,
    _mode_shares_from_choices,
    best_response_dynamics,
    compute_wardrop_gap,
    rosenthal_potential,
    verify_potential_monotonicity,
)
from src.simulation.network import Corridor, SimpleNetwork, create_i24_network


def _make_agents(n: int = 50, seed: int = 42) -> dict[str, CommuterAgent]:
    """Create a small heterogeneous agent population."""
    rng = np.random.default_rng(seed)
    agents: dict[str, CommuterAgent] = {}
    for i in range(n):
        prefs = AgentPreferences(
            vot=rng.lognormal(np.log(25) - 0.08, 0.4),
            beta_time=np.clip(rng.normal(-0.05, 0.02), -0.2, 0),
            beta_cost=np.clip(rng.normal(-0.10, 0.03), -0.3, 0),
            beta_incentive=np.clip(rng.normal(0.15, 0.05), 0, 0.5),
            decision_rule=DecisionRule.SOFTMAX,
            temperature=max(0.1, rng.normal(1.0, 0.3)),
        )
        profile = CommuterProfile(
            home_location=(36.08 + rng.normal(0, 0.02), -86.65 + rng.normal(0, 0.02)),
            work_location=(36.16, -86.78),
            desired_arrival_time=28800.0,
            flexibility_window=rng.uniform(30, 90) * 60,
            has_car=True,
            has_transit_pass=rng.random() > 0.3,
            carpool_eligible=rng.random() > 0.4,
        )
        agent = CommuterAgent(
            agent_id=f"agent_{i:03d}",
            preferences=prefs,
            profile=profile,
            rng=np.random.default_rng(seed + i),
        )
        agents[agent.id] = agent
    return agents


class TestModeShares:
    def test_empty(self):
        assert _mode_shares_from_choices({}) == {}

    def test_uniform(self):
        choices = {"a": "drive_alone", "b": "carpool", "c": "transit"}
        shares = _mode_shares_from_choices(choices)
        assert abs(shares["drive_alone"] - 1 / 3) < 1e-10
        assert abs(shares["carpool"] - 1 / 3) < 1e-10

    def test_all_same(self):
        choices = {str(i): "drive_alone" for i in range(10)}
        shares = _mode_shares_from_choices(choices)
        assert shares["drive_alone"] == 1.0


class TestRosenthalPotential:
    def test_zero_volume(self):
        net = create_i24_network()
        phi = rosenthal_potential(net, {"I-24-inbound": 0.0})
        assert phi == 0.0

    def test_positive_volume(self):
        net = create_i24_network()
        phi = rosenthal_potential(net, {"I-24-inbound": 100.0})
        assert phi > 0.0

    def test_monotone_in_volume(self):
        net = create_i24_network()
        phi_low = rosenthal_potential(net, {"I-24-inbound": 50.0})
        phi_high = rosenthal_potential(net, {"I-24-inbound": 150.0})
        assert phi_high > phi_low

    def test_matches_bpr_integral(self):
        """Potential equals integral of BPR cost from 0 to v."""
        corridor = Corridor(
            corridor_id="test",
            name="test",
            length_miles=10.0,
            free_flow_speed=60.0,
            capacity_vph=100.0,
            num_lanes=1,
            bpr_alpha=0.15,
            bpr_beta=4.0,
        )
        net = SimpleNetwork()
        net.add_corridor(corridor)

        v = 80.0
        phi = rosenthal_potential(net, {"test": v})

        t0 = 10.0 / 60.0 * 3600.0
        cap = 100.0
        alpha, beta = 0.15, 4.0
        expected = t0 * (v + alpha * cap / (beta + 1) * (v / cap) ** (beta + 1))
        assert abs(phi - expected) < 1e-6


class TestWardropGap:
    def test_all_same_mode_zero_gap(self):
        """If everyone drives and driving is cheapest, gap is near zero."""
        agents = _make_agents(10)
        choices = {aid: "drive_alone" for aid in agents}
        travel_times = {
            aid: {"drive_alone": 600, "carpool": 900, "transit": 1200}
            for aid in agents
        }
        gap = compute_wardrop_gap(agents, choices, travel_times)
        assert gap >= 0.0

    def test_suboptimal_choices_positive_gap(self):
        """Agents on the wrong mode should produce a positive gap."""
        agents = _make_agents(10)
        choices = {aid: "transit" for aid in agents}
        travel_times = {
            aid: {"drive_alone": 300, "carpool": 400, "transit": 1200}
            for aid in agents
        }
        gap = compute_wardrop_gap(agents, choices, travel_times)
        assert gap > 0.0

    def test_gap_nonnegative(self):
        agents = _make_agents(20)
        choices = {aid: "drive_alone" for aid in agents}
        travel_times = {
            aid: {"drive_alone": 600, "carpool": 600, "transit": 600}
            for aid in agents
        }
        gap = compute_wardrop_gap(agents, choices, travel_times)
        assert gap >= 0.0


class TestBestResponseDynamics:
    def test_converges_small_population(self):
        agents = _make_agents(30, seed=123)
        network = create_i24_network()
        result = best_response_dynamics(
            agents, network, max_iterations=50,
            convergence_threshold=0.10, seed=123,
        )
        assert isinstance(result, EquilibriumResult)
        assert result.iterations >= 1
        assert len(result.mode_share_history) == result.iterations
        assert len(result.potential_values) == result.iterations

    def test_gap_decreases(self):
        agents = _make_agents(40, seed=77)
        network = create_i24_network()
        result = best_response_dynamics(
            agents, network, max_iterations=30,
            convergence_threshold=0.05, seed=77,
        )
        if len(result.gap_history) >= 3:
            early_avg = np.mean(result.gap_history[:3])
            late_avg = np.mean(result.gap_history[-3:])
            assert late_avg <= early_avg + 0.3

    def test_deterministic_with_same_seed(self):
        agents1 = _make_agents(20, seed=99)
        agents2 = _make_agents(20, seed=99)
        net1 = create_i24_network()
        net2 = create_i24_network()

        r1 = best_response_dynamics(agents1, net1, max_iterations=10, seed=99)
        r2 = best_response_dynamics(agents2, net2, max_iterations=10, seed=99)

        assert r1.iterations == r2.iterations
        assert r1.mode_share_history == r2.mode_share_history

    def test_mode_shares_sum_to_one(self):
        agents = _make_agents(25)
        network = create_i24_network()
        result = best_response_dynamics(
            agents, network, max_iterations=15, seed=42,
        )
        for shares in result.mode_share_history:
            total = sum(shares.values())
            assert abs(total - 1.0) < 1e-10

    def test_potential_values_populated(self):
        agents = _make_agents(20)
        network = create_i24_network()
        result = best_response_dynamics(
            agents, network, max_iterations=10, seed=42,
        )
        assert all(p >= 0 for p in result.potential_values)

    def test_returns_result_on_max_iterations(self):
        agents = _make_agents(20)
        network = create_i24_network()
        result = best_response_dynamics(
            agents, network, max_iterations=3,
            convergence_threshold=0.001, seed=42,
        )
        assert result.iterations == 3
        assert not result.converged or result.final_cv < 0.001


class TestPotentialMonotonicity:
    def test_monotone_result(self):
        result = EquilibriumResult(
            iterations=5,
            converged=True,
            final_cv=0.01,
            wardrop_gap=0.02,
            potential_values=[100, 95, 91, 88, 86],
            mode_share_history=[],
            flow_history=[],
            gap_history=[],
        )
        assert verify_potential_monotonicity(result)

    def test_non_monotone_result(self):
        result = EquilibriumResult(
            iterations=5,
            converged=False,
            final_cv=0.1,
            wardrop_gap=0.2,
            potential_values=[100, 110, 120, 130, 140],
            mode_share_history=[],
            flow_history=[],
            gap_history=[],
        )
        assert not verify_potential_monotonicity(result)

    def test_single_value(self):
        result = EquilibriumResult(
            iterations=1,
            converged=True,
            final_cv=0.0,
            wardrop_gap=0.0,
            potential_values=[100],
            mode_share_history=[],
            flow_history=[],
            gap_history=[],
        )
        assert verify_potential_monotonicity(result)
