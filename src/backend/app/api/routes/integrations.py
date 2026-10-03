import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import BatteryProfile, ChargingSchedule, Station, Trip, Vehicle
from app.models.enums import ReservationStatus, TripPriority, TripStatus, VehiclePriority
from app.schemas.operations import FleetSyncIn
from app.services import audit
from app.services.config_service import now
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed, recalc_if_needed

router = APIRouter(prefix="/integrations", tags=["integrations"])


def integration_key(x_integration_key: str | None = Header(default=None)) -> None:
    expected = get_settings().integration_api_key
    if not expected:
        raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, "integration_disabled", "Fleet integration is not configured (INTEGRATION_API_KEY)")
    if not x_integration_key or not hmac.compare_digest(x_integration_key, expected):
        raise AppError(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Invalid integration key")


@router.post("/fleet-sync", dependencies=[Depends(integration_key)])
def fleet_sync(body: FleetSyncIn, db: Session = Depends(get_db)):
    stations = {s.code: s for s in db.scalars(select(Station))}
    profiles = {p.name: p for p in db.scalars(select(BatteryProfile))}
    errors: list[dict] = []
    v_created = v_updated = t_created = t_updated = 0
    for idx, item in enumerate(body.vehicles):
        station = stations.get(item.home_station_code.upper())
        profile = profiles.get(item.battery_profile)
        if station is None or profile is None:
            errors.append({"vehicle": item.external_ref, "error": "unknown station or battery profile"})
            continue
        v = db.scalar(select(Vehicle).where(Vehicle.external_ref == item.external_ref)) or db.scalar(select(Vehicle).where(Vehicle.registration == item.registration.upper()))
        if v is None:
            v = Vehicle(
                registration=item.registration.upper(),
                vehicle_type=profile.vehicle_type,
                battery_profile_id=profile.id,
                battery_capacity_kwh=profile.capacity_kwh,
                current_soc=item.current_soc if item.current_soc is not None else 50,
                required_departure_soc=item.required_departure_soc or 80,
                home_station_id=station.id,
                current_station_id=station.id,
                latitude=station.latitude,
                longitude=station.longitude,
                external_ref=item.external_ref,
                soc_updated_at=now(),
            )
            db.add(v)
            v_created += 1
        else:
            v.external_ref = item.external_ref
            v.home_station_id = station.id
            if item.current_soc is not None:
                v.current_soc = item.current_soc
                v.soc_updated_at = now()
            if item.required_departure_soc is not None and v.min_operating_soc <= item.required_departure_soc <= v.max_soc:
                v.required_departure_soc = item.required_departure_soc
            v_updated += 1
        if item.priority_category in {p.value for p in VehiclePriority}:
            v.priority_category = VehiclePriority(item.priority_category)
    db.flush()
    for item in body.trips:
        vehicle = None
        if item.vehicle_external_ref:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.external_ref == item.vehicle_external_ref))
        elif item.vehicle_registration:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.registration == item.vehicle_registration.upper()))
        station = stations.get(item.origin_station_code.upper())
        if station is None or item.departure_at.tzinfo is None:
            errors.append({"trip": item.external_ref, "error": "unknown origin station or naive datetime"})
            continue
        trip = db.scalar(select(Trip).where(Trip.external_ref == item.external_ref))
        status_value = TripStatus.CANCELLED if item.cancelled else (TripStatus.ASSIGNED if vehicle else TripStatus.UNASSIGNED)
        fields = dict(
            vehicle_id=vehicle.id if vehicle else None,
            origin_station_id=station.id,
            destination=item.destination,
            distance_km=item.distance_km,
            energy_kwh=item.energy_kwh,
            required_soc=item.required_soc,
            departure_at=item.departure_at,
            return_at=item.return_at,
            priority=TripPriority(item.priority) if item.priority in {p.value for p in TripPriority} else TripPriority.NORMAL,
        )
        if trip is None:
            db.add(Trip(code=f"ERP-{item.external_ref}"[:24], external_ref=item.external_ref, status=status_value, **fields))
            t_created += 1
        elif trip.status in (TripStatus.UNASSIGNED, TripStatus.ASSIGNED):
            for k, val in fields.items():
                setattr(trip, k, val)
            trip.status = status_value
            t_updated += 1
    summary = f"Fleet sync: {v_created} vehicles created, {v_updated} updated; {t_created} trips created, {t_updated} updated; {len(errors)} rejected"
    audit.record(db, actor=None, actor_label="integration:fleet-sync", action="integration.fleet_sync", category="integration", summary=summary, details={"errors": errors[:50]})
    mark_recalc_needed(db, "fleet sync")
    recalc_if_needed(db)
    db.commit()
    hub.publish("fleet.updated", {"sync": True})
    return {"vehicles_created": v_created, "vehicles_updated": v_updated, "trips_created": t_created, "trips_updated": t_updated, "errors": errors}


@router.get("/schedule-export", dependencies=[Depends(integration_key)])
def schedule_export(db: Session = Depends(get_db), hours: int = 24):
    at = now()
    rows = db.scalars(
        select(ChargingSchedule)
        .where(ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)), ChargingSchedule.end_at > at, ChargingSchedule.start_at < at + timedelta(hours=min(max(hours, 1), 72)))
        .options(selectinload(ChargingSchedule.vehicle), selectinload(ChargingSchedule.charger))
        .order_by(ChargingSchedule.start_at)
    )
    return {
        "generated_at": at,
        "reservations": [
            {
                "vehicle": r.vehicle.registration,
                "vehicle_external_ref": r.vehicle.external_ref,
                "charger": r.charger.code,
                "start_at": r.start_at,
                "end_at": r.end_at,
                "power_kw": r.power_kw,
                "planned_energy_kwh": r.planned_energy_kwh,
                "target_soc": r.target_soc,
                "status": r.status.value,
                "rules": r.rules,
            }
            for r in rows
        ],
    }
