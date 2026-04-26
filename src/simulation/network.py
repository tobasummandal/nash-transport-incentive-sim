"""
Simple road network representation for simulation.

Provides travel time estimation based on distance and congestion levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Corridor:
    """A major traffic corridor (e.g., I-24)."""

    corridor_id: str
    name: str
    length_miles: float
    free_flow_speed: float = 65.0  # mph
    capacity_vph: float = 2000.0  # vehicles per hour per lane
    num_lanes: int = 3
    direction: str = "inbound"  # inbound or outbound

    # BPR volume-delay parameters. Defaults follow the TRB-recommended
    # freeway values (Spiess 1990) which are stronger than the original
    # BPR(0.15, 4.0) and produce realistic peak-hour slowdowns.
    bpr_alpha: float = 0.83
    bpr_beta: float = 5.5

    # Current state
    current_volume: float = 0.0
    current_speed: float = 65.0
    peak_volume: float = 0.0
    peak_congestion_factor: float = 1.0

    # Pacer smoothing — calibrated from CIRCLES I-24 experiment
    # (Jang et al. 2024, IEEE Control Systems; Ameli et al. 2025).
    # At 4% penetration rate, 9.1% MPG improvement was observed.
    # We model this as pacers reducing the congestion factor by a
    # fraction proportional to penetration rate:
    #   cf_reduction = pacer_alpha * (active_pacers / current_volume)
    # With pacer_alpha = 2.25 (derived from 9%/4% = 2.25).
    active_pacers: int = 0
    pacer_alpha: float = 2.25

    def get_travel_time(self, congestion_factor: float = 1.0) -> float:
        """Get travel time in seconds given congestion."""
        effective_speed = self.free_flow_speed / max(1.0, congestion_factor)
        effective_speed = max(5.0, effective_speed)
        return (self.length_miles / effective_speed) * 3600

    def _instantaneous_capacity(self) -> float:
        """Max vehicles simultaneously on the corridor at capacity flow."""
        traversal_hours = self.length_miles / max(1.0, self.free_flow_speed)
        return self.capacity_vph * self.num_lanes * traversal_hours

    def get_congestion_factor(self) -> float:
        """Compute congestion factor with pacer smoothing.

        Uses instantaneous capacity (max simultaneous vehicles) rather
        than hourly flow so that the BPR function responds correctly to
        the instantaneous vehicle count. Active pacers then reduce the
        resulting congestion factor, modeling the wave-dampening effect
        observed in the CIRCLES field experiment on I-24 (Nov 2022).
        """
        inst_cap = self._instantaneous_capacity()
        vc_ratio = self.current_volume / max(1.0, inst_cap)
        raw_cf = 1.0 + self.bpr_alpha * (vc_ratio ** self.bpr_beta)

        if self.active_pacers > 0 and self.current_volume > 0:
            penetration = self.active_pacers / self.current_volume
            reduction = min(0.5, self.pacer_alpha * penetration)
            excess = raw_cf - 1.0
            raw_cf = 1.0 + excess * (1.0 - reduction)

        return raw_cf

    def add_vehicle(self) -> None:
        self.current_volume += 1
        if self.current_volume > self.peak_volume:
            self.peak_volume = self.current_volume
        cf = self.get_congestion_factor()
        if cf > self.peak_congestion_factor:
            self.peak_congestion_factor = cf

    def remove_vehicle(self) -> None:
        self.current_volume = max(0.0, self.current_volume - 1)

    def add_pacer(self) -> None:
        self.active_pacers += 1

    def remove_pacer(self) -> None:
        self.active_pacers = max(0, self.active_pacers - 1)


@dataclass
class NetworkNode:
    """A node in the road network (intersection, on/off ramp)."""

    node_id: str
    location: tuple[float, float]  # lat, lng
    node_type: str = "intersection"  # intersection, origin, destination, ramp


@dataclass
class NetworkLink:
    """A link connecting two nodes."""

    link_id: str
    from_node: str
    to_node: str
    length_miles: float
    free_flow_speed: float = 35.0
    capacity_vph: float = 1200.0
    corridor_id: Optional[str] = None

    current_volume: float = 0.0

    def get_travel_time(self) -> float:
        """Get travel time in seconds."""
        congestion = self.get_congestion_factor()
        effective_speed = self.free_flow_speed / congestion
        effective_speed = max(5.0, effective_speed)
        return (self.length_miles / effective_speed) * 3600

    def get_congestion_factor(self) -> float:
        """BPR congestion function."""
        vc_ratio = self.current_volume / max(1.0, self.capacity_vph)
        return 1.0 + 0.15 * (vc_ratio**4.0)


@dataclass
class SimpleNetwork:
    """
    Simple network for simulation experiments.

    Represents the I-24 corridor with origin/destination zones.
    """

    corridors: dict[str, Corridor] = field(default_factory=dict)
    nodes: dict[str, NetworkNode] = field(default_factory=dict)
    links: dict[str, NetworkLink] = field(default_factory=dict)

    # Zone definitions
    origin_zones: list[tuple[float, float, float]] = field(
        default_factory=list
    )  # (lat, lng, radius)
    destination_zones: list[tuple[float, float, float]] = field(default_factory=list)

    def add_corridor(self, corridor: Corridor) -> None:
        """Add a corridor to the network."""
        self.corridors[corridor.corridor_id] = corridor

    def add_node(self, node: NetworkNode) -> None:
        """Add a node to the network."""
        self.nodes[node.node_id] = node

    def add_link(self, link: NetworkLink) -> None:
        """Add a link to the network."""
        self.links[link.link_id] = link

    def get_travel_time(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        mode: str = "drive",
        corridor_id: Optional[str] = None,
    ) -> float:
        """
        Estimate travel time between two points.

        Uses link-level BPR travel times when the network has links,
        corridor-level BPR for labeled corridor trips, and haversine
        with area congestion as fallback.

        Returns:
            Travel time in seconds
        """
        distance = self._haversine_distance(origin, destination)

        if mode == "drive" or mode == "drive_alone":
            if corridor_id and corridor_id in self.corridors:
                corridor = self.corridors[corridor_id]
                congestion = corridor.get_congestion_factor()
                return corridor.get_travel_time(congestion)

            # Try link-level routing when links exist
            if self.links:
                link_time = self._route_via_links(origin, destination)
                if link_time is not None:
                    return link_time

            base_speed = 30.0
            congestion = self._estimate_area_congestion()
            effective_speed = base_speed / congestion
            return (distance / max(effective_speed, 5.0)) * 3600

        elif mode == "carpool":
            drive_time = self.get_travel_time(origin, destination, "drive", corridor_id)
            detour_time = 300
            return drive_time + detour_time

        elif mode == "pacer":
            if corridor_id and corridor_id in self.corridors:
                corridor = self.corridors[corridor_id]
                congestion = corridor.get_congestion_factor()
                return corridor.get_travel_time(congestion)
            return self.get_travel_time(origin, destination, "drive", corridor_id)

        elif mode == "transit":
            base_speed = 20.0
            wait_time = 600
            return (distance / base_speed) * 3600 + wait_time

        elif mode == "walk":
            return (distance / 3.0) * 3600

        elif mode == "bike":
            return (distance / 12.0) * 3600

        else:
            return (distance / 25.0) * 3600

    def _route_via_links(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> Optional[float]:
        """
        Greedy nearest-link routing with BPR travel times.

        Finds the closest origin and destination nodes, then walks
        the link graph greedily toward the destination. Each link
        contributes its own flow-dependent BPR travel time.
        """
        if not self.nodes or not self.links:
            return None

        origin_node = self._nearest_node(origin)
        dest_node = self._nearest_node(destination)
        if origin_node is None or dest_node is None or origin_node == dest_node:
            return None

        adjacency: dict[str, list[NetworkLink]] = {}
        for link in self.links.values():
            adjacency.setdefault(link.from_node, []).append(link)

        visited: set[str] = set()
        current = origin_node
        total_time = 0.0

        for _ in range(len(self.nodes)):
            if current == dest_node:
                return total_time
            if current in visited:
                break
            visited.add(current)

            outgoing = adjacency.get(current, [])
            if not outgoing:
                break

            dest_loc = self.nodes[dest_node].location
            best_link = min(
                outgoing,
                key=lambda lk: self._haversine_distance(
                    self.nodes[lk.to_node].location, dest_loc
                ),
            )
            total_time += best_link.get_travel_time()
            current = best_link.to_node

        return None

    def _nearest_node(self, point: tuple[float, float]) -> Optional[str]:
        if not self.nodes:
            return None
        return min(
            self.nodes,
            key=lambda nid: self._haversine_distance(
                self.nodes[nid].location, point
            ),
        )

    def update_volumes(self, departures: dict[str, int]) -> None:
        """
        Update corridor volumes based on departures.

        Args:
            departures: dict mapping corridor_id to number of vehicles
        """
        for corridor_id, volume in departures.items():
            if corridor_id in self.corridors:
                self.corridors[corridor_id].current_volume = volume

    def reset_volumes(self) -> None:
        """Reset all volumes to zero."""
        for corridor in self.corridors.values():
            corridor.current_volume = 0.0
        for link in self.links.values():
            link.current_volume = 0.0

    def _estimate_area_congestion(self) -> float:
        """Estimate overall area congestion from corridor states."""
        if not self.corridors:
            return 1.0

        factors = [c.get_congestion_factor() for c in self.corridors.values()]
        return np.mean(factors)

    def _haversine_distance(
        self,
        coord1: tuple[float, float],
        coord2: tuple[float, float],
    ) -> float:
        """Compute haversine distance in miles."""
        lat1, lon1 = np.radians(coord1)
        lat2, lon2 = np.radians(coord2)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))

        r = 3956  # Earth radius in miles
        return c * r


def create_i24_network() -> SimpleNetwork:
    """
    Create a simple I-24 corridor network for Nashville.

    Returns:
        SimpleNetwork configured for I-24 experiments
    """
    network = SimpleNetwork()

    # The I-24 MOTION testbed covers a 4-mile congestion-prone section
    # of I-24 (SR-254 to SR-171). Capacity is set to represent a
    # bottleneck segment (merge/weave area) so that the simulation
    # produces realistic congestion at typical agent counts (100-500).
    network.add_corridor(
        Corridor(
            corridor_id="I-24-inbound",
            name="I-24 Inbound (MOTION testbed)",
            length_miles=4.0,
            free_flow_speed=65.0,
            capacity_vph=120.0,
            num_lanes=3,
            direction="inbound",
        )
    )
    network.add_corridor(
        Corridor(
            corridor_id="I-24-outbound",
            name="I-24 Outbound (MOTION testbed)",
            length_miles=4.0,
            free_flow_speed=65.0,
            capacity_vph=120.0,
            num_lanes=3,
            direction="outbound",
        )
    )

    # Define zones
    # Origin zone: Southeast Nashville suburbs
    network.origin_zones = [(36.08, -86.65, 10.0)]  # center lat, lng, radius km

    # Destination zone: Downtown Nashville
    network.destination_zones = [(36.16, -86.78, 5.0)]

    return network


def create_stadium_network(
    stadium_location: tuple[float, float] = (36.166, -86.771),
    capacity: int = 10000,
) -> SimpleNetwork:
    """
    Create a network for stadium egress simulation.

    Args:
        stadium_location: (lat, lng) of stadium
        capacity: venue capacity

    Returns:
        SimpleNetwork configured for event egress
    """
    network = SimpleNetwork()

    # Add egress corridors (multiple directions)
    for i, (name, direction, length) in enumerate(
        [
            ("North Exit", "north", 2.0),
            ("South Exit", "south", 2.5),
            ("East Exit", "east", 1.5),
            ("West Exit", "west", 3.0),
        ]
    ):
        network.add_corridor(
            Corridor(
                corridor_id=f"egress-{direction}",
                name=name,
                length_miles=length,
                free_flow_speed=25.0,  # Slower urban streets
                capacity_vph=800.0,
                num_lanes=2,
                direction=direction,
            )
        )

    # Stadium as single origin
    network.origin_zones = [(stadium_location[0], stadium_location[1], 0.5)]

    # Dispersed destinations
    network.destination_zones = [
        (36.20, -86.75, 5.0),  # North
        (36.12, -86.80, 5.0),  # South
        (36.16, -86.65, 5.0),  # East
        (36.16, -86.85, 5.0),  # West
    ]

    return network
