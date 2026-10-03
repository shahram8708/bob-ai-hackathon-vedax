from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_or_404, require
from app.api.serializers import alert_out
from app.core.errors import bad_request, not_found
from app.core.permissions import Perm
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Alert, ChargingSchedule, EnergyReading, Station, User
from app.models.enums import AlertSeverity, AlertStatus, AlertType, ReservationStatus
from app.schemas.operations import AdvanceIn, AlertActionIn, AlertIn, ResetIn, ResolveIn
from app.services import alerts as alert_service
from app.services import audit, reports
from app.services.advisory import v2g_opportunities
from app.services.config_service import load_config, now, save_config
from app.services.dashboard import overview
from app.services.events import hub
from app.services.scheduler.service import run_scheduler
from app.services.seed import reset_operational_data
from app.services.tariffs import load_calendar

router = APIRouter(tags=["monitoring"])


@router.get("/dashboard/overview")
def dashboard_overview(_: User = Depends(require(Perm.VIEW_DASHBOARD)), db: Session = Depends(get_db), station_id: int | None = None):
    cfg = load_config(db)
    at = now()
    calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(hours=1), at + timedelta(hours=49))
    return overview(db, at, cfg, calendar, station_id)


@router.get("/dashboard/energy")
def dashboard_energy(_: User = Depends(require(Perm.VIEW_DASHBOARD)), db: Session = Depends(get_db), days: int = Query(default=14, ge=1, le=90)):
    cfg = load_config(db)
    at = now()
    calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(days=days), at + timedelta(hours=26))
    rng = reports.make_range(cfg, at.astimezone(cfg.tz).date() - timedelta(days=days - 1), None, at)
    cost = reports.cost_by_period(db, rng, cfg, calendar, at)
    trend = reports.peak_distribution(db, rng, cfg)
    by_station = reports.energy_consumption(db, rng, cfg, "station")
    step = timedelta(minutes=15)
    origin = at.replace(second=0, microsecond=0) - timedelta(minutes=at.minute % 15)
    buckets = [origin - timedelta(hours=6) + step * i for i in range(int(30 * 4))]
    planned = list(
        db.scalars(
            select(ChargingSchedule).where(
                ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)),
                ChargingSchedule.end_at > buckets[0],
                ChargingSchedule.start_at < buckets[-1] + step,
            )
        )
    )
    readings = list(
        db.execute(
            select(func.date_trunc("minute", EnergyReading.recorded_at).label("m"), func.sum(EnergyReading.power_kw))
            .where(EnergyReading.recorded_at >= buckets[0], EnergyReading.recorded_at <= at)
            .group_by("m")
        ).all()
    )
    measured: dict = {}
    for minute, kw in readings:
        b = minute - timedelta(minutes=minute.minute % 15)
        measured[b] = max(measured.get(b, 0.0), float(kw or 0))
    station_ids = [s.id for s in db.scalars(select(Station))]
    profile = []
    for b in buckets:
        load = sum(r.power_kw for r in planned if r.start_at < b + step and r.end_at > b and b >= at - step)
        q = calendar.quote(b + step / 2)
        profile.append(
            {
                "at": b,
                "planned_kw": round(load, 1) if b >= at - step else None,
                "measured_kw": round(measured[b], 1) if b in measured else None,
                "rate": q.rate,
                "kind": q.kind,
                "solar_kw": round(sum(calendar.solar_kw(b, sid) for sid in station_ids), 1),
            }
        )
    return {
        "as_of": at,
        "currency": cfg.currency,
        "cost": cost.as_dict(),
        "trend": trend.as_dict(),
        "by_station": by_station.as_dict(),
        "load_profile": profile,
        "v2g": v2g_opportunities(db, calendar, at, cfg),
        "simulated": True,
    }


@router.get("/alerts")
def list_alerts(
    _: User = Depends(require(Perm.VIEW_DASHBOARD)),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default="active", alias="status", pattern="^(active|open|acknowledged|resolved|all)$"),
    severity: AlertSeverity | None = None,
    type_filter: AlertType | None = Query(default=None, alias="type"),
    vehicle_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
):
    q = select(Alert).options(selectinload(Alert.vehicle), selectinload(Alert.charger))
    if status_filter == "active":
        q = q.where(Alert.status != AlertStatus.RESOLVED)
    elif status_filter in ("open", "acknowledged", "resolved"):
        q = q.where(Alert.status == AlertStatus(status_filter))
    if severity:
        q = q.where(Alert.severity == severity)
    if type_filter:
        q = q.where(Alert.type == type_filter)
    if vehicle_id:
        q = q.where(Alert.vehicle_id == vehicle_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Alert.status, Alert.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    counts = dict(db.execute(select(Alert.status, func.count()).group_by(Alert.status)).all())
    return {"items": [alert_out(a) for a in rows], "total": total, "page": page, "page_size": page_size, "counts": {k.value if hasattr(k, "value") else k: v for k, v in counts.items()}}


@router.post("/alerts", status_code=status.HTTP_201_CREATED)
def create_alert(body: AlertIn, actor: User = Depends(require(Perm.MANAGE_ALERTS)), db: Session = Depends(get_db)):
    alert = alert_service.raise_alert(
        db,
        type=AlertType.MANUAL_EXCEPTION,
        severity=body.severity,
        title=body.title,
        message=body.message,
        vehicle_id=body.vehicle_id,
        charger_id=body.charger_id,
        station_id=body.station_id,
        created_by=actor,
    )
    audit.record(db, actor=actor, action="alert.recorded", category="exception", summary=f"Recorded exception: {body.title}", entity_type="alert", entity_id=alert.id)
    db.commit()
    db.refresh(alert)
    return alert_out(alert)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int, body: AlertActionIn, actor: User = Depends(require(Perm.MANAGE_ALERTS)), db: Session = Depends(get_db)):
    alert = get_or_404(db, Alert, alert_id, "Alert")
    alert_service.acknowledge(db, alert, actor, body.note or None)
    db.commit()
    db.refresh(alert)
    return alert_out(alert)


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, body: ResolveIn, actor: User = Depends(require(Perm.MANAGE_ALERTS)), db: Session = Depends(get_db)):
    alert = get_or_404(db, Alert, alert_id, "Alert")
    alert_service.resolve(db, alert, actor, body.note)
    db.commit()
    db.refresh(alert)
    return alert_out(alert)


REPORTS = {
    "charging-history": "Vehicle charging history",
    "charger-utilization": "Charger utilization",
    "energy-by-vehicle": "Energy consumption by vehicle",
    "energy-by-station": "Energy consumption by station",
    "cost-by-period": "Energy cost by tariff period",
    "missed-at-risk": "Missed or at-risk charging requirements",
    "scheduled-vs-actual": "Scheduled versus actual charging time",
    "readiness": "Fleet readiness report",
    "peak-distribution": "Peak versus off-peak charging distribution",
    "exceptions": "Exception and fault history",
    "summary-daily": "Daily fleet charging summary",
    "summary-weekly": "Weekly fleet charging summary",
    "summary-monthly": "Monthly fleet charging summary",
}


def _build(key: str, db: Session, start: date | None, end: date | None, vehicle_id: int | None, station_id: int | None) -> reports.Report:
    cfg = load_config(db)
    at = now()
    rng = reports.make_range(cfg, start, end, at)
    if key == "charging-history":
        return reports.charging_history(db, rng, cfg, vehicle_id, station_id)
    if key == "charger-utilization":
        return reports.charger_utilization(db, rng, cfg, at)
    if key == "energy-by-vehicle":
        return reports.energy_consumption(db, rng, cfg, "vehicle")
    if key == "energy-by-station":
        return reports.energy_consumption(db, rng, cfg, "station")
    if key == "cost-by-period":
        calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, rng.start, rng.end)
        return reports.cost_by_period(db, rng, cfg, calendar, at)
    if key == "missed-at-risk":
        return reports.missed_requirements(db, rng, cfg, at)
    if key == "scheduled-vs-actual":
        return reports.scheduled_vs_actual(db, rng, cfg, at)
    if key == "readiness":
        return reports.readiness_report(db, rng, cfg, at)
    if key == "peak-distribution":
        return reports.peak_distribution(db, rng, cfg)
    if key == "exceptions":
        return reports.exception_history(db, rng, cfg)
    if key.startswith("summary-"):
        return reports.summary(db, cfg, key.split("-", 1)[1], at)
    raise not_found("Report")


def _respond(report: reports.Report, fmt: str, start: date | None, end: date | None):
    if fmt == "csv":
        suffix = f"_{start or ''}_{end or ''}".rstrip("_")
        return Response(
            content=report.as_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="chargeopt_{report.key}{suffix}.csv"'},
        )
    return report.as_dict()


@router.get("/reports")
def report_catalog(_: User = Depends(require(Perm.VIEW_REPORTS))):
    return [{"key": k, "title": v} for k, v in REPORTS.items()]


@router.get("/reports/metrics")
def metrics(_: User = Depends(require(Perm.VIEW_REPORTS)), db: Session = Depends(get_db), days: int = Query(default=30, ge=1, le=365)):
    cfg = load_config(db)
    return reports.success_metrics(db, cfg, now(), days)


@router.get("/reports/energy")
def report_energy(_: User = Depends(require(Perm.VIEW_REPORTS)), db: Session = Depends(get_db), start: date | None = None, end: date | None = None, group: str = Query(default="vehicle", pattern="^(vehicle|station)$"), format: str = Query(default="json", pattern="^(json|csv)$")):
    return _respond(_build(f"energy-by-{group}", db, start, end, None, None), format, start, end)


@router.get("/reports/cost")
def report_cost(_: User = Depends(require(Perm.VIEW_REPORTS)), db: Session = Depends(get_db), start: date | None = None, end: date | None = None, format: str = Query(default="json", pattern="^(json|csv)$")):
    return _respond(_build("cost-by-period", db, start, end, None, None), format, start, end)


@router.get("/reports/readiness")
def report_readiness(_: User = Depends(require(Perm.VIEW_REPORTS)), db: Session = Depends(get_db), start: date | None = None, end: date | None = None, format: str = Query(default="json", pattern="^(json|csv)$")):
    return _respond(_build("readiness", db, start, end, None, None), format, start, end)


@router.get("/reports/{key}")
def report(
    key: str,
    _: User = Depends(require(Perm.VIEW_REPORTS)),
    db: Session = Depends(get_db),
    start: date | None = None,
    end: date | None = None,
    vehicle_id: int | None = None,
    station_id: int | None = None,
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    if key not in REPORTS:
        raise not_found("Report")
    if start and end and (end - start).days > 366:
        raise bad_request("Report range is limited to one year")
    return _respond(_build(key, db, start, end, vehicle_id, station_id), format, start, end)


@router.get("/v2g/opportunities")
def v2g(_: User = Depends(require(Perm.VIEW_DASHBOARD)), db: Session = Depends(get_db)):
    cfg = load_config(db)
    at = now()
    return v2g_opportunities(db, load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(hours=1), at + timedelta(hours=32)), at, cfg)


@router.get("/simulation")
def simulation_state(_: User = Depends(require(Perm.VIEW_DASHBOARD)), db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {"enabled": cfg.simulation_enabled, "available": get_settings().simulation_enabled, "clock_offset_seconds": cfg.clock_offset_seconds, "now": now(), "timezone": cfg.timezone, "websocket_clients": hub.client_count}


@router.put("/simulation")
def toggle_simulation(body: dict, actor: User = Depends(require(Perm.CONTROL_SIMULATION)), db: Session = Depends(get_db)):
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise bad_request("Provide enabled: true or false")
    cfg = load_config(db)
    cfg.simulation_enabled = enabled
    save_config(db, cfg, actor.id)
    audit.record(db, actor=actor, action="simulation.toggled", category="simulation", summary=f"Charger telemetry simulation {'resumed' if enabled else 'paused'}")
    db.commit()
    hub.publish("config.updated", {"simulation": enabled})
    return {"enabled": enabled}


@router.post("/simulation/advance")
def advance(body: AdvanceIn, request: Request, actor: User = Depends(require(Perm.CONTROL_SIMULATION))):
    return request.app.state.simulation.advance(body.minutes, actor)


@router.post("/simulation/reset")
def reset(body: ResetIn, actor: User = Depends(require(Perm.CONTROL_SIMULATION)), db: Session = Depends(get_db)):
    if actor.role_code != "admin":
        raise bad_request("Only administrators can regenerate the demo scenario")
    summary = reset_operational_data(db, actor, simulation_enabled=body.simulation_enabled, scheduler_mode=body.scheduler_mode, history_days=body.history_days)
    db.flush()
    run_scheduler(db, trigger="demo scenario generated", user=actor)
    db.commit()
    hub.publish("schedule.updated", {"reset": True})
    hub.publish("fleet.updated", {"reset": True})
    return summary
