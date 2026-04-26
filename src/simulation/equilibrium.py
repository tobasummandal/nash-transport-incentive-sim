"""
Equilibrium computation for incentive-mediated congestion games.

Implements iterative best-response dynamics to find user equilibria,
computes the Rosenthal potential for congestion games, and measures
the Wardrop gap (distance from equilibrium).

Theory:
    The corridor congestion game is a weighted potential game
    (Rosenthal 1973). The potential function

        Φ(x) = Σ_e ∫_0^{x_e} c_e(z) dz

    where c_e is the BPR cost on edge e, guarantees that best-response
    dynamics converge to a pure Nash equilibrium. For BPR functions
    c(x) = t0 [1 + α(x/C)^β], the integral is:

        ∫_0^v c(z) dz = t0 [v + α C/(β+1) (v/C)^{β+1}]

    Every improvement step by any agent strictly decreases Φ, so the
    dynamics terminate in finite (though possibly exponential) steps.
    With softmax best responses the dynamics become stochastic but
    converge in expectation under standard conditions (Blume 1993).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from ..agents.base import (
    AgentPreferences,
    BaseAgent,
    TravelMode,
    TripAttributes,
)
from .network import Corridor, SimpleNetwork


@dataclass
class EquilibriumResult:
    """Result of an equilibrium computation."""

    iterations: int
    converged: bool
    final_cv: float
    wardrop_gap: float
    potential_values: list[float]
    mode_share_history: list[dict[str, float]]
    flow_history: list[dict[str, float]]
    gap_history: list[float]


def _mode_shares_from_choices(
    choices: dict[str, str],
) -> dict[str, float]:
    """Compute mode share fractions from agent choices."""
    if not choices:
        return {}
    counts: dict[str, int] = {}
    for mode in choices.values():
        counts[mode] = counts.get(mode, 0) + 1
    total = len(choices)
    return {m: c / total for m, c in counts.items()}


def _compute_travel_times(
    network: SimpleNetwork,
    choices: dict[str, str],
    agents: dict[str, BaseAgent],
    corridor_id: Optional[str] = None,
) -> dict[str, dict[str, float]]:
    """Compute travel times for each agent under each available mode.

    Returns {agent_id: {mode: travel_time_seconds}}.
    """
    volumes: dict[str, float] = {}
    for cid in network.corridors:
        volumes[cid] = 0.0

    target_cid = corridor_id or (
        next(iter(network.corridors)) if network.corridors else None
    )

    for aid, mode in choices.items():
        if mode in ("drive", "drive_alone", "pacer") and target_cid:
            volumes[target_cid] = volumes.get(target_cid, 0) + 1
        elif mode == "carpool" and target_cid:
            volumes[target_cid] = volumes.get(target_cid, 0) + 0.5

    net_copy = copy.deepcopy(network)
    for cid, vol in volumes.items():
        if cid in net_copy.corridors:
            net_copy.corridors[cid].current_volume = vol

    modes = ["drive_alone", "carpool", "transit"]
    result: dict[str, dict[str, float]] = {}

    for aid, agent in agents.items():
        origin = getattr(agent, "home_location", (36.08, -86.65))
        if hasattr(agent, "profile"):
            origin = getattr(agent.profile, "home_location", origin)
        dest = getattr(agent, "work_location", (36.16, -86.78))
        if hasattr(agent, "profile"):
            dest = getattr(agent.profile, "work_location", dest)

        times: dict[str, float] = {}
        for m in modes:
            tt = net_copy.get_travel_time(origin, dest, m, target_cid)
            times[m] = tt
        result[aid] = times

    return result


def compute_wardrop_gap(
    agents: dict[str, BaseAgent],
    choices: dict[str, str],
    travel_times: dict[str, dict[str, float]],
) -> float:
    """Compute the relative Wardrop gap.

    The gap measures total excess cost: for each agent, the difference
    between their current mode's cost and the best available mode's cost,
    summed and normalized by total system cost.

        gap = Σ_i [c_i(chosen) - min_m c_i(m)] / Σ_i c_i(chosen)

    At Wardrop equilibrium the gap is zero.
    """
    total_excess = 0.0
    total_cost = 0.0

    for aid, agent in agents.items():
        if aid not in choices or aid not in travel_times:
            continue
        chosen = choices[aid]
        times = travel_times[aid]
        if chosen not in times:
            continue

        prefs = agent.preferences
        chosen_cost = _agent_cost(prefs, chosen, times[chosen])
        best_cost = min(_agent_cost(prefs, m, t) for m, t in times.items())

        total_excess += max(0.0, chosen_cost - best_cost)
        total_cost += abs(chosen_cost)

    if total_cost < 1e-10:
        return 0.0
    return total_excess / total_cost


def _agent_cost(
    prefs: AgentPreferences, mode: str, travel_time_s: float
) -> float:
    """Generalized cost for an agent: β_time * time + β_cost * monetary."""
    time_min = travel_time_s / 60.0
    monetary = _mode_monetary_cost(mode, travel_time_s)
    return -(prefs.beta_time * time_min + prefs.beta_cost * monetary)


def _mode_monetary_cost(mode: str, travel_time_s: float) -> float:
    """Rough monetary cost by mode ($/trip)."""
    if mode in ("drive", "drive_alone"):
        return 0.21 * (travel_time_s / 3600.0) * 30.0
    elif mode == "carpool":
        return 0.12 * (travel_time_s / 3600.0) * 30.0
    elif mode == "transit":
        return 2.00
    return 0.0


def rosenthal_potential(
    network: SimpleNetwork,
    corridor_volumes: dict[str, float],
) -> float:
    r"""Compute the Rosenthal potential for the current flow pattern.

    For BPR cost functions c(v) = t0 [1 + α(v/C)^β], the potential is:

        Φ = Σ_e t0_e [v_e + α_e C_e / (β_e+1) (v_e/C_e)^{β_e+1}]

    This is the integral ∫_0^{v_e} c_e(z) dz summed over all corridors.
    Every unilateral improvement by an agent strictly decreases Φ,
    proving convergence of best-response dynamics (Rosenthal 1973).
    """
    phi = 0.0
    for cid, corridor in network.corridors.items():
        v = corridor_volumes.get(cid, 0.0)
        t0 = corridor.length_miles / max(corridor.free_flow_speed, 1.0) * 3600.0
        cap = corridor.capacity_vph * corridor.num_lanes
        alpha = corridor.bpr_alpha
        beta = corridor.bpr_beta

        linear_term = t0 * v
        bpr_term = t0 * alpha * cap / (beta + 1.0) * (v / max(cap, 1.0)) ** (beta + 1.0)
        phi += linear_term + bpr_term

    return phi


def best_response_dynamics(
    agents: dict[str, BaseAgent],
    network: SimpleNetwork,
    max_iterations: int = 50,
    convergence_threshold: float = 0.05,
    corridor_id: Optional[str] = None,
    seed: int = 42,
) -> EquilibriumResult:
    """Run iterative best-response dynamics to find user equilibrium.

    Each iteration:
      1. Compute travel times under current flow pattern.
      2. Each agent selects their utility-maximizing mode given
         current congestion (best response).
      3. Update corridor volumes from new mode choices.
      4. Check convergence: CV of mode shares across last 5 iterations.

    Convergence is guaranteed because the congestion game has a
    Rosenthal potential that strictly decreases with each improving
    move. With softmax decision rules the dynamics are stochastic,
    so convergence is assessed statistically.

    Args:
        agents: Agent population.
        network: Road network (corridors will be modified in-place;
                 pass a copy if originals must be preserved).
        max_iterations: Maximum BR iterations.
        convergence_threshold: CV threshold for declaring convergence.
        corridor_id: Target corridor for volume tracking.
        seed: Random seed for reproducibility.

    Returns:
        EquilibriumResult with convergence diagnostics.
    """
    rng = np.random.default_rng(seed)
    target_cid = corridor_id or (
        next(iter(network.corridors)) if network.corridors else None
    )
    modes = ["drive_alone", "carpool", "transit"]

    choices: dict[str, str] = {aid: "drive_alone" for aid in agents}

    mode_share_history: list[dict[str, float]] = []
    flow_history: list[dict[str, float]] = []
    potential_values: list[float] = []
    gap_history: list[float] = []

    for iteration in range(max_iterations):
        travel_times = _compute_travel_times(
            network, choices, agents, target_cid
        )

        new_choices: dict[str, str] = {}
        for aid, agent in agents.items():
            times = travel_times.get(aid, {})
            if not times:
                new_choices[aid] = choices.get(aid, "drive_alone")
                continue

            options = []
            for m in modes:
                tt = times.get(m, 9999.0)
                cost = _mode_monetary_cost(m, tt)
                asc = 0.0
                if m == "carpool":
                    asc = agent.preferences.asc_carpool
                elif m == "transit":
                    asc = agent.preferences.asc_transit

                options.append(TripAttributes(
                    mode=TravelMode.DRIVE_ALONE if m == "drive_alone"
                         else TravelMode.CARPOOL_PASSENGER if m == "carpool"
                         else TravelMode.TRANSIT,
                    travel_time=tt / 60.0,
                    cost=cost,
                    incentive=0.0,
                    comfort_score=1.0 if m == "drive_alone" else 0.8,
                    reliability=0.9,
                ))

            chosen_idx = agent.behavioral_model.choose_action(
                agent.preferences, options, rng
            )
            new_choices[aid] = modes[chosen_idx]

        choices = new_choices
        shares = _mode_shares_from_choices(choices)
        mode_share_history.append(shares)

        volumes: dict[str, float] = {}
        for cid in network.corridors:
            volumes[cid] = 0.0
        for aid, mode in choices.items():
            if mode in ("drive_alone", "pacer") and target_cid:
                volumes[target_cid] = volumes.get(target_cid, 0) + 1
            elif mode == "carpool" and target_cid:
                volumes[target_cid] = volumes.get(target_cid, 0) + 0.5
        flow_history.append(volumes)

        phi = rosenthal_potential(network, volumes)
        potential_values.append(phi)

        gap = compute_wardrop_gap(agents, choices, travel_times)
        gap_history.append(gap)

        if len(mode_share_history) >= 5:
            recent = mode_share_history[-5:]
            all_modes_in_recent = set()
            for s in recent:
                all_modes_in_recent.update(s.keys())

            cvs = []
            for m in all_modes_in_recent:
                vals = [s.get(m, 0.0) for s in recent]
                mean_val = np.mean(vals)
                if mean_val > 0.01:
                    cvs.append(np.std(vals) / mean_val)

            cv = np.mean(cvs) if cvs else 0.0

            if cv < convergence_threshold:
                return EquilibriumResult(
                    iterations=iteration + 1,
                    converged=True,
                    final_cv=cv,
                    wardrop_gap=gap,
                    potential_values=potential_values,
                    mode_share_history=mode_share_history,
                    flow_history=flow_history,
                    gap_history=gap_history,
                )

    final_cv = 0.0
    if len(mode_share_history) >= 2:
        recent = mode_share_history[-5:]
        all_modes_in_recent = set()
        for s in recent:
            all_modes_in_recent.update(s.keys())
        cvs = []
        for m in all_modes_in_recent:
            vals = [s.get(m, 0.0) for s in recent]
            mean_val = np.mean(vals)
            if mean_val > 0.01:
                cvs.append(np.std(vals) / mean_val)
        final_cv = np.mean(cvs) if cvs else 0.0

    return EquilibriumResult(
        iterations=max_iterations,
        converged=False,
        final_cv=final_cv,
        wardrop_gap=gap_history[-1] if gap_history else 1.0,
        potential_values=potential_values,
        mode_share_history=mode_share_history,
        flow_history=flow_history,
        gap_history=gap_history,
    )


def verify_potential_monotonicity(result: EquilibriumResult) -> bool:
    """Check that the potential decreased monotonically.

    In a pure best-response process the Rosenthal potential must
    strictly decrease at each iteration where at least one agent
    switches. With stochastic (softmax) responses, small increases
    are possible; this function checks whether the overall trend
    is non-increasing within tolerance.
    """
    if len(result.potential_values) < 2:
        return True
    diffs = np.diff(result.potential_values)
    n_increases = np.sum(diffs > 0)
    return n_increases <= len(diffs) * 0.2
