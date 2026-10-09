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

**MOTION harness skeleton** (`scripts/validate_motion.py`). Loads a
trajectory table, re-bases position, resamples to 1 Hz, computes the same
statistics as the simulation, runs a matched `OpenRoad`, prints a
side-by-side table with relative error and a KS statistic on speeds.
Column names are arguments because the file format is unconfirmed.

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

- Open-road dose-response. On a ring with one wave, one pacer is enough.
  Open freeways have wave trains; the penetration question is open and is
  the actual contribution. Needs a bottleneck profile from MOTION to be
  meaningful.
- Micro-to-macro `c_eff(p)` fit. Depends on the open-road sweep.
- Driver noise in IDM. Deterministic IDM gives an unrealistically clean
  0.00 std after dissipation; Stern's field ratio was ~5×.

## Asks

- I-24 MOTION: one or two westbound AM-peak days with a visible
  stop-and-go train. Coordinate convention, lane numbering, which release.
- Whether a single-lane comparison against one MOTION lane is acceptable
  for the first validation pass, or whether lane changing has to be in.
