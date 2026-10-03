# ChargeOpt — Rule-Based EV Fleet Charging & Energy Management

ChargeOpt keeps every scheduled EV ready for departure while moving flexible charging out of expensive tariff windows. It is a **deterministic, rule-based** platform as specified in `ChargeOpt_Final_PRD.pdf`: it never learns from history or makes probabilistic predictions, and every charging decision is explained by the rules (R1–R8, P1–P5) that triggered it.

## Architecture

```
Browser ── nginx (frontend container, :8080) ──┬── /            React SPA (static)
                                                ├── /api/*       FastAPI backend
                                                └── /api/ws      WebSocket live updates
Charge points ── ws /api/ocpp/{id} (OCPP 1.6-J) ┘
FastAPI ── PostgreSQL 16 (btree_gist exclusion constraint prevents charger double-booking)
```

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, Recharts, React-Leaflet (OpenStreetMap), IBM Plex fonts (self-hosted) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, PyJWT, bcrypt, SciPy/HiGHS (LP benchmark) |
| Database | PostgreSQL 16 |
| Real-time | WebSockets (with 30 s polling fallback) |
| Charger integration | OCPP 1.6-J central system + simulated telemetry for non-OCPP chargers |
| Deployment | Docker, Docker Compose |

Backend layout (`backend/app`): `api/routes` (HTTP/WebSocket endpoints), `schemas` (request validation), `models` (ORM), `services/scheduler` (pure deterministic engine, persistence layer, LP benchmark), `services/*` (tariffs, charging sessions, operations events, monitoring/alerts, reports, dashboard, advisory, simulation, OCPP, webhooks, audit, seed), `core` (config, security, RBAC, errors).

## Quick start

Prerequisites: Docker Desktop (or Docker Engine) with Compose v2, ~2 GB RAM for containers.

```bash
cp .env.example .env          # then replace every CHANGE_ME value
docker compose build
docker compose up -d
```

Open **http://localhost:8080** (or `APP_PORT`). On first start with an empty database and `SEED_DEMO_DATA=true`, the backend applies migrations and seeds:

* 3 depots (Peenya, Whitefield, Airport Logistics Hub), 22 chargers (one in fault, one in maintenance, two bidirectional, one OCPP-enabled), 4 tariff periods (off-peak 00–06, shoulder, peak 18–22, late shoulder), contingency provider directory samples;
* a 100-vehicle fleet with trips relative to the current time, including the PRD examples EV-027, EV-061 and EV-042, plus 30 days of **simulated** history;
* six users, one per role, all using `DEMO_USER_PASSWORD`:

| Email | Role |
|---|---|
| `admin@chargeopt.example` | Fleet Administrator |
| `manager@chargeopt.example` | Fleet Manager |
| `ops@chargeopt.example` | Operations Manager |
| `operator@chargeopt.example` | Charging Operator |
| `driver@chargeopt.example` | Driver (assigned to EV-027) |
| `viewer@chargeopt.example` | Viewer / Management |

The seeded scenario starts with the **static baseline** scheduler and the telemetry simulation **paused**, matching the PRD demo plan: review the baseline, compare, activate the rule-based scheduler, then resume the simulation. Administrators can regenerate the scenario at any time from *Rules & settings → Simulation*.

Health: `GET /api/health` (liveness), `GET /api/health/ready` (database). API docs: `http://localhost:8080/api/docs`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | Database password |
| `JWT_SECRET` | yes | ≥ 32 random characters for session tokens |
| `DEMO_USER_PASSWORD` | when seeding | Password for the six demo users (≥ 8 chars) |
| `POSTGRES_DB`, `POSTGRES_USER` | no | Database name/user (default `chargeopt`) |
| `APP_PORT` | no | Public port (default 8080) |
| `FLEET_TIMEZONE`, `CURRENCY` | no | Fleet locale (default `Asia/Kolkata`, `INR`) |
| `COOKIE_SECURE` | no | `true` when served over HTTPS |
| `JWT_EXPIRE_MINUTES` | no | Session lifetime (default 480) |
| `SEED_DEMO_DATA` | no | Seed demo data into an empty database (default `true`) |
| `INTEGRATION_API_KEY` | no | Enables fleet/ERP integration endpoints (≥ 24 chars) |
| `OCPP_BASIC_AUTH_PASSWORD` | no | OCPP security profile 1 password for charge points |
| `SIMULATION_ENABLED`, `SIMULATION_TICK_SECONDS` | no | Simulated charger telemetry (default on, 5 s) |

The backend refuses to start with a clear validation error if `DATABASE_URL` or a valid `JWT_SECRET` is missing. Secrets are never sent to the browser.

## How scheduling works (PRD §11–14, Appendix A)

1. **Identify** vehicles needing charge: current SoC vs the required SoC of the next assignment (operator-defined per trip, or trip energy + safety reserve — configurable). R1 if already met.
2. **Energy** to target, accounting for charging efficiency.
3. **Available time** until departure minus a configurable buffer.
4. **Eligible chargers**: same depot, usable status, connector compatibility, power, charger availability windows, depot load limit.
5. **Priority**: P1 emergency/critical, P2 urgent departure with insufficient SoC, P3 low SoC with a trip, P4 flexible, P5 no trip; ties by earliest departure → lowest SoC → first request (configurable).
6. **Tariff rules**: flexible vehicles (enough slack) take the cheapest contiguous window that still completes before departure (R4); urgent ones take the earliest-finishing window (R2). Readiness is never sacrificed for cost.
7. **Reserve** charger slots — conflicts are prevented in the engine and by a PostgreSQL exclusion constraint (R3).
8. **Recalculate on events**: arrival, departure, SoC change, charger fault (R5), missed slot (R6), trip change, override (R8), configuration/tariff change, plus periodic re-evaluation. Sessions complete at target (R7).

Each run is stored with its trigger, duration, created/kept/superseded reservations, conflicts prevented and at-risk count. Optional approval mode keeps the previous plan in force until a fleet manager approves the new one.

The *Baseline vs rule-based* view computes both plans on the same snapshot, and a HiGHS linear-programming relaxation provides a reference optimum (price per kWh) to measure the rules' optimality gap. These are modelled values from simulated telemetry and configured tariffs, not measured savings.

## AI / ML

None. The PRD defines a non-AI MVP ("No AI/ML models are required"; "It should not use AI/ML prediction"), so no Gemini or ML model is used anywhere. All decisions come from the deterministic rule engine; the LP benchmark is classical mathematical optimisation.

## PRD traceability

| PRD requirement | Implementation |
|---|---|
| FR-01 authentication & roles | Cookie/Bearer JWT auth, bcrypt, login throttling, 6 roles with permission matrix (`core/permissions.py`), UI permission gating |
| FR-02 vehicles create/edit/deactivate | `/api/vehicles` (GET/POST/PUT), Vehicles pages |
| FR-03 trips & departure requirements | `/api/trips` (GET/POST/PUT), CSV import, Trips page |
| FR-04/05 stations, chargers, availability | `/api/stations`, `/api/chargers`, status changes, availability windows, Depots & chargers page |
| FR-06 tariffs | `/api/tariffs` periods with demand charges, coverage check, dynamic price feed (JSON/CSV) |
| FR-07–10 deterministic scheduler | `services/scheduler/engine.py`, `/api/charging-schedules` |
| FR-11 manual override | `/api/charging-schedules/{id}/override`, `/api/charging-schedules/reservations` |
| FR-12 sessions & energy | Charging sessions, per-tariff cost breakdown, energy readings, OCPP meter values |
| FR-13 alerts | All 8 PRD alert types + departed-below-required + manual exceptions; acknowledge/resolve; webhook |
| FR-14 dashboards & downloadable reports | Overview, Schedule, Charging ops, Energy & cost, Reports (13 reports, CSV) |
| FR-15 audit log | Logins, overrides, schedule runs/mode changes, config, charger states, critical exceptions; Audit page |
| §15 real-time monitoring | Overview KPIs, WebSocket + polling |
| §25 security | RBAC, driver isolation, HTTP-only SameSite cookie, CSP & security headers, input validation, SSRF-safe webhooks |
| §26 should-have | Map view, WebSocket updates, CSV export, charger simulation, audit UI |
| §26 can-have / §29 future scope | OCPP 1.6-J, multi-depot scheduling, demand-charge estimates & site load limits, dynamic price feeds, solar availability, battery-storage peak-shaving model, V2G rule evaluation, automated charger control (remote start/stop, power limits), LP optimisation benchmark, fleet/ERP sync and schedule export, webhooks |
| §31 contingency behaviour | `/api/vehicles/{id}/contingency` — depot/public chargers, mobile charging, towing with ETA and cost |
| §28 success metrics | `/api/reports/metrics` and Reports page |

## Key API endpoints

All under `/api`. Interactive documentation at `/api/docs`.

* Auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `GET /auth/session`
* Fleet: `GET/POST /vehicles`, `GET/PUT /vehicles/{id}`, `POST /vehicles/{id}/soc|arrive|depart`, `GET /vehicles/{id}/contingency`, `GET /me/vehicle`, `GET/POST/PUT /drivers`
* Trips: `GET/POST /trips`, `PUT /trips/{id}`, `POST /trips/{id}/complete`, `POST /trips/import`
* Infrastructure: `GET/POST/PUT /stations`, `GET/POST/PUT /chargers`, `POST /chargers/{id}/status`, `POST /chargers/{id}/power-limit`
* Tariffs: `GET/POST/PUT /tariffs`, `GET /tariffs/calendar`, `GET/POST/DELETE /tariffs/price-feed`, `POST /tariffs/price-feed/csv`
* Scheduling: `GET/POST /charging-schedules`, `PUT /charging-schedules/mode`, `GET /charging-schedules/decisions|preview|comparison|runs`, `POST /charging-schedules/runs/{id}/approve|reject`, `POST /charging-schedules/{id}/override`, `POST /charging-schedules/reservations`
* Sessions: `GET/POST /charging-sessions`, `POST /charging-sessions/{id}/stop`, `GET /charging-sessions/{id}/readings`
* Alerts: `GET/POST /alerts`, `POST /alerts/{id}/acknowledge|resolve`
* Reports: `GET /reports`, `GET /reports/energy|cost|readiness|metrics`, `GET /reports/{key}?format=csv`
* Dashboards: `GET /dashboard/overview`, `GET /dashboard/energy`, `GET /v2g/opportunities`
* Admin: `GET/POST/PUT /users`, `GET /roles`, `GET/PUT /config`, `GET /audit-logs`, `GET/POST/DELETE /service-providers`
* Simulation: `GET/PUT /simulation`, `POST /simulation/advance`, `POST /simulation/reset`
* Integrations (header `X-Integration-Key`): `POST /integrations/fleet-sync`, `GET /integrations/schedule-export`
* Real-time: `ws /api/ws` (session cookie), `ws /api/ocpp/{charge-point-id}` (subprotocol `ocpp1.6`)

## Simulation and OCPP

Chargers without a live OCPP connection are simulated: sessions start at their reserved slot when the vehicle is at the depot, draw the reserved power, raise SoC, and vehicles depart/return on their trip times. Everything simulated is labelled in the UI and stored with `source = simulated`. The *Overview* page can pause, resume and fast-forward the simulation clock.

To exercise the OCPP path, run the bundled charge-point emulator (connects as `APH-C04`):

```bash
docker compose --profile ocpp up -d ocpp-charger
```

The central system then sends `RemoteStartTransaction`/`RemoteStopTransaction`, `SetChargingProfile` and `ChangeAvailability`, and records `MeterValues` as `source = ocpp`.

## Testing

```bash
# Backend: 34 tests (engine rules incl. PRD examples, API, RBAC, DB constraint, simulation, OCPP)
docker compose --profile test run --rm backend-tests

# Frontend unit tests and type check
cd frontend && npm ci && npm test && npm run typecheck

# Browser checks (requires the stack running and Chrome installed)
cd e2e && npm ci && DEMO_USER_PASSWORD=... node check.mjs
```

`e2e/demo.mjs` records the captioned product walkthrough to `demo/ChargeOpt_demo.mp4` (+ `.srt`). It resets the demo scenario first.

## Local development

```bash
docker compose up -d db
cd backend && pip install -r requirements-dev.txt
DATABASE_URL=postgresql+psycopg://chargeopt:<password>@localhost:5432/chargeopt JWT_SECRET=<32+ chars> DEMO_USER_PASSWORD=<pw> alembic upgrade head && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev      # proxies /api to localhost:8000
```

(Expose the database port locally with a compose override if needed.)

## Deployment notes

* Terminate TLS in front of the frontend container (load balancer or reverse proxy) and set `COOKIE_SECURE=true`.
* The OCPP endpoint is served at `/api/ocpp/...`; set `OCPP_BASIC_AUTH_PASSWORD` and use `wss://` in production.
* The operations loop (simulation, monitoring, periodic recalculation) uses PostgreSQL advisory locks, so multiple backend replicas do not double-process. WebSocket fan-out is per instance; use sticky sessions when scaling out.
* Migrations run automatically on backend start (`alembic upgrade head`).

## Troubleshooting

* **Backend unhealthy** — `docker compose logs backend`; check `POSTGRES_PASSWORD`/`JWT_SECRET` in `.env`.
* **No users / cannot sign in** — seeding needs `DEMO_USER_PASSWORD` and an empty database; `docker compose down -v` wipes the volume.
* **Map tiles missing** — the map loads OpenStreetMap tiles from the internet; everything else works offline.
* **Nothing is charging** — the demo starts with the simulation paused; resume it on the Overview page.
