# Reading notes: wave dissipation and micro–macro coupling

Short notes on the papers the Phase 2 validation depends on. Each entry
says what the paper established, the numbers to check against, and what in
this repo uses it. Written from the published papers; page references are
to the journal versions.

Last updated: 2026-10-08.

---

## Treiber, Hennecke, Helbing (2000). Congested traffic states in empirical observations and microscopic simulations. *Phys. Rev. E* 62(2), 1805.

**What it is.** Introduces the Intelligent Driver Model (IDM).
Acceleration = a[1 − (v/v₀)^δ − (s*/s)²], with desired gap
s* = s₀ + vT + vΔv / (2√(ab)). Six parameters, all with physical meaning.

**Numbers to remember.**
- Freeway defaults: v₀ = 120 km/h, T = 1.6 s, a = 0.73 m/s², b = 1.67 m/s², s₀ = 2 m, δ = 4.
- Linear string stability depends mostly on a and T. a ≈ 1.0, T ≈ 1.5 is
  stable at most densities; a = 0.73 is unstable in the 25–50 veh/km band.
- Jam density ≈ 1/(l + s₀) ≈ 143 veh/km for 5 m cars; outflow from jam
  ≈ 1800 veh/h/lane.

**Used here.** `IDMParams` default is the stable set (a=1.0, T=1.5), which
is why the first ring runs never jammed. `UNSTABLE` in the tests and
experiment script is the Treiber set. For I-24 the lane capacity in the BPR
model is 2000 vph, matching the IDM jam outflow to within 10%.

---

## Sugiyama et al. (2008). Traffic jams without bottlenecks: experimental evidence for the physical mechanism of the formation of a jam. *New J. Phys.* 10, 033001.

**What it is.** 22 cars on a 230 m circular track, drivers told to keep a
steady speed. Uniform flow breaks spontaneously into one backward-moving
jam. No bottleneck, no disturbance: the instability is intrinsic.

**Numbers to remember.**
- Density ≈ 96 veh/km. Jam appears within ~1–2 min.
- Jam propagates backward at **≈ 20 km/h**, consistent with the
  "universal" backward wave speed seen on freeways (15–20 km/h).
- Inside the jam, speeds fall to ~0; outside, ~30 km/h.

**Used here.** `RingRoad` is this geometry. Our 40 veh/km, 1 km ring is
sparser than Sugiyama's because IDM with freeway v₀ needs lower density to
be unstable. Wave speed −13 km/h is at the low end of the band;
expect closer to −18 when T is lowered toward 1.2 s.

---

## Stern et al. (2018). Dissipation of stop-and-go waves via control of autonomous vehicles: Field experiments. *Transp. Res. C* 89, 205–221.

**What it is.** Sugiyama's ring with 20–22 human-driven cars plus one
autonomous vehicle. Three controllers tested: FollowerStopper, PI with
saturation, and a baseline where the AV behaves like a human. The AV
dissipates the wave in every trial.

**Numbers to remember.**
- Velocity standard deviation drops **~5× (≈ 2.4 → 0.5 m/s)** with the AV active.
- Fuel consumption falls **up to 40%**; braking events fall **~98%**.
- Throughput rises ~15% in some trials (jam outflow vs free flow).
- FollowerStopper: commanded speed u, capped by three gap envelopes
  Δx_k = Δx⁰_k + (Δv⁻)² / (2 d_k), with Δx⁰ = (4.5, 5.25, 6.0) m and
  d = (1.5, 1.0, 0.5) m/s². Target u is the **running average** speed, not
  the leader's instantaneous speed. That averaging is what dissipates.

**Used here.** `FollowerStopperController` with the published envelopes and
an exponentially adapted target (tau = 40 s). The test
`test_fast_adaptation_fails_to_dissipate` checks the averaging claim: at
tau = 1 s the pacer is a human and the wave survives. Our 5.96 → 0.00 m/s
drop is stronger than Stern's 5× because IDM humans are deterministic;
expect a smaller ratio once driver noise is added.

**Gap for us.** Stern's result is one AV per 22 vehicles on a ring with
one wave. Open freeways have many waves and a pacer only affects the wave
it is in. Penetration needed on I-24 is an open question; this is the
contribution.

---

## Gloudemans et al. (2023). I-24 MOTION: An instrument for freeway traffic science. *Transp. Res. C* 155, 104311.

**What it is.** 276 cameras over 4.2 miles of I-24 southeast of
Nashville, producing lane-level vehicle trajectories at 25 Hz. The target
validation dataset.

**Numbers to remember.**
- Four lanes each direction plus HOV-ish inside lane in places.
- Trajectory post-processing (tracking + reconciliation) smooths speeds;
  wave speeds recovered from the data are in the **14–20 km/h** band.
- AM peak congestion is westbound (toward downtown), typically 06:30–09:00.
- Data released as per-day parquet / JSON with x position along the
  corridor, lane, timestamp, speed.

**Used here.** The `OpenRoad` class exists to be matched against one
westbound lane during an AM-peak window. Comparison targets: backward wave
speed, speed distribution (KS), throughput at a fixed cross-section,
amplitude decay along the corridor.

**To ask VECTOR for.** One or two AM-peak days, westbound, with a visible
stop-and-go train. Confirm the coordinate convention (x increases which
direction?) and which release (v1 vs v2 reconciliation).

---

## CIRCLES / Lee et al. (2024). Traffic smoothing via 100 AVs on I-24 (MegaVanderTest, Nov 2022).

**What it is.** 100 AV-equipped Nissan Rogues driven in I-24 AM peak over
one week, controllers designed to smooth flow. Measured with I-24 MOTION.

**Numbers to remember.**
- Penetration ~2–3% of flow in the equipped lane during the test window.
- Reported: measurable reduction in speed variance and fuel consumption in
  the vicinity of AVs; effect on corridor-level travel time small.
- The field result is weaker than the ring-road result, which is the
  expected direction and the thing our open-road layer should reproduce.

**Used here.** Sets the realistic expectation: a few percent penetration
gives local smoothing, not corridor-wide congestion elimination. The
spring paper's 71% was out of line with this.

---

## Micro-to-macro coupling: effective capacity

Not a single paper; the approach combines:

- **Daganzo (1994), cell transmission model** — capacity and wave speed
  are the two numbers that define a triangular fundamental diagram.
- **Treiber & Kesting (2013), *Traffic Flow Dynamics*, ch. 8** —
  string instability lowers effective capacity because the outflow from a
  jam (≈1800 vph) is below free-flow capacity (≈2200 vph). The "capacity
  drop" is 10–20%.
- **Stern 2018** — pacers raise throughput by reducing the capacity drop.

**Plan.** Run `OpenRoad` over a (demand × pacer fraction) grid, measure
throughput at a downstream section, fit c_eff(p) = c₀·[1 + κ·(1 − e^{−p/p₀})]
or a simple piecewise-linear version. Inject c_eff(p) into
`Corridor.capacity` in `network.py` so the pacer mechanism enters Table 5
through the same BPR function as everything else. Error bars from seeds.

---

## What to read next (not yet done)

- Wu, Bayen et al. (2017–2021), Flow framework — RL controllers for wave
  dissipation; useful if the bandit stretch item happens.
- Kesting, Treiber, Helbing (2010), ACC impact on capacity — the standard
  reference for penetration vs capacity gain curves.
- Treiber & Kesting, ch. 15, "Calibration and validation of car-following
  models" — for matching IDM parameters to MOTION trajectories.
