"""
Simulation-vs-I-24-MOTION validation harness.

Reads an I-24 MOTION v1.x trajectory file (INCEPTION release, JSON array of
per-vehicle records), selects one direction / lane / time window / mile
range, and computes the same wave statistics the car-following layer
produces. Then runs an ``OpenRoad`` simulation matched to the observed
inflow and prints both side by side.

Data: https://i24motion.org/data  (account required)
  I24MOTION_PUBLIC_v1.0/trajectory_data_by_date/<MM-DD-2022>/...
Schema: v1.x_I-24MOTION_data_documentation.pdf
  timestamp [s, unix], x_position [ft, increases eastbound],
  y_position [ft, lane bands], direction (1 EB, -1 WB), length [ft]

Usage::

    .venv/bin/python -m scripts.validate_motion \
        data/motion/INCEPTION.22-11-22.tutorial.json --lane 2 --direction -1

    # restrict to a mile-marker window and a clock window (local time)
    .venv/bin/python -m scripts.validate_motion data/motion/<file>.json \
        --direction -1 --lane 2 --mm-min 59.0 --mm-max 61.5 \
        --t-start 06:30 --t-end 08:30 --tz America/Chicago

Parsing is streaming (ijson) so multi-GB files work; the selected window
is cached to ``<file>.<direction>.lane<lane>.parquet`` for reuse.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Iterator, Optional

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

# Lane bands from the v1.x documentation (|y_position| in feet).
LANE_BANDS = {1: (12, 24), 2: (24, 36), 3: (36, 48), 4: (48, 60)}

UNSTABLE = IDMParams(v0=30, T=1.6, a=0.73, b=1.67, s0=2, length=5)


# ---------------------------------------------------------------- loading


def iter_records(path: Path) -> Iterator[dict]:
    """Stream top-level records from a MOTION JSON array.

    Accepts a ``.json`` file or a ``.zip`` containing one; the zip member is
    streamed without extraction because a day of INCEPTION is ~20+ GB raw.
    """
    import ijson

    if path.suffix.lower() == ".zip":
        import zipfile

        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".json")]
            if len(members) != 1:
                raise ValueError(f"expected one .json in {path}, found {members}")
            with zf.open(members[0]) as f:
                yield from ijson.items(f, "item", use_float=True)
    else:
        with open(path, "rb") as f:
            yield from ijson.items(f, "item", use_float=True)


def local_window_to_unix(
    day: dt.date, t_start: str, t_end: str, tz: str
) -> tuple[float, float]:
    from zoneinfo import ZoneInfo

    z = ZoneInfo(tz)
    h0, m0 = map(int, t_start.split(":"))
    h1, m1 = map(int, t_end.split(":"))
    a = dt.datetime(day.year, day.month, day.day, h0, m0, tzinfo=z).timestamp()
    b = dt.datetime(day.year, day.month, day.day, h1, m1, tzinfo=z).timestamp()
    return a, b


def load_window(
    path: Path,
    direction: int = -1,
    lane: Optional[int] = 2,
    mm_min: Optional[float] = None,
    mm_max: Optional[float] = None,
    t_start: Optional[float] = None,
    t_end: Optional[float] = None,
    min_duration: float = 5.0,
    lane_fraction: float = 0.8,
    cache: bool = True,
) -> pd.DataFrame:
    """Return a long-format table (id, t, x_ft, y_ft) for the selected window.

    A vehicle is assigned to ``lane`` when at least ``lane_fraction`` of its
    samples fall in that lane's band; lane-changers are dropped so the
    single-lane simulation has a like-for-like comparison.
    """
    cache_path = path.parent / f"{path.stem}.dir{direction}.lane{lane}.parquet"
    if cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
    else:
        rows = []
        band = LANE_BANDS.get(lane) if lane else None
        n_seen = n_kept = 0
        for rec in iter_records(path):
            n_seen += 1
            if rec.get("direction") != direction:
                continue
            ts = np.asarray(rec["timestamp"], dtype=float)
            if ts.size < 2 or ts[-1] - ts[0] < min_duration:
                continue
            x = np.asarray(rec["x_position"], dtype=float)
            y = np.abs(np.asarray(rec["y_position"], dtype=float))
            if band is not None:
                inside = (y >= band[0]) & (y < band[1])
                if inside.mean() < lane_fraction:
                    continue
            n_kept += 1
            vid = str(rec.get("_id", n_seen))
            rows.append(pd.DataFrame({"id": vid, "t": ts, "x_ft": x, "y_ft": y}))
        if not rows:
            raise ValueError("no trajectories matched direction/lane filter")
        df = pd.concat(rows, ignore_index=True)
        print(f"parsed {n_seen} records, kept {n_kept} in direction {direction} lane {lane}")
        if cache:
            df.to_parquet(cache_path)
    if mm_min is not None:
        df = df[df.x_ft >= mm_min * FEET_PER_MILE]
    if mm_max is not None:
        df = df[df.x_ft <= mm_max * FEET_PER_MILE]
    if t_start is not None:
        df = df[df.t >= t_start]
    if t_end is not None:
        df = df[df.t <= t_end]
    if df.empty:
        raise ValueError("no rows after mile/time filtering")
    return df


def table_to_trajectories(
    df: pd.DataFrame, direction: int, resample_s: float = 1.0
) -> Trajectories:
    """Resample to a regular grid and re-base x so travel is in +x from 0."""
    x_m = df.x_ft.to_numpy() * FT_TO_M
    x_rel = (x_m - x_m.min()) if direction > 0 else (x_m.max() - x_m)
    t_rel = df.t.to_numpy() - df.t.min()
    length = float(x_rel.max())
    ids, uniq = pd.factorize(df.id)
    n_ids = len(uniq)
    grid_t = np.arange(0.0, t_rel.max() + resample_s, resample_s)
    X = np.full((len(grid_t), n_ids), np.nan)
    V = np.full((len(grid_t), n_ids), np.nan)
    for vid in range(n_ids):
        m = ids == vid
        tt, xx = t_rel[m], x_rel[m]
        o = np.argsort(tt)
        tt, xx = tt[o], xx[o]
        if tt[-1] - tt[0] < 2 * resample_s:
            continue
        inside = (grid_t >= tt[0]) & (grid_t <= tt[-1])
        xi = np.interp(grid_t[inside], tt, xx)
        X[inside, vid] = xi
        V[inside, vid] = np.gradient(xi, resample_s) if xi.size > 1 else np.nan
    return Trajectories(
        t=grid_t, x=X, v=V, is_pacer=np.zeros(n_ids, dtype=bool),
        length=length, periodic=False,
    )


# ---------------------------------------------------------------- compare


def matched_simulation(
    obs: Trajectories,
    pacer_fraction: float = 0.0,
    bottleneck: Optional[tuple[float, float, float]] = None,
    seed: int = 1,
    params: IDMParams = UNSTABLE,
) -> Trajectories:
    """OpenRoad with the same length, duration, and upstream inflow as ``obs``."""
    inflow = obs.throughput_vph(x_probe=min(100.0, obs.length * 0.1))
    road = OpenRoad(
        length=obs.length, inflow_vph=inflow, params=params,
        pacer_fraction=pacer_fraction,
        controller_factory=lambda: FollowerStopperController(tau=40),
        bottleneck=bottleneck, seed=seed,
    )
    return road.run(float(obs.t[-1]), record_every=float(np.median(np.diff(obs.t))))


def fit_bottleneck(
    obs: Trajectories,
    factors=(0.15, 0.25, 0.35),
    inflows=(1200.0, 1500.0, 1800.0, 2100.0),
    fit_duration: float = 3600.0,
    warmup: float = 900.0,
    seed: int = 1,
    verbose: bool = True,
) -> tuple[tuple[float, float, float], float, list[dict]]:
    """Grid-search a downstream bottleneck so the open road matches MOTION.

    The observed window sits inside a congested region whose cause is
    downstream of it, so the bottleneck is placed over the last 10% of the
    road. Objective uses only coverage-invariant statistics (mean speed and
    speed std): v1.0 fragmentation biases absolute flow and density low by
    an unknown coverage factor, so Edie q and k cannot be matched directly.
    Returns (bottleneck, inflow_vph, rows).
    """
    v_obs, s_obs = obs.mean_speed(), obs.speed_std()
    xs, xe = obs.length * 0.9, obs.length
    rows, best, best_err = [], None, np.inf
    for f in factors:
        for inflow in inflows:
            road = OpenRoad(length=obs.length, inflow_vph=inflow, params=UNSTABLE,
                            bottleneck=(xs, xe, f), seed=seed)
            tr = road.run(fit_duration, record_every=1.0)
            v, sd = tr.mean_speed(after=warmup), tr.speed_std(after=warmup)
            q, k = tr.edie(after=warmup)
            err = abs(v - v_obs) / v_obs + abs(sd - s_obs) / s_obs
            rows.append(dict(factor=f, inflow=inflow, density=k, flow=q,
                             mean_speed=v, speed_std=sd, err=err))
            if verbose:
                print(f"  f={f:.2f} inflow={inflow:.0f} -> v={v:.1f} (obs {v_obs:.1f}) "
                      f"std={sd:.2f} (obs {s_obs:.2f}) q={q:.0f} k={k:.1f} err={err:.3f}")
            if err < best_err:
                best_err, best = err, ((xs, xe, f), inflow)
    return best[0], best[1], rows


def plot_side_by_side(obs: Trajectories, sim: Trajectories, out: Path, title_obs: str,
                      sim_title: str = "IDM open road, fitted bottleneck") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, tr, title in zip(axes, (obs, sim), (title_obs, sim_title)):
        for i in range(tr.n_vehicles):
            ok = ~np.isnan(tr.x[:, i])
            if ok.sum() < 2:
                continue
            ax.scatter(tr.t[ok] / 60, tr.x[ok, i] / 1000, c=tr.v[ok, i] * 2.237,
                       cmap="RdYlGn", vmin=0, vmax=70, s=0.3, linewidths=0)
        ax.set_title(title)
        ax.set_xlabel("Time (min)")
    axes[0].set_ylabel("Distance along travel direction (km)")
    sm = plt.cm.ScalarMappable(cmap="RdYlGn", norm=plt.Normalize(0, 70))
    fig.colorbar(sm, ax=axes, label="Speed (mph)", fraction=0.03)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def ks_speed(a: Trajectories, b: Trajectories) -> float:
    from scipy.stats import ks_2samp

    va, vb = a.v[~np.isnan(a.v)], b.v[~np.isnan(b.v)]
    return float(ks_2samp(va, vb).statistic)


def compare(obs: Trajectories, sim: Trajectories, warmup: float = 0.0) -> pd.DataFrame:
    so, ss = summarize(obs, after=warmup), summarize(sim, after=warmup)
    df = pd.DataFrame({k: (so[k], ss[k]) for k in so}, index=["MOTION", "simulation"]).T
    df["rel_error"] = (df["simulation"] - df["MOTION"]) / df["MOTION"].abs()
    df.loc["ks_speed"] = [np.nan, np.nan, ks_speed(obs, sim)]
    return df


def plot_timespace(obs: Trajectories, out: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    for i in range(obs.n_vehicles):
        ok = ~np.isnan(obs.x[:, i])
        if ok.sum() < 2:
            continue
        ax.scatter(obs.t[ok] / 60, obs.x[ok, i] / 1000, c=obs.v[ok, i] * 2.237,
                   cmap="RdYlGn", vmin=0, vmax=70, s=0.4, linewidths=0)
    sm = plt.cm.ScalarMappable(cmap="RdYlGn", norm=plt.Normalize(0, 70))
    fig.colorbar(sm, ax=ax, label="Speed (mph)")
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("Distance along travel direction (km)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--direction", type=int, default=-1, help="-1 westbound, 1 eastbound")
    ap.add_argument("--lane", type=int, default=2, help="1..4 per doc bands; 0 = all lanes")
    ap.add_argument("--mm-min", type=float, help="mile marker lower bound")
    ap.add_argument("--mm-max", type=float, help="mile marker upper bound")
    ap.add_argument("--t-start", help="HH:MM local, requires --date")
    ap.add_argument("--t-end", help="HH:MM local, requires --date")
    ap.add_argument("--date", help="YYYY-MM-DD of the file")
    ap.add_argument("--tz", default="America/Chicago")
    ap.add_argument("--resample", type=float, default=1.0)
    ap.add_argument("--warmup", type=float, default=0.0)
    ap.add_argument("--pacer-fraction", type=float, default=0.0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--plot", type=Path, help="write MOTION time-space PNG here")
    ap.add_argument("--fit", action="store_true", help="grid-fit a downstream bottleneck")
    ap.add_argument("--idm-config", type=Path,
                    help="use IDM params + bottleneck + inflow from configs/idm_calibrated.yaml")
    ap.add_argument("--compare-plot", type=Path, help="side-by-side MOTION vs sim PNG")
    args = ap.parse_args()

    t0 = t1 = None
    if args.t_start and args.t_end:
        if not args.date:
            raise SystemExit("--t-start/--t-end need --date")
        t0, t1 = local_window_to_unix(
            dt.date.fromisoformat(args.date), args.t_start, args.t_end, args.tz
        )

    df = load_window(
        args.path, direction=args.direction, lane=args.lane or None,
        mm_min=args.mm_min, mm_max=args.mm_max, t_start=t0, t_end=t1,
        cache=not args.no_cache,
    )
    obs = table_to_trajectories(df, args.direction, resample_s=args.resample)
    start = dt.datetime.fromtimestamp(df.t.min(), dt.timezone.utc)
    print(f"window: {obs.n_vehicles} vehicles, {obs.length:.0f} m, "
          f"{obs.t[-1]/60:.1f} min starting {start:%Y-%m-%d %H:%M} UTC")
    print("observed:", {k: round(v, 2) for k, v in summarize(obs, after=args.warmup).items()})
    if args.plot:
        plot_timespace(obs, args.plot, f"I-24 MOTION {args.path.name}, dir {args.direction}, lane {args.lane}")
        print("wrote", args.plot)

    if args.idm_config:
        import yaml

        cfg = yaml.safe_load(open(args.idm_config))
        i, b = cfg["idm"], cfg["bottleneck"]
        params = IDMParams(v0=i["v0"], T=i["T"], a=i["a"], b=i["b"], s0=i["s0"], length=i["length"])
        bn = (obs.length * b["start_frac"], obs.length * b["end_frac"], b["v0_factor"])
        print(f"calibrated IDM {params}, bottleneck factor {b['v0_factor']}, inflow {cfg['inflow_vph']:.0f}")
        road = OpenRoad(length=obs.length, inflow_vph=float(cfg["inflow_vph"]), params=params,
                        pacer_fraction=args.pacer_fraction,
                        controller_factory=lambda: FollowerStopperController(tau=40),
                        bottleneck=bn, seed=1)
        sim = road.run(float(obs.t[-1]), record_every=1.0)
    elif args.fit:
        print("fitting bottleneck...")
        bn, inflow, _ = fit_bottleneck(obs)
        print(f"best: bottleneck={bn}, inflow={inflow:.0f} vph")
        road = OpenRoad(length=obs.length, inflow_vph=inflow, params=UNSTABLE,
                        pacer_fraction=args.pacer_fraction,
                        controller_factory=lambda: FollowerStopperController(tau=40),
                        bottleneck=bn, seed=1)
        sim = road.run(float(obs.t[-1]), record_every=1.0)
    else:
        sim = matched_simulation(obs, pacer_fraction=args.pacer_fraction)
    print(compare(obs, sim, warmup=args.warmup).round(3).to_string())
    n_o, per_o = obs.wave_period(x_probe=(61.2 - 60.0) * 1609.34, after=args.warmup)
    n_s, per_s = sim.wave_period(x_probe=(61.2 - 60.0) * 1609.34, after=args.warmup)
    print(f"wave period at MM60: MOTION {per_o/60:.1f} min ({n_o} waves), sim {per_s/60:.1f} min ({n_s} waves)")
    if args.compare_plot:
        plot_side_by_side(obs, sim, args.compare_plot,
                          f"I-24 MOTION 2022-11-29 WB lane {args.lane}, MM {args.mm_min}-{args.mm_max}",
                          sim_title="IDM open road, calibrated (T=%.1f, a=%.2f), fitted bottleneck" % (params.T, params.a)
                          if args.idm_config else "IDM open road, fitted bottleneck")
        print("wrote", args.compare_plot)


if __name__ == "__main__":
    main()
