"""
Calibrate IDM (T, a) to the I-24 MOTION wave statistics.

For each (T, a) pair: refit the downstream bottleneck on mean speed and
speed std (coverage-invariant), then score the resulting wave speed and
inter-wave period against the observed targets. Runs param sets in
parallel. Writes ``report/data/idm_calibration.csv`` and
``configs/idm_calibrated.yaml`` with the best set.

Targets come from scripts/validate_motion.py on 2022-11-29 WB lane 3:
wave speed -21 km/h (ASM cross-checked), period 4.4 min with the
trough-count method used here for both data and simulation.

Usage::

    .venv/bin/python -m scripts.experiments.calibrate_idm --workers 6
"""

from __future__ import annotations

import argparse
import csv
import itertools
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import yaml

from src.simulation.car_following import IDMParams, OpenRoad, estimate_wave_speed_projection

LENGTH = 3058.0          # m, matches the MOTION window
TARGET_WAVE = -21.0      # km/h
TARGET_PERIOD = 4.4 * 60  # s
TARGET_V = 7.35          # m/s
TARGET_STD = 4.85        # m/s
X_PROBE = (61.2 - 60.0) * 1609.34  # MM 60 in window coordinates


def run_one(args):
    T, a, s0, factor, inflow, duration, warmup, seed = args
    p = IDMParams(v0=30, T=T, a=a, b=1.67, s0=s0, length=5)
    road = OpenRoad(length=LENGTH, inflow_vph=inflow, params=p,
                    bottleneck=(LENGTH * 0.9, LENGTH, factor), seed=seed)
    tr = road.run(duration, record_every=1.0)
    v, sd = tr.mean_speed(after=warmup), tr.speed_std(after=warmup)
    n, per = tr.wave_period(x_probe=X_PROBE, after=warmup)
    w = estimate_wave_speed_projection(tr, after=warmup, n_bins=100)
    q, k = tr.edie(after=warmup)
    fit_err = abs(v - TARGET_V) / TARGET_V + abs(sd - TARGET_STD) / TARGET_STD
    wave_err = (abs(w - TARGET_WAVE) / abs(TARGET_WAVE) if np.isfinite(w) else 2.0) + \
               (abs(per - TARGET_PERIOD) / TARGET_PERIOD if np.isfinite(per) else 2.0)
    return dict(T=T, a=a, s0=s0, factor=factor, inflow=inflow, seed=seed,
                mean_speed=v, speed_std=sd, wave_kmh=w, n_waves=n, period_s=per,
                flow=q, density=k, fit_err=fit_err, wave_err=wave_err)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--duration", type=float, default=3600)
    ap.add_argument("--warmup", type=float, default=900)
    ap.add_argument("--T", nargs="+", type=float, default=[1.0, 1.2, 1.4, 1.6])
    ap.add_argument("--a", nargs="+", type=float, default=[0.5, 0.73, 1.0])
    ap.add_argument("--s0", nargs="+", type=float, default=[2.0])
    ap.add_argument("--factors", nargs="+", type=float, default=[0.25, 0.35, 0.45])
    ap.add_argument("--inflows", nargs="+", type=float, default=[1500, 1800])
    args = ap.parse_args()

    jobs = [(T, a, s0, f, q, args.duration, args.warmup, 1)
            for T, a, s0, f, q in itertools.product(args.T, args.a, args.s0, args.factors, args.inflows)]
    print(f"{len(jobs)} simulations on {args.workers} workers")
    with Pool(args.workers) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            rows.append(r)
            print(f"[{i}/{len(jobs)}] T={r['T']} a={r['a']} f={r['factor']} q={r['inflow']:.0f} "
                  f"v={r['mean_speed']:.1f} sd={r['speed_std']:.2f} wave={r['wave_kmh']:.1f} "
                  f"per={r['period_s']/60 if np.isfinite(r['period_s']) else float('nan'):.1f}min "
                  f"fit={r['fit_err']:.2f} wave_err={r['wave_err']:.2f}", flush=True)

    Path("report/data").mkdir(parents=True, exist_ok=True)
    with open("report/data/idm_calibration.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    # Per (T, a, s0): best bottleneck by fit_err, then rank by wave_err.
    best_per = {}
    for r in rows:
        key = (r["T"], r["a"], r["s0"])
        if key not in best_per or r["fit_err"] < best_per[key]["fit_err"]:
            best_per[key] = r
    ranked = sorted(best_per.values(), key=lambda r: r["wave_err"] + 0.5 * r["fit_err"])
    print("\nbest bottleneck per IDM set, ranked by wave error (+0.5 fit error):")
    for r in ranked:
        print(f"  T={r['T']} a={r['a']} s0={r['s0']} | f={r['factor']} q={r['inflow']:.0f} | "
              f"v={r['mean_speed']:.1f} sd={r['speed_std']:.2f} wave={r['wave_kmh']:.1f} "
              f"per={r['period_s']/60 if np.isfinite(r['period_s']) else float('nan'):.1f} | "
              f"fit={r['fit_err']:.2f} wave_err={r['wave_err']:.2f}")
    b = ranked[0]
    out = dict(idm=dict(v0=30.0, T=b["T"], a=b["a"], b=1.67, s0=b["s0"], length=5.0),
               bottleneck=dict(start_frac=0.9, end_frac=1.0, v0_factor=b["factor"]),
               inflow_vph=b["inflow"],
               targets=dict(wave_kmh=TARGET_WAVE, period_s=TARGET_PERIOD, mean_speed=TARGET_V, speed_std=TARGET_STD),
               achieved=dict(wave_kmh=float(b["wave_kmh"]), period_s=float(b["period_s"]),
                             mean_speed=float(b["mean_speed"]), speed_std=float(b["speed_std"])),
               source="scripts/experiments/calibrate_idm.py vs I-24 MOTION 2022-11-29 WB lane 3")
    Path("configs").mkdir(exist_ok=True)
    with open("configs/idm_calibrated.yaml", "w") as f:
        yaml.safe_dump(out, f, sort_keys=False)
    print("wrote configs/idm_calibrated.yaml")


if __name__ == "__main__":
    main()
