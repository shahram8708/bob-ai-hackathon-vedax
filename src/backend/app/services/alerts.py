import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.models import Alert, User
from app.models.enums import AlertSeverity, AlertStatus, AlertType
from app.services import audit
from app.services.config_service import cached_config, now
from app.services.events import hub
from app.services.webhooks import dispatch_alert

log = logging.getLogger("chargeopt.alerts")


def raise_alert(
    db: Session,
    *,
    type: AlertType,
    severity: AlertSeverity,
    title: str,
    message: str,
    dedup_key: str | None = None,
    vehicle_id: int | None = None,
    charger_id: int | None = None,
    station_id: int | None = None,
    trip_id: int | None = None,
    schedule_id: int | None = None,
    details: dict | None = None,
    created_by: User | None = None,
) -> Alert | None:
    if dedup_key:
        existing = db.scalar(
            select(Alert).where(Alert.dedup_key == dedup_key, Alert.status != AlertStatus.RESOLVED)
        )
        if existing:
            return None
    alert = Alert(
        type=type,
        severity=severity,
        status=AlertStatus.OPEN,
        title=title[:200],
        message=message,
        dedup_key=dedup_key,
        vehicle_id=vehicle_id,
        charger_id=charger_id,
        station_id=station_id,
        trip_id=trip_id,
        schedule_id=schedule_id,
        details=details or {},
        created_at=now(),
        created_by_id=created_by.id if created_by else None,
    )
    db.add(alert)
    db.flush()
    if severity == AlertSeverity.CRITICAL:
        audit.record(
            db,
            actor=created_by,
            action="alert.raised",
            category="exception",
            summary=f"Critical exception: {title}",
            entity_type="alert",
            entity_id=alert.id,
            details={"type": type.value, "message": message},
        )
    log.info("Alert %s raised: %s", type.value, title)
    hub.publish("alert.created", {"id": alert.id, "type": type.value, "severity": severity.value, "title": alert.title})
    dispatch_alert(db, cached_config().webhook_url, alert)
    return alert


def acknowledge(db: Session, alert: Alert, user: User, note: str | None) -> Alert:
    if alert.status != AlertStatus.OPEN:
        raise bad_request(f"Alert is already {alert.status.value}")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = now()
    alert.acknowledged_by_id = user.id
    if note:
        alert.details = {**alert.details, "acknowledgement_note": note}
    audit.record(db, actor=user, action="alert.acknowledged", category="exception", summary=f"Acknowledged: {alert.title}", entity_type="alert", entity_id=alert.id, details={"note": note})
    hub.publish("alert.updated", {"id": alert.id})
    return alert


def resolve(db: Session, alert: Alert, user: User | None, note: str) -> Alert:
    if alert.status == AlertStatus.RESOLVED:
        raise bad_request("Alert is already resolved")
    stamp = now()
    if alert.acknowledged_at is None:
        alert.acknowledged_at = stamp
        alert.acknowledged_by_id = user.id if user else None
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = stamp
    alert.resolved_by_id = user.id if user else None
    alert.resolution_note = note
    audit.record(db, actor=user, action="alert.resolved", category="exception", summary=f"Resolved: {alert.title}", entity_type="alert", entity_id=alert.id, details={"note": note})
    hub.publish("alert.updated", {"id": alert.id})
    return alert


def auto_resolve(db: Session, dedup_key: str, note: str) -> None:
    alert = db.scalar(select(Alert).where(Alert.dedup_key == dedup_key, Alert.status != AlertStatus.RESOLVED))
    if alert:
        resolve(db, alert, None, note)
