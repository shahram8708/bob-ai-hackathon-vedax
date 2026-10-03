import os
from datetime import time

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_URL = os.environ["DATABASE_URL"]
ADMIN_URL = os.environ.get("ADMIN_DATABASE_URL", TEST_URL)
PASSWORD = "Correct-Horse-Battery-1"


def _recreate_database() -> None:
    name = make_url(TEST_URL).database
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _recreate_database()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


TABLES = [
    "energy_readings", "charging_sessions", "alerts", "charging_schedules", "charging_requests", "schedule_runs",
    "readiness_snapshots", "price_signals", "trips", "vehicles", "drivers", "chargers", "tariff_periods",
    "service_providers", "battery_profiles", "stations", "audit_logs", "system_config", "users", "roles",
]


@pytest.fixture(autouse=True)
def reset_login_throttle():
    from app.api.routes import auth

    auth._failures.clear()


@pytest.fixture()
def db():
    from app.db.session import SessionLocal, engine

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def world(db):
    from app.core.security import hash_password
    from app.models import BatteryProfile, Charger, Driver, Station, TariffPeriod, User
    from app.models.enums import RoleCode, SchedulerMode, TariffKind
    from app.services.config_service import OperationalConfig, save_config
    from app.services.seed import sync_roles

    sync_roles(db)
    save_config(db, OperationalConfig(timezone="Asia/Kolkata", currency="INR", scheduler_mode=SchedulerMode.RULE_BASED, simulation_enabled=True, default_rate_per_kwh=8.2), None)
    station = Station(code="TST", name="Test Depot", latitude=12.97, longitude=77.59, max_load_kw=500)
    other = Station(code="OTH", name="Other Depot", latitude=13.05, longitude=77.6, max_load_kw=500)
    db.add_all([station, other])
    db.flush()
    van = BatteryProfile(name="Van 60", vehicle_type="Van", capacity_kwh=60, max_ac_kw=11, max_dc_kw=50, charging_efficiency=0.9, consumption_kwh_per_km=0.2, connector_types=["CCS2", "Type2"])
    db.add(van)
    chargers = [Charger(code=f"TST-C0{i}", station_id=station.id, connector_type="CCS2", max_power_kw=50) for i in (1, 2)]
    chargers.append(Charger(code="TST-OCPP", station_id=station.id, connector_type="CCS2", max_power_kw=50, ocpp_identity="TST-OCPP", is_active=False))
    db.add_all(chargers)
    for name, kind, start, end, rate in (
        ("Off-peak", TariffKind.OFF_PEAK, time(0), time(6), 5.0),
        ("Shoulder", TariffKind.SHOULDER, time(6), time(18), 8.0),
        ("Peak", TariffKind.PEAK, time(18), time(22), 12.0),
        ("Late", TariffKind.SHOULDER, time(22), time(0), 8.0),
    ):
        db.add(TariffPeriod(name=name, kind=kind, start_time=start, end_time=end, rate_per_kwh=rate, demand_charge_per_kw=100 if kind == TariffKind.PEAK else None, days_of_week=list(range(7))))
    users = {}
    pw = hash_password(PASSWORD)
    for role in RoleCode:
        u = User(email=f"{role.value}@test.example", full_name=f"Test {role.value}", role_code=role.value, password_hash=pw)
        db.add(u)
        users[role.value] = u
    db.flush()
    driver = Driver(full_name="Test Driver", license_number="DL-0001", home_station_id=station.id, user_id=users["driver"].id)
    db.add(driver)
    db.commit()
    return {"station": station, "other": other, "profile": van, "chargers": chargers, "users": users, "driver": driver}


@pytest.fixture()
def client(world):
    from app.main import app
    from app.services.simulation import SimulationLoop

    app.state.simulation = SimulationLoop(60)
    yield TestClient(app, raise_server_exceptions=False)


def login(client: TestClient, role: str) -> TestClient:
    r = client.post("/api/auth/login", json={"email": f"{role}@test.example", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client
