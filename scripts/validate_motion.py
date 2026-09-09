"""
Simulation-vs-I-24-MOTION validation harness.

Computes the same wave statistics from (a) a MOTION trajectory file and
(b) an ``OpenRoad`` simulation calibrated to the same inflow, then reports
them side by side. Column names are configurable because MOTION releases
differ; defaults match the v2 reconciled trajectories.

Usage::

    .venv/bin/python -m scripts.validate_motion data/motion/2022-11-15_wb.parquet \
        --lane 2 --t-start 06:30 --t-end 08:30 --x-min 58.0 --x-max 60.5

Nothing here is run in tests; it needs real data. The ``motion_to_trajectories``
function is the only piece that depends on the file format.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.simulation.car_following import (
    FollowerStopperController,
    IDMParams,
    OpenRoad,
    Trajectories,
    estimate_wave_speed,
    summarize,
)

FEET_PER_MILE = 5280.0
FT_TO_M = 0.3048


def motion_to_trajectories(
    df: pd.DataFrame,
    *,
    id_col: str = "id",
    t_col: str = "timestamp",
    x_col: str = "x_position",
    v_col: str | None = "speed",
    lane_col: str = "lane",
    lane: int | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    x_in_feet: bool = True,
    resample_s: float = 1.0,
) -> Trajectories:
    """Convert a long-format MOTION trajectory table into ``Trajectories``.

    Positions are re-based so the study window starts at x=0 and increases
    in the direction of travel. Speeds are differentiated from position if
    ``v_col`` is None.
    """
    d = df
    if lane is not None:
        d = d[d[lane_col] == lane]
    if t_start is not None:
        d = d[d[t_col] >= t_start]
    if t_end is not None:
        d = d[d[t_col] <= t_end]
    if x_min is not None:
        d = d[d[x_col] >= x_min]
    if x_max is not None:
        d = d[d[x_col] <= x_max]
    if d.empty:
        raise ValueError("no rows after filtering")

    x = d[x_col].to_numpy(dtype=float)
    if x_in_feet:
        x = x * FT_TO_M
    x0 = x.min()
    # Westbound MOTION x decreases with travel; flip if needed.
    direction = np.sign(
        d.groupby(id_col)[x_col].agg(lambda s: s.iloc[-1] - s.iloc[0]).median()
    )
    x_rel = (x - x0) if direction >= 0 else (x.max() - x)
    length = float(x_rel.max())

    t = d[t_col].to_numpy(dtype=float)
    t_rel = t - t.min()
    ids = pd.factorize(d[id_col])[0]
    n_ids = ids.max() + 1

    grid_t = np.arange(0.0, t_rel.max() + resample_s, resample_s)
    X = np.full((len(grid_t), n_ids), np.nan)
    V = np.full((len(grid_t), n_ids), np.nan)
    v_raw = d[v_col].to_numpy(dtype=float) * (FT_TO_M if x_in_feet else 1.0) if v_col else None

    for vid in range(n_ids):
        m = ids == vid
        tt, xx = t_rel[m], x_rel[m]
        order = np.argsort(tt)
        tt, xx = tt[order], xx[order]
        if len(tt) < 2:
            continue
        inside = (grid_t >= tt[0]) & (grid_t <= tt[-1])
        X[inside, vid] = np.interp(grid_t[inside], tt, xx)
        if v_raw is not None:
            V[inside, vid] = np.interp(grid_t[inside], tt, v_raw[m][order])
        else:
            V[inside, vid] = np.gradient(X[inside, vid], resample_s)
    return Trajectories(
        t=grid_t, x=X, v=V, is_pacer=np.zeros(n_ids, dtype=bool),
        length=length, periodic=False,
    )


def observed_inflow_vph(traj: Trajectories, x_probe: float = 50.0) -> float:
    return traj.throughput_vph(x_probe=x_probe)


def matched_simulation(
    traj: Trajectories,
    pacer_fraction: float = 0.0,
    bottleneck: tuple[float, float, float] | None = None,
    seed: int = 1,
    params: IDMParams = IDMParams(v0=30, T=1.6, a=0.73, b=1.67, s0=2, length=5),
) -> Trajectories:
    """Run an OpenRoad with the same length, duration, and inflow as ``traj``."""
    road = OpenRoad(
        length=traj.length,
        inflow_vph=observed_inflow_vph(traj),
        params=params,
        pacer_fraction=pacer_fraction,
        controller_factory=lambda: FollowerStopperController(tau=40),
        bottleneck=bottleneck,
        seed=seed,
    )
    return road.run(float(traj.t[-1]), record_every=float(np.median(np.diff(traj.t))))


def ks_speed(a: Trajectories, b: Trajectories) -> float:
    from scipy.stats import ks_2samp

    va = a.v[~np.isnan(a.v)]
    vb = b.v[~np.isnan(b.v)]
    return float(ks_2samp(va, vb).statistic)


def compare(obs: Trajectories, sim: Trajectories, warmup: float = 0.0) -> pd.DataFrame:
    so, ss = summarize(obs, after=warmup), summarize(sim, after=warmup)
    rows = {k: (so[k], ss[k]) for k in so}
    df = pd.DataFrame(rows, index=["MOTION", "simulation"]).T
    df["rel_error"] = (df["simulation"] - df["MOTION"]) / df["MOTION"].abs()
    df.loc["ks_speed"] = [np.nan, np.nan, ks_speed(obs, sim)]
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--lane", type=int)
    ap.add_argument("--x-min", type=float, help="corridor position, miles or feet per file")
    ap.add_argument("--x-max", type=float)
    ap.add_argument("--t-start", type=float, help="unix seconds")
    ap.add_argument("--t-end", type=float)
    ap.add_argument("--x-col", default="x_position")
    ap.add_argument("--t-col", default="timestamp")
    ap.add_argument("--id-col", default="id")
    ap.add_argument("--v-col", default=None)
    ap.add_argument("--lane-col", default="lane")
    ap.add_argument("--feet", action="store_true", default=True)
    ap.add_argument("--pacer-fraction", type=float, default=0.0)
    args = ap.parse_args()

    df = pd.read_parquet(args.path) if args.path.suffix == ".parquet" else pd.read_csv(args.path)
    obs = motion_to_trajectories(
        df, id_col=args.id_col, t_col=args.t_col, x_col=args.x_col, v_col=args.v_col,
        lane_col=args.lane_col, lane=args.lane, x_min=args.x_min, x_max=args.x_max,
        t_start=args.t_start, t_end=args.t_end, x_in_feet=args.feet,
    )
    print(f"MOTION window: {obs.n_vehicles} vehicles, {obs.length:.0f} m, {obs.t[-1]:.0f} s")
    sim = matched_simulation(obs, pacer_fraction=args.pacer_fraction)
    print(compare(obs, sim).round(3).to_string())
    print("observed wave speed km/h:", round(estimate_wave_speed(obs), 1))


if __name__ == "__main__":
    main()
