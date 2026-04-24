"""
Event-driven simulation engine.

Core simulation engine that processes events and coordinates agents,
network, and metrics collection.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from ..agents.base import BaseAgent, TravelMode, TripAttributes
from ..agents.behavioral import LogitModel
from ..incentives.base import BaseIncentive, IncentiveAllocation
from ..optimization import Allocator, AlwaysAllocator, OfferRequest
from .events import (
    Event,
    EventType,
    create_arrival_event,
    create_metrics_snapshot_event,
)
from .metrics import MetricsCollector, TripRecord, PacerRecord, CarpoolRecord
from .network import SimpleNetwork


@dataclass
class SimulationConfig:
    """Configuration for a simulation run."""

    duration_seconds: float = 14400  # 4 hours
    warmup_seconds: float = 1800  # 30 minutes
    time_step_seconds: float = 1.0
    metrics_interval: float = 300.0  # 5 minutes
    random_seed: int = 42

    # Agent settings
    n_agents: int = 1000

    # Network settings
    corridor_ids: list[str] = field(default_factory=lambda: ["I-24-inbound"])

    # Incentive settings
    incentive_enabled: bool = True
    incentive_budget: float = 10000.0


@dataclass
class SimulationResult:
    """Results from a simulation run."""

    config: SimulationConfig
    metrics: dict[str, Any]
    raw_data: Any  # DataFrame of trip records
    time_series: list[dict]
    duration_seconds: float


class SimulationEngine:
    """
    Event-driven simulation engine.

    Processes events from a priority queue and coordinates agents,
    network state, and metrics collection.
    """

    def __init__(
        self,
        config: SimulationConfig,
        network: Optional[SimpleNetwork] = None,
        rng: Optional[np.random.Generator] = None,
        incentives: Optional[list[BaseIncentive]] = None,
        allocator: Optional[Allocator] = None,
    ):
        self.config = config
        self.network = network or SimpleNetwork()
        self.rng = rng or np.random.default_rng(config.random_seed)

        # Event queue (min-heap by time)
        self.event_queue: list[Event] = []

        # Agents
        self.agents: dict[str, BaseAgent] = {}

        # Incentives & allocator
        self.incentives: list[BaseIncentive] = incentives or []
        self.allocator: Allocator = allocator or AlwaysAllocator()
        # agent_id -> list of (incentive, allocation) pairs awaiting completion
        self._pending_allocations: dict[
            str, list[tuple[BaseIncentive, IncentiveAllocation]]
        ] = {}

        # Metrics
        self.metrics = MetricsCollector(snapshot_interval=config.metrics_interval)

        # State
        self.current_time: float = 0.0
        self.active_trips: dict[str, dict] = {}  # agent_id -> trip info
        self.is_running: bool = False

        # Event handlers
        self._handlers: dict[EventType, Callable[[Event], None]] = {
            EventType.DEPARTURE: self._handle_departure,
            EventType.ARRIVAL: self._handle_arrival,
            EventType.MODE_CHOICE: self._handle_mode_choice,
            EventType.PACING_UPDATE: self._handle_pacing_update,
            EventType.PACING_START: self._handle_pacing_start,
            EventType.PACING_END: self._handle_pacing_end,
            EventType.CARPOOL_MATCH: self._handle_carpool_match,
            EventType.CARPOOL_COMPLETE: self._handle_carpool_complete,
            EventType.INCENTIVE_OFFER: self._handle_incentive_offer,
            EventType.METRICS_SNAPSHOT: self._handle_metrics_snapshot,
            EventType.EVENT_END: self._handle_event_end,
        }

        # Behavioral model for mode choice
        self.behavioral_model = LogitModel(scale=1.0)

    def add_agent(self, agent: BaseAgent) -> None:
        """Add an agent to the simulation."""
        self.agents[agent.id] = agent

    def add_agents(self, agents: list[BaseAgent]) -> None:
        """Add multiple agents to the simulation."""
        for agent in agents:
            self.add_agent(agent)

    def schedule_event(self, event: Event) -> None:
        """Schedule an event for processing."""
        heapq.heappush(self.event_queue, event)

    def schedule_departure(
        self,
        agent_id: str,
        time: float,
        origin: tuple[float, float],
        destination: tuple[float, float],
        mode: str = "drive",
        corridor_id: Optional[str] = None,
    ) -> None:
        """Schedule a departure event."""
        event = Event(
            time=time,
            event_type=EventType.DEPARTURE,
            agent_id=agent_id,
            data={
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "corridor_id": corridor_id,
            },
        )
        self.schedule_event(event)

    def run(self, until: Optional[float] = None) -> SimulationResult:
        """
        Run the simulation.

        Args:
            until: End time (defaults to config.duration_seconds)

        Returns:
            SimulationResult with metrics and data
        """
        import time as time_module

        start_wall_time = time_module.time()

        end_time = until or self.config.duration_seconds
        self.is_running = True

        # Schedule periodic metrics snapshots
        snapshot_time = self.config.metrics_interval
        while snapshot_time < end_time:
            self.schedule_event(create_metrics_snapshot_event(snapshot_time))
            snapshot_time += self.config.metrics_interval

        # Process events
        while self.event_queue and self.is_running:
            event = heapq.heappop(self.event_queue)

            if event.time > end_time:
                break

            self.current_time = event.time

            handler = self._handlers.get(event.event_type)
            if handler:
                handler(event)

        self.is_running = False

        # Compile results
        wall_time = time_module.time() - start_wall_time
        metrics = self.metrics.get_summary_metrics()
        metrics.update(self.metrics.get_pacer_metrics())
        metrics.update(self.metrics.get_carpool_metrics())

        return SimulationResult(
            config=self.config,
            metrics=metrics,
            raw_data=self.metrics.to_dataframe(),
            time_series=[
                {
                    "time": ts.time,
                    "departures": ts.departures,
                    "arrivals": ts.arrivals,
                    "active_trips": ts.active_trips,
                    "avg_speed": ts.avg_speed,
                    "speed_variance": ts.speed_variance,
                }
                for ts in self.metrics.time_slices
            ],
            duration_seconds=wall_time,
        )

    def stop(self) -> None:
        """Stop the simulation."""
        self.is_running = False

    def reset(self) -> None:
        """Reset simulation state."""
        self.event_queue = []
        self.current_time = 0.0
        self.active_trips = {}
        self.is_running = False
        self.metrics.reset()

    # Event Handlers

    def _handle_departure(self, event: Event) -> None:
        """Handle agent departure."""
        agent_id = event.agent_id
        data = event.data

        origin = data["origin"]
        destination = data["destination"]
        mode = data.get("mode", "drive")
        corridor_id = data.get("corridor_id")

        # Compute travel time
        travel_time = self.network.get_travel_time(
            origin, destination, mode, corridor_id
        )

        # Add some randomness
        travel_time *= self.rng.uniform(0.9, 1.1)

        # Compute distance
        distance = self.network._haversine_distance(origin, destination)

        # Track active trip
        self.active_trips[agent_id] = {
            "departure_time": event.time,
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "corridor_id": corridor_id,
            "expected_travel_time": travel_time,
            "distance": distance,
            "incentive": 0.0,
        }

        # Offer incentives at departure (may flag trip as passenger-mode)
        self._offer_incentives(agent_id, self.active_trips[agent_id])

        # Record departure
        self.metrics.record_departure(agent_id, mode, corridor_id)

        # Update corridor volume — a successful carpool offer turns this
        # trip into a shared ride, so no additional vehicle enters the
        # corridor. This is the hook by which incentives reduce congestion.
        displaces_vehicle = self.active_trips[agent_id].get(
            "displaces_vehicle", False
        )
        if (
            corridor_id
            and corridor_id in self.network.corridors
            and not displaces_vehicle
        ):
            self.network.corridors[corridor_id].add_vehicle()

        # Schedule arrival
        arrival_event = create_arrival_event(
            time=event.time + travel_time,
            agent_id=agent_id,
            destination=destination,
            mode=mode,
            actual_travel_time=travel_time,
            corridor_id=corridor_id,
        )
        self.schedule_event(arrival_event)

        # If pacer, schedule pacing updates
        if mode == "pacer" and corridor_id:
            self._schedule_pacing_updates(
                agent_id, event.time, travel_time, corridor_id
            )

    def _handle_arrival(self, event: Event) -> None:
        """Handle agent arrival."""
        agent_id = event.agent_id
        data = event.data

        trip_info = self.active_trips.pop(agent_id, None)
        if not trip_info:
            return

        # Complete any pending incentive allocations for this trip
        self._complete_incentives(agent_id, trip_info, event.time)

        # Record trip
        trip_record = TripRecord(
            agent_id=agent_id,
            departure_time=trip_info["departure_time"],
            arrival_time=event.time,
            origin=trip_info["origin"],
            destination=trip_info["destination"],
            mode=trip_info["mode"],
            travel_time=data["actual_travel_time"],
            distance_miles=trip_info["distance"],
            incentive_received=trip_info.get("incentive", 0.0),
            corridor_id=trip_info.get("corridor_id"),
        )
        self.metrics.record_trip(trip_record)

        # Update corridor volume (mirror the departure-side displacement check)
        corridor_id = trip_info.get("corridor_id")
        if (
            corridor_id
            and corridor_id in self.network.corridors
            and not trip_info.get("displaces_vehicle", False)
        ):
            self.network.corridors[corridor_id].remove_vehicle()

    def _handle_mode_choice(self, event: Event) -> None:
        """Handle mode choice decision."""
        agent_id = event.agent_id
        data = event.data

        agent = self.agents.get(agent_id)
        if not agent:
            return

        available_modes = data.get("available_modes", ["drive"])
        trip_options = data.get("trip_options", {})

        # Use agent's preferences to choose mode
        if hasattr(agent, "decide_mode"):
            mode_enum = agent.decide_mode(
                [TravelMode[m.upper()] for m in available_modes]
            )
            chosen_mode = mode_enum.name.lower()
        else:
            chosen_mode = self.rng.choice(available_modes)

        # Update event data with chosen mode
        event.data["chosen_mode"] = chosen_mode

    def _handle_pacing_start(self, event: Event) -> None:
        """Handle pacer session start."""
        agent_id = event.agent_id
        data = event.data

        agent = self.agents.get(agent_id)
        if agent and hasattr(agent, "start_pacing"):
            agent.start_pacing(
                target_speed=data.get("target_speed", 55.0),
                corridor_id=data.get("corridor_id", "I-24"),
            )

    def _handle_pacing_update(self, event: Event) -> None:
        """Handle pacer speed update."""
        agent_id = event.agent_id
        data = event.data

        current_speed = data.get("current_speed", 55.0)

        # Record speed for variance calculation
        self.metrics.record_speed(current_speed)

        # Update agent state
        agent = self.agents.get(agent_id)
        if agent and hasattr(agent, "update_speed"):
            suggested = agent.update_speed(current_speed, self.current_time)
            # In a full simulation, this would affect traffic

    def _handle_pacing_end(self, event: Event) -> None:
        """Handle pacer session end."""
        agent_id = event.agent_id
        data = event.data

        agent = self.agents.get(agent_id)
        if agent and hasattr(agent, "end_pacing"):
            result = agent.end_pacing()

            # Record pacer session
            if result.get("smoothness_score", 0) > 0:
                record = PacerRecord(
                    agent_id=agent_id,
                    session_id=data.get("session_id", f"pacer_{agent_id}"),
                    corridor_id=data.get("corridor_id", "I-24"),
                    start_time=data.get("start_time", 0),
                    end_time=self.current_time,
                    distance_miles=data.get("distance", 0),
                    smoothness_score=result["smoothness_score"],
                    reward=data.get("reward", 0),
                    speed_samples=result.get("speeds", []),
                )
                self.metrics.record_pacer_session(record)

    def _handle_carpool_match(self, event: Event) -> None:
        """Handle carpool match formation."""
        data = event.data

        driver_id = data.get("driver_id")
        passenger_ids = data.get("passenger_ids", [])

        # Track match in active trips
        for pid in [driver_id] + passenger_ids:
            if pid in self.active_trips:
                self.active_trips[pid]["carpool_match"] = data.get("match_id")

    def _handle_carpool_complete(self, event: Event) -> None:
        """Handle carpool trip completion."""
        data = event.data

        record = CarpoolRecord(
            match_id=data.get("match_id", ""),
            driver_id=data.get("driver_id", ""),
            passenger_ids=data.get("passenger_ids", []),
            departure_time=data.get("departure_time", 0),
            arrival_time=self.current_time,
            distance_miles=data.get("distance", 0),
            total_reward=data.get("total_reward", 0),
            n_passengers=len(data.get("passenger_ids", [])),
        )
        self.metrics.record_carpool(record)

    def _handle_incentive_offer(self, event: Event) -> None:
        """Handle incentive offer to agent."""
        agent_id = event.agent_id
        data = event.data

        agent = self.agents.get(agent_id)
        if not agent:
            return

        # Agent decides whether to accept
        if hasattr(agent, "respond_to_incentive"):
            accepted = agent.respond_to_incentive(
                incentive_type=data.get("type", ""),
                incentive_amount=data.get("amount", 0),
                conditions=data.get("conditions", {}),
            )
            event.data["accepted"] = accepted

    def _handle_metrics_snapshot(self, event: Event) -> None:
        """Handle periodic metrics snapshot."""
        corridor_volumes = {
            cid: int(c.current_volume) for cid, c in self.network.corridors.items()
        }

        self.metrics.take_snapshot(
            time=self.current_time,
            active_trips=len(self.active_trips),
            corridor_volumes=corridor_volumes,
        )

    def _handle_event_end(self, event: Event) -> None:
        """Handle stadium/event end."""
        # This triggers egress behavior
        event.data["event_ended"] = True

    def _offer_incentives(self, agent_id: str, trip_info: dict) -> None:
        """
        Offer each configured incentive to the agent at departure.

        For every incentive whose eligibility checks pass, ask the allocator
        whether this offer is a good use of remaining budget. Accepted offers
        are parked in _pending_allocations until the trip completes.
        """
        if not self.incentives:
            return

        context = self._build_offer_context(agent_id, trip_info)
        agent = self.agents.get(agent_id)

        for incentive in self.incentives:
            if not incentive.config.enabled:
                continue

            is_eligible, _ = incentive.check_eligibility(agent_id, context)
            if not is_eligible:
                continue

            expected_reward = incentive.compute_reward(agent_id, context)
            if expected_reward <= 0:
                continue

            # Reserve against in-flight allocations: budget_daily already
            # counts total_allocated, so subtract that (not just total_spent)
            # to avoid over-committing while trips are still running.
            effective_remaining = max(
                0.0, incentive.config.budget_daily - incentive.total_allocated
            )
            if expected_reward > effective_remaining:
                continue

            request = OfferRequest(
                agent_id=agent_id,
                incentive_type=incentive.incentive_type.name,
                expected_reward=expected_reward,
                score=self._score_offer(incentive, context, expected_reward),
                context=context,
            )
            if not self.allocator.should_offer(request, effective_remaining):
                continue

            result = incentive.offer_incentive(agent_id, context)
            if not result.success or result.allocation is None:
                continue

            # Ask the agent whether to accept
            accepted = True
            if agent is not None and hasattr(agent, "respond_to_incentive"):
                accepted = bool(
                    agent.respond_to_incentive(
                        incentive_type=incentive.incentive_type.name.lower(),
                        incentive_amount=result.allocation.amount,
                        conditions=result.allocation.conditions,
                    )
                )

            if not accepted:
                result.allocation.status = "rejected"
                continue

            incentive.accept_incentive(result.allocation.allocation_id)
            self._pending_allocations.setdefault(agent_id, []).append(
                (incentive, result.allocation)
            )

            # Carpool acceptance removes this agent's vehicle from the
            # network: they are a passenger, not a driver.
            if incentive.incentive_type.name == "CARPOOL":
                trip_info["displaces_vehicle"] = True

    def _complete_incentives(
        self, agent_id: str, trip_info: dict, arrival_time: float
    ) -> None:
        """Settle all pending incentive allocations for an agent's completed trip."""
        pending = self._pending_allocations.pop(agent_id, [])
        total_earned = 0.0

        for incentive, allocation in pending:
            outcome = self._build_completion_outcome(trip_info, arrival_time)
            result = incentive.complete_incentive(allocation.allocation_id, outcome)
            if result.success and result.allocation is not None:
                total_earned += result.allocation.actual_reward
                self.allocator.observe_completion(
                    OfferRequest(
                        agent_id=agent_id,
                        incentive_type=incentive.incentive_type.name,
                        expected_reward=allocation.amount,
                        score=0.0,
                    ),
                    actual_cost=result.allocation.actual_reward,
                )

        if total_earned > 0:
            trip_info["incentive"] = trip_info.get("incentive", 0.0) + total_earned
            agent = self.agents.get(agent_id)
            if agent is not None:
                agent.state.incentives_earned += total_earned

    def _build_offer_context(self, agent_id: str, trip_info: dict) -> dict:
        """Build context dict passed to incentive eligibility/reward calls."""
        hour = int((self.current_time / 3600) % 24)
        agent = self.agents.get(agent_id)
        carpool_eligible = True
        has_car = True
        if agent is not None and hasattr(agent, "profile"):
            carpool_eligible = getattr(agent.profile, "carpool_eligible", True)
            has_car = getattr(agent.profile, "has_car", True)

        return {
            "timestamp": self.current_time,
            "hour": hour,
            "day_of_week": 0,  # weekday default — extend when calendar added
            "corridor_id": trip_info.get("corridor_id"),
            "distance_miles": trip_info.get("distance", 0.0),
            "expected_distance_miles": trip_info.get("distance", 0.0),
            "expected_smoothness": 0.8,
            "n_passengers": 1,
            "is_driver": trip_info.get("mode") in ("drive", "drive_alone", "carpool"),
            "carpool_eligible": carpool_eligible,
            "has_car": has_car,
            "enrolled_corridors": [trip_info.get("corridor_id")],
            "original_departure_time": trip_info.get("departure_time", 0.0),
            "shifted_departure_time": trip_info.get("departure_time", 0.0),
            "flexibility_window": 900,
        }

    def _build_completion_outcome(self, trip_info: dict, arrival_time: float) -> dict:
        """Build outcome dict for incentive completion verification."""
        hour = int((arrival_time / 3600) % 24)
        distance = trip_info.get("distance", 0.0)
        return {
            "timestamp": arrival_time,
            "trip_completed": True,
            "actual_passengers": 1,
            "is_driver": True,
            "actual_distance_miles": distance,
            "distance_miles": distance,
            "completion_hour": hour,
            "hour": hour,
            "smoothness_score": 0.85,
            "actual_departure_time": trip_info.get("departure_time", 0.0),
        }

    def _score_offer(
        self,
        incentive: BaseIncentive,
        context: dict,
        expected_reward: float,
    ) -> float:
        """
        Score an offer for the allocator (higher = more valuable).

        Heuristic: reward capped by distance — offers on longer trips during
        peak hours have higher congestion-reduction potential per dollar.
        """
        distance = context.get("distance_miles", 0.0)
        hour = context.get("hour", 8)
        peak_boost = 1.5 if hour in {7, 8, 9, 17, 18, 19} else 1.0
        return distance * peak_boost

    def _schedule_pacing_updates(
        self,
        agent_id: str,
        start_time: float,
        duration: float,
        corridor_id: str,
    ) -> None:
        """Schedule periodic pacing updates during a trip."""
        update_interval = 30.0  # Every 30 seconds
        current = start_time + update_interval

        while current < start_time + duration:
            # Simulate speed with some noise
            target_speed = self.network.corridors.get(corridor_id)
            base_speed = target_speed.free_flow_speed if target_speed else 55.0
            current_speed = base_speed * self.rng.uniform(0.85, 1.0)

            update_event = Event(
                time=current,
                event_type=EventType.PACING_UPDATE,
                agent_id=agent_id,
                data={
                    "corridor_id": corridor_id,
                    "current_speed": current_speed,
                    "position": (0, 0),  # Simplified
                },
            )
            self.schedule_event(update_event)

            current += update_interval


def run_simulation(
    config: SimulationConfig,
    agents: list[BaseAgent],
    network: Optional[SimpleNetwork] = None,
    departures: Optional[list[dict]] = None,
    incentives: Optional[list[BaseIncentive]] = None,
    allocator: Optional[Allocator] = None,
) -> SimulationResult:
    """
    Convenience function to run a simulation.

    Args:
        config: Simulation configuration
        agents: List of agents
        network: Road network (optional)
        departures: List of departure events to schedule
        incentives: List of incentive mechanisms (optional)
        allocator: Budget allocation strategy (optional, defaults to AlwaysAllocator)

    Returns:
        SimulationResult
    """
    engine = SimulationEngine(
        config, network, incentives=incentives, allocator=allocator
    )
    engine.add_agents(agents)

    # Schedule departures
    if departures:
        for dep in departures:
            engine.schedule_departure(
                agent_id=dep["agent_id"],
                time=dep["time"],
                origin=dep["origin"],
                destination=dep["destination"],
                mode=dep.get("mode", "drive"),
                corridor_id=dep.get("corridor_id"),
            )

    return engine.run()
