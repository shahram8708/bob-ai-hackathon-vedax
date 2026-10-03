from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Alert,
    Charger,
    ChargingRequest,
    ChargingSchedule,
    ChargingSession,
    ScheduleRun,
    Station,
    Vehicle,
)
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    AlertStatus,
    ChargerStatus,
    RequestStatus,
    ReservationStatus,
    SessionStatus,
    VehicleAvailability,
)
from app.services import monitoring
from app.services.config_service import OperationalConfig
from app.services.scheduler.service import next_trips
from app.services.tariffs import TariffCalendar


def local_midnight(at: datetime, cfg: OperationalConfig) -> datetime:
    local = at.astimezone(cfg.tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def tariff_strip(calendar: TariffCalendar, at: datetime, hours: int = 24, step_minutes: int = 30) -> list[dict]:
    start = at.replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % step_minutes)
    out = []
    for i in range(int(hours * 60 / step_minutes)):
        t = start + timedelta(minutes=step_minutes * i)
        q = calendar.quote(t)
        out.append({"at": t, "kind": q.kind, "rate": q.rate, "name": q.name, "source": q.source})
    return out


def requirement_for(v: Vehicle, trip, request: ChargingRequest | None) -> float:
    if request is not None and request.trip_id is not None and request.required_soc is not None:
        return request.required_soc
    if trip is not None and trip.required_soc is not None:
        return trip.required_soc
    return v.required_departure_soc


def overview(db: Session, at: datetime, cfg: OperationalConfig, calendar: TariffCalendar, station_id: int | None = None) -> dict:
    vq = select(Vehicle).where(Vehicle.is_active.is_(True))
    cq = select(Charger).where(Charger.is_active.is_(True)).options(selectinload(Charger.current_vehicle)).order_by(Charger.code)
    if station_id:
        vq = vq.where(Vehicle.home_station_id == station_id)
        cq = cq.where(Charger.station_id == station_id)
    vehicles = list(db.scalars(vq))
    chargers = list(db.scalars(cq))
    trips = next_trips(db, at)
    requests = {r.vehicle_id: r for r in db.scalars(select(ChargingRequest).where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES)))}
    vehicle_ids = {v.id for v in vehicles}

    ready = 0
    soc_buckets = [0] * 10
    for v in vehicles:
        soc_buckets[min(9, int(v.current_soc // 10))] += 1
        if v.availability in (VehicleAvailability.MAINTENANCE, VehicleAvailability.OUT_OF_SERVICE):
            continue
        if v.current_soc >= requirement_for(v, trips.get(v.id), requests.get(v.id)) - 0.5:
            ready += 1

    sessions = list(
        db.scalars(
            select(ChargingSession)
            .where(ChargingSession.status == SessionStatus.ACTIVE)
            .options(selectinload(ChargingSession.vehicle), selectinload(ChargingSession.charger), selectinload(ChargingSession.schedule))
        )
    )
    sessions = [s for s in sessions if s.vehicle_id in vehicle_ids or not station_id]
    midnight = local_midnight(at, cfg)
    today_sessions = list(db.scalars(select(ChargingSession).where(ChargingSession.started_at >= midnight)))
    energy_today = sum(s.energy_kwh for s in today_sessions)
    cost_today = sum(s.cost for s in today_sessions)
    horizon_end = at + timedelta(hours=cfg.horizon_hours)
    planned = list(
        db.scalars(
            select(ChargingSchedule).where(
                ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.ACTIVE)),
                ChargingSchedule.end_at > at,
                ChargingSchedule.start_at < horizon_end,
            )
        )
    )
    planned = [p for p in planned if p.vehicle_id in vehicle_ids or not station_id]
    scheduled_energy = sum(p.planned_energy_kwh for p in planned if p.status == ReservationStatus.PLANNED)
    scheduled_cost = sum(p.estimated_cost for p in planned if p.status == ReservationStatus.PLANNED)

    state = monitoring.readiness(db, at, cfg)
    at_risk = [r for r in state["at_risk"] if r["vehicle_id"] in vehicle_ids or not station_id]

    status_counts = {s.value: 0 for s in ChargerStatus}
    for c in chargers:
        status_counts[c.status.value] += 1

    alert_counts = dict(
        db.execute(select(Alert.severity, func.count()).where(Alert.status != AlertStatus.RESOLVED).group_by(Alert.severity)).all()
    )
    recent_alerts = list(db.scalars(select(Alert).where(Alert.status != AlertStatus.RESOLVED).order_by(Alert.created_at.desc()).limit(6)))
    last_run = db.scalar(select(ScheduleRun).order_by(ScheduleRun.id.desc()).limit(1))
    quote = calendar.quote(at)
    change = calendar.next_change(at)
    next_peak = calendar.next_kind_start(at, "peak") if quote.kind != "peak" else None
    stations = {s.id: s for s in db.scalars(select(Station))}
    session_by_charger = {s.charger_id: s for s in sessions}
    reservation_by_charger: dict[int, ChargingSchedule] = {}
    for p in sorted(planned, key=lambda p: p.start_at):
        if p.status == ReservationStatus.PLANNED:
            reservation_by_charger.setdefault(p.charger_id, p)

    def charger_view(c: Charger) -> dict:
        s = session_by_charger.get(c.id)
        nxt = reservation_by_charger.get(c.id)
        return {
            "id": c.id,
            "code": c.code,
            "station_id": c.station_id,
            "station_code": stations[c.station_id].code,
            "connector_type": c.connector_type,
            "max_power_kw": c.max_power_kw,
            "status": c.status.value,
            "status_note": c.status_note,
            "ocpp_connected": c.ocpp_connected,
            "session": {
                "id": s.id,
                "vehicle_id": s.vehicle_id,
                "registration": s.vehicle.registration,
                "soc": s.vehicle.current_soc,
                "target_soc": s.target_soc,
                "power_kw": s.power_kw,
                "energy_kwh": round(s.energy_kwh, 2),
                "cost": round(s.cost, 2),
                "ends_at": s.schedule.end_at if s.schedule else None,
                "source": s.source.value,
            }
            if s
            else None,
            "next_reservation": {"vehicle_id": nxt.vehicle_id, "start_at": nxt.start_at, "end_at": nxt.end_at} if nxt else None,
        }

    vehicle_reg = {v.id: v.registration for v in vehicles}
    return {
        "as_of": at,
        "timezone": cfg.timezone,
        "currency": cfg.currency,
        "kpis": {
            "total_vehicles": len(vehicles),
            "ready_vehicles": ready,
            "vehicles_requiring_charge": sum(1 for vid in requests if vid in vehicle_ids),
            "vehicles_charging": len(sessions),
            "vehicles_at_risk": len(at_risk),
            "vehicles_on_trip": sum(1 for v in vehicles if v.availability == VehicleAvailability.ON_TRIP),
            "available_chargers": status_counts["available"],
            "fault_chargers": status_counts["fault"],
            "maintenance_chargers": status_counts["maintenance"],
            "total_chargers": len(chargers),
            "current_power_kw": round(sum(s.power_kw for s in sessions), 1),
            "energy_today_kwh": round(energy_today, 1),
            "cost_today": round(cost_today, 2),
            "active_session_cost": round(sum(s.cost for s in sessions), 2),
            "scheduled_energy_kwh": round(scheduled_energy, 1),
            "scheduled_cost": round(scheduled_cost, 2),
            "active_reservations": len(planned),
            "readiness_pct": state["readiness_pct"],
            "departures_window": state["departures"],
            "open_alerts": sum(alert_counts.values()),
            "critical_alerts": alert_counts.get("critical", 0),
        },
        "soc_distribution": [{"range": f"{i * 10}–{i * 10 + 10}%", "count": n} for i, n in enumerate(soc_buckets)],
        "charger_status": status_counts,
        "chargers": [charger_view(c) for c in chargers],
        "at_risk": at_risk,
        "recent_alerts": [
            {"id": a.id, "type": a.type.value, "severity": a.severity.value, "status": a.status.value, "title": a.title, "created_at": a.created_at}
            for a in recent_alerts
        ],
        "queue": [
            {
                "vehicle_id": r.vehicle_id,
                "registration": vehicle_reg.get(r.vehicle_id, "?"),
                "status": r.status.value,
                "priority_level": r.priority_level,
                "target_soc": r.target_soc,
                "current_soc": r.current_soc,
                "deadline_at": r.deadline_at,
            }
            for r in sorted(requests.values(), key=lambda r: (r.priority_level, r.deadline_at or horizon_end))
            if r.vehicle_id in vehicle_ids and r.status in (RequestStatus.UNSCHEDULED, RequestStatus.AT_RISK)
        ][:20],
        "tariff": {
            "current": {"kind": quote.kind, "name": quote.name, "rate": quote.rate, "source": quote.source},
            "next_change": {"at": change[0], "kind": change[1].kind, "rate": change[1].rate, "name": change[1].name} if change else None,
            "next_peak_at": next_peak,
            "strip": tariff_strip(calendar, at),
        },
        "scheduler": {
            "mode": cfg.scheduler_mode.value,
            "last_run": {
                "id": last_run.id,
                "created_at": last_run.created_at,
                "trigger": last_run.trigger,
                "status": last_run.status.value,
                "duration_ms": last_run.duration_ms,
                "at_risk": last_run.at_risk_count,
                "conflicts_prevented": last_run.conflicts_prevented,
            }
            if last_run
            else None,
        },
        "simulation": {"enabled": cfg.simulation_enabled, "clock_offset_seconds": cfg.clock_offset_seconds},
    }
