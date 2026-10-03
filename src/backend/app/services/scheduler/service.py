import logging
import threading
import time as _time
from datetime import datetime, time, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Charger,
    ChargingRequest,
    ChargingSchedule,
    ChargingSession,
    ScheduleRun,
    Station,
    Trip,
    User,
    Vehicle,
)
from app.models.enums import (
    OPEN_REQUEST_STATUSES,
    ChargerStatus,
    RequestStatus,
    ReservationStatus,
    RunStatus,
    SchedulerMode,
    SessionStatus,
    TripStatus,
    VehicleAvailability,
)
from app.services import audit
from app.services.config_service import OperationalConfig, load_config, now
from app.services.events import hub
from app.services.scheduler.engine import (
    ChargerState,
    EngineConfig,
    FixedBooking,
    PlanResult,
    Scheduler,
    StationState,
    TripRequirement,
    VehicleState,
)
from app.services.tariffs import TariffCalendar, load_calendar

log = logging.getLogger("chargeopt.scheduler")

SCHEDULER_LOCK = 7_412_001
USABLE_CHARGER_STATES = (ChargerStatus.AVAILABLE, ChargerStatus.CHARGING, ChargerStatus.RESERVED)
LIVE_RESERVATIONS = (ReservationStatus.PLANNED, ReservationStatus.ACTIVE)


def engine_config(cfg: OperationalConfig, mode: SchedulerMode | str | None = None) -> EngineConfig:
    return EngineConfig(
        mode=str(mode or cfg.scheduler_mode),
        slot_minutes=cfg.slot_minutes,
        horizon_hours=cfg.horizon_hours,
        departure_buffer_minutes=cfg.departure_buffer_minutes,
        urgent_window_hours=cfg.urgent_window_hours,
        flex_slack_minutes=cfg.flex_slack_minutes,
        tariff_optimization=cfg.tariff_optimization,
        emergency_override=cfg.emergency_override,
        tie_breakers=tuple(cfg.tie_breakers),
        required_soc_mode=cfg.required_soc_mode,
        safety_reserve_type=cfg.safety_reserve_type,
        safety_reserve_value=cfg.safety_reserve_value,
        currency=cfg.currency,
    )


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour) % 24, int(minute))


def availability_windows(schedule: list[dict] | None):
    if not schedule:
        return None
    return tuple(
        (frozenset(w.get("days", list(range(7)))), _parse_hhmm(w["start"]), _parse_hhmm(w["end"]))
        for w in schedule
    )


def next_trips(db: Session, at: datetime) -> dict[int, Trip]:
    rows = db.scalars(
        select(Trip)
        .where(
            Trip.status == TripStatus.ASSIGNED,
            Trip.vehicle_id.is_not(None),
            Trip.departure_at >= at - timedelta(hours=6),
        )
        .order_by(Trip.departure_at)
    )
    result: dict[int, Trip] = {}
    for trip in rows:
        result.setdefault(trip.vehicle_id, trip)
    return result


def session_end_estimate(s: ChargingSession, at: datetime) -> datetime:
    if s.schedule is not None and s.schedule.end_at > at:
        return s.schedule.end_at
    vehicle = s.vehicle
    remaining = max(0.0, (s.target_soc - vehicle.current_soc) / 100 * vehicle.battery_capacity_kwh)
    hours = remaining / max(s.power_kw, 0.1) / vehicle.battery_profile.charging_efficiency
    return at + timedelta(hours=max(hours, 1 / 60))


def build_snapshot(db: Session, at: datetime, cfg: OperationalConfig, calendar: TariffCalendar | None = None):
    trips = next_trips(db, at)
    open_requests = {
        r.vehicle_id: r
        for r in db.scalars(select(ChargingRequest).where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES)))
    }
    vehicles = []
    for v in db.scalars(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.registration)):
        p = v.battery_profile
        trip = trips.get(v.id)
        held = v.charging_hold_until is not None and v.charging_hold_until > at
        schedulable = (
            v.availability in (VehicleAvailability.AVAILABLE, VehicleAvailability.CHARGING)
            and v.current_station_id is not None
            and not held
        )
        vehicles.append(
            VehicleState(
                id=v.id,
                registration=v.registration,
                station_id=v.current_station_id,
                schedulable=schedulable,
                availability="held by operator" if held else v.availability.value,
                current_soc=v.current_soc,
                capacity_kwh=v.battery_capacity_kwh,
                min_soc=v.min_operating_soc,
                default_target_soc=v.required_departure_soc,
                max_soc=v.max_soc,
                priority_category=v.priority_category.value,
                connectors=frozenset(p.connector_types),
                max_ac_kw=p.max_ac_kw,
                max_dc_kw=p.max_dc_kw,
                efficiency=p.charging_efficiency,
                created_at=v.created_at,
                trip=TripRequirement(
                    trip_id=trip.id,
                    code=trip.code,
                    departure_at=trip.departure_at,
                    required_soc=trip.required_soc,
                    energy_kwh=trip.energy_kwh if trip.energy_kwh is not None else trip.distance_km * p.consumption_kwh_per_km,
                    priority=trip.priority.value,
                )
                if trip
                else None,
                request_created_at=open_requests[v.id].created_at if v.id in open_requests else None,
            )
        )
    chargers = [
        ChargerState(
            id=c.id,
            code=c.code,
            station_id=c.station_id,
            connector=c.connector_type,
            power_kw=c.effective_power_kw,
            usable=c.status in USABLE_CHARGER_STATES,
            availability=availability_windows(c.availability_schedule),
        )
        for c in db.scalars(select(Charger).where(Charger.is_active.is_(True)).order_by(Charger.code))
    ]
    stations = [StationState(s.id, s.code, s.max_load_kw) for s in db.scalars(select(Station).where(Station.is_active.is_(True)))]
    fixed: list[FixedBooking] = []
    for s in db.scalars(
        select(ChargingSession)
        .where(ChargingSession.status == SessionStatus.ACTIVE)
        .options(selectinload(ChargingSession.schedule), selectinload(ChargingSession.vehicle))
    ):
        end = session_end_estimate(s, at)
        fixed.append(FixedBooking(s.vehicle_id, s.charger_id, at, end, s.power_kw, 0, "session", s.target_soc, s.schedule_id))
    for r in db.scalars(
        select(ChargingSchedule).where(
            ChargingSchedule.is_override.is_(True),
            ChargingSchedule.status == ReservationStatus.PLANNED,
            ChargingSchedule.end_at > at,
        )
    ):
        fixed.append(FixedBooking(r.vehicle_id, r.charger_id, max(r.start_at, at), r.end_at, r.power_kw, r.planned_energy_kwh, "override", r.target_soc, r.id))
    if calendar is None:
        calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(hours=1), at + timedelta(hours=cfg.horizon_hours + 1))
    return vehicles, chargers, stations, fixed, calendar


_compute_lock = threading.RLock()
_cache: dict[tuple, tuple[float, object]] = {}
CACHE_TTL_SECONDS = 45


def state_key(db: Session, cfg: OperationalConfig) -> tuple:
    latest = db.execute(select(ScheduleRun.id).order_by(ScheduleRun.id.desc()).limit(1)).scalar()
    return (latest, cfg.model_dump_json(), now().replace(second=0).isoformat())


def cached(key: tuple, compute):
    """Single-flight cache: concurrent identical requests share one computation."""
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    with _compute_lock:
        hit = _cache.get(key)
        if hit and _time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        value = compute()
        for k in [k for k, (t, _) in _cache.items() if _time.monotonic() - t >= CACHE_TTL_SECONDS]:
            _cache.pop(k, None)
        _cache[key] = (_time.monotonic(), value)
        return value


def preview_plan(db: Session, mode: SchedulerMode | str, cfg: OperationalConfig | None = None, at: datetime | None = None) -> PlanResult:
    cfg = cfg or load_config(db)
    at = at or now()

    def compute() -> PlanResult:
        vehicles, chargers, stations, fixed, calendar = build_snapshot(db, at, cfg)
        return Scheduler(engine_config(cfg, mode), calendar, vehicles, chargers, stations, fixed).plan(at)

    return cached(("plan", str(mode), *state_key(db, cfg)), compute)


def _key(start: datetime, end: datetime, vehicle_id: int, charger_id: int) -> tuple:
    return (vehicle_id, charger_id, start.replace(second=0, microsecond=0), end.replace(second=0, microsecond=0))


def run_scheduler(db: Session, *, trigger: str, user: User | None = None, context: dict | None = None) -> tuple[ScheduleRun, PlanResult]:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK})
    cfg = load_config(db)
    at = now()
    started = _time.perf_counter()
    vehicles, chargers, stations, fixed, calendar = build_snapshot(db, at, cfg)
    plan = Scheduler(engine_config(cfg), calendar, vehicles, chargers, stations, fixed).plan(at)
    elapsed_ms = (_time.perf_counter() - started) * 1000

    context = context or {}
    approval = cfg.require_schedule_approval
    run = ScheduleRun(
        created_at=at,
        planning_time=at,
        trigger=trigger[:80],
        mode=cfg.scheduler_mode,
        status=RunStatus.PENDING_APPROVAL if approval else RunStatus.APPLIED,
        triggered_by_id=user.id if user else None,
        duration_ms=round(elapsed_ms, 1),
        summary={},
    )
    db.add(run)
    db.flush()

    requests = _sync_requests(db, plan, run, at, context)

    existing = list(
        db.scalars(
            select(ChargingSchedule).where(
                ChargingSchedule.is_override.is_(False),
                ChargingSchedule.status.in_((ReservationStatus.PLANNED, ReservationStatus.PROPOSED)),
            )
        )
    )
    by_key = {_key(r.start_at, r.end_at, r.vehicle_id, r.charger_id): r for r in existing if r.status == ReservationStatus.PLANNED}
    keep_ids: set[int] = set()
    created = 0
    new_rows: list[ChargingSchedule] = []
    for res in plan.reservations:
        match = by_key.get(_key(res.start, res.end, res.vehicle_id, res.charger_id))
        request = requests.get(res.vehicle_id)
        rules = list(res.rules)
        if context.get("rule") and context.get("vehicle_ids") and res.vehicle_id in context["vehicle_ids"]:
            rules = sorted(set(rules) | {context["rule"]})
        if match is not None:
            keep_ids.add(match.id)
            match.run_id = run.id
            match.explanation = res.explanation
            match.rules = rules
            match.request_id = request.id if request else None
            match.estimated_cost = res.cost
            continue
        row = ChargingSchedule(
            run_id=run.id,
            request_id=request.id if request else None,
            vehicle_id=res.vehicle_id,
            charger_id=res.charger_id,
            start_at=res.start,
            end_at=res.end,
            power_kw=res.power_kw,
            planned_energy_kwh=res.energy_kwh,
            estimated_cost=res.cost,
            target_soc=res.target_soc,
            priority_level=res.priority_level,
            status=ReservationStatus.PROPOSED if approval else ReservationStatus.PLANNED,
            is_override=False,
            rules=rules,
            explanation=res.explanation,
            tariff_mix=res.tariff_mix,
        )
        new_rows.append(row)
        created += 1

    superseded = 0
    for r in existing:
        if r.id in keep_ids:
            continue
        if r.status == ReservationStatus.PROPOSED or not approval:
            r.status = ReservationStatus.SUPERSEDED
            superseded += 1
    db.flush()
    db.add_all(new_rows)
    db.flush()

    m = plan.metrics
    run.vehicles_evaluated = m["vehicles_evaluated"]
    run.vehicles_needing_charge = m["vehicles_needing_charge"]
    run.reservations_created = created
    run.reservations_kept = len(keep_ids)
    run.reservations_superseded = superseded
    run.conflicts_prevented = m["conflicts_prevented"]
    run.at_risk_count = m["at_risk"]
    run.planned_energy_kwh = m["planned_energy_kwh"]
    run.planned_cost = m["planned_cost"]
    run.summary = {**m, "context": {k: v for k, v in context.items() if k != "vehicle_ids"}}

    if created or superseded or user is not None:
        audit.record(
            db,
            actor=user,
            action="schedule.recalculated",
            category="schedule",
            summary=(
                f"Schedule run #{run.id} ({cfg.scheduler_mode.value.replace('_', '-')}, trigger: {trigger}) — "
                f"{created} new, {len(keep_ids)} kept, {superseded} superseded, {m['at_risk']} at risk"
            ),
            entity_type="schedule_run",
            entity_id=run.id,
            details={"duration_ms": run.duration_ms, "status": run.status.value},
        )
    log.info("Schedule run %s (%s) in %.0f ms: %s created, %s superseded", run.id, trigger, elapsed_ms, created, superseded)
    hub.publish("schedule.updated", {"run_id": run.id, "trigger": trigger, "status": run.status.value})
    return run, plan


_STATUS_MAP = {
    "scheduled": RequestStatus.SCHEDULED,
    "locked": RequestStatus.SCHEDULED,
    "at_risk": RequestStatus.AT_RISK,
    "unscheduled": RequestStatus.UNSCHEDULED,
}


def _sync_requests(db: Session, plan: PlanResult, run: ScheduleRun, at: datetime, context: dict) -> dict[int, ChargingRequest]:
    open_rows = {
        r.vehicle_id: r for r in db.scalars(select(ChargingRequest).where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES)))
    }
    result: dict[int, ChargingRequest] = {}
    for d in plan.decisions:
        row = open_rows.get(d.vehicle_id)
        if d.status == "satisfied":
            if row is not None:
                row.status = RequestStatus.SATISFIED
                row.closed_at = at
                row.explanation = d.explanation
                row.rules = d.rules
            continue
        if d.status == "away":
            continue
        status = _STATUS_MAP.get(d.status)
        if status is None:
            continue
        if row is not None and row.trip_id != d.trip_id:
            row.status = RequestStatus.CANCELLED
            row.closed_at = at
            row.explanation = "Superseded by a new trip requirement"
            db.flush()
            row = None
        if row is None:
            row = ChargingRequest(vehicle_id=d.vehicle_id, trip_id=d.trip_id, status=status, current_soc=d.current_soc, target_soc=d.target_soc, energy_needed_kwh=d.grid_kwh, priority_level=d.priority_level)
            db.add(row)
        rules = list(d.rules)
        if context.get("rule") and d.vehicle_id in context.get("vehicle_ids", ()):
            rules = sorted(set(rules) | {context["rule"]})
        row.run_id = run.id
        row.status = status
        row.priority_level = d.priority_level
        row.flexible = d.flexible
        row.current_soc = d.current_soc
        row.target_soc = d.target_soc
        row.required_soc = d.required_soc
        row.energy_needed_kwh = d.grid_kwh
        row.deadline_at = d.deadline
        row.projected_soc = d.projected_soc
        row.shortfall_kwh = d.shortfall_kwh
        row.rules = rules
        row.explanation = d.explanation
        result[d.vehicle_id] = row
    db.flush()
    return result


def approve_run(db: Session, run: ScheduleRun, user: User) -> ScheduleRun:
    proposed = list(db.scalars(select(ChargingSchedule).where(ChargingSchedule.run_id == run.id, ChargingSchedule.status == ReservationStatus.PROPOSED)))
    for r in db.scalars(
        select(ChargingSchedule).where(
            ChargingSchedule.status == ReservationStatus.PLANNED,
            ChargingSchedule.is_override.is_(False),
            ChargingSchedule.run_id != run.id,
        )
    ):
        r.status = ReservationStatus.SUPERSEDED
    db.flush()
    for r in proposed:
        r.status = ReservationStatus.PLANNED
    for older in db.scalars(select(ScheduleRun).where(ScheduleRun.status == RunStatus.PENDING_APPROVAL, ScheduleRun.id != run.id)):
        older.status = RunStatus.REJECTED
    run.status = RunStatus.APPROVED
    run.approved_by_id = user.id
    run.approved_at = now()
    audit.record(db, actor=user, action="schedule.approved", category="schedule", summary=f"Approved schedule run #{run.id} ({len(proposed)} reservations)", entity_type="schedule_run", entity_id=run.id)
    hub.publish("schedule.updated", {"run_id": run.id, "status": "approved"})
    return run


def reject_run(db: Session, run: ScheduleRun, user: User, reason: str) -> ScheduleRun:
    for r in db.scalars(select(ChargingSchedule).where(ChargingSchedule.run_id == run.id, ChargingSchedule.status == ReservationStatus.PROPOSED)):
        r.status = ReservationStatus.CANCELLED
    run.status = RunStatus.REJECTED
    run.approved_by_id = user.id
    run.approved_at = now()
    audit.record(db, actor=user, action="schedule.rejected", category="schedule", summary=f"Rejected schedule run #{run.id}: {reason}", entity_type="schedule_run", entity_id=run.id, details={"reason": reason})
    hub.publish("schedule.updated", {"run_id": run.id, "status": "rejected"})
    return run


def mark_recalc_needed(db: Session, reason: str, rule: str | None = None, vehicle_ids: list[int] | None = None) -> None:
    pending = db.info.setdefault("recalc", {"reasons": [], "rule": None, "vehicle_ids": []})
    pending["reasons"].append(reason)
    if rule:
        pending["rule"] = rule
    if vehicle_ids:
        pending["vehicle_ids"].extend(vehicle_ids)


def recalc_if_needed(db: Session, user: User | None = None) -> ScheduleRun | None:
    pending = db.info.pop("recalc", None)
    if not pending:
        return None
    context = {"reasons": pending["reasons"]}
    if pending["rule"]:
        context["rule"] = pending["rule"]
        context["vehicle_ids"] = pending["vehicle_ids"]
    trigger = "event: " + ", ".join(dict.fromkeys(pending["reasons"]))
    run, _ = run_scheduler(db, trigger=trigger, user=user, context=context)
    return run
