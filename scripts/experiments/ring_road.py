"""
Ring-road wave dissipation experiment.

Reproduces the Sugiyama (2008) / Stern (2018) setup with IDM vehicles:
a dense ring develops a stop-and-go wave; a small fraction of pacer
vehicles running a FollowerStopper controller dissipates it.

Produces two figures in ``report/figures/`` and a CSV of the dose-response
sweep in ``report/data/``:

* ``ring_timespace.png``  - trajectories, baseline vs 1 pacer in 40
* ``ring_dose_response.png`` - wave amplitude / throughput / accel vs pacer %

Usage::

    .venv/bin/python -m scripts.experiments.ring_road
    .venv/bin/python -m scripts.experiments.ring_road --seeds 5 --duration 2400
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.simulation.car_following import (  # noqa: E402
    FollowerStopperController,
    IDMParams,
    RingRoad,
    SmoothedVelocityController,
    Trajectories,
    summarize,
)

UNSTABLE = IDMParams(v0=30, T=1.6, a=0.73, b=1.67, s0=2, length=5)
N_VEH, LENGTH = 40, 1000.0
FIG_DIR = Path("report/figures")
DATA_DIR = Path("report/data")


def run_ring(pacer_fraction: float, seed: int, duration: float, tau: float,
             controller: str = "fs") -> Trajectories:
    if controller == "fs":
        factory = lambda: FollowerStopperController(tau=tau)  # noqa: E731
    else:
        factory = lambda: SmoothedVelocityController(tau=tau)  # noqa: E731
    road = RingRoad(
        n_vehicles=N_VEH, length=LENGTH, params=UNSTABLE,
        pacer_fraction=pacer_fraction, controller_factory=factory,
        v0_cv=0.05, T_cv=0.05, seed=seed,
    )
    return road.run(duration, perturbation=3.0, record_every=0.5)


def plot_timespace(base: Trajectories, paced: Trajectories, out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    vmin, vmax = 0, UNSTABLE.v0 * 0.7
    for ax, tr, title in zip(
        axes, (base, paced),
        ("Baseline: 40 IDM vehicles, 1 km ring",
         f"With 1 pacer ({int(paced.is_pacer.sum())} of {paced.n_vehicles}, FollowerStopper)"),
    ):
        # Draw each trajectory as a scatter coloured by speed; break at wrap.
        for i in range(tr.n_vehicles):
            x, v = tr.x[:, i], tr.v[:, i]
            lw = 1.6 if tr.is_pacer[i] else 0.5
            ax.scatter(x, tr.t, c=v, s=lw, cmap="RdYlGn", vmin=vmin, vmax=vmax,
                       marker="." if not tr.is_pacer[i] else "s", linewidths=0)
        ax.set_title(title)
        ax.set_xlabel("Position on ring (m)")
        ax.set_xlim(0, LENGTH)
    axes[0].set_ylabel("Time (s)")
    sm = plt.cm.ScalarMappable(cmap="RdYlGn", norm=plt.Normalize(vmin, vmax))
    fig.colorbar(sm, ax=axes, label="Speed (m/s)", fraction=0.025)
    fig.suptitle("Stop-and-go wave on a ring road and its dissipation by one pacer")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def dose_response(fractions, seeds, duration, tau, warmup):
    rows = []
    for pf in fractions:
        for seed in seeds:
            tr = run_ring(pf, seed, duration, tau)
            s = summarize(tr, after=warmup)
            s.update(pacer_fraction=pf, n_pacers=int(tr.is_pacer.sum()), seed=seed)
            rows.append(s)
            print(f"p={pf:.3f} seed={seed} std={s['speed_std_mps']:.2f} "
                  f"thr={s['throughput_vph']:.0f} acc={s['mean_abs_accel']:.3f} "
                  f"wave={s['wave_speed_kmh']:.1f}")
    return rows


def plot_dose_response(rows, out: Path) -> None:
    fracs = sorted({r["pacer_fraction"] for r in rows})
    def agg(key):
        m = [np.mean([r[key] for r in rows if r["pacer_fraction"] == f]) for f in fracs]
        s = [np.std([r[key] for r in rows if r["pacer_fraction"] == f]) for f in fracs]
        return np.array(m), np.array(s)
    pct = np.array(fracs) * 100
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, key, label in zip(
        axes,
        ("speed_std_mps", "throughput_vph", "mean_abs_accel"),
        ("Speed std across vehicles (m/s)\n= wave amplitude",
         "Throughput (veh/h)", "Mean |accel| (m/s$^2$)\n= fuel / comfort proxy"),
    ):
        m, s = agg(key)
        ax.errorbar(pct, m, yerr=s, marker="o", capsize=3)
        ax.set_xlabel("Pacer penetration (%)")
        ax.set_ylabel(label)
        ax.grid(alpha=0.3)
    fig.suptitle("Ring-road dose-response: effect of pacer penetration (mean ± sd over seeds)")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--duration", type=float, default=2400)
    ap.add_argument("--warmup", type=float, default=1200)
    ap.add_argument("--tau", type=float, default=40.0)
    args = ap.parse_args()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    base = run_ring(0.0, 1, args.duration, args.tau)
    paced = run_ring(1 / N_VEH, 1, args.duration, args.tau)
    print("baseline:", {k: round(v, 2) for k, v in summarize(base, args.warmup).items()})
    print("1 pacer: ", {k: round(v, 2) for k, v in summarize(paced, args.warmup).items()})
    plot_timespace(base, paced, FIG_DIR / "ring_timespace.png")

    fractions = [0.0, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20]
    rows = dose_response(fractions, range(1, args.seeds + 1), args.duration,
                         args.tau, args.warmup)
    with open(DATA_DIR / "ring_dose_response.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    plot_dose_response(rows, FIG_DIR / "ring_dose_response.png")
    print("wrote", FIG_DIR / "ring_timespace.png", FIG_DIR / "ring_dose_response.png")


if __name__ == "__main__":
    main()
