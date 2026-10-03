# 🚀 ChargeOpt: EV Fleet Charging Optimisation Engine

**Problem statement A3 · VGEC x IBM Bob AI Hackathon 2026**

ChargeOpt makes sure every EV in a fleet has enough charge for its next trip, and buys that energy as cheaply as possible without putting the departure at risk.

---

## 👥 Team

| Field | Value |
|---|---|
| **Team Name** | VedaX |
| **Track** | Sustainability |
| **Team Lead** | Shah Ram — shahram6708@gmail.com |
| **Members** | Nisarg, Jamila, Nisha, Shreya |

---

## 🎯 Problem Statement

Most EV fleet depots charge on a fixed routine: a vehicle plugs in when it returns and charges to full, whatever the tariff and whenever its next trip is. Because vehicles mostly come back in the evening, that charging piles up in the peak-tariff window. Meanwhile a van leaving at 06:00 can end up queued behind a car that isn't needed until tomorrow afternoon. Fleet operators pay for this twice: in energy bills and demand charges (30 to 50% extra, according to the A3 brief), and in vehicles that roll out under-charged.

## 💡 Solution

ChargeOpt is a full-stack charging platform with a deterministic scheduling engine at its core. For every vehicle at a depot, it works out the energy needed for the next trip and the time left before departure. It then ranks vehicles by urgency and reserves a specific charger for a specific slot. Vehicles with slack are moved into the cheapest window that still finishes in time, while urgent ones charge immediately. The plan is rebuilt automatically whenever something changes (a vehicle arrives, a charger faults, a trip moves), and each reservation records which rules produced it, so operators can see why.

---

## ✨ Key Features

- **Explainable rule engine:** eight rules (R1 to R8) and five priority levels (P1 to P5). It never trades readiness for a cheaper tariff, and every decision reads as a sentence, e.g. *"R4: shifted to off-peak window — est. 1246.45 INR vs 2537.42 INR if charged immediately. Reserved APH-C01 00:00–01:51 at 120 kW."*
- **No double-booking, ever:** charger conflicts are prevented inside the engine and again by a PostgreSQL `EXCLUDE USING gist` constraint. Depot load limits and charger availability windows are respected too.
- **Event-driven recalculation:** arrivals, departures, SoC changes, charger faults, missed slots, trip edits and manual overrides all trigger a new plan. There is an optional approval step for fleet managers.
- **Proof, not just claims:** a *Baseline vs rule-based* view runs both strategies on the same snapshot, and a HiGHS linear-programming relaxation computes a lower bound on achievable cost, so the rule engine's optimality gap is measured rather than guessed.
- **Operations console:** OCPP 1.6-J charger control (remote start/stop, power limits), live WebSocket updates, eight alert types with acknowledge/resolve, a fleet map, 13 downloadable reports, an audit log and six role-based views, including a mobile driver view.

### Results on the seeded 100-vehicle scenario (modelled, next 24 h)

| Metric | Static baseline | ChargeOpt | Change |
|---|---|---|---|
| Planned energy cost | ₹37,607 | ₹15,602 | **−58.5%** |
| Average price paid | ₹10.79 / kWh | ₹6.61 / kWh | −39% |
| Energy bought in peak window | 82.3% | 21.6% | −60.7 pts |
| Energy drawn from grid | 3,486 kWh | 2,359 kWh | −32% |
| Projected departure readiness (66 departures) | 87.9% | 93.9% | +6.0 pts |
| Peak site load (sum of depots) | 1,245 kW | 1,031 kW | −214 kW |
| Charger conflicts prevented | 0 | 33 | |
| LP lower bound on cost | | ₹15,116 | gap **3.2%** |

These come from simulated telemetry and the configured tariff table (₹5.60 off-peak, ₹8.20 shoulder, ₹11.40 peak), not from a real fleet. The four vehicles still at risk under ChargeOpt are physically infeasible cases, for example a vehicle leaving in 35 minutes that needs 69 kWh. ChargeOpt flags these straight away instead of hiding them.

---

## 🛠️ Tech Stack

| Category | Technologies |
|---|---|
| **Languages** | Python 3.12, TypeScript, SQL |
| **Frameworks** | FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, React 18, Vite, Tailwind CSS, TanStack Query, Recharts, React-Leaflet |
| **IBM Technologies** | IBM Bob (AI development partner during the build), IBM Plex typeface |
| **Databases** | PostgreSQL 16 (with `btree_gist` exclusion constraint) |
| **Other** | Docker Compose, nginx, SciPy/HiGHS, OCPP 1.6-J, WebSockets, pytest, Vitest, Playwright |

---

## 📁 Repository Structure

```
├── src/                      # All source code
│   ├── backend/              # FastAPI API, scheduling engine, OCPP central system, tests
│   ├── frontend/             # React + TypeScript operations console
│   ├── e2e/                  # Playwright browser checks and demo recorder
│   ├── docker-compose.yml    # db, backend, frontend (+ optional OCPP emulator, test runner)
│   └── .env.example          # Every environment variable, with safe placeholder values
├── docs/                     # Written documentation
│   ├── problem-statement.md
│   ├── solution-overview.md
│   ├── architecture.md
│   ├── setup-guide.md
│   └── ChargeOpt_Final_PRD.pdf   # Our product requirements document
├── demo/                     # Demo artifacts
│   ├── screenshots/          # App screenshots
│   ├── demo-video-link.txt   # Link to demo video
│   └── live-demo-url.txt
├── presentation/             # Slide deck
└── submission.yaml           # Structured submission metadata
```

---

## ⚡ How to Run

> These are the same steps as [`docs/setup-guide.md`](docs/setup-guide.md), which also covers verification and troubleshooting.

```bash
# 1. Clone the repo
git clone https://github.com/shahram8708/bob-ai-hackathon-vedax.git
cd bob-ai-hackathon-vedax/src

# 2. Configure environment
cp .env.example .env
# Edit .env and replace the three CHANGE_ME values
# (POSTGRES_PASSWORD, JWT_SECRET, DEMO_USER_PASSWORD)

# 3. Build and start (Docker installs all dependencies inside the images)
docker compose build
docker compose up -d

# 4. Open the app
#    http://localhost:8080  →  sign in as admin@chargeopt.example
#    with the DEMO_USER_PASSWORD you chose
```

The first start runs database migrations and seeds three Bengaluru depots, 22 chargers, four tariff periods and a 100-vehicle fleet with trips. The demo starts on the **static baseline** with the simulation **paused**, so you can see the "before" picture first. Then go to *Schedule → Baseline vs rule-based*, click **Activate rule-based scheduler**, and resume the simulation on the Overview page.

---

## 🖥️ Demo

| Artifact | Link |
|---|---|
| 📹 Demo Video | [See demo/demo-video-link.txt](demo/demo-video-link.txt) |
| 🌐 Live Demo | [See demo/live-demo-url.txt](demo/live-demo-url.txt) |
| 🖼️ Screenshots | [See demo/screenshots/](demo/screenshots/) |
| 📊 Presentation | [See presentation/](presentation/) |

---

## ⚠️ Known Limitations

- **Simulated data.** All energy, cost and readiness figures come from simulated charger telemetry and a configured tariff table. We haven't run ChargeOpt against a real fleet, so we don't claim real-world savings.
- **No forecasting.** Trip energy comes from the trip schedule (entered, imported via CSV, or synced through the integration API). There is no learned route-demand model. We chose this on purpose for transparency, but it means the engine is only as good as the trip data it gets.
- **Battery health is indirect.** ChargeOpt charges to what the next trip needs (plus a reserve) instead of to the maximum, which cut grid energy by 32% in the demo. We don't model degradation, though, so we make no claim about extra battery life.
- **OCPP tested against an emulator.** The OCPP 1.6-J central system works with the bundled charge-point emulator. It hasn't been tried on physical hardware.
- **Single-instance real-time.** WebSocket fan-out is per backend process, so running several replicas needs sticky sessions. The background loop itself is safe to replicate because it uses PostgreSQL advisory locks.
- **Map tiles need internet.** The fleet map loads OpenStreetMap tiles. Everything else works offline.

---

## 🏅 What We're Most Proud Of

The scheduling engine in [`src/backend/app/services/scheduler/engine.py`](src/backend/app/services/scheduler/engine.py). It is a pure function from a fleet snapshot to a plan, with no hidden state and no randomness, so any decision can be reproduced and explained. We also didn't want to simply assert that a heuristic is good enough, so we wrote [`optimizer.py`](src/backend/app/services/scheduler/optimizer.py). It solves the LP relaxation of the same problem with HiGHS and reports how far the rule-based plan is from the theoretical best. On the demo fleet that gap is 3.2%, and the LP solve takes about 0.4 s. The engine has 15 unit tests of its own, including the three worked examples from our PRD (EV-027 shifts to off-peak, EV-061 is left alone, EV-042's emergency overrides the tariff), plus 19 API tests covering RBAC, the database constraint, OCPP and the simulation.

---
