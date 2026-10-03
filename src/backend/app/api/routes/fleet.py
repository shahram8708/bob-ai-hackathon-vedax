from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_or_404, require
from app.api.serializers import driver_out, request_out, reservation_out, trip_out, vehicle_out
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import (
    BatteryProfile,
    ChargingRequest,
    ChargingSchedule,
    ChargingSession,
    Driver,
    Station,
    Trip,
    User,
    Vehicle,
)
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    ReservationStatus,
    SessionStatus,
    TripStatus,
    VehicleAvailability,
)
from app.schemas.fleet import ArriveIn, DepartIn, DriverIn, DriverPatch, SocUpdate, VehicleIn, VehiclePatch
from app.services import audit, operations
from app.services.advisory import contingency
from app.services.config_service import load_config, now
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed, next_trips, recalc_if_needed
from app.services.tariffs import load_calendar

router = APIRouter(tags=["fleet"])


def _enrich(db: Session, vehicles: list[Vehicle]) -> list[dict]:
    if not vehicles:
        return []
    ids = [v.id for v in vehicles]
    trips = next_trips(db, now())
    requests = {r.vehicle_id: r for r in db.scalars(select(ChargingRequest).where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES), ChargingRequest.vehicle_id.in_(ids)))}
    latest_ids = select(func.max(ChargingSession.id)).where(ChargingSession.vehicle_id.in_(ids)).group_by(ChargingSession.vehicle_id)
    last = {s.vehicle_id: s for s in db.scalars(select(ChargingSession).where(ChargingSession.id.in_(latest_ids)))}
    return [
        vehicle_out(v, trips.get(v.id), requests.get(v.id), last.get(v.id), charging=last.get(v.id) is not None and last[v.id].status == SessionStatus.ACTIVE)
        for v in vehicles
    ]


@router.get("/vehicles")
def list_vehicles(
    _: User = Depends(require(Perm.VIEW_FLEET)),
    db: Session = Depends(get_db),
    search: str | None = Query(default=None, max_length=60),
    station_id: int | None = None,
    availability: VehicleAvailability | None = None,
    readiness: str | None = Query(default=None, pattern="^(ready|needs_charge|charging|at_risk|on_trip|maintenance|out_of_service)$"),
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
):
    q = select(Vehicle).options(selectinload(Vehicle.assigned_driver))
    if not include_inactive:
        q = q.where(Vehicle.is_active.is_(True))
    if search:
        like = f"%{search.strip()}%"
        q = q.outerjoin(Driver, Driver.id == Vehicle.assigned_driver_id).where(or_(Vehicle.registration.ilike(like), Vehicle.vehicle_type.ilike(like), Driver.full_name.ilike(like)))
    if station_id:
        q = q.where(Vehicle.home_station_id == station_id)
    if availability:
        q = q.where(Vehicle.availability == availability)
    vehicles = list(db.scalars(q.order_by(Vehicle.registration)))
    items = _enrich(db, vehicles)
    if readiness:
        items = [i for i in items if i["readiness"] == readiness]
    counts: dict[str, int] = {}
    for i in items:
        counts[i["readiness"]] = counts.get(i["readiness"], 0) + 1
    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start : start + page_size], "total": total, "page": page, "page_size": page_size, "readiness_counts": counts}


@router.post("/vehicles", status_code=status.HTTP_201_CREATED)
def create_vehicle(body: VehicleIn, actor: User = Depends(require(Perm.MANAGE_VEHICLES)), db: Session = Depends(get_db)):
    if db.scalar(select(Vehicle).where(Vehicle.registration == body.registration)):
        raise conflict(f"Vehicle {body.registration} already exists")
    profile = get_or_404(db, BatteryProfile, body.battery_profile_id, "Battery profile")
    station = get_or_404(db, Station, body.home_station_id, "Station")
    if body.assigned_driver_id:
        get_or_404(db, Driver, body.assigned_driver_id, "Driver")
    v = Vehicle(
        **body.model_dump(exclude={"vehicle_type", "battery_capacity_kwh"}),
        vehicle_type=body.vehicle_type or profile.vehicle_type,
        battery_capacity_kwh=body.battery_capacity_kwh or profile.capacity_kwh,
        current_station_id=station.id,
        latitude=station.latitude,
        longitude=station.longitude,
        soc_updated_at=now(),
    )
    db.add(v)
    db.flush()
    audit.record(db, actor=actor, action="vehicle.created", category="vehicle", summary=f"Created vehicle {v.registration} ({v.vehicle_type})", entity_type="vehicle", entity_id=v.id)
    mark_recalc_needed(db, "vehicle added")
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("fleet.updated", {"vehicle_id": v.id})
    return _enrich(db, [v])[0]


@router.get("/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: int, _: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    data = _enrich(db, [v])[0]
    data["trips"] = [trip_out(t) for t in db.scalars(select(Trip).where(Trip.vehicle_id == v.id).order_by(Trip.departure_at.desc()).limit(15))]
    data["reservations"] = [
        reservation_out(r)
        for r in db.scalars(
            select(ChargingSchedule)
            .where(ChargingSchedule.vehicle_id == v.id, ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE, ReservationStatus.PROPOSED)))
            .order_by(ChargingSchedule.start_at)
        )
    ]
    data["sessions"] = [
        {
            "id": s.id,
            "charger_id": s.charger_id,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "start_soc": s.start_soc,
            "end_soc": s.end_soc,
            "energy_kwh": round(s.energy_kwh, 2),
            "cost": round(s.cost, 2),
            "status": s.status.value,
            "source": s.source.value,
        }
        for s in db.scalars(select(ChargingSession).where(ChargingSession.vehicle_id == v.id).order_by(ChargingSession.started_at.desc()).limit(15))
    ]
    data["home_station"] = v.home_station.name
    data["current_station"] = v.current_station.name if v.current_station else None
    return data


@router.put("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, body: VehiclePatch, actor: User = Depends(require(Perm.MANAGE_VEHICLES)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    data = body.model_dump(exclude_unset=True, exclude={"clear_driver", "clear_hold"})
    mins = {k: data.get(k, getattr(v, k)) for k in ("min_operating_soc", "required_departure_soc", "max_soc")}
    if not mins["min_operating_soc"] <= mins["required_departure_soc"] <= mins["max_soc"]:
        raise bad_request("SoC limits must satisfy minimum ≤ required departure ≤ maximum")
    if "battery_profile_id" in data:
        get_or_404(db, BatteryProfile, data["battery_profile_id"], "Battery profile")
    if "home_station_id" in data:
        get_or_404(db, Station, data["home_station_id"], "Station")
    if data.get("assigned_driver_id"):
        get_or_404(db, Driver, data["assigned_driver_id"], "Driver")
    if data.get("availability") in (VehicleAvailability.CHARGING, VehicleAvailability.ON_TRIP):
        raise bad_request("Charging and on-trip states are set by sessions and trip events")
    before = {k: getattr(v, k) for k in data}
    for k, val in data.items():
        setattr(v, k, val)
    if body.clear_driver:
        v.assigned_driver_id = None
        data["assigned_driver_id"] = None
    if body.clear_hold:
        v.charging_hold_until = None
        data["charging_hold_until"] = None
    if data.get("is_active") is False:
        for r in db.scalars(select(ChargingSchedule).where(ChargingSchedule.vehicle_id == v.id, ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.PROPOSED)))):
            r.status = ReservationStatus.CANCELLED
    audit.record(
        db,
        actor=actor,
        action="vehicle.deactivated" if data.get("is_active") is False else "vehicle.updated",
        category="vehicle",
        summary=f"{'Deactivated' if data.get('is_active') is False else 'Updated'} vehicle {v.registration}",
        entity_type="vehicle",
        entity_id=v.id,
        details=audit.diff({k: str(x) for k, x in before.items()}, {k: str(x) for k, x in data.items()}),
    )
    mark_recalc_needed(db, "vehicle updated")
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("fleet.updated", {"vehicle_id": v.id})
    return _enrich(db, [v])[0]


@router.post("/vehicles/{vehicle_id}/soc")
def set_soc(vehicle_id: int, body: SocUpdate, actor: User = Depends(require(Perm.VEHICLE_EVENTS)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    operations.update_soc(db, v, body.soc, actor)
    recalc_if_needed(db, actor)
    db.commit()
    return _enrich(db, [v])[0]


@router.post("/vehicles/{vehicle_id}/arrive")
def vehicle_arrive(vehicle_id: int, body: ArriveIn, actor: User = Depends(require(Perm.VEHICLE_EVENTS)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    station = get_or_404(db, Station, body.station_id, "Station")
    trip = db.scalar(select(Trip).where(Trip.vehicle_id == v.id, Trip.status == TripStatus.IN_PROGRESS))
    if trip is not None:
        operations.complete_trip(db, trip, body.soc if body.soc is not None else v.current_soc, station, actor)
    else:
        operations.arrive(db, v, station, body.soc, actor)
    recalc_if_needed(db, actor)
    db.commit()
    return _enrich(db, [v])[0]


@router.post("/vehicles/{vehicle_id}/depart")
def vehicle_depart(vehicle_id: int, body: DepartIn, actor: User = Depends(require(Perm.VEHICLE_EVENTS)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    if v.availability not in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING):
        raise conflict(f"{v.registration} cannot depart while {v.availability.value.replace('_', ' ')}")
    trip = None
    if body.trip_id:
        trip = get_or_404(db, Trip, body.trip_id, "Trip")
        if trip.vehicle_id != v.id or trip.status != TripStatus.ASSIGNED:
            raise bad_request("Trip is not assigned to this vehicle")
    else:
        trip = next_trips(db, now()).get(v.id)
    operations.depart(db, v, trip, actor)
    recalc_if_needed(db, actor)
    db.commit()
    return _enrich(db, [v])[0]


@router.get("/vehicles/{vehicle_id}/contingency")
def vehicle_contingency(vehicle_id: int, user: User = Depends(require(Perm.VIEW_FLEET, Perm.VIEW_OWN_VEHICLE)), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vehicle_id, "Vehicle")
    if user.role_code == "driver" and (user.driver is None or v.assigned_driver_id != user.driver.id):
        raise forbidden("Drivers can only view their assigned vehicle")
    cfg = load_config(db)
    return contingency(db, v, load_calendar(db, cfg.tz, cfg.default_rate_per_kwh), now(), cfg)


@router.get("/me/vehicle")
def my_vehicle(user: User = Depends(require(Perm.VIEW_OWN_VEHICLE)), db: Session = Depends(get_db)):
    if user.driver is None:
        raise not_found("Driver profile")
    v = db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id == user.driver.id, Vehicle.is_active.is_(True)))
    if v is None:
        return {"driver": driver_out(user.driver), "vehicle": None}
    cfg = load_config(db)
    data = _enrich(db, [v])[0]
    reservations = list(
        db.scalars(
            select(ChargingSchedule)
            .where(ChargingSchedule.vehicle_id == v.id, ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)))
            .options(selectinload(ChargingSchedule.charger))
            .order_by(ChargingSchedule.start_at)
        )
    )
    tz = cfg.tz
    instructions: list[str] = []
    req = data["request"]
    if data["readiness"] == "ready":
        instructions.append(f"No charging needed — {v.current_soc:.0f}% already meets the {data['required_soc']:.0f}% requirement.")
    for r in reservations:
        station = r.charger.station.name
        if r.status == ReservationStatus.ACTIVE:
            instructions.append(f"Charging now on {r.charger.code} at {station} until about {r.end_at.astimezone(tz):%H:%M}. Leave the vehicle connected.")
        else:
            plug_by = r.start_at - timedelta(minutes=10)
            instructions.append(
                f"Park at {station} and connect to {r.charger.code} by {plug_by.astimezone(tz):%H:%M}. Charging runs {r.start_at.astimezone(tz):%H:%M}–{r.end_at.astimezone(tz):%H:%M} to reach {r.target_soc:.0f}%."
            )
    if not reservations and data["readiness"] not in ("ready", "on_trip"):
        instructions.append("Charging has not been scheduled yet — contact the depot charging operator.")
    if req and req.get("status") == "at_risk":
        instructions.append("Your departure is at risk: the depot team has been alerted.")
    return {
        "driver": driver_out(user.driver),
        "vehicle": data,
        "home_station": v.home_station.name,
        "reservations": [reservation_out(r) for r in reservations],
        "instructions": instructions,
        "timezone": cfg.timezone,
    }


@router.get("/drivers")
def list_drivers(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    drivers = list(db.scalars(select(Driver).options(selectinload(Driver.user)).order_by(Driver.full_name)))
    assigned = dict(db.execute(select(Vehicle.assigned_driver_id, Vehicle.registration).where(Vehicle.assigned_driver_id.is_not(None))).all())
    return [{**driver_out(d), "vehicle": assigned.get(d.id)} for d in drivers]


@router.post("/drivers", status_code=status.HTTP_201_CREATED)
def create_driver(body: DriverIn, actor: User = Depends(require(Perm.MANAGE_DRIVERS)), db: Session = Depends(get_db)):
    if body.user_id:
        u = get_or_404(db, User, body.user_id, "User")
        if u.role_code != "driver":
            raise bad_request("Linked user must have the driver role")
    d = Driver(**body.model_dump())
    db.add(d)
    db.flush()
    audit.record(db, actor=actor, action="driver.created", category="trip", summary=f"Added driver {d.full_name}", entity_type="driver", entity_id=d.id)
    db.commit()
    return driver_out(d)


@router.put("/drivers/{driver_id}")
def update_driver(driver_id: int, body: DriverPatch, actor: User = Depends(require(Perm.MANAGE_DRIVERS)), db: Session = Depends(get_db)):
    d = get_or_404(db, Driver, driver_id, "Driver")
    data = body.model_dump(exclude_unset=True)
    if data.get("user_id"):
        u = get_or_404(db, User, data["user_id"], "User")
        if u.role_code != "driver":
            raise bad_request("Linked user must have the driver role")
    for k, v in data.items():
        setattr(d, k, v)
    audit.record(db, actor=actor, action="driver.updated", category="trip", summary=f"Updated driver {d.full_name}", entity_type="driver", entity_id=d.id, details={k: str(v) for k, v in data.items()})
    db.commit()
    return driver_out(d)


@router.get("/charging-requests")
def list_requests(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db), open_only: bool = True):
    q = select(ChargingRequest).options(selectinload(ChargingRequest.vehicle))
    if open_only:
        q = q.where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES))
    rows = db.scalars(q.order_by(ChargingRequest.priority_level, ChargingRequest.deadline_at.nulls_last()).limit(500))
    return [{**request_out(r), "vehicle": r.vehicle.registration} for r in rows]
