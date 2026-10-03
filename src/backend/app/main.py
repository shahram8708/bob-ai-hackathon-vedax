import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import admin, auth, charging, fleet, infrastructure, integrations, monitoring, realtime, trips
from app.core.config import get_settings
from app.core.errors import AppError, register_error_handlers
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.events import hub
from app.services.ocpp.central import registry
from app.services.seed import bootstrap
from app.services.simulation import SimulationLoop, run_initial_schedule

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("chargeopt")


def _bootstrap() -> None:
    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()
    run_initial_schedule()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    hub.bind(loop)
    registry.bind(loop)
    await asyncio.to_thread(_bootstrap)
    app.state.simulation = SimulationLoop(settings.simulation_tick_seconds)
    app.state.simulation.start()
    log.info("ChargeOpt API ready (%s)", settings.environment)
    yield
    await app.state.simulation.stop()


app = FastAPI(
    title="ChargeOpt API",
    version="1.0.0",
    description="Rule-based EV fleet charging and energy management.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
register_error_handlers(app)
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Integration-Key"],
    )


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/") and request.method == "GET" and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


api = APIRouter(prefix="/api")


@api.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@api.get("/health/ready", tags=["health"])
def ready():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise AppError(503, "database_unavailable", "Database is not reachable") from exc
    finally:
        db.close()
    return {"status": "ready", "database": "ok", "simulation": settings.simulation_enabled}


for module in (auth, admin, fleet, trips, infrastructure, charging, monitoring, integrations):
    api.include_router(module.router)
app.include_router(api)
app.include_router(realtime.router, prefix="/api")
