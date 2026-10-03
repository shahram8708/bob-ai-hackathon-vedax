from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict
from app.models import Charger, ChargingRequest, ChargingSchedule, ChargingSession, EnergyReading, User, Vehicle
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    AlertSeverity,
    AlertType,
    ChargerStatus,
    RequestStatus,
    ReservationStatus,
    SessionSource,
    SessionStatus,
    VehicleAvailability,
)
from app.services import alerts, audit
from app.services.config_service import now
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed
from app.services.tariffs import TariffCalendar


def charger_power_for(vehicle: Vehicle, charger: Charger) -> float:
    profile = vehicle.battery_profile
    is_dc = charger.max_power_kw > 22 or charger.connector_type in {"CCS2", "CHAdeMO", "GB/T"}
    return round(min(charger.effective_power_kw, profile.max_dc_kw if is_dc else profile.max_ac_kw), 2)


def active_session_for_charger(db: Session, charger_id: int) -> ChargingSession | None:
    return db.scalar(select(ChargingSession).where(ChargingSession.charger_id == charger_id, ChargingSession.status == SessionStatus.ACTIVE))


def active_session_for_vehicle(db: Session, vehicle_id: int) -> ChargingSession | None:
    return db.scalar(select(ChargingSession).where(ChargingSession.vehicle_id == vehicle_id, ChargingSession.status == SessionStatus.ACTIVE))


def start_session(
    db: Session,
    *,
    vehicle: Vehicle,
    charger: Charger,
    source: SessionSource,
    schedule: ChargingSchedule | None = None,
    target_soc: float | None = None,
    user: User | None = None,
    at: datetime | None = None,
    ocpp_transaction_id: int | None = None,
    meter_start_wh: float | None = None,
) -> ChargingSession:
    at = at or now()
    if charger.status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE) or not charger.is_active:
        raise conflict(f"Charger {charger.code} is not usable ({charger.status.value})")
    if vehicle.current_station_id != charger.station_id:
        raise bad_request(f"{vehicle.registration} is not at the charger's depot")
    if vehicle.availability not in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING):
        raise conflict(f"{vehicle.registration} is {vehicle.availability.value.replace('_', ' ')}")
    if charger.connector_type not in vehicle.battery_profile.connector_types:
        raise bad_request(f"{vehicle.registration} does not support the {charger.connector_type} connector")
    if active_session_for_charger(db, charger.id):
        raise conflict(f"Charger {charger.code} already has an active session")
    if active_session_for_vehicle(db, vehicle.id):
        raise conflict(f"{vehicle.registration} is already charging")
    target = target_soc if target_soc is not None else (schedule.target_soc if schedule else vehicle.required_departure_soc)
    target = min(target, vehicle.max_soc)
    if vehicle.current_soc >= target - 0.05:
        raise bad_request(f"{vehicle.registration} is already at or above the {target:.0f}% target")
    session = ChargingSession(
        schedule_id=schedule.id if schedule else None,
        vehicle_id=vehicle.id,
        charger_id=charger.id,
        started_at=at,
        start_soc=vehicle.current_soc,
        target_soc=target,
        power_kw=schedule.power_kw if schedule else charger_power_for(vehicle, charger),
        energy_kwh=0,
        cost=0,
        tariff_breakdown={},
        status=SessionStatus.ACTIVE,
        source=source,
        ocpp_transaction_id=ocpp_transaction_id,
        meter_start_wh=meter_start_wh,
        last_reading_at=at,
    )
    db.add(session)
    if schedule is not None:
        schedule.status = ReservationStatus.ACTIVE
    charger.status = ChargerStatus.CHARGING
    charger.current_vehicle_id = vehicle.id
    charger.status_changed_at = at
    vehicle.availability = VehicleAvailability.CHARGING
    db.flush()
    if user is not None:
        audit.record(db, actor=user, action="session.started", category="session", summary=f"Started charging {vehicle.registration} on {charger.code}", entity_type="charging_session", entity_id=session.id)
    hub.publish("session.updated", {"id": session.id, "status": "active", "vehicle": vehicle.registration})
    return session


def accrue(session: ChargingSession, vehicle: Vehicle, energy_kwh: float, at: datetime, calendar: TariffCalendar, station_id: int) -> None:
    if energy_kwh <= 0:
        return
    quote = calendar.quote(at, station_id)
    session.energy_kwh = round(session.energy_kwh + energy_kwh, 4)
    session.cost = round(session.cost + energy_kwh * quote.rate, 4)
    breakdown = dict(session.tariff_breakdown or {})
    bucket = dict(breakdown.get(quote.kind, {"kwh": 0.0, "cost": 0.0}))
    bucket["kwh"] = round(bucket["kwh"] + energy_kwh, 4)
    bucket["cost"] = round(bucket["cost"] + energy_kwh * quote.rate, 4)
    breakdown[quote.kind] = bucket
    session.tariff_breakdown = breakdown
    gained = energy_kwh * vehicle.battery_profile.charging_efficiency / vehicle.battery_capacity_kwh * 100
    vehicle.current_soc = round(min(vehicle.max_soc, 100.0, vehicle.current_soc + gained), 2)
    vehicle.soc_updated_at = at


def record_reading(db: Session, session: ChargingSession, vehicle: Vehicle, at: datetime, power_kw: float) -> None:
    db.add(
        EnergyReading(
            session_id=session.id,
            charger_id=session.charger_id,
            vehicle_id=session.vehicle_id,
            recorded_at=at,
            power_kw=power_kw,
            energy_kwh=session.energy_kwh,
            soc=vehicle.current_soc,
            source=session.source,
        )
    )
    session.last_reading_at = at


def finish_session(
    db: Session,
    session: ChargingSession,
    *,
    status: SessionStatus,
    reason: str,
    at: datetime | None = None,
    user: User | None = None,
    charger_status: ChargerStatus | None = None,
) -> ChargingSession:
    at = at or now()
    vehicle = db.get(Vehicle, session.vehicle_id)
    charger = db.get(Charger, session.charger_id)
    session.status = status
    session.ended_at = at
    session.end_soc = vehicle.current_soc
    session.stop_reason = reason[:160]
    record_reading(db, session, vehicle, at, 0)
    if session.schedule_id:
        schedule = db.get(ChargingSchedule, session.schedule_id)
        if schedule is not None and schedule.status == ReservationStatus.ACTIVE:
            schedule.status = ReservationStatus.INTERRUPTED if status == SessionStatus.INTERRUPTED else ReservationStatus.COMPLETED
    if charger.current_vehicle_id == vehicle.id:
        charger.current_vehicle_id = None
    if charger_status is not None:
        charger.status = charger_status
    elif charger.status == ChargerStatus.CHARGING:
        charger.status = ChargerStatus.AVAILABLE
    charger.status_changed_at = at
    if vehicle.availability == VehicleAvailability.CHARGING:
        vehicle.availability = VehicleAvailability.AVAILABLE
    request = db.scalar(select(ChargingRequest).where(ChargingRequest.vehicle_id == vehicle.id, ChargingRequest.status.in_(OPEN_REQUEST_STATUSES)))
    if request is not None and vehicle.current_soc >= request.target_soc - 0.1:
        request.status = RequestStatus.FULFILLED
        request.closed_at = at
        request.rules = sorted(set(request.rules or []) | {"R7"})
    if user is not None:
        audit.record(db, actor=user, action="session.stopped", category="session", summary=f"Stopped charging {vehicle.registration} on {charger.code}: {reason}", entity_type="charging_session", entity_id=session.id)
    if status == SessionStatus.INTERRUPTED:
        alerts.raise_alert(
            db,
            type=AlertType.SESSION_INTERRUPTED,
            severity=AlertSeverity.WARNING,
            title=f"Charging interrupted: {vehicle.registration} on {charger.code}",
            message=f"Session #{session.id} stopped at {vehicle.current_soc:.0f}% (target {session.target_soc:.0f}%): {reason}. The schedule is being recalculated.",
            dedup_key=f"interrupted:{session.id}",
            vehicle_id=vehicle.id,
            charger_id=charger.id,
            station_id=charger.station_id,
            schedule_id=session.schedule_id,
        )
    mark_recalc_needed(db, "session ended")
    hub.publish("session.updated", {"id": session.id, "status": status.value, "vehicle": vehicle.registration})
    return session
