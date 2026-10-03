from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChargingRequest, ChargingSchedule, ReadinessSnapshot, Trip, Vehicle
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    AlertSeverity,
    AlertType,
    RequestStatus,
    ReservationStatus,
    TripStatus,
)
from app.services import alerts
from app.services.config_service import OperationalConfig
from app.services.tariffs import TariffCalendar


def readiness(db: Session, at: datetime, cfg: OperationalConfig) -> dict:
    horizon = at + timedelta(hours=cfg.readiness_window_hours)
    trips = list(
        db.scalars(
            select(Trip).where(
                Trip.status == TripStatus.ASSIGNED,
                Trip.vehicle_id.is_not(None),
                Trip.departure_at >= at - timedelta(hours=1),
                Trip.departure_at <= horizon,
            )
        )
    )
    seen: set[int] = set()
    rows = []
    for t in sorted(trips, key=lambda t: t.departure_at):
        if t.vehicle_id in seen:
            continue
        seen.add(t.vehicle_id)
        rows.append(t)
    requests = {
        r.vehicle_id: r
        for r in db.scalars(select(ChargingRequest).where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES)))
    }
    vehicles = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(seen or {0})))}
    ready = projected = 0
    at_risk: list[dict] = []
    for t in rows:
        v = vehicles.get(t.vehicle_id)
        if v is None or not v.is_active:
            continue
        req = requests.get(v.id)
        if req is not None and req.trip_id == t.id and req.required_soc is not None:
            required = req.required_soc
        else:
            required = t.required_soc or v.required_departure_soc
        if v.current_soc >= required - 0.5:
            ready += 1
            projected += 1
            continue
        if req is not None and req.trip_id == t.id and req.status == RequestStatus.SCHEDULED:
            projected += 1
            continue
        at_risk.append(
            {
                "vehicle_id": v.id,
                "registration": v.registration,
                "trip_id": t.id,
                "trip_code": t.code,
                "departure_at": t.departure_at,
                "current_soc": v.current_soc,
                "required_soc": required,
                "projected_soc": req.projected_soc if req else v.current_soc,
                "reason": (req.explanation if req else "No charging request has been evaluated yet"),
            }
        )
    total = len(rows)
    return {
        "departures": total,
        "ready_now": ready,
        "projected_ready": projected,
        "at_risk": at_risk,
        "readiness_pct": round(projected / total * 100, 1) if total else 100.0,
        "ready_now_pct": round(ready / total * 100, 1) if total else 100.0,
    }


def evaluate_alerts(db: Session, at: datetime, cfg: OperationalConfig, calendar: TariffCalendar) -> dict:
    state = readiness(db, at, cfg)
    warn_until = at + timedelta(hours=cfg.at_risk_warning_hours)
    for item in state["at_risk"]:
        if item["departure_at"] <= warn_until:
            alerts.raise_alert(
                db,
                type=AlertType.BELOW_REQUIRED_SOC,
                severity=AlertSeverity.CRITICAL,
                title=f"{item['registration']} at risk of missing departure SoC",
                message=(
                    f"Trip {item['trip_code']} departs {item['departure_at'].astimezone(cfg.tz):%H:%M}; current SoC "
                    f"{item['current_soc']:.0f}%, projected {item['projected_soc'] or item['current_soc']:.0f}% vs {item['required_soc']:.0f}% required."
                ),
                dedup_key=f"risk:{item['trip_id']}",
                vehicle_id=item["vehicle_id"],
                trip_id=item["trip_id"],
            )

    if state["departures"] and state["readiness_pct"] < cfg.readiness_threshold_pct:
        alerts.raise_alert(
            db,
            type=AlertType.READINESS_BELOW_THRESHOLD,
            severity=AlertSeverity.WARNING,
            title=f"Fleet readiness {state['readiness_pct']:.0f}% below {cfg.readiness_threshold_pct:.0f}% threshold",
            message=(
                f"{state['projected_ready']} of {state['departures']} departures in the next {cfg.readiness_window_hours:g} h are projected ready; "
                f"{len(state['at_risk'])} at risk."
            ),
            dedup_key="readiness",
        )
    elif state["readiness_pct"] >= cfg.readiness_threshold_pct:
        alerts.auto_resolve(db, "readiness", f"Readiness recovered to {state['readiness_pct']:.0f}%")

    peak_start = calendar.next_kind_start(at, "peak")
    if peak_start is not None and peak_start - at <= timedelta(minutes=cfg.peak_warning_minutes):
        incomplete = list(
            db.execute(
                select(Vehicle.registration)
                .join(ChargingRequest, ChargingRequest.vehicle_id == Vehicle.id)
                .outerjoin(
                    ChargingSchedule,
                    (ChargingSchedule.vehicle_id == Vehicle.id)
                    & ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)),
                )
                .where(
                    ChargingRequest.status.in_(OPEN_REQUEST_STATUSES),
                    ChargingRequest.deadline_at.is_not(None),
                    (ChargingSchedule.id.is_(None)) | (ChargingSchedule.end_at > peak_start),
                )
                .distinct()
            ).scalars()
        )
        if incomplete:
            alerts.raise_alert(
                db,
                type=AlertType.PEAK_APPROACHING,
                severity=AlertSeverity.WARNING,
                title=f"Peak tariff starts {peak_start.astimezone(cfg.tz):%H:%M} with {len(incomplete)} vehicle(s) still charging",
                message=f"Required charging is incomplete for {', '.join(sorted(incomplete)[:8])}{'…' if len(incomplete) > 8 else ''}. Readiness is protected; these sessions will continue into peak if needed.",
                dedup_key=f"peak:{peak_start.isoformat()}",
                details={"vehicles": sorted(incomplete)},
            )
    return state


def snapshot_readiness(db: Session, at: datetime, cfg: OperationalConfig) -> None:
    last = db.scalar(select(func.max(ReadinessSnapshot.recorded_at)))
    if last is not None and at - last < timedelta(hours=1):
        return
    state = readiness(db, at, cfg)
    db.add(
        ReadinessSnapshot(
            recorded_at=at,
            vehicles_with_trip=state["departures"],
            ready_count=state["ready_now"],
            projected_ready_count=state["projected_ready"],
            at_risk_count=len(state["at_risk"]),
            readiness_pct=state["readiness_pct"],
        )
    )
