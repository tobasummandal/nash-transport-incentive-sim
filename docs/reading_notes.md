# Reading notes: wave dissipation and micro–macro coupling

These are my notes on the papers the validation work leans on. For each one
I wrote down what it established, the numbers I need to check against, and
where it shows up in the repo. Page references are to the journal versions.

---

## Treiber, Hennecke, Helbing (2000). Congested traffic states in empirical observations and microscopic simulations. *Phys. Rev. E* 62(2), 1805.

**What it is.** The paper that introduced the Intelligent Driver Model.
Acceleration = a[1 − (v/v₀)^δ − (s*/s)²], with desired gap
s* = s₀ + vT + vΔv / (2√(ab)). Six parameters, each with a physical meaning.

**Numbers I'm using.**
- Freeway defaults: v₀ = 120 km/h, T = 1.6 s, a = 0.73 m/s², b = 1.67 m/s², s₀ = 2 m, δ = 4.
- String stability depends mostly on a and T. a ≈ 1.0, T ≈ 1.5 is stable at
  most densities; a = 0.73 goes unstable in the 25–50 veh/km band.
- Jam density ≈ 1/(l + s₀) ≈ 143 veh/km for 5 m cars; outflow from a jam
  ≈ 1800 veh/h/lane.

**Where it lives here.** My `IDMParams` default is the stable set (a=1.0,
T=1.5), which is why my first ring runs never jammed. `UNSTABLE` in the
tests and experiment script is the Treiber set. The I-24 lane capacity in
the BPR model is 2000 vph, within 10% of the IDM jam outflow.

---

## Sugiyama et al. (2008). Traffic jams without bottlenecks: experimental evidence for the physical mechanism of the formation of a jam. *New J. Phys.* 10, 033001.

**What it is.** 22 cars on a 230 m circular track, drivers told to keep a
steady speed. Uniform flow breaks spontaneously into one backward-moving
jam. No bottleneck, no disturbance: the instability is intrinsic.

**Numbers I'm using.**
- Density ≈ 96 veh/km. Jam appears within 1–2 min.
- Jam propagates backward at **≈ 20 km/h**, the same "universal" backward
  wave speed seen on freeways (15–20 km/h).
- Inside the jam, speeds fall to ~0; outside, ~30 km/h.

**Where it lives here.** `RingRoad` is this geometry. My 40 veh/km, 1 km
ring is sparser than Sugiyama's because IDM with freeway v₀ needs lower
density to go unstable. I get −13 km/h on the ring, the low end of the
band; lowering T toward 1.2 s pushes it toward −18.

---

## Stern et al. (2018). Dissipation of stop-and-go waves via control of autonomous vehicles: Field experiments. *Transp. Res. C* 89, 205–221.

**What it is.** Sugiyama's ring with 20–22 human-driven cars plus one
autonomous vehicle. Three controllers: FollowerStopper, PI with saturation,
and a baseline where the AV drives like a human. The AV dissipates the wave
in every trial.

**Numbers I'm using.**
- Velocity standard deviation drops **~5× (≈ 2.4 → 0.5 m/s)** with the AV on.
- Fuel consumption falls **up to 40%**; braking events fall **~98%**.
- Throughput rises ~15% in some trials.
- FollowerStopper: commanded speed u, capped by three gap envelopes
  Δx_k = Δx⁰_k + (Δv⁻)² / (2 d_k), with Δx⁰ = (4.5, 5.25, 6.0) m and
  d = (1.5, 1.0, 0.5) m/s². The target u is a **running average** speed,
  not the leader's instantaneous speed. The averaging is what dissipates.

**Where it lives here.** `FollowerStopperController` uses the published
envelopes and an exponentially adapted target (tau = 40 s). My test
`test_fast_adaptation_fails_to_dissipate` checks the averaging claim: at
tau = 1 s the pacer behaves like a human and the wave survives. My
5.96 → 0.00 m/s drop is stronger than Stern's 5× because IDM humans are
deterministic; I expect a smaller ratio once I add driver noise.

**What it doesn't tell me.** Stern's result is one AV per 22 vehicles on a
ring with one wave. Open freeways have wave trains and a pacer only
affects the wave it's in. The penetration needed on I-24 is the open
question, and my open-road sweep says the answer has a cost: pacers there
trade throughput for smoothness.

---

## Gloudemans et al. (2023). I-24 MOTION: An instrument for freeway traffic science. *Transp. Res. C* 155, 104311.

**What it is.** 276 cameras over 4.2 miles of I-24 southeast of Nashville,
producing lane-level vehicle trajectories at 25 Hz. The validation dataset.

**Numbers I'm using.**
- Four lanes each direction plus an HOV-ish inside lane in places.
- Post-processing (tracking + reconciliation) smooths speeds; wave speeds
  recovered from the data sit in the **14–20 km/h** band.
- AM-peak congestion is westbound (toward downtown), roughly 06:30–09:00.
- Released as per-day JSON with x position along the corridor in feet,
  y position (lane bands), timestamps, direction.

**Where it lives here.** `OpenRoad` exists to be matched against one
westbound lane during an AM-peak window. My comparison targets: backward
wave speed, speed distribution (KS), throughput at a cross-section,
amplitude decay along the corridor. I used the 29 Nov 2022 INCEPTION day,
lane 3, MM 59.3–61.2, and got −21 km/h.

---

## CIRCLES / Lee et al. (2024). Traffic smoothing via 100 AVs on I-24 (MegaVanderTest, Nov 2022).

**What it is.** 100 AV-equipped Nissan Rogues driven in I-24 AM peak over
one week, controllers designed to smooth flow. Measured with I-24 MOTION.

**Numbers I'm using.**
- Penetration ~2–3% of flow in the equipped lane during the test window.
- Reported: measurable reduction in speed variance and fuel consumption
  near AVs; effect on corridor-level travel time small.
- The field result is weaker than the ring-road result, which is the
  direction I'd expect and the thing my open-road layer should reproduce.

**Where it lives here.** This sets the realistic expectation: a few
percent penetration gives local smoothing, not corridor-wide congestion
elimination. My spring paper's 71% was out of line with this, which is
part of why I cut it.

---

## Micro-to-macro coupling: effective capacity

Not a single paper. I'm combining:

- **Daganzo (1994), cell transmission model** — capacity and wave speed
  are the two numbers that define a triangular fundamental diagram.
- **Treiber & Kesting (2013), *Traffic Flow Dynamics*, ch. 8** — string
  instability lowers effective capacity because the outflow from a jam
  (≈1800 vph) is below free-flow capacity (≈2200 vph). The "capacity drop"
  is 10–20%.
- **Stern 2018** — pacers raise throughput on the ring by removing the drop.

**What I did with it.** Ran `OpenRoad` over a pacer-fraction grid on the
MOTION-calibrated road, measured throughput at a downstream section, and
fit c_eff(p) = 1 + κ(1 − e^(−p/p₀)). I inject c_eff(p) into
`Corridor.capacity` in `network.py` so the pacer enters Table 5 through
the same BPR function as everything else. The fitted κ came out negative,
which is the open-road result in one number.

---

## What I still need to read

- Wu, Bayen et al. (2017–2021), Flow framework — RL controllers for wave
  dissipation; relevant if the bandit stretch item happens.
- Kesting, Treiber, Helbing (2010), ACC impact on capacity — the standard
  reference for penetration-vs-capacity curves.
- Treiber & Kesting, ch. 15, calibration and validation of car-following
  models — for matching IDM parameters to MOTION trajectories properly
  rather than by grid search.
