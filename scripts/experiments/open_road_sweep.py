"""
Open-road pacer penetration sweep and effective-capacity fit.

Uses the calibrated IDM parameters and fitted bottleneck from
``configs/idm_calibrated.yaml`` (produced by calibrate_idm.py), sweeps the
pacer fraction, and measures what the macroscopic model needs: throughput
through the bottleneck (Edie flow over the downstream half), speed std,
and mean |accel|. Fits c_eff(p) = 1 + kappa * (1 - exp(-p / p0)) to the
throughput ratio and writes ``configs/ceff_tau40.yaml`` for ``Corridor``.

Simulated trajectories are fully observed, so Edie flow here is unbiased
(unlike v1.0 MOTION data).

Usage::

    .venv/bin/python -m scripts.experiments.open_road_sweep --workers 6 --seeds 3
"""

from __future__ import annotations

import argparse
import csv
import itertools
from multiprocessing import Pool
from pathlib import Path

import matplotlib
import numpy as np
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.simulation.car_following import (  # noqa: E402
    FollowerStopperController, IDMParams, OpenRoad, Trajectories,
)

LENGTH = 3058.0


def load_calibration(path: Path) -> tuple[IDMParams, tuple[float, float, float], float]:
    cfg = yaml.safe_load(open(path))
    i = cfg["idm"]
    params = IDMParams(v0=i["v0"], T=i["T"], a=i["a"], b=i["b"], s0=i["s0"], length=i["length"])
    b = cfg["bottleneck"]
    bn = (LENGTH * b["start_frac"], LENGTH * b["end_frac"], b["v0_factor"])
    return params, bn, float(cfg["inflow_vph"])


def downstream_flow(tr: Trajectories, after: float) -> float:
    """Edie flow over the downstream half of the road (through the bottleneck)."""
    m = tr.t >= after
    t, x, v = tr.t[m], tr.x[m], tr.v[m]
    dt = float(np.median(np.diff(t)))
    half = x >= 0.5 * tr.length
    dist = float(np.nansum(np.where(half & np.isfinite(v), v, 0.0)) * dt)
    area = 0.5 * tr.length * (t[-1] - t[0])
    return dist / area * 3600.0


def run_one(args):
    p, seed, params, bn, inflow, duration, warmup, tau = args
    road = OpenRoad(length=LENGTH, inflow_vph=inflow, params=params,
                    pacer_fraction=p,
                    controller_factory=lambda: FollowerStopperController(tau=tau),
                    bottleneck=bn, seed=seed)
    tr = road.run(duration, record_every=1.0)
    q, k = tr.edie(after=warmup)
    return dict(pacer_fraction=p, seed=seed, n_pacers=int(tr.is_pacer.sum()),
                flow_vph=q, downstream_flow_vph=downstream_flow(tr, warmup),
                density=k, mean_speed=tr.mean_speed(after=warmup),
                speed_std=tr.speed_std(after=warmup),
                mean_abs_accel=tr.fuel_proxy(after=warmup))


def fit_ceff(p: np.ndarray, ratio: np.ndarray) -> tuple[float, float]:
    from scipy.optimize import curve_fit

    f = lambda p, kappa, p0: 1.0 + kappa * (1.0 - np.exp(-p / p0))  # noqa: E731
    (kappa, p0), _ = curve_fit(f, p, ratio, p0=(0.1, 0.05), bounds=([-0.5, 1e-3], [1.0, 1.0]))
    return float(kappa), float(p0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", type=Path, default=Path("configs/idm_calibrated.yaml"))
    ap.add_argument("--fractions", nargs="+", type=float,
                    default=[0.0, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--duration", type=float, default=3600)
    ap.add_argument("--warmup", type=float, default=900)
    ap.add_argument("--tau", type=float, default=40.0)
    ap.add_argument("--tag", default="", help="suffix for output files, e.g. _tau15")
    args = ap.parse_args()
    tag = args.tag

    params, bn, inflow = load_calibration(args.calibration)
    print(f"IDM {params}, bottleneck {bn}, inflow {inflow:.0f}")
    jobs = [(p, s, params, bn, inflow, args.duration, args.warmup, args.tau)
            for p, s in itertools.product(args.fractions, range(1, args.seeds + 1))]
    with Pool(args.workers) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            rows.append(r)
            print(f"[{i}/{len(jobs)}] p={r['pacer_fraction']:.3f} seed={r['seed']} "
                  f"q_down={r['downstream_flow_vph']:.0f} std={r['speed_std']:.2f} "
                  f"acc={r['mean_abs_accel']:.3f}", flush=True)

    Path("report/data").mkdir(parents=True, exist_ok=True)
    with open(f"report/data/open_road_sweep{tag}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    fr = np.array(sorted({r["pacer_fraction"] for r in rows}))
    def agg(key):
        m = np.array([np.mean([r[key] for r in rows if r["pacer_fraction"] == p]) for p in fr])
        s = np.array([np.std([r[key] for r in rows if r["pacer_fraction"] == p]) for p in fr])
        return m, s
    qd, qd_s = agg("downstream_flow_vph")
    ratio = qd / qd[0]
    kappa, p0 = fit_ceff(fr, ratio)
    print(f"\nc_eff(p) = 1 + {kappa:.3f} * (1 - exp(-p / {p0:.3f}))")
    for p, r in zip(fr, ratio):
        print(f"  p={p:.3f}: throughput ratio {r:.3f}, fit {1 + kappa * (1 - np.exp(-p / p0)):.3f}")

    with open(f"configs/ceff{tag}.yaml", "w") as f:
        yaml.safe_dump(dict(pacer_model="micro", ceff_kappa=kappa, ceff_p0=p0, tau=args.tau,
                            baseline_downstream_flow_vph=float(qd[0]),
                            source="scripts/experiments/open_road_sweep.py on configs/idm_calibrated.yaml",
                            fractions=[float(x) for x in fr], throughput_ratio=[float(x) for x in ratio]),
                       f, sort_keys=False)
    print(f"wrote configs/ceff{tag}.yaml")

    Path("report/figures").mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    pp = np.linspace(0, fr.max(), 100)
    axes[0].errorbar(fr * 100, ratio, yerr=qd_s / qd[0], marker="o", capsize=3, label="simulated")
    axes[0].plot(pp * 100, 1 + kappa * (1 - np.exp(-pp / p0)), "--", label=f"fit κ={kappa:.2f}, p₀={p0*100:.1f}%")
    axes[0].set_ylabel("Throughput ratio c_eff(p)"); axes[0].legend()
    for ax, key, lab in zip(axes[1:], ("speed_std", "mean_abs_accel"),
                            ("Speed std (m/s)", "Mean |accel| (m/s²)")):
        m, s = agg(key); ax.errorbar(fr * 100, m, yerr=s, marker="o", capsize=3); ax.set_ylabel(lab)
    for ax in axes:
        ax.set_xlabel("Pacer penetration (%)"); ax.grid(alpha=0.3)
    fig.suptitle(f"Open-road pacer sweep, calibrated IDM, FollowerStopper tau={args.tau:.0f}s (mean ± sd over seeds)")
    fig.tight_layout(); fig.savefig(f"report/figures/open_road_dose_response{tag}.png", dpi=150)
    print(f"wrote report/figures/open_road_dose_response{tag}.png")


if __name__ == "__main__":
    main()
