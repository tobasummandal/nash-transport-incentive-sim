# Claim triage: my spring 2026 report

Before building anything this semester I went back through my CS 3860 report
and listed every number it claims, then checked each one against the code
that supposedly produced it. This is the result. I use three labels:

- **KEEP** — I can regenerate it from the repo as-is
- **REVALIDATE** — plausible, but I need to regenerate it once the
  car-following layer and the recalibration are in
- **CUT** — I could not reproduce it from the repo, or new work contradicts it

The "Reason" column is what I found when I looked, plus what the October
work has since shown.

## Headline results

| # | Claim (section) | Status | What I found |
|---|---|---|---|
| 1 | 5% pacer enrollment reduces congestion by 71% (abstract, §10.2, Fig. 9) | **CUT** | Fig. 9 came from a standalone 200-vehicle, 120 s flow demo I built separately from the BPR corridor model, and the script that produced it is not in the repo. It was never tied to the main simulation or checked against real I-24 data, so I replaced it. On the ring road one pacer in 40 dissipates the wave completely; on the MOTION-calibrated open road the picture is different (see #3). |
| 2 | Average speed +20.1% with pacers (§10.2) | **CUT** | Same source as #1. Ring-road IDM gives mean speed +3–4%, throughput +3.6%. |
| 3 | Diminishing returns above ~8% enrollment (Fig. 10) | **CUT, replaced** | Open-road sweep on the MOTION-calibrated road: speed variance and braking saturate by ~5%, but throughput falls monotonically (−8 to −13% at 5%). Figure 10's throughput gains have the wrong sign. |
| 4 | Pacer smoothness 0.82 among qualifiers (§10.2) | **REVALIDATE** | This was computed inside `PacerIncentive` on the BPR layer, which generates its own speed samples rather than reading them from a vehicle model. Needs to come from car-following speed traces. |
| 5 | Pacer result invariant to beta_incentive (Table 8) | **KEEP, reword** | True by construction: the BPR pacer effect never goes through mode choice. I should say that instead of calling it robustness. |
| 6 | `PacerProfile.max_speed_reduction = 0.2` is a sensible enrollment parameter | **CUT** | Ring-road test: a controller that respects a 20% speed floor cannot dissipate anything, because the wave's mean speed sits 50%+ below free flow. The parameter needs to be reinterpreted or removed. |
| 7 | Carpool elasticity 0.51, participation 18.3% → 27.6% (§10.3) | **REVALIDATE** | Single method-of-moments beta. Needs the supervised refit and reweighting interval from Phase 3. |
| 8 | Only 42% of agent pairs spatially compatible; peak matching 1.8× (§10.3) | **KEEP** | Follows directly from the synthetic O-D draws and the thresholds in `carpool.py`. Reproducible. I need to state that O-D is synthetic. |
| 9 | Stadium egress: 34% spike flattening, 47→31 min (§10.4) | **KEEP** | BPR-only, scripted in `scripts/experiments/event_egress.py`. Flag as macroscopic. |
| 10 | Transit 50% subsidy: 8.2% → 14.7% share (§10.5) | **REVALIDATE** | Depends on beta_cost / ASC calibration. Re-report with intervals. |
| 11 | Table 5 cross-mechanism comparison | **REVALIDATE** | The pacer row used a hand-set capacity bump. It now uses `c_eff(p)` fitted from the microscopic layer, which changes its sign on travel time. Other rows need calibration intervals. |
| 12 | Combined > sum of parts (31.2% peak shift) | **REVALIDATE** | Follows from #11. |
| 13 | Greedy 71.3% / secretary 41.8% / always-on 54.6% of optimum at $10K (Tables 6, 7) | **KEEP** | `optimization/allocator.py`, tested, five seeds. Independent of pacer physics. |
| 14 | Greedy is (1−1/e) because W is monotone submodular (Prop. 2) | **KEEP** | `verify_submodularity()` over 200 random pairs. It is an empirical check, not a proof, and I should say so. |
| 15 | NP-hardness via Knapsack (Thm. 1) | **KEEP** | Standard reduction. |
| 16 | Five tractable special cases (§7.4) | **KEEP, trim** | Listed, but only the DP one is implemented. Either implement the rest or cut to a one-sentence remark. |
| 17 | Best-response converges, median CV 0.034 (§3.3) | **KEEP** | `equilibrium.py`, tested. |
| 18 | Mixed logit best holdout fit, rho² 0.267 (Table 4) | **REVALIDATE** | The numbers came from a single run of `train_model.py`. Re-run with seeds and report CIs. |
| 19 | "ZCTA demographics enable equity-aware allocation" (§11.2) | **CUT** | I ingested the demographics but never computed an equity metric, and no allocator reads them. Replace with Phase 4 results or drop. |
| 20 | BPR within 10–15% of microsimulation below 1.2× capacity, 30–40% above (§11.1) | **REVALIDATE** | I quoted this from the literature. It is now measurable: compare BPR travel time against `OpenRoad` over a demand sweep. |

## What the car-following layer changed

The weakest claim was the pacer number, so that is where I started. The
ring road gives a cleaner statement:

- On a 1 km ring at 40 veh/km, IDM (a=0.73, T=1.6) produces a stop-and-go
  wave with speeds 0.6–18 m/s moving upstream at −13 km/h, inside the
  published 10–20 km/h band.
- One FollowerStopper pacer (2.5%) dissipates it completely: speed std
  5.96 → 0.00 m/s, mean |accel| 0.47 → 0.00 m/s², throughput +3.6%.
- Dissipation only happens if the pacer adapts slowly (tau ≥ 20 s). A pacer
  that just follows its leader does nothing.
- A pacer that will not drop more than 20% below free flow does nothing.

That last one matters: the incentive I designed last semester would have
paid drivers for behaviour that cannot dissipate waves.

The open road then changed the story again. Calibrated to I-24 MOTION, 5%
pacers cut braking ~80% and speed variance ~45% but reduce throughput
8–13%, the opposite sign from the ring. Details in `progress_2026-10.md`.
