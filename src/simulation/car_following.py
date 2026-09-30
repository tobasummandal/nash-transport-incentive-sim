"""
Microscopic car-following layer: IDM vehicles with a pluggable pacer controller.

This module grounds the pacer incentive in actual wave physics. The BPR
corridor model in ``network.py`` has no time dynamics and cannot represent
stop-and-go waves; this layer can. It is deliberately standalone (NumPy only)
so it can be validated against I-24 MOTION trajectories and then coupled
back to the macroscopic model through an effective-capacity fit.

Two road geometries:

* ``RingRoad`` - periodic, fixed vehicle count. Reproduces the Sugiyama (2008)
  instability: uniform flow breaks into a single backward-moving jam.
* ``OpenRoad`` - a multi-lane-equivalent single lane with an upstream inflow
  and downstream free exit, for matching an I-24 MOTION segment.

Pacer controllers implement ``PacerController.command`` and return a desired
speed; the vehicle then tracks that speed with IDM-style bounded
acceleration so the pacer never rear-ends its leader.

References
----------
Treiber, Hennecke, Helbing (2000). Congested traffic states in empirical
    observations and microscopic simulations. Phys. Rev. E 62, 1805.
Sugiyama et al. (2008). Traffic jams without bottlenecks. New J. Phys. 10.
Stern et al. (2018). Dissipation of stop-and-go waves via control of
    autonomous vehicles: Field experiments. Transp. Res. C 89, 205-221.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import numpy as np


# ---------------------------------------------------------------------------
# IDM parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IDMParams:
    """Intelligent Driver Model parameters (SI units).

    Defaults follow Treiber's freeway calibration. ``v0`` is overridden per
    vehicle when heterogeneous desired speeds are drawn.
    """

    v0: float = 30.0  # desired speed [m/s]  (~67 mph)
    T: float = 1.5  # safe time headway [s]
    a: float = 1.0  # max acceleration [m/s^2]
    b: float = 2.0  # comfortable deceleration [m/s^2]
    s0: float = 2.0  # minimum gap [m]
    delta: float = 4.0  # acceleration exponent
    length: float = 5.0  # vehicle length [m]


def idm_acceleration(
    v: np.ndarray,
    gap: np.ndarray,
    dv: np.ndarray,
    v0: np.ndarray,
    T: np.ndarray,
    a: float,
    b: float,
    s0: float,
    delta: float,
) -> np.ndarray:
    """Vectorised IDM acceleration.

    Parameters
    ----------
    v : own speed
    gap : bumper-to-bumper gap to leader (must be > 0)
    dv : approach rate ``v - v_leader`` (positive when closing)
    v0, T : per-vehicle desired speed and time headway
    """
    gap = np.maximum(gap, 0.1)
    s_star = s0 + v * T + v * dv / (2.0 * np.sqrt(a * b))
    s_star = np.maximum(s_star, s0)
    free = 1.0 - (v / v0) ** delta
    interaction = (s_star / gap) ** 2
    return a * (free - interaction)


# ---------------------------------------------------------------------------
# Pacer controllers
# ---------------------------------------------------------------------------


class PacerController(Protocol):
    """A pacer policy maps local observations to a commanded speed."""

    def command(
        self,
        t: float,
        v: float,
        gap: float,
        v_leader: float,
        v_free: float,
    ) -> float:
        """Return desired speed [m/s] for this step."""
        ...

    def reset(self) -> None: ...


@dataclass
class FollowerStopperController:
    """Stern et al. (2018) FollowerStopper, simplified.

    Tracks a target speed ``u`` but caps the command by three concentric
    safety envelopes (gap thresholds grow quadratically with approach
    rate). Between envelopes the command blends linearly from 0 to ``u``.

    ``u`` is a slowly adapted estimate of the local mean speed so the pacer
    drives at the average of the wave rather than its peaks and troughs.
    """

    dx_1: float = 4.5
    dx_2: float = 5.25
    dx_3: float = 6.0
    d_1: float = 1.5
    d_2: float = 1.0
    d_3: float = 0.5
    tau: float = 40.0  # adaptation time constant for target speed [s]
    dt: float = 0.1
    u: float = field(default=0.0, init=False)
    _initialised: bool = field(default=False, init=False)

    def reset(self) -> None:
        self.u = 0.0
        self._initialised = False

    def command(
        self, t: float, v: float, gap: float, v_leader: float, v_free: float
    ) -> float:
        if not self._initialised:
            self.u = v
            self._initialised = True
        # Slow adaptation toward leader speed: this is the "drive the mean"
        # behaviour. Fast adaptation reproduces the wave; slow damps it.
        self.u += (self.dt / self.tau) * (v_leader - self.u)
        u = max(0.0, min(self.u, v_free))

        dv = min(v_leader - v, 0.0)  # negative when closing
        q1 = self.dx_1 + max(0.0, dv**2 / (2 * self.d_1))
        q2 = self.dx_2 + max(0.0, dv**2 / (2 * self.d_2))
        q3 = self.dx_3 + max(0.0, dv**2 / (2 * self.d_3))
        v_lead_clip = max(0.0, v_leader)

        if gap <= q1:
            return 0.0
        if gap <= q2:
            return v_lead_clip * (gap - q1) / (q2 - q1)
        if gap <= q3:
            return v_lead_clip + (u - v_lead_clip) * (gap - q2) / (q3 - q2)
        return u


@dataclass
class SmoothedVelocityController:
    """Exponentially smoothed leader-speed tracker with a reduction floor.

    This is the controller the existing ``PacerProfile`` describes: the pacer
    drives a smoothed version of upstream speed and will never command a
    speed below ``(1 - max_speed_reduction) * v_free`` unless the gap forces
    it. ``tau`` is the smoothing time constant in seconds.
    """

    tau: float = 20.0
    max_speed_reduction: float = 0.2
    dt: float = 0.1
    _v_smooth: Optional[float] = field(default=None, init=False)

    def reset(self) -> None:
        self._v_smooth = None

    def command(
        self, t: float, v: float, gap: float, v_leader: float, v_free: float
    ) -> float:
        if self._v_smooth is None:
            self._v_smooth = v
        alpha = self.dt / self.tau
        self._v_smooth += alpha * (v_leader - self._v_smooth)
        floor = (1.0 - self.max_speed_reduction) * v_free
        return float(np.clip(self._v_smooth, min(floor, v_leader), v_free))


# ---------------------------------------------------------------------------
# Ring road
# ---------------------------------------------------------------------------


@dataclass
class RingRoad:
    """Single-lane periodic road with IDM vehicles and optional pacers.

    Parameters
    ----------
    length : ring circumference [m]
    n_vehicles : vehicle count; density = n / length
    params : IDM parameters
    pacer_fraction : fraction of vehicles running ``controller``
    controller_factory : callable returning a fresh controller per pacer
    v0_cv, T_cv : coefficient of variation for heterogeneous v0 and T
    dt : integration step [s]
    seed : RNG seed (controls heterogeneity draw and pacer placement)
    """

    length: float = 230.0
    n_vehicles: int = 22
    params: IDMParams = field(default_factory=IDMParams)
    pacer_fraction: float = 0.0
    controller_factory: Optional[callable] = None
    v0_cv: float = 0.1
    T_cv: float = 0.1
    dt: float = 0.1
    seed: int = 42

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        n, p = self.n_vehicles, self.params
        self.v0 = p.v0 * np.clip(self.rng.normal(1.0, self.v0_cv, n), 0.6, 1.4)
        self.T = p.T * np.clip(self.rng.normal(1.0, self.T_cv, n), 0.6, 1.4)
        n_pacers = int(round(self.pacer_fraction * n))
        self.is_pacer = np.zeros(n, dtype=bool)
        if n_pacers > 0:
            # Evenly spaced pacers: that is the deployment that matters for
            # wave dissipation (one pacer per wave), not random clusters.
            idx = np.linspace(0, n, n_pacers, endpoint=False).astype(int)
            self.is_pacer[idx] = True
        self.controllers: dict[int, PacerController] = {}
        if self.controller_factory is not None:
            for i in np.flatnonzero(self.is_pacer):
                self.controllers[int(i)] = self.controller_factory()
        self.reset()

    # -- state --------------------------------------------------------------

    def reset(self, perturbation: float = 0.0) -> None:
        """Place vehicles uniformly at the equilibrium speed, then perturb.

        ``perturbation`` is a speed kick [m/s] applied to vehicle 0, the
        standard way to seed the Sugiyama instability.
        """
        n = self.n_vehicles
        spacing = self.length / n
        self.x = np.arange(n) * spacing
        v_eq = self.equilibrium_speed(spacing - self.params.length)
        self.v = np.full(n, v_eq)
        self.v[0] = max(0.0, v_eq - perturbation)
        self.t = 0.0
        for c in self.controllers.values():
            c.reset()

    def equilibrium_speed(self, gap: float) -> float:
        """Homogeneous IDM equilibrium speed for a given gap (bisection)."""
        p = self.params
        lo, hi = 0.0, p.v0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            s_star = p.s0 + mid * p.T
            acc = p.a * (1 - (mid / p.v0) ** p.delta - (s_star / gap) ** 2)
            if acc > 0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # -- dynamics -----------------------------------------------------------

    def _gaps(self) -> tuple[np.ndarray, np.ndarray]:
        leader = np.roll(self.x, -1)
        gap = (leader - self.x) % self.length - self.params.length
        v_leader = np.roll(self.v, -1)
        return gap, v_leader

    def step(self) -> None:
        p = self.params
        gap, v_leader = self._gaps()
        dv = self.v - v_leader
        acc = idm_acceleration(
            self.v, gap, dv, self.v0, self.T, p.a, p.b, p.s0, p.delta
        )
        # Pacer override: track commanded speed with bounded acceleration,
        # but never exceed IDM's own (safe) acceleration.
        for i, ctrl in self.controllers.items():
            u = ctrl.command(self.t, self.v[i], gap[i], v_leader[i], self.v0[i])
            track = np.clip((u - self.v[i]) / 1.0, -p.b, p.a)
            acc[i] = min(acc[i], track)
        self.v = np.maximum(self.v + acc * self.dt, 0.0)
        self.x = (self.x + self.v * self.dt) % self.length
        self.t += self.dt

    def run(
        self,
        duration: float,
        perturbation: float = 2.0,
        record_every: float = 1.0,
    ) -> "Trajectories":
        """Integrate for ``duration`` seconds and return recorded trajectories."""
        self.reset(perturbation=perturbation)
        n_steps = int(round(duration / self.dt))
        every = max(1, int(round(record_every / self.dt)))
        times, xs, vs = [], [], []
        for k in range(n_steps + 1):
            if k % every == 0:
                times.append(self.t)
                xs.append(self.x.copy())
                vs.append(self.v.copy())
            if k < n_steps:
                self.step()
        return Trajectories(
            t=np.array(times),
            x=np.array(xs),
            v=np.array(vs),
            is_pacer=self.is_pacer.copy(),
            length=self.length,
            periodic=True,
        )


# ---------------------------------------------------------------------------
# Open road (for MOTION segment matching)
# ---------------------------------------------------------------------------


@dataclass
class OpenRoad:
    """Single-lane open road with Poisson inflow at x=0 and free exit.

    Vehicles are inserted at the upstream boundary when the gap allows.
    A fraction ``pacer_fraction`` of inserted vehicles are pacers. An
    optional ``bottleneck`` tuple ``(x_start, x_end, v0_factor)`` reduces
    desired speed over a stretch to trigger waves at a fixed location.
    """

    length: float = 3000.0
    inflow_vph: float = 1800.0
    params: IDMParams = field(default_factory=IDMParams)
    pacer_fraction: float = 0.0
    controller_factory: Optional[callable] = None
    v0_cv: float = 0.1
    T_cv: float = 0.1
    bottleneck: Optional[tuple[float, float, float]] = None
    dt: float = 0.1
    seed: int = 42

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.reset()

    def reset(self) -> None:
        self.t = 0.0
        self.x = np.empty(0)
        self.v = np.empty(0)
        self.v0 = np.empty(0)
        self.T = np.empty(0)
        self.ids = np.empty(0, dtype=int)
        self.is_pacer = np.empty(0, dtype=bool)
        self.controllers: dict[int, PacerController] = {}
        self._pacer_log: list[int] = []
        self._next_id = 0
        self._next_arrival = self.rng.exponential(3600.0 / self.inflow_vph)
        self.exited: list[dict] = []

    def _try_insert(self) -> None:
        p = self.params
        while self.t >= self._next_arrival:
            v_in = p.v0 * 0.9
            if self.x.size and self.x[-1] - p.length < p.s0 + v_in * p.T:
                return  # blocked; try again next step (arrival is queued)
            self._next_arrival += self.rng.exponential(3600.0 / self.inflow_vph)
            is_p = self.rng.random() < self.pacer_fraction and (
                self.controller_factory is not None
            )
            vid = self._next_id
            self._next_id += 1
            self.x = np.append(self.x, 0.0)
            self.v = np.append(self.v, min(v_in, self.v[-1]) if self.v.size else v_in)
            self.v0 = np.append(
                self.v0, p.v0 * float(np.clip(self.rng.normal(1, self.v0_cv), 0.6, 1.4))
            )
            self.T = np.append(
                self.T, p.T * float(np.clip(self.rng.normal(1, self.T_cv), 0.6, 1.4))
            )
            self.ids = np.append(self.ids, vid)
            self.is_pacer = np.append(self.is_pacer, is_p)
            if is_p:
                self.controllers[vid] = self.controller_factory()
                self._pacer_log.append(vid)

    def step(self) -> None:
        self._try_insert()
        p = self.params
        n = self.x.size
        if n == 0:
            self.t += self.dt
            return
        v0 = self.v0.copy()
        if self.bottleneck is not None:
            xs, xe, f = self.bottleneck
            v0[(self.x >= xs) & (self.x < xe)] *= f
        # Index 0 is the most downstream vehicle (first inserted); leader of
        # vehicle i is i-1. Vehicle 0 has free road ahead.
        gap = np.empty(n)
        v_leader = np.empty(n)
        gap[0] = 1e4
        v_leader[0] = self.v[0]
        gap[1:] = self.x[:-1] - self.x[1:] - p.length
        v_leader[1:] = self.v[:-1]
        dv = self.v - v_leader
        acc = idm_acceleration(self.v, gap, dv, v0, self.T, p.a, p.b, p.s0, p.delta)
        for i in np.flatnonzero(self.is_pacer):
            ctrl = self.controllers[int(self.ids[i])]
            u = ctrl.command(self.t, self.v[i], gap[i], v_leader[i], v0[i])
            track = np.clip((u - self.v[i]) / 1.0, -p.b, p.a)
            acc[i] = min(acc[i], track)
        self.v = np.maximum(self.v + acc * self.dt, 0.0)
        self.x = self.x + self.v * self.dt
        self.t += self.dt
        done = self.x >= self.length
        if done.any():
            for i in np.flatnonzero(done):
                self.exited.append({"id": int(self.ids[i]), "t_exit": self.t})
                self.controllers.pop(int(self.ids[i]), None)
            keep = ~done
            self.x, self.v, self.v0, self.T = (
                self.x[keep], self.v[keep], self.v0[keep], self.T[keep]
            )
            self.ids, self.is_pacer = self.ids[keep], self.is_pacer[keep]

    def run(self, duration: float, record_every: float = 1.0) -> "Trajectories":
        """Integrate and return ragged trajectories padded with NaN."""
        self.reset()
        n_steps = int(round(duration / self.dt))
        every = max(1, int(round(record_every / self.dt)))
        frames: list[tuple[float, np.ndarray, np.ndarray, np.ndarray]] = []
        for k in range(n_steps + 1):
            if k % every == 0:
                frames.append((self.t, self.ids.copy(), self.x.copy(), self.v.copy()))
            if k < n_steps:
                self.step()
        n_ids = self._next_id
        t = np.array([f[0] for f in frames])
        x = np.full((len(frames), n_ids), np.nan)
        v = np.full((len(frames), n_ids), np.nan)
        pacer_flags = np.zeros(n_ids, dtype=bool)
        for row, (_, ids, xs, vs) in enumerate(frames):
            x[row, ids] = xs
            v[row, ids] = vs
        pacer_flags[self._pacer_log] = True
        return Trajectories(t=t, x=x, v=v, is_pacer=pacer_flags, length=self.length, periodic=False)



# ---------------------------------------------------------------------------
# Trajectories + wave statistics
# ---------------------------------------------------------------------------


@dataclass
class Trajectories:
    """Recorded (time x vehicle) positions and speeds."""

    t: np.ndarray
    x: np.ndarray
    v: np.ndarray
    is_pacer: np.ndarray
    length: float
    periodic: bool

    @property
    def n_vehicles(self) -> int:
        return self.x.shape[1]

    def mean_speed(self, after: float = 0.0) -> float:
        m = self.t >= after
        return float(np.nanmean(self.v[m]))

    def speed_std(self, after: float = 0.0) -> float:
        """Std of speed across vehicles and time: the wave-amplitude proxy."""
        m = self.t >= after
        return float(np.nanstd(self.v[m]))

    def throughput_vph(self, x_probe: Optional[float] = None, after: float = 0.0) -> float:
        """Flow past a fixed point, vehicles/hour.

        On a ring the probe defaults to x=0; crossings are counted via wrap.
        """
        m = self.t >= after
        t, x = self.t[m], self.x[m]
        if x_probe is None:
            x_probe = 0.0 if self.periodic else self.length * 0.5
        if self.periodic:
            # Count wrap-arounds past probe: position drops sharply.
            d = np.diff((x - x_probe) % self.length, axis=0)
            crossings = np.sum(d < -self.length / 2)
        else:
            crossings = np.sum(
                (x[:-1] < x_probe) & (x[1:] >= x_probe), where=~np.isnan(x[:-1])
            )
        hours = (t[-1] - t[0]) / 3600.0
        return float(crossings / hours) if hours > 0 else float("nan")

    def edie(self, after: float = 0.0) -> tuple[float, float]:
        """Edie's generalized (flow [veh/h], density [veh/km]) over the window.

        q = total distance travelled / (L*T), k = total time spent / (L*T).
        Robust to trajectory fragmentation, unlike point-crossing counts, as
        long as coverage is spatially uniform. Works on ring and open roads.
        """
        m = self.t >= after
        t, x, v = self.t[m], self.x[m], self.v[m]
        if len(t) < 2:
            return float("nan"), float("nan")
        dt = float(np.median(np.diff(t)))
        ok = np.isfinite(v)
        dist = float(np.nansum(np.where(ok, v, 0.0)) * dt)  # metres
        time_spent = float(ok.sum() * dt)  # vehicle-seconds
        area = self.length * (t[-1] - t[0])  # metre-seconds
        q = dist / area * 3600.0
        k = time_spent / area * 1000.0
        return q, k

    def wave_period(
        self,
        x_probe: Optional[float] = None,
        after: float = 0.0,
        v_threshold: float = 15 * 0.44704,
        smooth_s: float = 30.0,
        min_separation_s: float = 60.0,
        n_bins: int = 100,
    ) -> tuple[int, float]:
        """Count waves passing a fixed point and return (count, median period [s]).

        A wave is a trough in the spatially averaged speed series at
        ``x_probe`` (default mid-road) that drops below ``v_threshold``.
        Same definition is applied to observed and simulated fields so the
        comparison is like-for-like. Returns (0, nan) when fewer than two
        troughs are found.
        """
        from scipy.ndimage import uniform_filter1d
        from scipy.signal import find_peaks

        t, c, g = self.speed_grid(n_bins=n_bins)
        m = t >= after
        t, g = t[m], g[m]
        if len(t) < 3:
            return 0, float("nan")
        if x_probe is None:
            x_probe = 0.5 * self.length
        j = int(np.argmin(np.abs(c - x_probe)))
        s = np.nanmean(g[:, max(0, j - 3): j + 4], axis=1)
        fill = np.nanmean(s) if np.isfinite(s).any() else 0.0
        s = np.where(np.isnan(s), fill, s)
        dt = float(np.median(np.diff(t)))
        s = uniform_filter1d(s, size=max(1, int(round(smooth_s / dt))))
        troughs, _ = find_peaks(
            -s, height=-v_threshold, distance=max(1, int(round(min_separation_s / dt))),
            prominence=1.5,
        )
        if len(troughs) < 2:
            return int(len(troughs)), float("nan")
        return int(len(troughs)), float(np.median(np.diff(t[troughs])))

    def fuel_proxy(self, after: float = 0.0) -> float:
        """Mean absolute acceleration [m/s^2], a standard comfort/fuel proxy."""
        m = self.t >= after
        dt = np.diff(self.t[m])
        acc = np.diff(self.v[m], axis=0) / dt[:, None]
        return float(np.nanmean(np.abs(acc)))

    def speed_grid(self, n_bins: int = 100) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Eulerian speed field: (times, bin_centres, mean speed per cell).

        Produces the time-space diagram used in validation against MOTION's
        per-segment speed grids.
        """
        edges = np.linspace(0, self.length, n_bins + 1)
        grid = np.full((len(self.t), n_bins), np.nan)
        for k in range(len(self.t)):
            xk, vk = self.x[k], self.v[k]
            ok = ~np.isnan(xk)
            idx = np.clip(np.digitize(xk[ok], edges) - 1, 0, n_bins - 1)
            sums = np.bincount(idx, weights=vk[ok], minlength=n_bins)
            cnt = np.bincount(idx, minlength=n_bins)
            with np.errstate(invalid="ignore", divide="ignore"):
                grid[k] = np.where(cnt > 0, sums / np.maximum(cnt, 1), np.nan)
        return self.t, 0.5 * (edges[:-1] + edges[1:]), grid


def estimate_wave_speed(
    traj: Trajectories,
    after: float = 0.0,
    n_bins: int = 200,
    lag: float = 20.0,
    v_threshold: Optional[float] = None,
) -> float:
    """Estimate backward wave propagation speed [km/h] from the speed field.

    Method: threshold the Eulerian speed grid into "jammed" cells, then for
    frame pairs ``lag`` seconds apart find the space shift maximising the
    cross-correlation of the jam indicator. A long lag beats the
    one-bin-per-frame quantisation of consecutive frames. Negative means
    upstream-moving. Returns NaN when there is no jam.
    """
    t, centres, grid = traj.speed_grid(n_bins=n_bins)
    m = t >= after
    t, grid = t[m], grid[m]
    if len(t) < 2:
        return float("nan")
    if v_threshold is None:
        v_threshold = 0.5 * np.nanmean(grid)
    jam = np.nan_to_num((grid < v_threshold).astype(float))
    if jam.sum() < 10:
        return float("nan")
    dt = float(np.median(np.diff(t)))
    k_lag = max(1, int(round(lag / dt)))
    if len(t) <= k_lag:
        return float("nan")
    dx = centres[1] - centres[0]
    max_shift = n_bins // 2
    shifts = []
    for k in range(0, len(t) - k_lag, k_lag):
        a, b = jam[k], jam[k + k_lag]
        if a.sum() == 0 or b.sum() == 0:
            continue
        if traj.periodic:
            scores = [float(np.dot(a, np.roll(b, -s))) for s in range(-max_shift, max_shift + 1)]
        else:
            scores = []
            for s in range(-max_shift, max_shift + 1):
                if s >= 0:
                    scores.append(float(np.dot(a[: n_bins - s], b[s:])))
                else:
                    scores.append(float(np.dot(a[-s:], b[: n_bins + s])))
        shifts.append(int(np.argmax(scores)) - max_shift)
    if not shifts:
        return float("nan")
    speed_ms = float(np.median(shifts)) * dx / (k_lag * dt)
    return speed_ms * 3.6


def estimate_wave_speed_projection(
    traj: Trajectories,
    after: float = 0.0,
    n_bins: int = 100,
    speeds_kmh: Optional[np.ndarray] = None,
) -> float:
    """Wave speed [km/h] by Radon-style projection of the speed field.

    For each candidate propagation speed c, shift every spatial column by
    x / c in time and average across columns; the c that maximises the
    variance of the averaged profile is the speed at which the jam bands
    line up. Continuous in c (no bin/lag quantisation), so it is the
    estimator to use for calibration. Negative = upstream-moving.
    """
    t, centres, grid = traj.speed_grid(n_bins=n_bins)
    m = t >= after
    t, grid = t[m], grid[m]
    if len(t) < 3 or not np.isfinite(grid).any():
        return float("nan")
    fill = np.nanmean(grid)
    g = np.where(np.isfinite(grid), grid, fill)
    if speeds_kmh is None:
        speeds_kmh = np.arange(-40.0, -4.0, 0.25)
    best_c, best_score = float("nan"), -np.inf
    for c in speeds_kmh:
        shift = (centres / 1000.0) / c * 3600.0  # seconds
        prof = np.array([
            np.interp(t + shift[j], t, g[:, j], left=np.nan, right=np.nan)
            for j in range(len(centres))
        ])
        score = float(np.nanvar(np.nanmean(prof, axis=0)))
        if score > best_score:
            best_score, best_c = score, float(c)
    return best_c


def summarize(traj: Trajectories, after: float = 0.0) -> dict[str, float]:
    """Headline wave statistics for a run."""
    q, k = traj.edie(after)
    return {
        "mean_speed_mps": traj.mean_speed(after),
        "speed_std_mps": traj.speed_std(after),
        "throughput_vph": traj.throughput_vph(after=after),
        "edie_flow_vph": q,
        "edie_density_vpkm": k,
        "mean_abs_accel": traj.fuel_proxy(after),
        "wave_speed_kmh": estimate_wave_speed(traj, after=after),
    }
