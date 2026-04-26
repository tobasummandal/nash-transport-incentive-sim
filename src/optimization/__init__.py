"""Budget-constrained incentive allocation strategies and complexity analysis."""

from .allocator import (
    Allocator,
    AlwaysAllocator,
    GreedyAllocator,
    OfferRequest,
    SecretaryAllocator,
)
from .complexity import (
    ComplexityResult,
    KnapsackInstance,
    compute_approximation_bounds,
    congestion_welfare,
    identify_tractable_cases,
    reduce_knapsack_to_allocation,
    run_complexity_analysis,
    solve_knapsack_dp,
    verify_submodularity,
)

__all__ = [
    "Allocator",
    "OfferRequest",
    "GreedyAllocator",
    "SecretaryAllocator",
    "AlwaysAllocator",
    "ComplexityResult",
    "KnapsackInstance",
    "compute_approximation_bounds",
    "congestion_welfare",
    "identify_tractable_cases",
    "reduce_knapsack_to_allocation",
    "run_complexity_analysis",
    "solve_knapsack_dp",
    "verify_submodularity",
]
