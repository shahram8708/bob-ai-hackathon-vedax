import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_or_404, require
from app.api.serializers import charger_out, signal_out, tariff_out
from app.core.errors import bad_request, conflict
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import Charger, PriceSignal, Station, TariffPeriod, User
from app.models.enums import ChargerStatus
from app.schemas.fleet import ChargerIn, ChargerPatch, ChargerStatusIn, PowerLimitIn, PriceFeedIn, TariffIn
from app.services import audit, operations
from app.services.charger_control import command_availability, command_power_limit
from app.services.config_service import load_config, now
from app.services.dashboard import tariff_strip
from app.services.events import hub
from app.services.scheduler.service import mark_recalc_needed, recalc_if_needed
from app.services.tariffs import coverage_gaps, load_calendar, period_rule

router = APIRouter(tags=["infrastructure"])


@router.get("/chargers")
def list_chargers(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db), station_id: int | None = None, status_filter: ChargerStatus | None = Query(default=None, alias="status")):
    q = select(Charger).options(selectinload(Charger.station), selectinload(Charger.current_vehicle)).order_by(Charger.code)
    if station_id:
        q = q.where(Charger.station_id == station_id)
    if status_filter:
        q = q.where(Charger.status == status_filter)
    return [charger_out(c) for c in db.scalars(q)]


@router.post("/chargers", status_code=status.HTTP_201_CREATED)
def create_charger(body: ChargerIn, actor: User = Depends(require(Perm.MANAGE_INFRASTRUCTURE)), db: Session = Depends(get_db)):
    get_or_404(db, Station, body.station_id, "Station")
    if db.scalar(select(Charger).where(Charger.code == body.code)):
        raise conflict(f"Charger {body.code} already exists")
    data = body.model_dump()
    data["availability_schedule"] = [w.model_dump() for w in body.availability_schedule] if body.availability_schedule else None
    c = Charger(**data, status=ChargerStatus.AVAILABLE, status_changed_at=now())
    db.add(c)
    db.flush()
    audit.record(db, actor=actor, action="charger.created", category="charger", summary=f"Created charger {c.code} ({c.connector_type}, {c.max_power_kw:g} kW)", entity_type="charger", entity_id=c.id)
    mark_recalc_needed(db, "charger added")
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(c)
    hub.publish("charger.updated", {"id": c.id})
    return charger_out(c)


@router.put("/chargers/{charger_id}")
def update_charger(charger_id: int, body: ChargerPatch, actor: User = Depends(require(Perm.MANAGE_INFRASTRUCTURE)), db: Session = Depends(get_db)):
    c = get_or_404(db, Charger, charger_id, "Charger")
    data = body.model_dump(exclude_unset=True, exclude={"clear_availability_schedule"})
    if "availability_schedule" in data:
        data["availability_schedule"] = [w.model_dump() for w in body.availability_schedule] if body.availability_schedule else None
    if body.clear_availability_schedule:
        data["availability_schedule"] = None
    if data.get("is_active") is False and c.current_vehicle_id:
        raise conflict(f"{c.code} has an active session; stop it before deactivating")
    before = {k: str(getattr(c, k)) for k in data}
    for k, v in data.items():
        setattr(c, k, v)
    audit.record(db, actor=actor, action="charger.updated", category="charger", summary=f"Updated charger {c.code}", entity_type="charger", entity_id=c.id, details=audit.diff(before, {k: str(v) for k, v in data.items()}))
    mark_recalc_needed(db, f"charger {c.code} updated", rule="R5" if data.get("is_active") is False else None)
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(c)
    hub.publish("charger.updated", {"id": c.id})
    return charger_out(c)


@router.post("/chargers/{charger_id}/status")
def change_status(charger_id: int, body: ChargerStatusIn, actor: User = Depends(require(Perm.CHARGER_STATE)), db: Session = Depends(get_db)):
    c = get_or_404(db, Charger, charger_id, "Charger")
    operations.set_charger_status(db, c, body.status, body.note, actor)
    command_availability(c, body.status not in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE))
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(c)
    return charger_out(c)


@router.post("/chargers/{charger_id}/power-limit")
def power_limit(charger_id: int, body: PowerLimitIn, actor: User = Depends(require(Perm.CHARGER_STATE)), db: Session = Depends(get_db)):
    c = get_or_404(db, Charger, charger_id, "Charger")
    if body.limit_kw is not None and body.limit_kw > c.max_power_kw:
        raise bad_request(f"Limit cannot exceed the charger's {c.max_power_kw:g} kW rating")
    command_power_limit(db, c, body.limit_kw, actor)
    mark_recalc_needed(db, f"charger {c.code} power limit")
    recalc_if_needed(db, actor)
    db.commit()
    db.refresh(c)
    hub.publish("charger.updated", {"id": c.id})
    return charger_out(c)


@router.get("/tariffs")
def list_tariffs(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    cfg = load_config(db)
    periods = list(db.scalars(select(TariffPeriod).order_by(TariffPeriod.start_time)))
    active = [period_rule(p) for p in periods if p.is_active]
    gaps = coverage_gaps([p for p in active if p.station_id is None], cfg.tz)
    return {"periods": [tariff_out(p) for p in periods], "coverage_gaps": gaps[:20], "gap_count": len(gaps), "default_rate_per_kwh": cfg.default_rate_per_kwh, "currency": cfg.currency, "timezone": cfg.timezone}


def _tariff_save(db: Session, t: TariffPeriod, body: TariffIn, actor: User, created: bool) -> dict:
    if body.station_id:
        get_or_404(db, Station, body.station_id, "Station")
    before = tariff_out(t) if not created else {}
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.flush()
    after = tariff_out(t)
    audit.record(
        db,
        actor=actor,
        action="tariff.created" if created else "tariff.updated",
        category="config",
        summary=f"{'Created' if created else 'Updated'} tariff period {t.name} {after['start_time']}–{after['end_time']} @ {after['rate_per_kwh']}/kWh",
        entity_type="tariff_period",
        entity_id=t.id,
        details=audit.diff(before, after),
    )
    mark_recalc_needed(db, "tariff changed")
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("tariff.updated", {"id": t.id})
    return after


@router.post("/tariffs", status_code=status.HTTP_201_CREATED)
def create_tariff(body: TariffIn, actor: User = Depends(require(Perm.MANAGE_TARIFFS)), db: Session = Depends(get_db)):
    t = TariffPeriod()
    db.add(t)
    return _tariff_save(db, t, body, actor, True)


@router.put("/tariffs/{tariff_id}")
def update_tariff(tariff_id: int, body: TariffIn, actor: User = Depends(require(Perm.MANAGE_TARIFFS)), db: Session = Depends(get_db)):
    return _tariff_save(db, get_or_404(db, TariffPeriod, tariff_id, "Tariff period"), body, actor, False)


@router.get("/tariffs/calendar")
def tariff_calendar(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db), hours: int = Query(default=48, ge=6, le=168)):
    cfg = load_config(db)
    at = now()
    calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh, at - timedelta(hours=1), at + timedelta(hours=hours + 1))
    return {"strip": tariff_strip(calendar, at, hours=hours, step_minutes=30), "timezone": cfg.timezone, "currency": cfg.currency}


@router.get("/tariffs/price-feed")
def list_signals(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    at = now()
    rows = db.scalars(select(PriceSignal).where(PriceSignal.ends_at > at - timedelta(hours=6)).order_by(PriceSignal.starts_at).limit(500))
    return [signal_out(s) for s in rows]


def _store_feed(db: Session, feed: PriceFeedIn, actor: User) -> int:
    signals = sorted(feed.signals, key=lambda s: s.starts_at)
    for a, b in zip(signals, signals[1:]):
        if a.station_id == b.station_id and b.starts_at < a.ends_at:
            raise bad_request(f"Overlapping price intervals at {b.starts_at.isoformat()}")
    for sid in {s.station_id for s in signals}:
        if sid:
            get_or_404(db, Station, sid, "Station")
    if feed.replace_window:
        start, end = signals[0].starts_at, max(s.ends_at for s in signals)
        db.execute(delete(PriceSignal).where(PriceSignal.starts_at < end, PriceSignal.ends_at > start))
    stamp = now()
    db.add_all(PriceSignal(station_id=s.station_id, starts_at=s.starts_at, ends_at=s.ends_at, rate_per_kwh=s.rate_per_kwh, source=feed.source, created_at=stamp) for s in signals)
    audit.record(db, actor=actor, action="tariff.price_feed", category="config", summary=f"Loaded {len(signals)} dynamic price intervals from {feed.source}")
    mark_recalc_needed(db, "price feed updated")
    recalc_if_needed(db, actor)
    db.commit()
    hub.publish("tariff.updated", {"price_feed": len(signals)})
    return len(signals)


@router.post("/tariffs/price-feed")
def load_feed(body: PriceFeedIn, actor: User = Depends(require(Perm.MANAGE_TARIFFS)), db: Session = Depends(get_db)):
    return {"loaded": _store_feed(db, body, actor)}


@router.post("/tariffs/price-feed/csv")
async def load_feed_csv(file: UploadFile = File(...), actor: User = Depends(require(Perm.MANAGE_TARIFFS)), db: Session = Depends(get_db)):
    raw = await file.read(500_001)
    if len(raw) > 500_000:
        raise bad_request("CSV file is larger than 500 KB")
    cfg = load_config(db)
    stations = {s.code: s.id for s in db.scalars(select(Station))}
    signals = []
    try:
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
            start = datetime.fromisoformat(row["starts_at"].strip())
            end = datetime.fromisoformat(row["ends_at"].strip())
            code = (row.get("station") or "").strip().upper()
            signals.append(
                {
                    "starts_at": start if start.tzinfo else start.replace(tzinfo=cfg.tz),
                    "ends_at": end if end.tzinfo else end.replace(tzinfo=cfg.tz),
                    "rate_per_kwh": float(row["rate_per_kwh"]),
                    "station_id": stations[code] if code else None,
                }
            )
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise bad_request(f"Could not parse price feed CSV: {exc}") from exc
    if not signals:
        raise bad_request("Price feed CSV has no rows")
    return {"loaded": _store_feed(db, PriceFeedIn(source=f"CSV · {file.filename or 'upload'}"[:60], signals=signals), actor)}


@router.delete("/tariffs/price-feed", status_code=status.HTTP_204_NO_CONTENT)
def clear_feed(actor: User = Depends(require(Perm.MANAGE_TARIFFS)), db: Session = Depends(get_db)):
    db.execute(delete(PriceSignal))
    audit.record(db, actor=actor, action="tariff.price_feed_cleared", category="config", summary="Cleared dynamic price feed; static tariff periods apply")
    mark_recalc_needed(db, "price feed cleared")
    recalc_if_needed(db, actor)
    db.commit()
