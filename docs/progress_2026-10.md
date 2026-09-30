# Progress update, October 2026 (month 1 of CS 3861)

Proposal timeline: Weeks 1–3 feedback / triage / data / reading; Weeks 4–8
car-following layer. Status at end of week 4.

## Done

**Claim triage** (`docs/claim_triage.md`). Twenty claims from the spring
report, each marked keep / revalidate / cut. Six cut outright, including the
71% headline and the equity claim. Allocator and equilibrium results keep.

**Reading notes** (`docs/reading_notes.md`). Treiber IDM, Sugiyama ring,
Stern FollowerStopper, I-24 MOTION, CIRCLES, and the effective-capacity
coupling plan. Each with the numbers to validate against.

**Car-following layer** (`src/simulation/car_following.py`, 24 tests).
- IDM with heterogeneous desired speed and headway.
- `RingRoad`: periodic, Sugiyama geometry.
- `OpenRoad`: Poisson inflow, free exit, optional bottleneck. Built for
  matching a MOTION segment.
- Two pacer controllers: `FollowerStopperController` (Stern 2018 envelopes,
  slowly adapted target) and `SmoothedVelocityController` (what last
  semester's `PacerProfile` implied).
- Wave statistics: speed std, throughput, mean |accel|, and a backward
  wave-speed estimator from the Eulerian speed field.

**Ring-road experiment** (`scripts/experiments/ring_road.py`,
`report/figures/ring_timespace.png`, `ring_dose_response.png`).

| Setting | Speed std (m/s) | Mean |accel| (m/s²) | Throughput (vph) | Wave speed (km/h) |
|---|---|---|---|---|
| Baseline, 40 veh on 1 km | 5.96 | 0.47 | 1390 | −13 |
| 1 pacer in 40 (2.5%) | 0.00 | 0.00 | 1440 | no wave |

Three seeds each. The wave speed sits in the published 10–20 km/h band.

**I-24 MOTION validation, first pass** (`scripts/validate_motion.py`,
`report/figures/motion_timespace.png`, `motion_vs_sim.png`).
INCEPTION v1.0, Tuesday 29 Nov 2022 (`63858a2cfb3ff533c12df166__post9`),
westbound lane 3, MM 59.3–61.2 (stops short of the pole-25 gap at 61.4),
06:30–08:30 CST. Streamed from the 20 GB JSON inside the zip; 830,415
records parsed, 67,921 westbound lane-3 fragments kept, 20,248 in the window.

| Quantity, observed | Value |
|---|---|
| Backward wave speed, raw grid estimator | −22 to −25 km/h, stable across settings and both hours |
| Backward wave speed, lab's ASM-smoothed field | −21 to −23 km/h (correlation), −20.5 km/h (projection) |
| Inter-wave period at MM 60 | 4.4 min median, IQR 3.4–5.9 (troughs below 15 mph) |
| Speed std across samples | 5.2 m/s |
| Mean / median speed | 7.6 m/s / 15.8 mph |
| Mean abs acceleration | 0.40 m/s² |

Reference from the group's own wave catalog (`I24-MOTION/wave-analysis`,
Nov 22 2022, lane 3, one week earlier): wave speed median 19.3 km/h,
IQR 17.6–20.0; inter-wave period at MM 60 median 8.5 min, IQR 6.8–11.6.
Three independent wave-speed methods on our window agree at 20–23 km/h,
so the estimator is sound and the ~21 km/h figure is the one to use. The
period gap (4.4 vs 8.5 min) is partly method (point-trough counting splits
waves that their trajectory clustering merges) and partly day; needs the
same method on both days before it means anything. Our time-space plot
reproduces the official `_wb_L003_speed.png` wave train.
See `docs/related_lab_work.md` for which lab tools were used.

One data-handling result worth knowing: v1.0 trajectories in congestion
are short fragments (median 11 s, 0.06 mi), so point-crossing throughput
undercounts by 4–5×. Flow and density are therefore computed with Edie's
generalized definitions over the space-time window, which are
fragment-robust. Added to `Trajectories.edie()` with a ring-road
consistency test.

Coverage check: Edie flow on the window is ~400 vph against a plausible
~1500 vph for a congested lane, so roughly a quarter of vehicle-time is
captured. Absolute flow and density from v1.0 in congestion are therefore
not usable as fit targets; mean speed, speed std, acceleration, and wave
speed are coverage-invariant and are what the comparison uses.

**Matched simulation** (`docs/figures/motion_vs_sim.png`). `OpenRoad` of
the same length and duration, Treiber IDM (a=0.73, T=1.6), downstream
bottleneck over the last 10% grid-fitted on mean speed and speed std.
Best fit: speed factor 0.35, inflow 1500 vph.

| Statistic | MOTION | IDM open road | Rel. error |
|---|---|---|---|
| Mean speed (m/s) | 7.35 | 7.40 | +1% |
| Speed std (m/s) | 4.85 | 4.30 | −11% |
| Mean abs accel (m/s²) | 0.40 | 0.38 | −4% |
| Wave speed (km/h) | −21 (ASM) | −11.0 | −48% |
| Inter-wave period at MM 60 (min) | 4.4 | 2.8 | −36% |
| KS statistic on speeds | | | 0.10 |

Speed level, variance, and acceleration match. Wave speed does not, and
the time-space plot shows why: the simulated wave train is too regular,
too frequent (period ~2 min vs 5–8 min observed), and too slow. IDM's
wave speed is set by (vehicle length + s0) / T, so this is a headway
calibration problem, not a bottleneck problem. That is the next task.
Target: −21 km/h and a 4–8 min period.

**IDM calibration** (`scripts/experiments/calibrate_idm.py`,
`configs/idm_calibrated.yaml`). Grid over T ∈ [0.8, 1.6], a ∈ [0.5, 1.5],
s0 ∈ {1, 2}, each with its own bottleneck refit, scored on wave speed and
period with a continuous projection estimator (the bin-correlation one
quantises at 3.7 km/h and cannot rank headways). Best: T = 1.0 s,
a = 1.0 m/s², s0 = 2 m, bottleneck factor 0.25, inflow 1800 vph.

| Statistic (2 h window, 15 min warmup) | MOTION | Treiber IDM (T=1.6) | Calibrated (T=1.0) |
|---|---|---|---|
| Wave speed (km/h) | −21 | −11 | −16.5 |
| Period at MM 60 (min) | 3.8 | 2.8 | 2.5 |
| Mean speed (m/s) | 7.35 | 7.40 | 5.8 |
| Speed std (m/s) | 4.85 | 4.30 | 5.1 |
| Mean abs accel (m/s²) | 0.40 | 0.38 | 0.47 |
| KS on speeds | | 0.10 | 0.28 |

Calibration closes about half the wave-speed gap at the cost of mean
speed (−21%) and speed-distribution fit (KS 0.28 vs 0.10). Shorter
headways or smaller gaps than this make homogeneous IDM lose its waves
entirely, so the remaining gap needs driver heterogeneity or noise, not
more tuning. Both parameter sets are kept; the sweep below uses the
calibrated one because wave physics is what the pacer acts on.

**Open-road pacer sweep** (`scripts/experiments/open_road_sweep.py`,
`docs/figures/open_road_dose_response.png`, `configs/ceff*.yaml`).
Calibrated road, FollowerStopper pacers at 0–20% penetration, three
seeds, three controller time constants. Throughput is Edie flow over the
downstream half (fully observed in simulation, so unbiased).

| Penetration | Throughput | Speed std | Mean abs accel |
|---|---|---|---|
| 2% | −5 to −7% | −35% | −55 to −65% |
| 5% | −8 to −13% | −45% | −80 to −90% |
| 10% | −13 to −26% | −50% | −90% |

Ranges span tau = 10, 15, 40 s. The direction does not depend on the
controller: on a bottleneck-fed open road, pacers smooth traffic and
reduce throughput, because they hold upstream flow below what the
bottleneck can pass and density rises behind them. This is the opposite
sign from the ring, where the single wave is the only thing limiting
flow. Fitted c_eff(p) = 1 + κ(1 − e^(−p/p₀)) with κ = −0.34, p₀ = 0.156
at tau = 15 (`configs/ceff_tau15.yaml`).

**Macro coupling.** `Corridor` now has `pacer_model = "micro"` which
scales BPR capacity by c_eff(p) (`src/simulation/network.py`,
`tests/test_network_ceff.py`). `configs/pacer_i24.yaml` is switched to
it. The pacer therefore enters Table 5 through the same travel-time
function as every other mechanism, and with the fitted sign it will
raise travel time, not lower it. The pacer's benefit is in braking and
speed variance (fuel, comfort, safety), which the BPR layer does not
price. Table 5 needs a column for that before the comparison is fair.

## Two results worth discussing

1. **Dissipation needs slow adaptation.** A pacer whose target speed
   tracks its leader with time constant 1 s does nothing; at 20 s and
   above it kills the wave. The incentive should reward driving at the
   long-run mean, not "smoothness" measured over short windows.

2. **The 20% speed-reduction cap from last semester makes pacers
   useless.** A controller that will not drop more than 20% below free
   flow cannot reach the wave's mean speed (here ~33% of free flow) and
   leaves the wave untouched. `PacerProfile.max_speed_reduction` has to
   be reinterpreted or removed.

## Not done

- Driver heterogeneity / noise in IDM to close the remaining wave-speed
  gap (−16 vs −21 km/h) and break the perfect periodicity.
- Second day (22 or 30 Nov) and a second lane as replication.
- Re-run Table 5 with the micro pacer model and add a braking /
  speed-variance column so the pacer is scored on what it actually does.
- Controllers designed not to lose throughput (CIRCLES-style), to see
  whether the smoothing-vs-throughput trade is intrinsic or a
  FollowerStopper property.

## Asks

- Whether a single-lane comparison against one MOTION lane is acceptable
  for the first validation pass, or whether lane changing has to be in.
- Whether v1.0 fragmentation is known to bias speed statistics in
  congestion (fragments break more when vehicles are slow and occluded).
