from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.services.config_service import now


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    category: str,
    summary: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict | None = None,
    ip_address: str | None = None,
    actor_label: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        created_at=now(),
        user_id=actor.id if actor else None,
        actor=actor_label or (f"{actor.full_name} ({actor.role_code})" if actor else "system"),
        action=action,
        category=category,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:500],
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def diff(before: dict, after: dict) -> dict:
    return {k: {"from": before.get(k), "to": v} for k, v in after.items() if before.get(k) != v}
