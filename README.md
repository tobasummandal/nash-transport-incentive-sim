# Nashville I-24 Corridor — Incentive Simulation

Agent-based simulation for evaluating incentive mechanisms (carpooling, pacer driving, departure shifting) to reduce congestion on Nashville's I-24 corridor.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│               Next.js Frontend (web/frontend/)                  │
│  Dual corridor viz · synchronized playback · stats comparison   │
├─────────────────────────────────────────────────────────────────┤
│               FastAPI Simulation API (web/sim_api.py)           │
│  POST /api/simulate   POST /api/compare   GET /api/health      │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Agents     │  │  Incentive   │  │  I-24 MOTION Network │  │
│  │  (Commuter,  │◄─┤  Mechanisms  │◄─┤  (BPR congestion,    │  │
│  │   Pacer)     │  │              │  │   pacer smoothing)   │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────────┘  │
│         ▼                                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Event-Driven Simulation Engine              │  │
│  │  Priority queue · BPR travel times · budget allocators   │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Optimization │  │     ML       │  │   dbt + DuckDB       │  │
│  │  Allocators  │  │  Calibration │  │   Data Pipeline      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Incentive Mechanisms

| Mechanism | How it works | Effect |
|-----------|-------------|--------|
| **Carpooling** | Reward per passenger ($2.50 default) | Removes vehicles from corridor |
| **Pacer driving** | Reward per mile ($0.15) for smooth driving | Dampens stop-and-go waves; effect on capacity fitted from the IDM car-following layer |
| **Departure shift** | Reward for moving peak departure to shoulder period | Spreads demand across time |

The pacer's effect is grounded in a microscopic car-following layer (`src/simulation/car_following.py`) validated against [I-24 MOTION](https://i24motion.org) trajectories. On a bottleneck-fed open road, 5% pacer penetration cuts braking by ~80% and speed variance by ~45% but reduces throughput 8–13%; the fitted capacity curve c_eff(p) is what the BPR corridor uses. Figures in [`docs/figures/`](docs/figures/); claim-by-claim audit of the earlier paper in [`docs/claim_triage.md`](docs/claim_triage.md).

## Project Structure

```
├── src/
│   ├── agents/           # Agent models
│   │   ├── base.py       # TravelMode, AgentPreferences, LinearUtilityModel
│   │   ├── commuter.py   # CommuterAgent, population generation
│   │   ├── pacer.py      # PacerAgent, pacing sessions
│   │   └── behavioral.py # Logit, mixed logit, prospect theory, regret models
│   ├── incentives/       # Incentive mechanisms
│   │   ├── base.py       # BaseIncentive, IncentiveConfig, offer/accept/complete
│   │   ├── carpool.py    # CarpoolIncentive, spatial matching
│   │   ├── pacer.py      # PacerIncentive, smoothness verification
│   │   └── temporal.py   # DepartureShiftIncentive, time slot management
│   ├── simulation/       # Core engine
│   │   ├── engine.py     # SimulationEngine (event loop, incentive wiring)
│   │   ├── network.py    # Corridor with BPR congestion + fitted pacer capacity curve
│   │   ├── car_following.py # IDM ring/open road, pacer controllers, wave statistics
│   │   ├── events.py     # Event types and scheduling
│   │   ├── metrics.py    # TripRecord, MetricsCollector
│   │   └── equilibrium.py
│   ├── optimization/     # Budget allocators
│   │   ├── allocator.py  # Always, Greedy, Secretary allocators
│   │   └── complexity.py # Approximation analysis
│   └── ml/
│       └── calibration.py # Hytch behavioral calibration (optional)
├── web/
│   ├── sim_api.py        # FastAPI backend
│   ├── requirements.txt
│   └── frontend/         # Next.js dashboard
│       ├── app/          # Layout, page, globals.css
│       └── components/   # Controls, CorridorViz, StatsBar
├── tests/                # 12 test modules, 321 tests
├── dbt/                  # dbt Core + DuckDB pipeline
├── scripts/              # run_simulation, validate_motion (I-24 MOTION harness), experiments/
├── docs/                 # progress notes, claim triage, reading notes, figures
├── configs/              # YAML simulation configs
├── report/               # LaTeX paper + figures
└── hytch data info/      # Hytch data documentation
```

## Quick Start

### Backend API

```bash
pip install -r requirements.txt
cd web && pip install -r requirements.txt
uvicorn web.sim_api:app --port 8000
```

### Frontend

```bash
cd web/frontend
npm install
npm run dev
```

Open [localhost:3000](http://localhost:3000) — configure parameters in the sidebar, hit Run, and watch both corridors animate side-by-side.

### CLI Simulation

```bash
python -m scripts.run_simulation --config configs/pacer_i24.yaml
```

### Tests

```bash
pytest tests/ -v
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/simulate` | Single simulation run |
| `POST` | `/api/compare` | Baseline vs incentivized comparison (same seed) |

### Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| `n_agents` | 200 | 10–5,000 |
| `duration_hours` | 3.0 | 0.5–8 |
| `carpool_enabled` | true | |
| `carpool_reward_per_passenger` | $2.50 | |
| `pacer_enabled` | true | |
| `pacer_reward_per_mile` | $0.15 | |
| `departure_shift_enabled` | false | |
| `departure_shift_budget` | $2,000 | |
| `allocator` | `always` | `always`, `greedy`, `secretary` |

## Congestion Model

The corridor uses a BPR (Bureau of Public Roads) volume-delay function with instantaneous capacity:

```
congestion_factor = 1 + α × (V/C)^β
```

where V is current vehicle count, C is instantaneous capacity, α=0.83, β=5.5.

Pacers enter through the capacity term. With `pacer_model: micro` (the default in `configs/pacer_i24.yaml`), C is scaled by c_eff(p) = 1 + κ(1 − e^(−p/p₀)) where p is pacer penetration and κ, p₀ come from the open-road sweep in `scripts/experiments/open_road_sweep.py` (`configs/ceff_tau15.yaml`: κ = −0.34, p₀ = 0.156). The older hand-set linear reduction is still available as `pacer_model: linear`.

### Microscopic layer and I-24 MOTION validation

`src/simulation/car_following.py` implements IDM vehicles on a ring road and an open road with pluggable pacer controllers (FollowerStopper after Stern et al. 2018). `scripts/validate_motion.py` streams I-24 MOTION INCEPTION trajectories and compares wave speed, speed distribution, and acceleration against a matched simulation. Calibrated parameters are in `configs/idm_calibrated.yaml`.

```bash
python -m scripts.experiments.ring_road                # ring-road wave dissipation
python -m scripts.validate_motion data/motion/<file>.zip --direction -1 --lane 3 \
    --mm-min 59.3 --mm-max 61.2 --date 2022-11-29 --t-start 06:30 --t-end 08:30 \
    --idm-config configs/idm_calibrated.yaml --compare-plot report/figures/motion_vs_sim.png
python -m scripts.experiments.calibrate_idm            # IDM grid vs MOTION wave statistics
python -m scripts.experiments.open_road_sweep --tau 15 # pacer penetration sweep, writes configs/ceff*.yaml
```

MOTION data is downloaded from https://i24motion.org/data (account required) into `data/motion/`, which is gitignored.

## Key Results

Macroscopic results (200 agents, 3-hour window) were produced with the earlier linear pacer model and are being re-run with the fitted curve; the pacer row below will change sign on travel time. See `docs/claim_triage.md` for which earlier claims survive.

| Scenario | Peak CF | Avg Travel Time | Change |
|----------|---------|----------------|--------|
| No incentives | 2.02x | 4.2 min | — |
| Pacer only (linear model, superseded) | 1.72x | 4.0 min | −6.9% |
| Carpool only | 1.03x | 3.7 min | −12.6% |
| All three | 1.00x | 3.7 min | −12.6% |

Microscopic results against I-24 MOTION (29 Nov 2022, WB lane 3): observed wave speed ≈ −21 km/h; calibrated IDM reproduces −16.5 km/h. Open-road pacer sweep at 5% penetration: braking −80 to −90%, speed std −45%, throughput −8 to −13%. Figures in `docs/figures/`.

## Data Pipeline

The `dbt/` directory contains a dbt Core + DuckDB transformation pipeline:

```bash
cd dbt && dbt build
```

Layers: staging (raw cleaning) → intermediate (feature engineering) → marts (analytics-ready facts/dimensions).
