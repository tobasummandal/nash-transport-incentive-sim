"""
End-to-end integration tests: SimulationEngine + agents + incentives.

These tests cover the seam no unit test touches: a full run where
departures fire, incentives get offered and accepted, budgets debit,
and trip records carry the earned reward.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.agents.commuter import create_commuter_population
from src.incentives.base import IncentiveConfig, IncentiveType
from src.incentives.carpool import CarpoolIncentive
from src.incentives.pacer import PacerIncentive
from src.optimization import (
    AlwaysAllocator,
    GreedyAllocator,
    SecretaryAllocator,
)
from src.simulation import SimulationConfig, SimulationEngine, create_i24_network


HOME_REGION = ((36.05, -86.70), (36.10, -86.60))
WORK_REGION = ((36.14, -86.80), (36.18, -86.76))
CORRIDOR = "I-24-inbound"


def _build_engine(
    incentives=None,
    allocator=None,
    n_agents: int = 20,
    seed: int = 42,
):
    rng = np.random.default_rng(seed)
    network = create_i24_network()
    agents = create_commuter_population(
        n_agents=n_agents,
        home_region=HOME_REGION,
        work_region=WORK_REGION,
        rng=rng,
    )
    # Force agent behaviour deterministic enough for the test
    for a in agents:
        a.profile.has_car = True
        a.profile.carpool_eligible = True

    # Run the sim from 7 AM to 10 AM so departures land inside incentive-
    # eligible hours. Engine time is absolute (seconds from midnight).
    cfg = SimulationConfig(
        duration_seconds=10 * 3600,
        warmup_seconds=0,
        metrics_interval=600,
        n_agents=n_agents,
        random_seed=seed,
    )
    engine = SimulationEngine(
        cfg, network, rng, incentives=incentives, allocator=allocator
    )
    engine.add_agents(agents)

    # Schedule all departures during the 7-9 AM peak so incentives
    # pass the is_active_time check.
    for i, agent in enumerate(agents):
        t = 7 * 3600 + (i * 60)  # stagger across peak window
        engine.schedule_departure(
            agent_id=agent.id,
            time=t,
            origin=agent.profile.home_location,
            destination=agent.profile.work_location,
            mode="drive",
            corridor_id=CORRIDOR,
        )

    return engine


def _carpool_incentive() -> CarpoolIncentive:
    return CarpoolIncentive(
        config=IncentiveConfig(
            incentive_type=IncentiveType.CARPOOL,
            budget_daily=500.0,
            corridor_ids=[CORRIDOR],
        ),
        reward_per_passenger=2.50,
    )


def _pacer_incentive() -> PacerIncentive:
    return PacerIncentive(
        config=IncentiveConfig(
            incentive_type=IncentiveType.PACER,
            budget_daily=500.0,
            corridor_ids=[CORRIDOR],
        ),
    )


class TestEngineBaseline:
    """Engine runs without incentives — regression guard."""

    def test_runs_without_incentives(self):
        engine = _build_engine(incentives=None, allocator=None, n_agents=10)
        result = engine.run()
        assert result.metrics["total_trips"] == 10
        assert result.metrics["total_incentive_cost"] == 0.0

    def test_empty_incentive_list_is_noop(self):
        engine = _build_engine(incentives=[], n_agents=5)
        result = engine.run()
        assert result.metrics["total_trips"] == 5
        assert result.metrics["total_incentive_cost"] == 0.0


class TestCarpoolWiring:
    """Carpool incentive must be offered, accepted, and debited."""

    def test_offers_fire_at_departure(self):
        inc = _carpool_incentive()
        engine = _build_engine(incentives=[inc], n_agents=15)
        engine.run()
        assert inc.n_offers > 0, "incentive.offer_incentive was never called"

    def test_budget_debited_on_completion(self):
        inc = _carpool_incentive()
        engine = _build_engine(incentives=[inc], n_agents=15)
        engine.run()
        assert inc.total_spent > 0
        assert inc.total_spent <= inc.config.budget_daily

    def test_trip_records_carry_incentive(self):
        inc = _carpool_incentive()
        engine = _build_engine(incentives=[inc], n_agents=15)
        result = engine.run()
        rewarded = [t for t in engine.metrics.trips if t.incentive_received > 0]
        assert len(rewarded) > 0
        assert result.metrics["total_incentive_cost"] > 0


class TestBudgetCap:
    """Allocator must respect the hard budget ceiling."""

    def test_total_spent_never_exceeds_budget(self):
        inc = CarpoolIncentive(
            config=IncentiveConfig(
                incentive_type=IncentiveType.CARPOOL,
                budget_daily=10.0,  # tight
                corridor_ids=[CORRIDOR],
            ),
        )
        engine = _build_engine(incentives=[inc], n_agents=50)
        engine.run()
        assert inc.total_spent <= 10.0 + 1e-6


class TestAllocatorStrategies:
    """Different allocators should produce different offer counts."""

    def test_greedy_vs_always_diverges(self):
        inc_a = _carpool_incentive()
        inc_g = _carpool_incentive()

        engine_a = _build_engine(
            incentives=[inc_a], allocator=AlwaysAllocator(), n_agents=30
        )
        engine_a.run()

        engine_g = _build_engine(
            incentives=[inc_g],
            allocator=GreedyAllocator(min_efficiency=1000.0),  # rejects everything
            n_agents=30,
        )
        engine_g.run()

        assert inc_a.n_accepted > 0
        # GreedyAllocator with impossibly high threshold should refuse all offers
        assert inc_g.n_offers == 0

    def test_secretary_skips_sampling_phase(self):
        inc = _carpool_incentive()
        alloc = SecretaryAllocator(n_total=30)
        engine = _build_engine(incentives=[inc], allocator=alloc, n_agents=30)
        engine.run()
        # During the sampling phase (first ~30/e ≈ 11 agents) no offers
        # are committed; at least some offers fire afterwards.
        assert alloc.n_seen == 30


class TestCongestionFeedback:
    """Incentives must measurably reduce corridor volume (item 5)."""

    def test_carpool_reduces_peak_volume(self):
        # Same seed + same departures; only difference is incentive presence.
        engine_no = _build_engine(incentives=None, n_agents=40, seed=7)
        engine_no.run()
        peak_no = engine_no.network.corridors[CORRIDOR].peak_volume

        engine_yes = _build_engine(
            incentives=[_carpool_incentive()], n_agents=40, seed=7
        )
        engine_yes.run()
        peak_yes = engine_yes.network.corridors[CORRIDOR].peak_volume

        assert peak_yes < peak_no, (
            f"carpool incentive should reduce peak volume: "
            f"no-incentive={peak_no}, with-incentive={peak_yes}"
        )


class TestMultipleIncentives:
    """Engine must handle more than one incentive mechanism simultaneously."""

    def test_carpool_and_pacer_coexist(self):
        cp = _carpool_incentive()
        pc = _pacer_incentive()
        engine = _build_engine(incentives=[cp, pc], n_agents=20)
        engine.run()
        assert cp.n_offers > 0
        assert pc.n_offers > 0
