from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_or_404, require
from app.api.serializers import audit_out, profile_out, provider_out, station_out, user_out
from app.core.errors import bad_request, conflict, not_found
from app.core.permissions import Perm
from app.core.security import hash_password
from app.db.session import get_db
from app.models import AuditLog, BatteryProfile, Role, ServiceProvider, Station, User
from app.models.enums import ProviderKind
from app.schemas.fleet import ServiceProviderIn, StationIn, StationPatch
from app.schemas.operations import UserIn, UserPatch
from app.services import audit
from app.services.config_service import OperationalConfig, load_config, save_config
from app.services.events import hub
from app.services.scheduler.engine import PRIORITY_TEXT, RULE_TEXT
from app.services.scheduler.service import mark_recalc_needed, recalc_if_needed

router = APIRouter(tags=["administration"])


@router.get("/roles")
def list_roles(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"code": r.code, "name": r.name, "description": r.description, "permissions": r.permissions} for r in db.scalars(select(Role).order_by(Role.code))]


@router.get("/users")
def list_users(_: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.full_name))]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, actor: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise conflict("A user with this email already exists")
    user = User(email=body.email, full_name=body.full_name, role_code=body.role.value, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.record(db, actor=actor, action="user.created", category="config", summary=f"Created user {body.email} ({body.role.value})", entity_type="user", entity_id=user.id)
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, actor: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)):
    user = get_or_404(db, User, user_id, "User")
    if user.id == actor.id and (body.is_active is False or (body.role and body.role.value != actor.role_code)):
        raise bad_request("You cannot deactivate yourself or change your own role")
    changes = {}
    if body.full_name is not None:
        changes["full_name"] = body.full_name
        user.full_name = body.full_name
    if body.role is not None:
        changes["role"] = body.role.value
        user.role_code = body.role.value
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    audit.record(db, actor=actor, action="user.updated", category="config", summary=f"Updated user {user.email}: {', '.join(changes)}", entity_type="user", entity_id=user.id, details=changes)
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.get("/stations")
def list_stations(_: User = Depends(require(Perm.VIEW_FLEET, Perm.VIEW_OWN_VEHICLE)), db: Session = Depends(get_db)):
    return [station_out(s) for s in db.scalars(select(Station).order_by(Station.code))]


@router.post("/stations", status_code=status.HTTP_201_CREATED)
def create_station(body: StationIn, actor: User = Depends(require(Perm.MANAGE_INFRASTRUCTURE)), db: Session = Depends(get_db)):
    if db.scalar(select(Station).where(Station.code == body.code)):
        raise conflict(f"Station code {body.code} already exists")
    st = Station(**body.model_dump())
    db.add(st)
    db.flush()
    audit.record(db, actor=actor, action="station.created", category="config", summary=f"Created station {st.code} — {st.name}", entity_type="station", entity_id=st.id)
    db.commit()
    return station_out(st)


@router.put("/stations/{station_id}")
def update_station(station_id: int, body: StationPatch, actor: User = Depends(require(Perm.MANAGE_INFRASTRUCTURE)), db: Session = Depends(get_db)):
    st = db.get(Station, station_id)
    if st is None:
        raise not_found("Station")
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(st, k) for k in data}
    for k, v in data.items():
        setattr(st, k, v)
    audit.record(db, actor=actor, action="station.updated", category="config", summary=f"Updated station {st.code}", entity_type="station", entity_id=st.id, details=audit.diff(before, data))
    mark_recalc_needed(db, f"station {st.code} updated")
    recalc_if_needed(db, actor)
    db.commit()
    return station_out(st)


@router.get("/battery-profiles")
def list_profiles(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    return [profile_out(p) for p in db.scalars(select(BatteryProfile).order_by(BatteryProfile.name))]


@router.get("/service-providers")
def list_providers(_: User = Depends(require(Perm.VIEW_FLEET)), db: Session = Depends(get_db)):
    return [provider_out(p) for p in db.scalars(select(ServiceProvider).where(ServiceProvider.is_active.is_(True)).order_by(ServiceProvider.kind, ServiceProvider.name))]


@router.post("/service-providers", status_code=status.HTTP_201_CREATED)
def create_provider(body: ServiceProviderIn, actor: User = Depends(require(Perm.MANAGE_CONFIG)), db: Session = Depends(get_db)):
    p = ServiceProvider(**{**body.model_dump(), "kind": ProviderKind(body.kind)})
    db.add(p)
    db.flush()
    audit.record(db, actor=actor, action="provider.created", category="config", summary=f"Added contingency provider {p.name}", entity_type="service_provider", entity_id=p.id)
    db.commit()
    return provider_out(p)


@router.delete("/service-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, actor: User = Depends(require(Perm.MANAGE_CONFIG)), db: Session = Depends(get_db)):
    p = db.get(ServiceProvider, provider_id)
    if p is None:
        raise not_found("Service provider")
    p.is_active = False
    audit.record(db, actor=actor, action="provider.deactivated", category="config", summary=f"Removed contingency provider {p.name}", entity_type="service_provider", entity_id=p.id)
    db.commit()


@router.get("/config")
def get_config(_: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {
        "config": cfg.model_dump(mode="json"),
        "rules": [{"code": k, "description": v} for k, v in RULE_TEXT.items()],
        "priorities": [{"level": k, "description": v} for k, v in PRIORITY_TEXT.items()],
    }


@router.put("/config")
def update_config(body: dict, actor: User = Depends(require(Perm.MANAGE_CONFIG)), db: Session = Depends(get_db)):
    current = load_config(db)
    protected = {"clock_offset_seconds"}
    unknown = set(body) - set(OperationalConfig.model_fields)
    if unknown:
        raise bad_request(f"Unknown settings: {', '.join(sorted(unknown))}")
    if protected & set(body):
        raise bad_request("The simulation clock is controlled from the simulation endpoints")
    merged = OperationalConfig(**{**current.model_dump(), **body})
    changes = audit.diff(current.model_dump(mode="json"), merged.model_dump(mode="json"))
    save_config(db, merged, actor.id)
    if changes:
        audit.record(db, actor=actor, action="config.updated", category="config", summary=f"Updated operational rules: {', '.join(changes)}", details=changes)
        mark_recalc_needed(db, "configuration changed")
        recalc_if_needed(db, actor)
    db.commit()
    hub.publish("config.updated", {"keys": list(changes)})
    return {"config": merged.model_dump(mode="json"), "changed": list(changes)}


@router.get("/audit-logs")
def list_audit(
    _: User = Depends(require(Perm.VIEW_AUDIT)),
    db: Session = Depends(get_db),
    category: str | None = None,
    search: str | None = Query(default=None, max_length=100),
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    q = select(AuditLog)
    if category:
        q = q.where(AuditLog.category == category)
    if search:
        like = f"%{search}%"
        q = q.where(or_(AuditLog.summary.ilike(like), AuditLog.actor.ilike(like), AuditLog.action.ilike(like)))
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at < until)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    categories = [c for (c,) in db.execute(select(AuditLog.category).distinct().order_by(AuditLog.category))]
    return {"items": [audit_out(a) for a in rows], "total": total, "page": page, "page_size": page_size, "categories": categories}
