"""
Computational complexity analysis for incentive allocation problems.

Establishes NP-hardness of the general problem via reduction from
Knapsack, verifies submodularity of the welfare function empirically,
identifies tractable special cases, and computes approximation bounds.

Key results:
    1. General incentive allocation is NP-hard (Theorem 1).
    2. When welfare is monotone submodular, greedy gives (1-1/e)
       approximation (Nemhauser et al. 1978).
    3. Uniform-cost special case is polynomial (reduces to sorting).
    4. Online allocation: 1/e competitive ratio is tight for the
       secretary variant (Babaioff et al. 2007).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .allocator import AlwaysAllocator, GreedyAllocator, OfferRequest


@dataclass
class ComplexityResult:
    """Result of a complexity analysis run."""

    problem_class: str
    is_np_hard: bool
    approximation_ratio: float
    tight_bound: bool
    tractable_cases: list[str]
    submodularity_verified: bool
    marginal_gains: list[float]
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class KnapsackInstance:
    """An instance of the 0-1 Knapsack problem."""

    values: list[float]
    weights: list[float]
    capacity: float


def reduce_knapsack_to_allocation(
    instance: KnapsackInstance,
) -> tuple[list[OfferRequest], float]:
    """Reduce a Knapsack instance to an incentive allocation instance.

    This polynomial-time reduction proves that incentive allocation
    is at least as hard as Knapsack (which is NP-hard). Each knapsack
    item maps to an agent offer:

        item i  -->  OfferRequest(
                         agent_id = str(i),
                         expected_reward = weight_i,  (budget cost)
                         score = value_i,             (welfare gain)
                     )
        capacity --> budget B

    An optimal allocation maximizing total score subject to budget B
    gives an optimal knapsack solution. Since Knapsack is NP-hard
    (Karp 1972), so is incentive allocation. QED.

    Returns:
        (list of OfferRequests, budget)
    """
    requests = []
    for i, (v, w) in enumerate(zip(instance.values, instance.weights)):
        requests.append(OfferRequest(
            agent_id=str(i),
            incentive_type="generic",
            expected_reward=w,
            score=v,
        ))
    return requests, instance.capacity


def solve_knapsack_dp(instance: KnapsackInstance) -> tuple[float, list[int]]:
    """Solve 0-1 Knapsack exactly via dynamic programming.

    Time: O(n * W) where W = capacity discretized to integer cents.
    This is pseudo-polynomial, confirming NP-hardness is in the weak
    sense (the problem admits an FPTAS).
    """
    n = len(instance.values)
    scale = 100
    W = int(instance.capacity * scale)
    weights = [int(w * scale) for w in instance.weights]

    dp = [0.0] * (W + 1)
    choice = [[False] * n for _ in range(W + 1)]

    for i in range(n):
        for w in range(W, weights[i] - 1, -1):
            if dp[w - weights[i]] + instance.values[i] > dp[w]:
                dp[w] = dp[w - weights[i]] + instance.values[i]
                choice[w][i] = True

    selected: list[int] = []
    w = W
    for i in range(n - 1, -1, -1):
        if choice[w][i]:
            selected.append(i)
            w -= weights[i]

    return dp[W], sorted(selected)


def verify_submodularity(
    welfare_fn: Callable[[set[int]], float],
    n_items: int,
    n_samples: int = 200,
    seed: int = 42,
) -> tuple[bool, list[float]]:
    """Empirically verify that a welfare function is submodular.

    Submodularity requires diminishing marginal returns:
        f(A ∪ {j}) - f(A) >= f(B ∪ {j}) - f(B)  for all A ⊆ B, j ∉ B

    We sample random set pairs (A ⊆ B) and elements j, checking
    the inequality. Returns (is_submodular, list_of_marginal_gains).
    """
    rng = np.random.default_rng(seed)
    marginal_gains: list[float] = []
    violations = 0

    items = list(range(n_items))

    for _ in range(n_samples):
        b_size = rng.integers(1, max(2, n_items))
        b_items = set(rng.choice(items, size=b_size, replace=False).tolist())

        remaining = [x for x in items if x not in b_items]
        if not remaining:
            continue

        a_size = rng.integers(0, len(b_items))
        a_items = set(list(b_items)[:a_size])

        j = rng.choice(remaining)

        mg_a = welfare_fn(a_items | {j}) - welfare_fn(a_items)
        mg_b = welfare_fn(b_items | {j}) - welfare_fn(b_items)
        marginal_gains.append(mg_a)

        if mg_a < mg_b - 1e-10:
            violations += 1

    is_submodular = violations == 0
    return is_submodular, marginal_gains


def congestion_welfare(
    selected: set[int],
    n_total: int,
    corridor_capacity: float = 6000.0,
    bpr_alpha: float = 0.83,
    bpr_beta: float = 5.5,
    base_volume: float = 5000.0,
    free_flow_time: float = 600.0,
) -> float:
    """Welfare function for the congestion game.

    Models the total travel time saved when a subset of agents
    switch from driving alone to carpooling (removing vehicles).
    Each selected agent removes one vehicle from the corridor.

    Welfare = TotalTime(no incentive) - TotalTime(with selected removed)
    """
    n_selected = len(selected)
    v_base = base_volume
    v_reduced = max(0, base_volume - n_selected)

    def total_time(v: float) -> float:
        vc = v / max(1.0, corridor_capacity)
        cf = 1.0 + bpr_alpha * (vc ** bpr_beta)
        return v * free_flow_time * cf

    return total_time(v_base) - total_time(v_reduced)


def compute_approximation_bounds(
    n_agents: int,
    budget: float,
    avg_cost: float,
) -> dict[str, float]:
    """Compute approximation bounds for different allocators.

    Returns theoretical guarantees and effective bounds given
    the problem parameters.

    Args:
        n_agents: Number of candidate agents.
        budget: Total budget.
        avg_cost: Average per-agent incentive cost.
    """
    k = int(budget / max(avg_cost, 0.01))

    greedy_ratio = 1.0 - 1.0 / math.e
    secretary_ratio = 1.0 / math.e

    greedy_effective = greedy_ratio
    if k >= n_agents:
        greedy_effective = 1.0

    secretary_effective = secretary_ratio
    if n_agents < 10:
        secretary_effective = max(0.0, secretary_ratio * (1.0 - 3.0 / n_agents))

    fptas_ratio = lambda eps: 1.0 - eps
    fptas_time = lambda eps: n_agents**2 / max(eps, 1e-6)

    return {
        "greedy_guarantee": greedy_ratio,
        "greedy_effective": greedy_effective,
        "secretary_guarantee": secretary_ratio,
        "secretary_effective": secretary_effective,
        "fptas_0.01": fptas_ratio(0.01),
        "fptas_0.01_time": fptas_time(0.01),
        "max_items_in_budget": k,
        "budget_binding": k < n_agents,
    }


def identify_tractable_cases() -> list[dict[str, str]]:
    """Identify polynomial-time solvable special cases.

    Returns a list of tractable problem variants with their
    complexity class and solving algorithm.
    """
    return [
        {
            "case": "Uniform costs",
            "complexity": "O(n log n)",
            "algorithm": "Sort by score, select top-k",
            "condition": "All agents have equal expected_reward",
            "guarantee": "Optimal",
        },
        {
            "case": "Fractional relaxation",
            "complexity": "O(n log n)",
            "algorithm": "Sort by score/cost ratio, fill greedily",
            "condition": "Agents can be partially allocated",
            "guarantee": "Optimal (LP relaxation upper bound)",
        },
        {
            "case": "Matroid constraint",
            "complexity": "O(n log n)",
            "algorithm": "Greedy on matroid",
            "condition": "Feasible sets form a matroid",
            "guarantee": "Optimal (Rado-Edmonds)",
        },
        {
            "case": "Fixed number of types",
            "complexity": "O(n * k^2)",
            "algorithm": "DP over type counts",
            "condition": "k incentive types, k = O(1)",
            "guarantee": "Optimal",
        },
        {
            "case": "Online with i.i.d. arrivals",
            "complexity": "O(n)",
            "algorithm": "Threshold policy",
            "condition": "Agent scores drawn i.i.d.",
            "guarantee": "1 - 1/e (prophet inequality)",
        },
    ]


def run_complexity_analysis(
    n_agents: int = 100,
    budget: float = 1000.0,
    avg_cost: float = 10.0,
    seed: int = 42,
) -> ComplexityResult:
    """Run the full complexity analysis pipeline.

    1. Constructs a Knapsack instance and reduces it.
    2. Solves exactly via DP and approximately via greedy.
    3. Verifies submodularity of congestion welfare.
    4. Computes approximation bounds.
    5. Identifies tractable special cases.
    """
    rng = np.random.default_rng(seed)

    values = rng.uniform(1, 20, n_agents).tolist()
    weights = rng.uniform(5, 25, n_agents).tolist()
    knapsack = KnapsackInstance(values=values, weights=weights, capacity=budget)

    requests, alloc_budget = reduce_knapsack_to_allocation(knapsack)

    opt_value, opt_items = solve_knapsack_dp(knapsack)

    greedy = GreedyAllocator(min_efficiency=0.0)
    sorted_requests = sorted(requests, key=lambda r: r.score / max(r.expected_reward, 0.01), reverse=True)
    greedy_value = 0.0
    greedy_budget = alloc_budget
    for req in sorted_requests:
        if greedy.should_offer(req, greedy_budget):
            greedy_value += req.score
            greedy_budget -= req.expected_reward

    empirical_ratio = greedy_value / max(opt_value, 1e-10)

    def welfare_fn(s: set[int]) -> float:
        return congestion_welfare(s, n_agents)

    is_submodular, marginals = verify_submodularity(
        welfare_fn, min(n_agents, 50), n_samples=200, seed=seed
    )

    bounds = compute_approximation_bounds(n_agents, budget, avg_cost)
    tractable = identify_tractable_cases()

    return ComplexityResult(
        problem_class="NP-hard (weak sense, reduction from 0-1 Knapsack)",
        is_np_hard=True,
        approximation_ratio=empirical_ratio,
        tight_bound=abs(empirical_ratio - (1 - 1 / math.e)) < 0.15,
        tractable_cases=[c["case"] for c in tractable],
        submodularity_verified=is_submodular,
        marginal_gains=marginals,
        details={
            "optimal_dp_value": opt_value,
            "greedy_value": greedy_value,
            "theoretical_greedy_bound": 1 - 1 / math.e,
            "bounds": bounds,
            "tractable_details": tractable,
            "knapsack_n_items": n_agents,
            "knapsack_capacity": budget,
        },
    )
