import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_or_404, require
from app.api.serializers import trip_out
from app.core.errors import bad_request, conflict
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import Driver, Station, Trip, User, Vehicle
from app.models.enums import TripPriority, TripStatus
from app.schemas.fleet import CompleteTripIn, TripIn, TripPatch
from app.services import audit, operations
from app.services.config_service import load_config, now
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed, recalc_if_needed

router = APIRouter(prefix="/trips", tags=["trips"])

MAX_IMPORT_BYTES = 1_000_000


def _next_code(db: Session) -> str:
    n = (db.scalar(select(func.max(Trip.id))) or 0) + 9001
    while db.scalar(select(Trip.id).where(Trip.code == f"TRP-{n}")):
        n += 1
    return f"TRP-{n}"


def _validate_refs(db: Session, vehicle_id: int | None, driver_id: int | None, station_id: int | None) -> Vehicle | None:
    vehicle = get_or_404(db, Vehicle, vehicle_id, "Vehicle") if vehicle_id else None
    if vehicle is not None and not vehicle.is_active:
        raise bad_request(f"{vehicle.registration} is deactivated")
    if driver_id:
        get_or_404(db, Driver, driver_id, "Driver")
    if station_id:
        get_or_404(db, Station, station_id, "Station")
    return vehicle


def _overlap_check(db: Session, vehicle_id: int, departure: datetime, return_at: datetime | None, exclude: int | None = None) -> None:
    end = return_at or departure + timedelta(hours=1)
    q = select(Trip).where(
        Trip.vehicle_id == vehicle_id,
        Trip.status.in_((TripStatus.ASSIGNED, TripStatus.IN_PROGRESS)),
        Trip.departure_at < end,
        func.coalesce(Trip.return_at, Trip.departure_at + timedelta(hours=1)) > departure,
    )
    if exclude:
        q = q.where(Trip.id != exclude)
    clash = db.scalar(q)
    if clash:
        raise conflict(f"Vehicle already has trip {clash.code} in that window")


@router.get("")
def list_trips(
    _: User = Depends(require(Perm.VIEW_FLEET)),
    db: Session = Depends(get_db),
    status_filter: TripStatus | None = Query(default=None, alias="status"),
    vehicle_id: int | None = None,
    search: str | None = Query(default=None, max_length=60),
    upcoming: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
):
    q = select(Trip).options(selectinload(Trip.vehicle), selectinload(Trip.driver), selectinload(Trip.origin_station))
    if status_filter:
        q = q.where(Trip.status == status_filter)
    if vehicle_id:
        q = q.where(Trip.vehicle_id == vehicle_id)
    if upcoming:
        q = q.where(Trip.status.in_((TripStatus.UNASSIGNED, TripStatus.ASSIGNED, TripStatus.IN_PROGRESS)))
    if search:
        like = f"%{search}%"
        q = q.outerjoin(Vehicle, Vehicle.id == Trip.vehicle_id).where(or_(Trip.code.ilike(like), Trip.destination.ilike(like), Vehicle.registration.ilike(like)))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    order = Trip.departure_at.asc() if upcoming else Trip.departure_at.desc()
    rows = db.scalars(q.order_by(order).offset((page - 1) * page_size).limit(page_size))
    return {"items": [trip_out(t) for t in rows], "total": total, "page": page, "page_size": page_size}


def _create(db: Session, body: TripIn, actor: User) -> Trip:
    vehicle = _validate_refs(db, body.vehicle_id, body.driver_id, body.origin_station_id)
    if body.departure_at < now() - timedelta(minutes=5):
        raise bad_request("Departure time is in the past")
    if body.code and db.scalar(select(Trip).where(Trip.code == body.code)):
        raise conflict(f"Trip {body.code} already exists")
    if vehicle is not None:
        _overlap_check(db, vehicle.id, body.departure_at, body.return_at)
    data = body.model_dump()
    data["code"] = body.code or _next_code(db)
    if vehicle is not None and data.get("driver_id") is None:
        data["driver_id"] = vehicle.assigned_driver_id
    trip = Trip(**data, status=TripStatus.ASSIGNED if vehicle else TripStatus.UNASSIGNED)
    db.add(trip)
    db.flush()
    audit.record(db, actor=actor, action="trip.created", category="trip", summary=f"Created trip {trip.code}" + (f" for {vehicle.registration}" if vehicle else " (unassigned)"), entity_type="trip", entity_id=trip.id)
    return trip


@router.post("", status_code=status.HTTP_201_CREATED)
def create_trip(body: TripIn, actor: User = Depends(require(Perm.MANAGE_TRIPS)), db: Session = Depends(get_db)):
    trip = _create(db, body, actor)
    if trip.vehicle_id:
        mark_recalc_needed(db, "trip created", vehicle_ids=[trip.vehicle_id])
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("fleet.updated", {"trip_id": trip.id})
    db.refresh(trip)
    return trip_out(trip)


@router.put("/{trip_id}")
def update_trip(trip_id: int, body: TripPatch, actor: User = Depends(require(Perm.MANAGE_TRIPS)), db: Session = Depends(get_db)):
    trip = get_or_404(db, Trip, trip_id, "Trip")
    if trip.status in (TripStatus.COMPLETED, TripStatus.CANCELLED):
        raise conflict(f"Trip {trip.code} is {trip.status.value} and cannot be changed")
    data = body.model_dump(exclude_unset=True, exclude={"unassign"})
    if data.get("status") not in (None, TripStatus.CANCELLED):
        raise bad_request("Only cancellation can be set directly; departures and arrivals are recorded as events")
    if trip.status == TripStatus.IN_PROGRESS and set(data) - {"return_at", "destination"}:
        raise conflict("Only the return time and destination can change while a trip is in progress")
    vehicle_id = None if body.unassign else data.get("vehicle_id", trip.vehicle_id)
    _validate_refs(db, data.get("vehicle_id"), data.get("driver_id"), None)
    departure = data.get("departure_at", trip.departure_at)
    return_at = data.get("return_at", trip.return_at)
    if return_at and return_at <= departure:
        raise bad_request("Return time must be after departure time")
    if vehicle_id and data.get("status") != TripStatus.CANCELLED:
        _overlap_check(db, vehicle_id, departure, return_at, exclude=trip.id)
    before = {k: str(getattr(trip, k)) for k in data}
    previous_vehicle = trip.vehicle_id
    for k, v in data.items():
        setattr(trip, k, v)
    if body.unassign:
        trip.vehicle_id = None
    if trip.status in (TripStatus.UNASSIGNED, TripStatus.ASSIGNED) and data.get("status") != TripStatus.CANCELLED:
        trip.status = TripStatus.ASSIGNED if trip.vehicle_id else TripStatus.UNASSIGNED
    audit.record(
        db,
        actor=actor,
        action="trip.cancelled" if data.get("status") == TripStatus.CANCELLED else "trip.updated",
        category="trip",
        summary=f"{'Cancelled' if data.get('status') == TripStatus.CANCELLED else 'Updated'} trip {trip.code}",
        entity_type="trip",
        entity_id=trip.id,
        details=audit.diff(before, {k: str(v) for k, v in data.items()}),
    )
    affected = [x for x in (previous_vehicle, trip.vehicle_id) if x]
    mark_recalc_needed(db, "trip changed", vehicle_ids=affected)
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("fleet.updated", {"trip_id": trip.id})
    db.refresh(trip)
    return trip_out(trip)


@router.post("/{trip_id}/complete")
def complete(trip_id: int, body: CompleteTripIn, actor: User = Depends(require(Perm.VEHICLE_EVENTS)), db: Session = Depends(get_db)):
    trip = get_or_404(db, Trip, trip_id, "Trip")
    station = get_or_404(db, Station, body.station_id or trip.origin_station_id, "Station")
    operations.complete_trip(db, trip, body.arrival_soc, station, actor)
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(trip)
    return trip_out(trip)


@router.post("/import")
async def import_trips(file: UploadFile = File(...), actor: User = Depends(require(Perm.MANAGE_TRIPS)), db: Session = Depends(get_db)):
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise bad_request("CSV file is larger than 1 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise bad_request("CSV must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"vehicle", "origin_station", "destination", "distance_km", "departure_at"}
    if not reader.fieldnames or not required <= {f.strip() for f in reader.fieldnames}:
        raise bad_request(f"CSV must include columns: {', '.join(sorted(required))}")
    cfg = load_config(db)
    stations = {s.code: s.id for s in db.scalars(select(Station))}
    vehicles = {v.registration: v.id for v in db.scalars(select(Vehicle).where(Vehicle.is_active.is_(True)))}
    created, errors = [], []
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        try:
            reg = row["vehicle"].upper()
            if reg and reg not in vehicles:
                raise ValueError(f"unknown vehicle {reg}")
            st = row["origin_station"].upper()
            if st not in stations:
                raise ValueError(f"unknown station {st}")
            departure = datetime.fromisoformat(row["departure_at"])
            if departure.tzinfo is None:
                departure = departure.replace(tzinfo=cfg.tz)
            ret = datetime.fromisoformat(row["return_at"]) if row.get("return_at") else None
            if ret is not None and ret.tzinfo is None:
                ret = ret.replace(tzinfo=cfg.tz)
            body = TripIn(
                code=row.get("code") or None,
                vehicle_id=vehicles.get(reg) if reg else None,
                origin_station_id=stations[st],
                destination=row["destination"],
                distance_km=float(row["distance_km"]),
                energy_kwh=float(row["energy_kwh"]) if row.get("energy_kwh") else None,
                required_soc=float(row["required_soc"]) if row.get("required_soc") else None,
                departure_at=departure,
                return_at=ret,
                priority=TripPriority(row.get("priority") or "normal"),
            )
            with db.begin_nested():
                trip = _create(db, body, actor)
            created.append(trip.code)
        except ValidationError as exc:
            errors.append({"line": line, "error": "; ".join(e["msg"] for e in exc.errors())})
        except Exception as exc:  # noqa: BLE001
            message = getattr(exc, "message", None) or str(exc)
            errors.append({"line": line, "error": message})
    if created:
        audit.record(db, actor=actor, action="trip.imported", category="trip", summary=f"Imported {len(created)} trips from {file.filename or 'CSV'} ({len(errors)} rejected)")
        mark_recalc_needed(db, "trips imported")
        recalc_if_needed(db, actor)
    db.commit()
    hub.publish("fleet.updated", {"imported": len(created)})
    return {"created": created, "errors": errors}
