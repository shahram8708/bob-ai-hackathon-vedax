# Setup Guide

> **This file is read by the automated evaluation pipeline. Be precise and complete.**

The whole stack (PostgreSQL, the FastAPI backend and the React frontend behind nginx) runs with Docker Compose. You don't need to install Python, Node.js or PostgreSQL on your machine to run the app. Docker builds everything inside the images.

All commands below are run from the **`src/`** folder of this repository, because that's where `docker-compose.yml` and `.env.example` live.

## Prerequisites

Before you begin, make sure you have the following:

- [ ] **Docker Desktop** (Windows/macOS) or **Docker Engine** (Linux) with the **Compose v2** plugin, i.e. `docker compose version` prints v2.x
- [ ] About **2 GB of free RAM** for the containers and **~3 GB of disk** for the images
- [ ] **Git**
- [ ] Port **8080** free on your machine (or choose another with `APP_PORT`)
- [ ] An internet connection for the first build (to pull base images and packages) and for map tiles on the Fleet map page

Only needed if you want to run the frontend or browser tests outside Docker (optional):

- [ ] Node.js 20+ and npm (the frontend image itself uses Node 22)
- [ ] Google Chrome (used by the Playwright browser checks)

No cloud accounts or API keys are needed. ChargeOpt doesn't call any external AI or paid service.

## Environment Variables

Copy `.env.example` to `.env` inside `src/`:

```bash
cd src
cp .env.example .env
```

The values in `.env.example` are placeholders, but they are valid ones, so the app will start even if you don't change anything. For anything other than a local demo, replace every value that starts with `CHANGE_ME`.

| Variable | Description | Required |
|---|---|---|
| `POSTGRES_PASSWORD` | Password for the PostgreSQL user | Yes |
| `JWT_SECRET` | Secret used to sign session tokens. **At least 32 characters.** Generate one with `openssl rand -hex 32` or `python -c "import secrets; print(secrets.token_hex(32))"` | Yes |
| `DEMO_USER_PASSWORD` | Password for the six seeded demo users. **At least 8 characters.** | Yes (when seeding) |
| `INTEGRATION_API_KEY` | Key for the fleet/ERP integration endpoints (`X-Integration-Key` header). **At least 24 characters. Must not be empty.** | Yes |
| `OCPP_BASIC_AUTH_PASSWORD` | HTTP Basic password for OCPP charge points. **At least 12 characters. Must not be empty.** | Yes |
| `APP_PORT` | Port the app is published on (default `8080`) | No |
| `POSTGRES_DB`, `POSTGRES_USER` | Database name and user (default `chargeopt`) | No |
| `FLEET_TIMEZONE` | Fleet's local time zone (default `Asia/Kolkata`) | No |
| `CURRENCY` | 3-letter currency code (default `INR`) | No |
| `JWT_EXPIRE_MINUTES` | Session lifetime in minutes (default `480`) | No |
| `COOKIE_SECURE` | Set to `true` only when serving over HTTPS (default `false`) | No |
| `SEED_DEMO_DATA` | Seed the demo fleet into an empty database (default `true`) | No |
| `SIMULATION_ENABLED` | Run simulated charger telemetry (default `true`) | No |
| `SIMULATION_TICK_SECONDS` | How often the background loop runs, 1–60 s (default `5`) | No |
| `LOG_LEVEL` | Backend log level (default `INFO`) | No |
| `ENVIRONMENT` | Free-text environment label shown in logs (default `production`) | No |

`DATABASE_URL` is built by `docker-compose.yml` from the Postgres values above, so you don't set it yourself when using Docker.

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/[your-github-username]/bob-ai-hackathon-vedax.git
cd bob-ai-hackathon-vedax/src

# 2. Create your environment file (see the table above)
cp .env.example .env

# 3. Build the images (installs all Python and Node dependencies inside Docker)
docker compose build
```

The first build takes a few minutes, depending on your connection. There's no separate database setup step. On startup the backend runs `alembic upgrade head` to create the schema, and because the database is empty it seeds the demo data.

## Running the Application

```bash
# Start PostgreSQL, the backend and the frontend in the background
docker compose up -d

# Watch the backend come up (Ctrl+C to stop following; the app keeps running)
docker compose logs -f backend
```

Wait until all three containers report **healthy**. The backend can take 20–40 seconds on its first start while it migrates and seeds:

```bash
docker compose ps
```

The application will then be available at: **`http://localhost:8080`** (or the `APP_PORT` you set).

### Signing in

Every demo user shares the password you set in `DEMO_USER_PASSWORD`:

| Email | Role | Good for seeing… |
|---|---|---|
| `admin@chargeopt.example` | Fleet Administrator | Everything, including settings and simulation controls |
| `manager@chargeopt.example` | Fleet Manager | Schedule approval, overrides, reports |
| `ops@chargeopt.example` | Operations Manager | Trips and departures |
| `operator@chargeopt.example` | Charging Operator | Chargers and live sessions |
| `driver@chargeopt.example` | Driver (EV-027) | The mobile "My vehicle" view |
| `viewer@chargeopt.example` | Viewer / Management | Read-only dashboards and reports |

### Stopping

```bash
docker compose down        # stop, keep the data
docker compose down -v     # stop and wipe the database (re-seeds on next start)
```

## Verifying It Works

1. **Health checks**: both should return JSON:
   ```bash
   curl http://localhost:8080/api/health          # {"status":"ok"}
   curl http://localhost:8080/api/health/ready    # {"status":"ready","database":"ok",...}
   ```
2. **API docs**: open `http://localhost:8080/api/docs`. You should see the Swagger UI listing all endpoints.
3. **Seeded data**: sign in as `admin@chargeopt.example`. The Overview should show a fleet of **100** vehicles, **22** chargers (one in fault, one in maintenance) and a yellow banner saying *Static baseline schedule is active*.
4. **The core feature, end to end**:
   1. Open **Schedule → Baseline vs rule-based**. Both plans are computed on the same snapshot. The rule-based column should show a lower cost, a much lower peak-tariff share and higher projected readiness, plus the LP lower bound and the gap.
   2. Click **Activate rule-based scheduler**. A new run appears in *Run history*, and the **Timeline** shows reservations moving into the blue off-peak band (00:00–06:00).
   3. Open **Decisions & rules** and click any vehicle. Its explanation names the rules that applied (for example *R4: shifted to off-peak window…*).
   4. Go back to **Overview**, click **Resume** on the simulation bar, then **+60 min** a few times. Sessions start on their reserved chargers, SoC rises and KPIs update live.
   5. Open **Charging ops**, click **Status** on a charger that has a reservation and set it to **Fault**. An alert appears under **Alerts**, and the affected vehicle is moved to another compatible charger (rule R5).
5. **Driver view**: sign in as `driver@chargeopt.example` (a narrow window or phone works best). You should see EV-027's charge, the requirement for its next trip and where and when to plug in.

To restore the original demo state at any time, sign in as admin and go to **Rules & settings → Simulation → Regenerate scenario**, or run `docker compose down -v && docker compose up -d`.

## Running Tests

```bash
# Backend: 34 pytest tests (15 engine tests incl. the PRD examples, 19 API tests:
# auth, RBAC, DB exclusion constraint, overrides, alerts, simulation, OCPP).
# Uses a separate chargeopt_test database on the same Postgres container.
docker compose --profile test run --rm backend-tests

# Frontend: unit tests and type check (needs Node.js 20+ locally)
cd frontend
npm ci
npm test
npm run typecheck
cd ..

# Browser checks: visits every page and reports console errors, failed API calls
# and horizontal overflow (needs the stack running and Google Chrome installed)
cd e2e
npm ci
DEMO_USER_PASSWORD=<your demo password> node check.mjs
cd ..
```

On Windows PowerShell, set the variable for the browser check like this: `$env:DEMO_USER_PASSWORD="<your demo password>"; node check.mjs`

## Quick Demo (Optional)

**OCPP charger emulator.** This starts a simulated OCPP 1.6-J charge point that connects as `APH-C04`. The central system then sends it real `RemoteStartTransaction` / `SetChargingProfile` commands, and the meter values it returns are stored as `source = ocpp`:

```bash
docker compose --profile ocpp up -d ocpp-charger
```

On the **Charging ops** page, `APH-C04` changes from *OCPP offline* to connected.

**Recorded walkthrough.** `e2e/demo.mjs` drives the app through the full PRD demo plan with on-screen captions and records it as `src/demo/ChargeOpt_demo.mp4` plus an `.srt` subtitle file. It resets the scenario first, and it needs Google Chrome and `ffmpeg` on your PATH:

```bash
cd e2e && npm ci && DEMO_USER_PASSWORD=<your demo password> node demo.mjs
```

## Local Development (without Docker for the app)

If you want hot reload while editing code:

```bash
# Database only, in Docker. Add a compose override that publishes port 5432
# (e.g. "ports: ['5432:5432']" under the db service) so the host can reach it.
docker compose up -d db

# Backend (Python 3.12)
cd backend
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://chargeopt:<POSTGRES_PASSWORD>@localhost:5432/chargeopt
export JWT_SECRET=<32+ characters>
export DEMO_USER_PASSWORD=<8+ characters>
alembic upgrade head
uvicorn app.main:app --reload            # http://localhost:8000

# Frontend, in another terminal (proxies /api to localhost:8000)
cd frontend
npm install
npm run dev                               # http://localhost:5173
```

## Troubleshooting

| Issue | Solution |
|---|---|
| Backend keeps restarting, logs show `String should have at least 24 characters` (or 8 / 12 / 32) | A secret in `.env` is too short or empty. `INTEGRATION_API_KEY` needs 24+, `OCPP_BASIC_AUTH_PASSWORD` 12+, `JWT_SECRET` 32+, `DEMO_USER_PASSWORD` 8+ characters. Fix `.env`, then `docker compose up -d`. |
| `docker compose` says `Set POSTGRES_PASSWORD in .env` or `Set JWT_SECRET in .env` | You're not in `src/`, or `.env` doesn't exist there. Run `cd src && cp .env.example .env`. |
| Backend shows **unhealthy** | Check `docker compose logs backend`. Usually a bad `.env` value (see above) or the database still starting. Wait 30 s and run `docker compose ps` again. |
| `Bind for 0.0.0.0:8080 failed: port is already allocated` | Another program is using 8080. Set `APP_PORT=8081` (or any free port) in `.env` and open that port instead. |
| Can't sign in / "no users" | Seeding only happens on an **empty** database with `DEMO_USER_PASSWORD` set. Run `docker compose down -v && docker compose up -d` to start fresh. |
| Signed in, but nothing is charging | Expected: the demo starts with the simulation **paused** so you can review the baseline first. Click **Resume** on the Overview page. |
| Fleet map is grey | Map tiles come from OpenStreetMap and need internet access. The rest of the app works offline. |
| `exec /app/docker-entrypoint.sh: no such file or directory` or `set: illegal option -` on Windows | Git converted the shell script to CRLF line endings. This repo's `.gitattributes` prevents it on a fresh clone. If you cloned before it existed, run `git rm --cached -r . && git reset --hard`, then `docker compose build --no-cache backend`. |
| `backend-tests` fails to connect | Make sure the `db` service is up (`docker compose up -d db`). The test runner creates its own `chargeopt_test` database. |
| Browser check (`check.mjs`) can't launch Chrome | The scripts use your installed Google Chrome (`channel: "chrome"`). Install Chrome and run the command again. |
| `demo.mjs` fails with `spawnSync ffmpeg ENOENT` | Install `ffmpeg` and make sure it is on your PATH. It's only needed to turn the recording into an MP4. |
