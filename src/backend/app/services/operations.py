from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict
from app.models import Charger, ChargingRequest, ChargingSchedule, Station, Trip, User, Vehicle
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    AlertSeverity,
    AlertType,
    ChargerStatus,
    RequestStatus,
    ReservationStatus,
    SessionSource,
    SessionStatus,
    TripStatus,
    VehicleAvailability,
)
from app.services import alerts, audit
from app.services.charging import active_session_for_charger, active_session_for_vehicle, charger_power_for, finish_session, start_session
from app.services.config_service import cached_config, now
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed


def set_charger_status(db: Session, charger: Charger, status: ChargerStatus, note: str, user: User | None) -> Charger:
    previous = charger.status
    if previous == status:
        return charger
    if status == ChargerStatus.CHARGING:
        raise bad_request("Charging status is set automatically when a session starts")
    at = now()
    session = active_session_for_charger(db, charger.id)
    displaced = [
        r.vehicle_id
        for r in db.scalars(
            select(ChargingSchedule).where(ChargingSchedule.charger_id == charger.id, ChargingSchedule.status == ReservationStatus.PLANNED, ChargingSchedule.end_at > at)
        )
    ]
    if session is not None and status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE, ChargerStatus.AVAILABLE):
        displaced.append(session.vehicle_id)
        finish_session(
            db,
            session,
            status=SessionStatus.INTERRUPTED if status != ChargerStatus.AVAILABLE else SessionStatus.STOPPED,
            reason=f"charger set to {status.value}" + (f": {note}" if note else ""),
            at=at,
            charger_status=status,
        )
    charger.status = status
    charger.status_note = note[:255]
    charger.status_changed_at = at
    if status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE):
        for r in db.scalars(select(ChargingSchedule).where(ChargingSchedule.charger_id == charger.id, ChargingSchedule.status == ReservationStatus.PLANNED, ChargingSchedule.end_at > at)):
            r.status = ReservationStatus.SUPERSEDED
    if status == ChargerStatus.FAULT:
        alerts.raise_alert(
            db,
            type=AlertType.CHARGER_FAULT,
            severity=AlertSeverity.CRITICAL,
            title=f"Charger fault: {charger.code}",
            message=f"{charger.code} reported a fault{': ' + note if note else ''}. {len(displaced)} reservation(s) affected — reassigning to compatible chargers (R5).",
            dedup_key=f"fault:{charger.id}",
            charger_id=charger.id,
            station_id=charger.station_id,
        )
    audit.record(
        db,
        actor=user,
        action="charger.status_changed",
        category="charger",
        summary=f"{charger.code}: {previous.value} → {status.value}" + (f" ({note})" if note else ""),
        entity_type="charger",
        entity_id=charger.id,
        details={"from": previous.value, "to": status.value, "note": note},
    )
    mark_recalc_needed(db, f"charger {charger.code} {status.value}", rule="R5" if status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE) else None, vehicle_ids=displaced)
    hub.publish("charger.updated", {"id": charger.id, "status": status.value})
    return charger


def update_soc(db: Session, vehicle: Vehicle, soc: float, user: User | None, source: str = "manual") -> Vehicle:
    previous = vehicle.current_soc
    vehicle.current_soc = round(min(max(soc, 0.0), 100.0), 2)
    vehicle.soc_updated_at = now()
    audit.record(db, actor=user, action="vehicle.soc_updated", category="vehicle", summary=f"{vehicle.registration} SoC {previous:.0f}% → {vehicle.current_soc:.0f}% ({source})", entity_type="vehicle", entity_id=vehicle.id)
    mark_recalc_needed(db, "SoC changed")
    hub.publish("fleet.updated", {"vehicle_id": vehicle.id})
    return vehicle


def arrive(db: Session, vehicle: Vehicle, station: Station, soc: float | None, user: User | None) -> Vehicle:
    if vehicle.availability not in (VehicleAvailability.ON_TRIP, VehicleAvailability.MAINTENANCE, VehicleAvailability.OUT_OF_SERVICE) and vehicle.current_station_id == station.id:
        raise bad_request(f"{vehicle.registration} is already at {station.name}")
    vehicle.availability = VehicleAvailability.AVAILABLE
    vehicle.current_station_id = station.id
    vehicle.latitude, vehicle.longitude = station.latitude, station.longitude
    if soc is not None:
        vehicle.current_soc = round(min(max(soc, 0.0), 100.0), 2)
        vehicle.soc_updated_at = now()
    audit.record(db, actor=user, action="vehicle.arrived", category="vehicle", summary=f"{vehicle.registration} arrived at {station.name} ({vehicle.current_soc:.0f}% SoC)", entity_type="vehicle", entity_id=vehicle.id)
    mark_recalc_needed(db, "vehicle arrived")
    hub.publish("fleet.updated", {"vehicle_id": vehicle.id})
    return vehicle


def required_soc_for(db: Session, vehicle: Vehicle, trip: Trip) -> float:
    request = db.scalar(select(ChargingRequest).where(ChargingRequest.vehicle_id == vehicle.id, ChargingRequest.trip_id == trip.id).order_by(ChargingRequest.id.desc()))
    if request is not None and request.required_soc is not None:
        return request.required_soc
    if trip.required_soc is not None:
        return trip.required_soc
    return vehicle.required_departure_soc


def depart(db: Session, vehicle: Vehicle, trip: Trip | None, user: User | None, at: datetime | None = None) -> Vehicle:
    at = at or now()
    if vehicle.availability in (VehicleAvailability.ON_TRIP,):
        raise conflict(f"{vehicle.registration} is already on a trip")
    session = active_session_for_vehicle(db, vehicle.id)
    if session is not None:
        finish_session(db, session, status=SessionStatus.STOPPED, reason="vehicle departed", at=at)
    for r in db.scalars(select(ChargingSchedule).where(ChargingSchedule.vehicle_id == vehicle.id, ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.PROPOSED)), ChargingSchedule.end_at > at)):
        r.status = ReservationStatus.CANCELLED
    met = None
    if trip is not None:
        required = required_soc_for(db, vehicle, trip)
        met = vehicle.current_soc >= required - 0.5
        trip.status = TripStatus.IN_PROGRESS
        trip.departed_at = at
        trip.departure_soc = vehicle.current_soc
        trip.requirement_met = met
        for req in db.scalars(select(ChargingRequest).where(ChargingRequest.vehicle_id == vehicle.id, ChargingRequest.status.in_(OPEN_REQUEST_STATUSES + (RequestStatus.FULFILLED, RequestStatus.SATISFIED)), ChargingRequest.trip_id == trip.id)):
            req.status = RequestStatus.MET if met else RequestStatus.MISSED
            req.closed_at = at
        if not met:
            alerts.raise_alert(
                db,
                type=AlertType.DEPARTED_BELOW_REQUIRED,
                severity=AlertSeverity.CRITICAL,
                title=f"{vehicle.registration} departed below required SoC",
                message=f"Trip {trip.code} departed with {vehicle.current_soc:.0f}% against a {required:.0f}% requirement.",
                dedup_key=f"departed:{trip.id}",
                vehicle_id=vehicle.id,
                trip_id=trip.id,
                station_id=vehicle.current_station_id,
            )
        else:
            alerts.auto_resolve(db, f"risk:{trip.id}", f"Departed with {vehicle.current_soc:.0f}% — requirement met")
    vehicle.availability = VehicleAvailability.ON_TRIP
    vehicle.current_station_id = None
    audit.record(
        db,
        actor=user,
        action="vehicle.departed",
        category="vehicle",
        summary=f"{vehicle.registration} departed" + (f" on {trip.code} ({'requirement met' if met else 'below requirement'})" if trip else ""),
        entity_type="vehicle",
        entity_id=vehicle.id,
    )
    mark_recalc_needed(db, "vehicle departed")
    hub.publish("fleet.updated", {"vehicle_id": vehicle.id})
    return vehicle


def complete_trip(db: Session, trip: Trip, arrival_soc: float, station: Station, user: User | None, at: datetime | None = None) -> Trip:
    at = at or now()
    if trip.status != TripStatus.IN_PROGRESS:
        raise conflict(f"Trip {trip.code} is not in progress")
    vehicle = db.get(Vehicle, trip.vehicle_id)
    trip.status = TripStatus.COMPLETED
    trip.arrived_at = at
    trip.arrival_soc = arrival_soc
    used = max(0.0, ((trip.departure_soc or vehicle.current_soc) - arrival_soc) / 100 * vehicle.battery_capacity_kwh)
    trip.actual_energy_kwh = round(used, 2)
    expected = trip.energy_kwh if trip.energy_kwh is not None else trip.distance_km * vehicle.battery_profile.consumption_kwh_per_km
    threshold = cached_config().unexpected_consumption_pct
    if expected > 0 and used > expected * (1 + threshold / 100):
        alerts.raise_alert(
            db,
            type=AlertType.UNEXPECTED_CONSUMPTION,
            severity=AlertSeverity.WARNING,
            title=f"Unexpected energy consumption: {vehicle.registration}",
            message=f"Trip {trip.code} used {used:.1f} kWh against {expected:.1f} kWh expected (+{(used / expected - 1) * 100:.0f}%, threshold {threshold:.0f}%).",
            dedup_key=f"consumption:{trip.id}",
            vehicle_id=vehicle.id,
            trip_id=trip.id,
            details={"expected_kwh": round(expected, 2), "actual_kwh": round(used, 2)},
        )
    if vehicle.availability == VehicleAvailability.ON_TRIP:
        arrive(db, vehicle, station, arrival_soc, user)
    audit.record(db, actor=user, action="trip.completed", category="trip", summary=f"Trip {trip.code} completed — {used:.1f} kWh used", entity_type="trip", entity_id=trip.id)
    return trip


def _overlapping(db: Session, charger_id: int, start: datetime, end: datetime, exclude_id: int | None = None) -> list[ChargingSchedule]:
    q = select(ChargingSchedule).where(
        ChargingSchedule.charger_id == charger_id,
        ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)),
        ChargingSchedule.start_at < end,
        ChargingSchedule.end_at > start,
    )
    if exclude_id is not None:
        q = q.where(ChargingSchedule.id != exclude_id)
    return list(db.scalars(q))


def create_override(
    db: Session,
    *,
    vehicle: Vehicle,
    charger: Charger,
    start: datetime,
    end: datetime | None,
    target_soc: float | None,
    reason: str,
    user: User,
    original: ChargingSchedule | None = None,
    preempt: bool = False,
    emergency: bool = False,
) -> ChargingSchedule:
    at = now()
    if charger.status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE) or not charger.is_active:
        raise conflict(f"Charger {charger.code} is {charger.status.value}")
    if vehicle.current_station_id is not None and vehicle.current_station_id != charger.station_id:
        raise bad_request(f"{vehicle.registration} is at a different depot than {charger.code}")
    if vehicle.current_station_id is None and vehicle.home_station_id != charger.station_id:
        raise bad_request(f"{charger.code} is not at {vehicle.registration}'s home depot")
    if charger.connector_type not in vehicle.battery_profile.connector_types:
        raise bad_request(f"{vehicle.registration} does not support {charger.connector_type}")
    if start < at - timedelta(minutes=1):
        raise bad_request("Start time cannot be in the past")
    target = min(target_soc if target_soc is not None else vehicle.required_departure_soc, vehicle.max_soc)
    power = charger_power_for(vehicle, charger)
    energy = max(0.0, (target - vehicle.current_soc) / 100 * vehicle.battery_capacity_kwh) / vehicle.battery_profile.charging_efficiency
    if end is None:
        if energy <= 0:
            raise bad_request(f"{vehicle.registration} already meets the {target:.0f}% target")
        end = start + timedelta(hours=energy / power)
    if end <= start:
        raise bad_request("End time must be after start time")
    energy = min(energy, power * (end - start).total_seconds() / 3600) if energy > 0 else power * (end - start).total_seconds() / 3600

    own_active = active_session_for_vehicle(db, vehicle.id)
    if own_active is not None:
        finish_session(db, own_active, status=SessionStatus.STOPPED, reason="replaced by manual override", at=at)
    clashes = _overlapping(db, charger.id, start, end, original.id if original else None)
    other_session = active_session_for_charger(db, charger.id)
    blocking = other_session is not None and (
        start <= at + timedelta(minutes=1) or any(c.status == ReservationStatus.ACTIVE for c in clashes)
    )
    if blocking:
        if not preempt:
            raise conflict(
                f"{charger.code} is in use by another vehicle during that window. Enable pre-emption to stop that session.",
                {"session_id": other_session.id},
            )
        finish_session(db, other_session, status=SessionStatus.STOPPED, reason=f"pre-empted by override for {vehicle.registration}", at=at)
        clashes = _overlapping(db, charger.id, start, end, original.id if original else None)
    displaced: list[int] = []
    for c in clashes:
        if c.status == ReservationStatus.PLANNED:
            c.status = ReservationStatus.SUPERSEDED
            if c.vehicle_id != vehicle.id:
                displaced.append(c.vehicle_id)
                other = db.get(Vehicle, c.vehicle_id)
                alerts.raise_alert(
                    db,
                    type=AlertType.RESERVATION_CONFLICT,
                    severity=AlertSeverity.WARNING,
                    title=f"Reservation conflict on {charger.code}",
                    message=f"Manual override for {vehicle.registration} displaced {other.registration}'s reservation; it is being rescheduled.",
                    dedup_key=f"conflict:{c.id}",
                    vehicle_id=c.vehicle_id,
                    charger_id=charger.id,
                    schedule_id=c.id,
                )
    for r in db.scalars(select(ChargingSchedule).where(ChargingSchedule.vehicle_id == vehicle.id, ChargingSchedule.status == ReservationStatus.PLANNED, ChargingSchedule.end_at > at)):
        if original is None or r.id != original.id:
            r.status = ReservationStatus.SUPERSEDED
    if original is not None:
        original.status = ReservationStatus.SUPERSEDED
    db.flush()
    rules = ["R8"]
    row = ChargingSchedule(
        run_id=None,
        vehicle_id=vehicle.id,
        charger_id=charger.id,
        start_at=max(start, at),
        end_at=end,
        power_kw=power,
        planned_energy_kwh=round(energy, 3),
        estimated_cost=0,
        target_soc=target,
        priority_level=1 if emergency else (original.priority_level if original else 3),
        status=ReservationStatus.PLANNED,
        is_override=True,
        override_reason=reason[:500],
        created_by_id=user.id,
        rules=rules,
        explanation=f"Manual override by {user.full_name}: {reason}",
        tariff_mix={},
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor=user,
        action="schedule.override",
        category="override",
        summary=f"Override for {vehicle.registration} on {charger.code} {row.start_at:%Y-%m-%d %H:%M}–{row.end_at:%H:%M} UTC: {reason}",
        entity_type="charging_schedule",
        entity_id=row.id,
        details={"original_id": original.id if original else None, "displaced_vehicle_ids": displaced, "emergency": emergency, "preempt": preempt},
    )
    mark_recalc_needed(db, "manual override", rule="R3" if displaced else None, vehicle_ids=displaced)
    if row.start_at <= at + timedelta(seconds=30) and vehicle.current_station_id == charger.station_id:
        if active_session_for_vehicle(db, vehicle.id) is None:
            start_session(db, vehicle=vehicle, charger=charger, schedule=row, source=SessionSource.SIMULATED if not charger.ocpp_connected else SessionSource.OCPP, user=user, at=at)
    hub.publish("schedule.updated", {"override_id": row.id})
    return row


def cancel_reservation(db: Session, reservation: ChargingSchedule, user: User, reason: str, hold_hours: float | None) -> ChargingSchedule:
    if reservation.status not in (ReservationStatus.PLANNED, ReservationStatus.PROPOSED):
        raise conflict(f"Only planned reservations can be cancelled (current: {reservation.status.value})")
    reservation.status = ReservationStatus.CANCELLED
    reservation.override_reason = reason[:500]
    vehicle = db.get(Vehicle, reservation.vehicle_id)
    if hold_hours:
        vehicle.charging_hold_until = now() + timedelta(hours=hold_hours)
    audit.record(
        db,
        actor=user,
        action="schedule.override",
        category="override",
        summary=f"Cancelled reservation #{reservation.id} for {vehicle.registration}" + (f" and held charging for {hold_hours:g} h" if hold_hours else "") + f": {reason}",
        entity_type="charging_schedule",
        entity_id=reservation.id,
        details={"hold_hours": hold_hours},
    )
    mark_recalc_needed(db, "reservation cancelled")
    return reservation


def release_missed(db: Session, reservation: ChargingSchedule, at: datetime) -> None:
    reservation.status = ReservationStatus.MISSED
    vehicle = db.get(Vehicle, reservation.vehicle_id)
    charger = db.get(Charger, reservation.charger_id)
    alerts.raise_alert(
        db,
        type=AlertType.MISSED_SLOT,
        severity=AlertSeverity.WARNING,
        title=f"{vehicle.registration} missed its reserved slot",
        message=f"Reserved {charger.code} from {reservation.start_at:%H:%M} UTC but the vehicle did not arrive. Reservation released and rescheduling (R6).",
        dedup_key=f"missed:{reservation.id}",
        vehicle_id=vehicle.id,
        charger_id=charger.id,
        schedule_id=reservation.id,
    )
    audit.record(db, actor=None, action="schedule.slot_missed", category="schedule", summary=f"Released missed reservation #{reservation.id} for {vehicle.registration} on {charger.code}", entity_type="charging_schedule", entity_id=reservation.id)
    mark_recalc_needed(db, "missed slot", rule="R6", vehicle_ids=[vehicle.id])
