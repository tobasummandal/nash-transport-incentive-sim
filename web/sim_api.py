"""
Simulation API — runs the IHUTE engine, returns trajectory + metrics JSON.

POST /api/simulate   — single run
POST /api/compare    — baseline vs incentivized (same agents/departures)
GET  /api/health
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.commuter import create_commuter_population
from src.incentives.base import IncentiveConfig, IncentiveType
from src.incentives.carpool import CarpoolIncentive
from src.incentives.pacer import PacerIncentive
from src.incentives.temporal import DepartureShiftIncentive
from src.optimization import AlwaysAllocator, GreedyAllocator, SecretaryAllocator
from src.simulation import SimulationConfig, SimulationEngine, create_i24_network

app = FastAPI(title="I-24 Corridor Simulation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SNAPSHOT_INTERVAL = 15
HOME_REGION = ((36.05, -86.70), (36.10, -86.60))
WORK_REGION = ((36.14, -86.80), (36.18, -86.76))
CORRIDOR = "I-24-inbound"


class SimRequest(BaseModel):
    n_agents: int = Field(200, ge=10, le=5000)
    duration_hours: float = Field(3.0, ge=0.5, le=8.0)
    seed: int = 42
    carpool_enabled: bool = True
    carpool_budget: float = 5000.0
    carpool_reward_per_passenger: float = 2.50
    pacer_enabled: bool = True
    pacer_budget: float = 3000.0
    pacer_reward_per_mile: float = 0.15
    departure_shift_enabled: bool = False
    departure_shift_budget: float = 2000.0
    allocator: str = "always"


class RunResult(BaseModel):
    label: str
    metrics: dict[str, Any]
    time_series: list[dict[str, Any]]
    incentive_summary: dict[str, Any]
    corridor_state: dict[str, Any]
    trajectories: list[dict[str, Any]]
    wall_time_seconds: float


class CompareResponse(BaseModel):
    baseline: RunResult
    incentivized: RunResult


def _build_allocator(name: str, n: int):
    if name == "greedy":
        return GreedyAllocator(min_efficiency=0.5)
    if name == "secretary":
        return SecretaryAllocator(n_total=n)
    return AlwaysAllocator()


def _build_incentives(req: SimRequest) -> list:
    incentives: list = []
    if req.carpool_enabled:
        incentives.append(
            CarpoolIncentive(
                config=IncentiveConfig(
                    incentive_type=IncentiveType.CARPOOL,
                    budget_daily=req.carpool_budget,
                    corridor_ids=[CORRIDOR],
                ),
                reward_per_passenger=req.carpool_reward_per_passenger,
            )
        )
    if req.pacer_enabled:
        incentives.append(
            PacerIncentive(
                config=IncentiveConfig(
                    incentive_type=IncentiveType.PACER,
                    budget_daily=req.pacer_budget,
                    corridor_ids=[CORRIDOR],
                ),
                reward_per_mile=req.pacer_reward_per_mile,
            )
        )
    if req.departure_shift_enabled:
        ds = DepartureShiftIncentive(
            config=IncentiveConfig(
                incentive_type=IncentiveType.DEPARTURE_SHIFT,
                budget_daily=req.departure_shift_budget,
            ),
        )
        ds.setup_default_slots()
        incentives.append(ds)
    return incentives


def _apply_departure_shift(
    departures: list[dict],
    agents: list,
    budget: float,
    rng: np.random.Generator,
) -> tuple[list[dict], dict]:
    """Shift peak-period departures to shoulder periods.

    Agents departing during 7-9 AM peak are offered an incentive to
    depart earlier (6-7 AM) or later (9-10 AM). Acceptance depends on
    agent incentive sensitivity. Returns modified departures and a
    summary dict.
    """
    peak_start, peak_end = 7 * 3600, 9 * 3600
    base_reward = 3.0
    reward_per_min = 0.10

    agent_map = {a.id: a for a in agents}
    shifted = []
    total_spent = 0.0
    n_offered = 0
    n_accepted = 0
    n_completed = 0

    for dep in departures:
        t = dep["time"]
        if not (peak_start <= t < peak_end) or total_spent >= budget:
            shifted.append(dep)
            continue

        n_offered += 1

        dist_early = t - peak_start
        dist_late = peak_end - t
        if dist_early <= dist_late:
            new_t = peak_start - min(dist_early, 1800)
        else:
            new_t = peak_end + min(dist_late, 1800)

        shift_min = abs(new_t - t) / 60
        if shift_min < 15:
            shifted.append(dep)
            continue

        reward = base_reward + reward_per_min * min(shift_min, 60) + 3.0

        if total_spent + reward > budget:
            shifted.append(dep)
            continue

        agent = agent_map.get(dep["agent_id"])
        accept_prob = 0.5
        if agent and hasattr(agent, "preferences"):
            beta = abs(getattr(agent.preferences, "beta_incentive", 0.15))
            accept_prob = min(0.95, 0.3 + beta * reward)

        if rng.random() < accept_prob:
            n_accepted += 1
            n_completed += 1
            total_spent += reward
            new_dep = dict(dep)
            new_dep["time"] = new_t
            shifted.append(new_dep)
        else:
            shifted.append(dep)

    summary = {
        "offers": n_offered,
        "accepted": n_accepted,
        "completed": n_completed,
        "total_spent": round(total_spent, 2),
        "budget": budget,
    }
    return shifted, summary


def _run_one(
    req: SimRequest,
    label: str,
    incentives: list | None,
    agents,
    departures: list[dict],
) -> RunResult:
    """Execute a single simulation run and extract results."""
    t0 = time.time()
    rng = np.random.default_rng(req.seed)
    network = create_i24_network()

    # Apply departure shift pre-processing (modifies schedule before sim)
    ds_summary: dict | None = None
    run_departures = [dict(d) for d in departures]
    if req.departure_shift_enabled and incentives:
        run_departures, ds_summary = _apply_departure_shift(
            run_departures, agents, req.departure_shift_budget, rng
        )
        # Remove DepartureShiftIncentive from engine incentives since
        # we handle it pre-sim; avoids double-counting.
        incentives = [
            i for i in incentives
            if i.incentive_type.name != "DEPARTURE_SHIFT"
        ]

    allocator = (
        _build_allocator(req.allocator, req.n_agents) if incentives else AlwaysAllocator()
    )

    sim_start = 6 * 3600
    sim_end = sim_start + req.duration_hours * 3600

    cfg = SimulationConfig(
        duration_seconds=sim_end,
        warmup_seconds=0,
        metrics_interval=300,
        n_agents=req.n_agents,
        random_seed=req.seed,
    )

    engine = SimulationEngine(
        cfg, network, rng, incentives=incentives or [], allocator=allocator
    )
    engine.add_agents(agents)

    for dep in run_departures:
        engine.schedule_departure(**dep)

    result = engine.run()

    # ---- Analyze trips ----
    trips = engine.metrics.trips
    # Carpool passengers have mode="carpool_passenger" — they are NOT
    # separate vehicles on the road.
    vehicle_trips = [t for t in trips if t.mode != "carpool_passenger"]
    passenger_trips = [t for t in trips if t.mode == "carpool_passenger"]

    # ---- Build trajectory snapshots (vehicles only, not passengers) ----
    snap_times = np.arange(sim_start, sim_end, SNAPSHOT_INTERVAL)

    trajectory_frames: list[dict[str, Any]] = []
    for st in snap_times:
        agents_at_t = []
        for tr in vehicle_trips:
            if tr.departure_time <= st < tr.arrival_time:
                progress = (st - tr.departure_time) / max(
                    1.0, tr.arrival_time - tr.departure_time
                )
                got_incentive = tr.incentive_received > 0
                agents_at_t.append(
                    {
                        "p": round(float(progress), 3),
                        "m": str(tr.mode),
                        "inc": bool(got_incentive),
                    }
                )
        trajectory_frames.append(
            {
                "t": round(float(st - sim_start)),
                "n": len(agents_at_t),
                "agents": agents_at_t,
            }
        )

    # Trim empty leading/trailing frames
    first_nonempty = next(
        (i for i, f in enumerate(trajectory_frames) if f["n"] > 0), 0
    )
    last_nonempty = next(
        (
            i
            for i in range(len(trajectory_frames) - 1, -1, -1)
            if trajectory_frames[i]["n"] > 0
        ),
        len(trajectory_frames) - 1,
    )
    trajectory_frames = trajectory_frames[first_nonempty : last_nonempty + 1]

    # ---- Incentive summary ----
    inc_summary: dict[str, Any] = {}
    for inc in incentives or []:
        name = inc.incentive_type.name.lower()
        inc_summary[name] = {
            "offers": inc.n_offers,
            "accepted": inc.n_accepted,
            "completed": inc.n_completed,
            "total_spent": round(float(inc.total_spent), 2),
            "budget": float(inc.config.budget_daily),
        }
    if ds_summary:
        inc_summary["departure_shift"] = ds_summary

    # ---- Corridor state ----
    corridor = network.corridors.get(CORRIDOR)
    corridor_state = {}
    if corridor:
        inst_cap = corridor._instantaneous_capacity()
        corridor_state = {
            "peak_volume": float(corridor.peak_volume),
            "instantaneous_capacity": round(float(inst_cap), 1),
            "peak_congestion_factor": round(
                float(corridor.peak_congestion_factor), 2
            ),
        }

    # ---- Compute metrics that actually differ between baseline/incentivized ----
    n_vehicles = len(vehicle_trips)
    n_passengers = len(passenger_trips)
    vehicle_vmt = sum(t.distance_miles for t in vehicle_trips)
    total_vmt = sum(t.distance_miles for t in trips)
    vehicle_travel_times = [t.travel_time for t in vehicle_trips]
    avg_travel_time = (
        float(np.mean(vehicle_travel_times)) if vehicle_travel_times else 0.0
    )

    # Peak simultaneous vehicles from trajectory frames
    peak_vehicles = max((f["n"] for f in trajectory_frames), default=0)

    # Compute total incentive cost (engine incentives + pre-sim departure shift)
    total_incentive_cost = sum(
        inc.total_spent for inc in (incentives or [])
    )
    if ds_summary:
        total_incentive_cost += ds_summary["total_spent"]

    metrics = {
        "total_trips": len(trips),
        "vehicles": n_vehicles,
        "passengers_removed": n_passengers,
        "carpool_rate": round(n_passengers / max(1, len(trips)) * 100, 1),
        "vehicle_vmt": round(float(vehicle_vmt), 1),
        "total_vmt": round(float(total_vmt), 1),
        "avg_travel_time": round(avg_travel_time, 1),
        "peak_vehicles": peak_vehicles,
        "total_incentive_cost": round(float(total_incentive_cost), 2),
    }

    # Fold in engine metrics that don't overlap
    for k, v in result.metrics.items():
        if k not in metrics:
            if isinstance(v, (int, float, np.integer, np.floating)):
                metrics[k] = round(float(v), 2)

    return RunResult(
        label=label,
        metrics=metrics,
        time_series=result.time_series,
        incentive_summary=inc_summary,
        corridor_state=corridor_state,
        trajectories=trajectory_frames,
        wall_time_seconds=round(time.time() - t0, 3),
    )


def _prepare_agents_and_departures(req: SimRequest):
    """Create agents and departure schedule (shared across comparison runs)."""
    rng = np.random.default_rng(req.seed)
    agents = create_commuter_population(
        n_agents=req.n_agents,
        home_region=HOME_REGION,
        work_region=WORK_REGION,
        rng=rng,
    )
    for a in agents:
        a.profile.has_car = True
        a.profile.carpool_eligible = True

    sim_start = 6 * 3600
    sim_end = sim_start + req.duration_hours * 3600

    departures = []
    for agent in agents:
        dep_time = sim_start + rng.exponential(req.duration_hours * 3600 / 4)
        dep_time = min(dep_time, sim_end - 900)
        departures.append(
            {
                "agent_id": agent.id,
                "time": dep_time,
                "origin": agent.profile.home_location,
                "destination": agent.profile.work_location,
                "mode": "drive",
                "corridor_id": CORRIDOR,
            }
        )
    return agents, departures


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/simulate", response_model=RunResult)
def simulate(req: SimRequest):
    agents, departures = _prepare_agents_and_departures(req)
    incentives = _build_incentives(req)
    return _run_one(req, "simulation", incentives, agents, departures)


@app.post("/api/compare", response_model=CompareResponse)
def compare(req: SimRequest):
    """Run baseline (no incentives) and incentivized with same agents/schedule."""
    agents_base, departures = _prepare_agents_and_departures(req)
    baseline = _run_one(req, "No incentives", None, agents_base, departures)

    # Re-create agents (engine mutates agent state)
    agents_inc, _ = _prepare_agents_and_departures(req)
    incentives = _build_incentives(req)
    incentivized = _run_one(req, "With incentives", incentives, agents_inc, departures)

    return CompareResponse(baseline=baseline, incentivized=incentivized)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
