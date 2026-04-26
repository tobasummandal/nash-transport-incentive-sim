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
| **Pacer driving** | Reward per mile ($0.15) for smooth driving | Dampens stop-and-go waves (CIRCLES-calibrated) |
| **Departure shift** | Reward for moving peak departure to shoulder period | Spreads demand across time |

The pacer congestion model is calibrated from the [CIRCLES Consortium](https://circles-consortium.github.io/) I-24 field experiment (Nov 2022), where 100 AI-equipped vehicles achieved 9.1% fuel efficiency improvement at 4% penetration rate.

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
│   │   ├── network.py    # Corridor with BPR congestion + pacer smoothing
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
├── tests/                # 10 test modules
├── dbt/                  # dbt Core + DuckDB pipeline
├── scripts/              # CLI tools (run_simulation, experiments, etc.)
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

where V is current vehicle count, C is instantaneous capacity, α=0.83, β=5.5. Active pacers reduce the congestion factor proportional to their penetration rate, calibrated from CIRCLES data (pacer_alpha=2.25, capped at 50% reduction).

## Key Results (200 agents, 3-hour window)

| Scenario | Peak CF | Avg Travel Time | Change |
|----------|---------|----------------|--------|
| No incentives | 2.02x | 4.2 min | — |
| Pacer only | 1.72x | 4.0 min | −6.9% |
| Carpool only | 1.03x | 3.7 min | −12.6% |
| All three | 1.00x | 3.7 min | −12.6% |

## Data Pipeline

The `dbt/` directory contains a dbt Core + DuckDB transformation pipeline:

```bash
cd dbt && dbt build
```

Layers: staging (raw cleaning) → intermediate (feature engineering) → marts (analytics-ready facts/dimensions).
