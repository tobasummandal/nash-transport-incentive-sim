# Claim triage: CS 3860 report (April 2026)

Every quantitative claim in the spring report, with a verdict on whether it
survives into the revised paper. Status codes:

- **KEEP** — supported by code in the repo and reproducible from it
- **REVALIDATE** — plausible, but the number must be regenerated after the
  microscopic layer / recalibration lands
- **CUT** — not supported by anything in the repo, or contradicted by it

Last updated: 2026-10-08.

## Headline results

| # | Claim (section) | Status | Reason |
|---|---|---|---|
| 1 | 5% pacer enrollment reduces congestion by 71% (abstract, §10.2, Fig. 9) | **CUT** | Fig. 9 comes from a 200-vehicle, 120 s demo whose source is not in the repo. Not connected to the BPR model. Ring-road IDM runs (Oct 2026) show a single pacer in 40 dissipates the wave entirely, so the right statement is "complete dissipation on a ring; open-road effect pending MOTION validation". |
| 2 | Average speed +20.1% with pacers (§10.2) | **CUT** | Same source as #1. Ring-road result: mean speed +3–4%, throughput +3.6%. The large number came from an unvalidated demo. |
| 3 | Diminishing returns above ~8% enrollment (Fig. 10) | **REVALIDATE** | Ring road saturates at 2.5% (1 pacer). On an open road the number depends on wave frequency. Re-derive from open-road sweep once MOTION gives a bottleneck profile. |
| 4 | Pacer smoothness 0.82 among qualifiers (§10.2) | **REVALIDATE** | Computed from the BPR-layer `PacerIncentive`, which fabricates speed samples. Must come from car-following speed traces. |
| 5 | Pacer result invariant to beta_incentive (Table 8) | **KEEP, reword** | True by construction: the BPR pacer effect does not go through mode choice. Say that explicitly instead of calling it "robustness". |
| 6 | `PacerProfile.max_speed_reduction = 0.2` is a sensible enrollment parameter | **CUT** | Ring-road test shows a controller that respects a 20% speed floor cannot dissipate anything. Pacers must be allowed to drive at the wave's mean speed, which can be 50%+ below free flow. Parameter needs renaming / reinterpreting. |
| 7 | Carpool elasticity 0.51, participation 18.3% → 27.6% (§10.3) | **REVALIDATE** | Single method-of-moments beta; needs supervised refit + reweighting interval (Phase 3). |
| 8 | Only 42% of agent pairs spatially compatible; peak matching 1.8× (§10.3) | **KEEP** | Pure function of synthetic O-D draws + thresholds in `carpool.py`. Reproducible. State that O-D is synthetic. |
| 9 | Stadium egress: 34% spike flattening, 47→31 min (§10.4) | **KEEP** | BPR-only, scripted in `scripts/experiments/event_egress.py`. Flag that it is macroscopic. |
| 10 | Transit 50% subsidy: 8.2% → 14.7% share (§10.5) | **REVALIDATE** | Depends on beta_cost / ASC calibration; re-report with intervals. |
| 11 | Table 5 cross-mechanism comparison | **REVALIDATE** | Pacer row is BPR with a hand-set capacity bump. Replace with `c_eff(p)` fitted from the microscopic layer. Other rows re-run with calibration intervals. |
| 12 | Combined > sum of parts (31.2% peak shift) | **REVALIDATE** | Follows from #11. |
| 13 | Greedy 71.3% / secretary 41.8% / always-on 54.6% of optimum at $10K (Table 6, 7) | **KEEP** | `optimization/allocator.py`, tested, five seeds. Independent of pacer physics. |
| 14 | Greedy is (1−1/e) because W is monotone submodular (Prop. 2) | **KEEP** | `verify_submodularity()` over 200 random pairs. Note it is empirical verification, not a proof. |
| 15 | NP-hardness via Knapsack (Thm. 1) | **KEEP** | Standard reduction, fine. |
| 16 | Five tractable special cases (§7.4) | **KEEP, trim** | Listed, none implemented except DP. Either implement or move to a one-sentence remark. |
| 17 | Best-response converges, median CV 0.034 (§3.3) | **KEEP** | `equilibrium.py`, tested. |
| 18 | Mixed logit best holdout fit, rho² 0.267 (Table 4) | **REVALIDATE** | Numbers exist but the fitting script that produced them is `train_model.py` with a single run. Re-run with seeds and report CIs. |
| 19 | "ZCTA demographics enable equity-aware allocation" (§11.2) | **CUT** | No equity metric computed, no allocator reads demographics. Replace with Phase 4 results. |
| 20 | BPR within 10–15% of microsimulation below 1.2× capacity, 30–40% above (§11.1) | **REVALIDATE** | Quoted from literature, now measurable: compare BPR travel time to `OpenRoad` travel time over a demand sweep. |

## What the ring-road layer changes about the story

The spring paper's weakest claim was the pacer number. The new layer gives a
cleaner and more defensible one:

- On a 1 km ring at 40 veh/km, IDM (a=0.73, T=1.6) produces a stop-and-go
  wave with speeds 0.6–18 m/s and backward speed −13 km/h, inside the
  published 10–20 km/h band.
- One FollowerStopper pacer (2.5%) fully dissipates it; speed std falls from
  5.96 to 0.00 m/s, mean |accel| from 0.47 to 0.00 m/s², throughput +3.6%.
- The dissipation depends on the pacer adapting slowly (tau ≥ 20 s). A pacer
  that simply follows its leader (tau → 0) does nothing.
- A pacer forbidden from dropping more than 20% below free flow does nothing.

That last point is a result in itself: the incentive design from last
semester would have paid drivers for behaviour that cannot dissipate waves.

## Open items blocked on data

- I-24 MOTION AM-peak segment: needed for open-road validation of wave speed,
  amplitude, dissipation rate.
- Confirm which MOTION release and which lane(s); the car-following layer is
  single-lane so comparisons should use lane-aggregated speed fields.
