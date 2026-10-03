"""Simulated charger telemetry and operational clock.

Chargers without an OCPP connection are simulated: sessions draw their planned power,
SoC rises accordingly, and vehicles depart/return on their trip times. All values
produced here are stored with source = 'simulated'.
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models import Charger, ChargingSchedule, ChargingSession, ScheduleRun, Station, Trip, Vehicle
from app.models.enums import (
    ChargerStatus,
    ReservationStatus,
    SessionSource,
    SessionStatus,
    TripStatus,
    VehicleAvailability,
)
from app.services import audit, monitoring
from app.services.charger_control import command_start, is_remote
from app.services.charging import accrue, finish_session, record_reading
from app.core.config import get_settings
from app.core.errors import bad_request
from app.services.config_service import OperationalConfig, load_config, now, save_config
from app.services.events import hub
from app.services.operations import complete_trip, depart, release_missed
from app.services.scheduler.service import SCHEDULER_LOCK, mark_recalc_needed, recalc_if_needed, run_scheduler
from app.services.tariffs import load_calendar

log = logging.getLogger("chargeopt.simulation")

READING_INTERVAL = timedelta(seconds=60)


def _start_due(db: Session, at: datetime, remote_only: bool = False) -> None:
    due = db.scalars(
        select(ChargingSchedule)
        .where(ChargingSchedule.status == ReservationStatus.PLANNED, ChargingSchedule.start_at <= at, ChargingSchedule.end_at > at)
        .order_by(ChargingSchedule.priority_level, ChargingSchedule.start_at)
    ).all()
    for r in due:
        vehicle = db.get(Vehicle, r.vehicle_id)
        charger = db.get(Charger, r.charger_id)
        if charger.status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE):
            continue
        if remote_only and not is_remote(charger):
            continue
        present = vehicle.availability in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING) and vehicle.current_station_id == charger.station_id
        if not present:
            continue
        if charger.current_vehicle_id not in (None, vehicle.id):
            continue
        if vehicle.current_soc >= r.target_soc - 0.1:
            r.status = ReservationStatus.COMPLETED
            continue
        try:
            command_start(db, charger, vehicle, r)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not start reservation %s: %s", r.id, exc)


def _release_missed(db: Session, at: datetime, cfg: OperationalConfig) -> None:
    grace = timedelta(minutes=cfg.missed_slot_grace_minutes)
    for r in db.scalars(
        select(ChargingSchedule).where(ChargingSchedule.status == ReservationStatus.PLANNED, ChargingSchedule.start_at + grace < at)
    ).all():
        vehicle = db.get(Vehicle, r.vehicle_id)
        charger = db.get(Charger, r.charger_id)
        if vehicle.current_station_id == charger.station_id and vehicle.availability in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING) and r.end_at > at:
            continue
        if r.end_at <= at and vehicle.current_station_id == charger.station_id:
            r.status = ReservationStatus.SUPERSEDED
            mark_recalc_needed(db, "stale reservation")
            continue
        release_missed(db, r, at)


def _advance_sessions(db: Session, at: datetime, dt_seconds: float, calendar) -> None:
    sessions = db.scalars(
        select(ChargingSession)
        .where(ChargingSession.status == SessionStatus.ACTIVE, ChargingSession.source != SessionSource.OCPP)
        .options(selectinload(ChargingSession.schedule))
    ).all()
    for s in sessions:
        vehicle = db.get(Vehicle, s.vehicle_id)
        charger = db.get(Charger, s.charger_id)
        start_point = max(s.started_at, at - timedelta(seconds=dt_seconds))
        hours = max(0.0, (at - start_point).total_seconds() / 3600)
        power = min(s.power_kw, charger.effective_power_kw)
        remaining_grid = max(0.0, (s.target_soc - vehicle.current_soc) / 100 * vehicle.battery_capacity_kwh) / vehicle.battery_profile.charging_efficiency
        energy = min(power * hours, remaining_grid)
        accrue(s, vehicle, energy, start_point, calendar, charger.station_id)
        if s.last_reading_at is None or at - s.last_reading_at >= READING_INTERVAL:
            record_reading(db, s, vehicle, at, power)
        if vehicle.current_soc >= s.target_soc - 0.05:
            finish_session(db, s, status=SessionStatus.COMPLETED, reason="target SoC reached (R7)", at=at)
        elif s.schedule is not None and at >= s.schedule.end_at + timedelta(minutes=2):
            finish_session(db, s, status=SessionStatus.COMPLETED, reason="reserved window ended", at=at)
    if sessions:
        hub.publish("session.progress", {"count": len(sessions)})


def _trip_events(db: Session, at: datetime) -> None:
    for trip in db.scalars(
        select(Trip).where(Trip.status == TripStatus.ASSIGNED, Trip.departure_at <= at, Trip.vehicle_id.is_not(None)).order_by(Trip.departure_at)
    ).all():
        vehicle = db.get(Vehicle, trip.vehicle_id)
        if vehicle.availability in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING) and vehicle.current_station_id is not None:
            depart(db, vehicle, trip, None, at=at)
        elif at - trip.departure_at > timedelta(hours=6):
            trip.status = TripStatus.CANCELLED
    for trip in db.scalars(
        select(Trip).where(Trip.status == TripStatus.IN_PROGRESS, Trip.return_at.is_not(None), Trip.return_at <= at)
    ).all():
        vehicle = db.get(Vehicle, trip.vehicle_id)
        expected = trip.energy_kwh if trip.energy_kwh is not None else trip.distance_km * vehicle.battery_profile.consumption_kwh_per_km
        arrival = max(5.0, (trip.departure_soc or vehicle.current_soc) - expected / vehicle.battery_capacity_kwh * 100)
        station = db.get(Station, trip.origin_station_id)
        complete_trip(db, trip, round(arrival, 1), station, None, at=at)


def _housekeeping(db: Session, at: datetime) -> None:
    referenced = text(
        "id NOT IN (SELECT schedule_id FROM charging_sessions WHERE schedule_id IS NOT NULL) "
        "AND id NOT IN (SELECT schedule_id FROM alerts WHERE schedule_id IS NOT NULL)"
    )
    db.execute(
        delete(ChargingSchedule)
        .where(ChargingSchedule.status.in_((ReservationStatus.SUPERSEDED, ReservationStatus.CANCELLED)), ChargingSchedule.updated_at < at - timedelta(days=2))
        .where(referenced)
    )


def tick(db: Session, at: datetime, dt_seconds: float, cfg: OperationalConfig, force_recalc: bool = False) -> None:
    calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(hours=2), at + timedelta(hours=cfg.horizon_hours + 2))
    simulate = cfg.simulation_enabled and get_settings().simulation_enabled
    if simulate:
        _advance_sessions(db, at, dt_seconds, calendar)
        _trip_events(db, at)
    _release_missed(db, at, cfg)
    last_run = db.scalar(select(ScheduleRun.created_at).order_by(ScheduleRun.id.desc()).limit(1))
    if force_recalc or last_run is None or at - last_run >= timedelta(minutes=cfg.auto_recalc_minutes):
        mark_recalc_needed(db, "periodic re-evaluation")
    recalc_if_needed(db)
    _start_due(db, at, remote_only=not simulate)
    monitoring.evaluate_alerts(db, at, cfg, calendar)
    monitoring.snapshot_readiness(db, at, cfg)


class SimulationLoop:
    def __init__(self, interval: float):
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._last: datetime | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.step)
            except Exception:  # noqa: BLE001
                log.exception("Simulation tick failed")
            await asyncio.sleep(self.interval)

    def step(self) -> None:
        with self._lock:
            db = SessionLocal()
            try:
                if not db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK + 1}).scalar():
                    db.rollback()
                    return
                cfg = load_config(db)
                at = now()
                dt = (at - self._last).total_seconds() if self._last and cfg.simulation_enabled else self.interval
                tick(db, at, min(max(dt, 0.0), 120.0), cfg)
                if self._last is None or at.minute != self._last.minute:
                    _housekeeping(db, at)
                db.commit()
                self._last = at
                hub.publish("tick", {"at": at.isoformat()})
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def advance(self, minutes: int, user) -> dict:
        with self._lock:
            db = SessionLocal()
            try:
                db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK + 1})
                cfg = load_config(db)
                if not (cfg.simulation_enabled and get_settings().simulation_enabled):
                    raise bad_request("Resume the telemetry simulation before advancing the clock")
                before = now()
                for _ in range(minutes):
                    cfg.clock_offset_seconds += 60
                    save_config(db, cfg, user.id if user else None)
                    tick(db, now(), 60, cfg)
                audit.record(db, actor=user, action="simulation.advanced", category="simulation", summary=f"Simulation clock advanced {minutes} min ({before:%H:%M} → {now():%H:%M} UTC)")
                db.commit()
                self._last = now()
                hub.publish("schedule.updated", {"simulation": "advanced"})
                return {"from": before, "to": now()}
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()


def run_initial_schedule() -> None:
    db = SessionLocal()
    try:
        load_config(db)
        run_scheduler(db, trigger="startup")
        db.commit()
    finally:
        db.close()
