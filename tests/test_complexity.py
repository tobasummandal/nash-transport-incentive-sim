"""Tests for computational complexity analysis module."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.optimization.allocator import GreedyAllocator, OfferRequest
from src.optimization.complexity import (
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


class TestKnapsackReduction:
    def test_reduction_preserves_sizes(self):
        instance = KnapsackInstance(
            values=[10, 20, 30],
            weights=[5, 10, 15],
            capacity=20,
        )
        requests, budget = reduce_knapsack_to_allocation(instance)
        assert len(requests) == 3
        assert budget == 20

    def test_reduction_maps_values(self):
        instance = KnapsackInstance(
            values=[10, 20],
            weights=[5, 15],
            capacity=20,
        )
        requests, _ = reduce_knapsack_to_allocation(instance)
        assert requests[0].score == 10
        assert requests[0].expected_reward == 5
        assert requests[1].score == 20
        assert requests[1].expected_reward == 15

    def test_reduction_is_polynomial(self):
        """Reduction should be O(n) — just mapping items."""
        instance = KnapsackInstance(
            values=list(range(1000)),
            weights=list(range(1, 1001)),
            capacity=5000,
        )
        requests, budget = reduce_knapsack_to_allocation(instance)
        assert len(requests) == 1000


class TestKnapsackDP:
    def test_trivial_instance(self):
        instance = KnapsackInstance(values=[10], weights=[5], capacity=10)
        value, items = solve_knapsack_dp(instance)
        assert value == 10
        assert items == [0]

    def test_budget_too_small(self):
        instance = KnapsackInstance(values=[10], weights=[20], capacity=5)
        value, items = solve_knapsack_dp(instance)
        assert value == 0
        assert items == []

    def test_known_solution(self):
        instance = KnapsackInstance(
            values=[60, 100, 120],
            weights=[10, 20, 30],
            capacity=50,
        )
        value, items = solve_knapsack_dp(instance)
        assert value == 220
        assert set(items) == {1, 2}

    def test_all_fit(self):
        instance = KnapsackInstance(
            values=[5, 10, 15],
            weights=[1, 1, 1],
            capacity=10,
        )
        value, items = solve_knapsack_dp(instance)
        assert value == 30
        assert set(items) == {0, 1, 2}


class TestSubmodularity:
    def test_congestion_welfare_is_submodular(self):
        def welfare(s: set[int]) -> float:
            return congestion_welfare(s, 100)

        is_sub, marginals = verify_submodularity(welfare, 30, n_samples=100)
        assert is_sub

    def test_linear_function_is_submodular(self):
        """Linear functions are both submodular and supermodular."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        def linear_welfare(s: set[int]) -> float:
            return sum(values[i] for i in s)

        is_sub, _ = verify_submodularity(linear_welfare, 5, n_samples=50)
        assert is_sub

    def test_supermodular_detected(self):
        """A supermodular function should fail submodularity check."""
        def supermodular(s: set[int]) -> float:
            return len(s) ** 2

        is_sub, _ = verify_submodularity(supermodular, 10, n_samples=200)
        assert not is_sub

    def test_marginal_gains_returned(self):
        def welfare(s: set[int]) -> float:
            return congestion_welfare(s, 50)

        _, marginals = verify_submodularity(welfare, 20, n_samples=50)
        assert len(marginals) > 0
        assert all(isinstance(m, float) for m in marginals)


class TestCongestionWelfare:
    def test_empty_set_zero_welfare(self):
        assert congestion_welfare(set(), 100) == 0.0

    def test_positive_welfare(self):
        w = congestion_welfare({0, 1, 2}, 100)
        assert w > 0.0

    def test_monotone(self):
        w1 = congestion_welfare({0}, 100)
        w2 = congestion_welfare({0, 1}, 100)
        w3 = congestion_welfare({0, 1, 2}, 100)
        assert w2 >= w1
        assert w3 >= w2

    def test_diminishing_returns(self):
        """Marginal gain should decrease — submodularity."""
        w0 = congestion_welfare(set(), 100)
        w1 = congestion_welfare({0}, 100)
        w10 = congestion_welfare(set(range(10)), 100)
        w11 = congestion_welfare(set(range(11)), 100)

        mg_first = w1 - w0
        mg_eleventh = w11 - w10
        assert mg_first >= mg_eleventh


class TestApproximationBounds:
    def test_greedy_bound(self):
        bounds = compute_approximation_bounds(100, 1000, 10)
        assert abs(bounds["greedy_guarantee"] - (1 - 1 / math.e)) < 1e-10

    def test_secretary_bound(self):
        bounds = compute_approximation_bounds(100, 1000, 10)
        assert abs(bounds["secretary_guarantee"] - 1 / math.e) < 1e-10

    def test_budget_binding(self):
        bounds = compute_approximation_bounds(100, 50, 10)
        assert bounds["budget_binding"]
        assert bounds["max_items_in_budget"] == 5

    def test_budget_nonbinding(self):
        bounds = compute_approximation_bounds(10, 10000, 10)
        assert not bounds["budget_binding"]
        assert bounds["greedy_effective"] == 1.0

    def test_fptas_near_optimal(self):
        bounds = compute_approximation_bounds(100, 1000, 10)
        assert bounds["fptas_0.01"] == 0.99


class TestTractableCases:
    def test_returns_cases(self):
        cases = identify_tractable_cases()
        assert len(cases) >= 4

    def test_uniform_cost_case(self):
        cases = identify_tractable_cases()
        names = [c["case"] for c in cases]
        assert "Uniform costs" in names

    def test_all_have_required_fields(self):
        cases = identify_tractable_cases()
        for c in cases:
            assert "case" in c
            assert "complexity" in c
            assert "algorithm" in c
            assert "guarantee" in c


class TestRunComplexityAnalysis:
    def test_returns_result(self):
        result = run_complexity_analysis(n_agents=20, budget=100, avg_cost=5)
        assert isinstance(result, ComplexityResult)
        assert result.is_np_hard

    def test_greedy_beats_zero(self):
        result = run_complexity_analysis(n_agents=30, budget=200, avg_cost=10)
        assert result.approximation_ratio > 0

    def test_submodularity_checked(self):
        result = run_complexity_analysis(n_agents=20, budget=100, avg_cost=5)
        assert result.submodularity_verified

    def test_tractable_cases_listed(self):
        result = run_complexity_analysis(n_agents=20, budget=100, avg_cost=5)
        assert len(result.tractable_cases) >= 4

    def test_dp_optimal_geq_greedy(self):
        result = run_complexity_analysis(n_agents=50, budget=300, avg_cost=10)
        opt = result.details["optimal_dp_value"]
        greedy = result.details["greedy_value"]
        assert opt >= greedy - 1e-10

    def test_greedy_within_bound(self):
        result = run_complexity_analysis(n_agents=50, budget=300, avg_cost=10, seed=7)
        opt = result.details["optimal_dp_value"]
        greedy = result.details["greedy_value"]
        if opt > 0:
            ratio = greedy / opt
            assert ratio >= 0.5
