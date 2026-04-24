"""
Budget-constrained incentive allocation.

Two strategies:
    GreedyAllocator     — offline, ranks offers by score/cost and accepts
                          greedily under budget.
    SecretaryAllocator  — online, single-pass, uses sample-and-threshold
                          (classical secretary problem ~1/e competitive ratio)
                          to commit without lookahead.

Both implement the Allocator Protocol. The engine calls `should_offer` at
the moment an agent becomes eligible; the allocator answers yes/no given
remaining budget and whatever state it has accumulated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class OfferRequest:
    """A candidate incentive offer awaiting allocation decision."""

    agent_id: str
    incentive_type: str
    expected_reward: float
    score: float  # higher = more valuable (mode-shift potential, congestion impact)
    context: dict[str, Any] = field(default_factory=dict)


class Allocator(Protocol):
    """Strategy interface for incentive allocation under a budget."""

    def should_offer(self, request: OfferRequest, remaining_budget: float) -> bool:
        """Decide whether to offer this incentive right now."""
        ...

    def observe_completion(self, request: OfferRequest, actual_cost: float) -> None:
        """Called after an offer completes so the allocator can update state."""
        ...


class GreedyAllocator:
    """
    Offline-style greedy allocation.

    Accepts every request whose score/cost ratio clears `min_efficiency`
    and whose expected reward fits the remaining budget. Approximates the
    knapsack LP relaxation — the classic (1-1/e) approximation bound when
    requests arrive in arbitrary order.
    """

    def __init__(self, min_efficiency: float = 0.5):
        self.min_efficiency = min_efficiency
        self.n_accepted = 0
        self.n_rejected = 0

    def should_offer(self, request: OfferRequest, remaining_budget: float) -> bool:
        if request.expected_reward <= 0:
            return False
        if request.expected_reward > remaining_budget:
            self.n_rejected += 1
            return False

        efficiency = request.score / max(request.expected_reward, 0.01)
        if efficiency < self.min_efficiency:
            self.n_rejected += 1
            return False

        self.n_accepted += 1
        return True

    def observe_completion(self, request: OfferRequest, actual_cost: float) -> None:
        pass


class SecretaryAllocator:
    """
    Online secretary-style allocation.

    Single-pass, no demand forecasts. Samples the first `n_total / e`
    requests to learn a score threshold, then accepts any subsequent
    request that beats the threshold and fits the budget. Competitive
    ratio approaches 1/e as n_total grows.
    """

    def __init__(self, n_total: int):
        self.n_total = max(1, n_total)
        self.sample_size = max(1, int(n_total / math.e))
        self.observed: list[float] = []
        self.threshold: Optional[float] = None
        self.n_seen = 0
        self.n_accepted = 0

    def should_offer(self, request: OfferRequest, remaining_budget: float) -> bool:
        self.n_seen += 1

        if request.expected_reward > remaining_budget:
            return False

        # Sampling phase: observe scores, never commit
        if self.n_seen <= self.sample_size:
            self.observed.append(request.score)
            return False

        # Lock threshold at end of sampling
        if self.threshold is None and self.observed:
            self.threshold = max(self.observed)

        if self.threshold is None or request.score >= self.threshold:
            self.n_accepted += 1
            return True

        return False

    def observe_completion(self, request: OfferRequest, actual_cost: float) -> None:
        pass


class AlwaysAllocator:
    """Null allocator — accepts everything that fits the budget. For testing."""

    def should_offer(self, request: OfferRequest, remaining_budget: float) -> bool:
        return 0 < request.expected_reward <= remaining_budget

    def observe_completion(self, request: OfferRequest, actual_cost: float) -> None:
        pass
