from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_or_404, require
from app.api.serializers import request_out, reservation_out, run_out, session_out
from app.core.errors import bad_request, conflict
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import Charger, ChargingRequest, ChargingSchedule, ChargingSession, EnergyReading, ScheduleRun, User, Vehicle
from app.models.enums import OPEN_REQUEST_STATUSES, ReservationStatus, RunStatus, SchedulerMode, SessionStatus
from app.schemas.operations import ManualReservationIn, ModeIn, OverrideIn, RunDecisionIn, SessionStartIn, SessionStopIn
from app.services import audit, operations
from app.services.charger_control import command_start, command_stop
from app.services.config_service import load_config, now, save_config
from app.services.scheduler.engine import Scheduler
from app.services.scheduler.optimizer import lp_lower_bound
from app.services.scheduler.service import (
    approve_run,
    build_snapshot,
    cached,
    state_key,
    engine_config,
    preview_plan,
    recalc_if_needed,
    reject_run,
    run_scheduler,
)

router = APIRouter(tags=["charging"])


@router.get("/charging-schedules")
def list_reservations(
    _: User = Depends(require(Perm.VIEW_FLEET)),
    db: Session = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    station_id: int | None = None,
    vehicle_id: int | None = None,
    include_history: bool = False,
):
    at = now()
    start = start or at - timedelta(hours=2)
    end = end or at + timedelta(hours=26)
    statuses = [ReservationStatus.PLANNED, ReservationStatus.ACTIVE, ReservationStatus.PROPOSED]
    if include_history:
        statuses += [ReservationStatus.COMPLETED, ReservationStatus.MISSED, ReservationStatus.INTERRUPTED, ReservationStatus.CANCELLED]
    q = (
        select(ChargingSchedule)
        .where(ChargingSchedule.status.in_(statuses), ChargingSchedule.end_at > start, ChargingSchedule.start_at < end)
        .options(selectinload(ChargingSchedule.vehicle), selectinload(ChargingSchedule.charger))
        .order_by(ChargingSchedule.start_at)
    )
    if vehicle_id:
        q = q.where(ChargingSchedule.vehicle_id == vehicle_id)
    if station_id:
        q = q.join(Charger, Charger.id == ChargingSchedule.charger_id).where(Charger.station_id == station_id)
    cfg = load_config(db)
    latest = db.scalar(select(ScheduleRun).order_by(ScheduleRun.id.desc()).limit(1))
    pending = db.scalar(select(ScheduleRun).where(ScheduleRun.status == RunStatus.PENDING_APPROVAL).order_by(ScheduleRun.id.desc()).limit(1))
    return {
        "as_of": at,
        "window": {"start": start, "end": end},
        "mode": cfg.scheduler_mode.value,
        "require_approval": cfg.require_schedule_approval,
        "latest_run": run_out(latest) if latest else None,
        "pending_run": run_out(pending) if pending else None,
        "reservations": [reservation_out(r) for r in db.scalars(q)],
    }


@router.post("/charging-schedules", status_code=status.HTTP_201_CREATED)
def recalculate(actor: User = Depends(require(Perm.RUN_SCHEDULER)), db: Session = Depends(get_db)):
    run, plan = run_scheduler(db, trigger="manual recalculation", user=actor)
    db.commit()
    return {"run": run_out(run), "metrics": plan.metrics}


@router.put("/charging-schedules/mode")
def set_mode(body: ModeIn, actor: User = Depends(require(Perm.APPROVE_SCHEDULE)), db: Session = Depends(get_db)):
    cfg = load_config(db)
    previous = cfg.scheduler_mode
    cfg.scheduler_mode = body.mode
    save_config(db, cfg, actor.id)
    label = {SchedulerMode.BASELINE: "static baseline", SchedulerMode.RULE_BASED: "rule-based"}
    audit.record(db, actor=actor, action="schedule.mode_changed", category="schedule", summary=f"Scheduler switched from {label[previous]} to {label[body.mode]}", details={"from": previous.value, "to": body.mode.value})
    run, plan = run_scheduler(db, trigger=f"{label[body.mode]} scheduler activated", user=actor)
    db.commit()
    return {"mode": body.mode.value, "run": run_out(run), "metrics": plan.metrics}


@router.get("/charging-schedules/decisions")
def decisions(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ChargingRequest)
        .where(ChargingRequest.status.in_(OPEN_REQUEST_STATUSES))
        .options(selectinload(ChargingRequest.vehicle), selectinload(ChargingRequest.trip))
        .order_by(ChargingRequest.priority_level, ChargingRequest.deadline_at.nulls_last())
    )
    return [{**request_out(r), "vehicle": r.vehicle.registration, "trip_code": r.trip.code if r.trip else None, "departure_at": r.trip.departure_at if r.trip else None} for r in rows]


@router.get("/charging-schedules/preview")
def preview(mode: SchedulerMode, _: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    plan = preview_plan(db, mode)
    return {
        "mode": mode.value,
        "planning_time": plan.planning_time,
        "metrics": plan.metrics,
        "reservations": [
            {
                "vehicle_id": r.vehicle_id,
                "vehicle": r.registration,
                "charger_id": r.charger_id,
                "charger": r.charger_code,
                "station_id": r.station_id,
                "start_at": r.start,
                "end_at": r.end,
                "power_kw": r.power_kw,
                "planned_energy_kwh": r.energy_kwh,
                "estimated_cost": r.cost,
                "target_soc": r.target_soc,
                "priority_level": r.priority_level,
                "rules": r.rules,
                "explanation": r.explanation,
                "tariff_mix": r.tariff_mix,
                "status": "preview",
                "is_override": False,
            }
            for r in plan.reservations
        ],
        "decisions": [
            {
                "vehicle_id": d.vehicle_id,
                "vehicle": d.registration,
                "status": d.status,
                "priority_level": d.priority_level,
                "current_soc": d.current_soc,
                "target_soc": d.target_soc,
                "projected_soc": d.projected_soc,
                "departure_at": d.departure_at,
                "rules": d.rules,
                "explanation": d.explanation,
            }
            for d in plan.decisions
        ],
    }


@router.get("/charging-schedules/comparison")
def comparison(_: User = Depends(require(Perm.VIEW_REPORTS)), db: Session = Depends(get_db), include_lp: bool = True):
    cfg = load_config(db)
    return cached(("comparison", include_lp, *state_key(db, cfg)), lambda: _comparison(db, cfg, include_lp))


def _comparison(db: Session, cfg, include_lp: bool) -> dict:
    at = now()
    baseline = preview_plan(db, SchedulerMode.BASELINE, cfg, at)
    rule = preview_plan(db, SchedulerMode.RULE_BASED, cfg, at)
    result = {"as_of": at, "currency": cfg.currency, "baseline": baseline.metrics, "rule_based": rule.metrics, "simulated": True}
    if include_lp:
        vehicles, chargers, stations, fixed, calendar = build_snapshot(db, at, cfg)
        lp = lp_lower_bound(Scheduler(engine_config(cfg, SchedulerMode.RULE_BASED), calendar, vehicles, chargers, stations, fixed), at)
        if lp.get("avg_rate_per_kwh") and rule.metrics["avg_rate_per_kwh"]:
            lp["rule_based_gap_pct"] = round((rule.metrics["avg_rate_per_kwh"] / lp["avg_rate_per_kwh"] - 1) * 100, 1)
        result["lp_benchmark"] = lp
    b, r = baseline.metrics, rule.metrics
    result["delta"] = {
        "cost": round(r["planned_cost"] - b["planned_cost"], 2),
        "cost_pct": round((r["planned_cost"] / b["planned_cost"] - 1) * 100, 1) if b["planned_cost"] else None,
        "energy_kwh": round(r["planned_energy_kwh"] - b["planned_energy_kwh"], 1),
        "peak_energy_kwh": round(r["peak_energy_kwh"] - b["peak_energy_kwh"], 1),
        "readiness_pct": round(r["projected_readiness_pct"] - b["projected_readiness_pct"], 1),
        "peak_site_load_kw": round(r["peak_site_load_kw"] - b["peak_site_load_kw"], 1),
    }
    return result


@router.get("/charging-schedules/runs")
def list_runs(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db), limit: int = Query(default=30, ge=1, le=200)):
    return [run_out(r) for r in db.scalars(select(ScheduleRun).order_by(ScheduleRun.id.desc()).limit(limit))]


@router.post("/charging-schedules/runs/{run_id}/approve")
def approve(run_id: int, actor: User = Depends(require(Perm.APPROVE_SCHEDULE)), db: Session = Depends(get_db)):
    run = get_or_404(db, ScheduleRun, run_id, "Schedule run")
    if run.status != RunStatus.PENDING_APPROVAL:
        raise conflict(f"Run #{run.id} is {run.status.value}, not pending approval")
    approve_run(db, run, actor)
    db.commit()
    return run_out(run)


@router.post("/charging-schedules/runs/{run_id}/reject")
def reject(run_id: int, body: RunDecisionIn, actor: User = Depends(require(Perm.APPROVE_SCHEDULE)), db: Session = Depends(get_db)):
    run = get_or_404(db, ScheduleRun, run_id, "Schedule run")
    if run.status != RunStatus.PENDING_APPROVAL:
        raise conflict(f"Run #{run.id} is {run.status.value}, not pending approval")
    reject_run(db, run, actor, body.reason or "No reason given")
    db.commit()
    return run_out(run)


@router.post("/charging-schedules/reservations", status_code=status.HTTP_201_CREATED)
def manual_reservation(body: ManualReservationIn, actor: User = Depends(require(Perm.OVERRIDE_SCHEDULE)), db: Session = Depends(get_db)):
    vehicle = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    charger = get_or_404(db, Charger, body.charger_id, "Charger")
    row = operations.create_override(
        db,
        vehicle=vehicle,
        charger=charger,
        start=body.start_at or now(),
        end=body.end_at,
        target_soc=body.target_soc,
        reason=body.reason,
        user=actor,
        preempt=body.preempt,
        emergency=body.emergency,
    )
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(row)
    return reservation_out(row)


@router.post("/charging-schedules/{reservation_id}/override")
def override(reservation_id: int, body: OverrideIn, actor: User = Depends(require(Perm.OVERRIDE_SCHEDULE)), db: Session = Depends(get_db)):
    original = get_or_404(db, ChargingSchedule, reservation_id, "Reservation")
    if original.status not in (ReservationStatus.PLANNED, ReservationStatus.PROPOSED, ReservationStatus.ACTIVE):
        raise conflict(f"Reservation is {original.status.value} and can no longer be overridden")
    vehicle = db.get(Vehicle, original.vehicle_id)
    if body.action == "cancel":
        if original.status == ReservationStatus.ACTIVE:
            raise conflict("Stop the active session instead of cancelling its reservation")
        row = operations.cancel_reservation(db, original, actor, body.reason, body.hold_hours)
    else:
        charger = get_or_404(db, Charger, body.charger_id or original.charger_id, "Charger")
        start = now() if body.action == "charge_now" else body.start_at
        if original.status == ReservationStatus.ACTIVE and body.action == "reschedule" and start > now() + timedelta(minutes=1):
            session = db.scalar(select(ChargingSession).where(ChargingSession.schedule_id == original.id, ChargingSession.status == SessionStatus.ACTIVE))
            if session is not None:
                command_stop(db, session, "rescheduled by manual override", actor)
        row = operations.create_override(
            db,
            vehicle=vehicle,
            charger=charger,
            start=start,
            end=body.end_at,
            target_soc=body.target_soc or original.target_soc,
            reason=body.reason,
            user=actor,
            original=original if original.status != ReservationStatus.ACTIVE else None,
            preempt=body.preempt,
            emergency=body.action == "charge_now",
        )
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(row)
    return reservation_out(row)


@router.get("/charging-sessions")
def list_sessions(
    _: User = Depends(require(Perm.VIEW_FLEET)),
    db: Session = Depends(get_db),
    active: bool | None = None,
    vehicle_id: int | None = None,
    charger_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
):
    q = select(ChargingSession).options(selectinload(ChargingSession.vehicle), selectinload(ChargingSession.charger), selectinload(ChargingSession.schedule))
    if active is True:
        q = q.where(ChargingSession.status == SessionStatus.ACTIVE)
    elif active is False:
        q = q.where(ChargingSession.status != SessionStatus.ACTIVE)
    if vehicle_id:
        q = q.where(ChargingSession.vehicle_id == vehicle_id)
    if charger_id:
        q = q.where(ChargingSession.charger_id == charger_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(ChargingSession.started_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [session_out(s) for s in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/charging-sessions", status_code=status.HTTP_201_CREATED)
def start(body: SessionStartIn, actor: User = Depends(require(Perm.MANAGE_SESSIONS)), db: Session = Depends(get_db)):
    vehicle = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    charger = get_or_404(db, Charger, body.charger_id, "Charger")
    at = now()
    planned = db.scalar(
        select(ChargingSchedule).where(
            ChargingSchedule.charger_id == charger.id,
            ChargingSchedule.status == ReservationStatus.PLANNED,
            ChargingSchedule.start_at <= at + timedelta(minutes=30),
            ChargingSchedule.end_at > at,
        )
    )
    if planned is not None and planned.vehicle_id != vehicle.id:
        raise conflict(f"{charger.code} is reserved for another vehicle now; use a manual override to displace it")
    if planned is None:
        clash = db.scalar(
            select(ChargingSchedule).where(
                ChargingSchedule.charger_id == charger.id,
                ChargingSchedule.status == ReservationStatus.PLANNED,
                ChargingSchedule.start_at < at + timedelta(hours=1),
                ChargingSchedule.end_at > at,
            )
        )
        if clash is not None:
            raise conflict(f"{charger.code} has a reservation starting soon; use a manual override instead")
    session = command_start(db, charger, vehicle, planned if planned and planned.vehicle_id == vehicle.id else None, actor)
    if session is not None and body.target_soc is not None:
        session.target_soc = min(body.target_soc, vehicle.max_soc)
    audit.record(db, actor=actor, action="session.manual_start", category="override", summary=f"Manually started charging {vehicle.registration} on {charger.code}", entity_type="vehicle", entity_id=vehicle.id)
    recalc_if_needed(db, actor)
    db.commit()
    if session is None:
        return {"status": "remote_start_requested", "charger": charger.code}
    db.refresh(session)
    return session_out(session)


@router.post("/charging-sessions/{session_id}/stop")
def stop(session_id: int, body: SessionStopIn, actor: User = Depends(require(Perm.MANAGE_SESSIONS)), db: Session = Depends(get_db)):
    session = get_or_404(db, ChargingSession, session_id, "Session")
    if session.status != SessionStatus.ACTIVE:
        raise bad_request("Session is not active")
    command_stop(db, session, body.reason, actor)
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(session)
    return session_out(session)


@router.get("/charging-sessions/{session_id}/readings")
def readings(session_id: int, _: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    get_or_404(db, ChargingSession, session_id, "Session")
    rows = db.scalars(select(EnergyReading).where(EnergyReading.session_id == session_id).order_by(EnergyReading.recorded_at).limit(2000))
    return [{"recorded_at": r.recorded_at, "power_kw": r.power_kw, "energy_kwh": r.energy_kwh, "soc": r.soc, "source": r.source.value} for r in rows]
