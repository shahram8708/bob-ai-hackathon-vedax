import ipaddress
import logging
import socket
import threading
from urllib.parse import urlparse

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger("chargeopt.webhooks")


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return False
    return True


def _post(url: str, payload: dict) -> None:
    host = urlparse(url).hostname or ""
    if not _is_public_host(host):
        log.warning("Webhook target %s rejected: host resolves to a non-public address", host)
        return
    try:
        httpx.post(url, json=payload, timeout=5.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        log.warning("Webhook delivery to %s failed: %s", host, exc.__class__.__name__)


def dispatch_alert(db: Session, url: str | None, alert) -> None:
    if not url:
        return
    payload = {
        "event": "alert.created",
        "alert": {
            "id": alert.id,
            "type": alert.type.value,
            "severity": alert.severity.value,
            "title": alert.title,
            "message": alert.message,
            "vehicle_id": alert.vehicle_id,
            "charger_id": alert.charger_id,
            "created_at": alert.created_at.isoformat(),
        },
    }
    db.info.setdefault("pending_webhooks", []).append((url, payload))


@event.listens_for(Session, "after_commit")
def _flush_webhooks(session: Session) -> None:
    for url, payload in session.info.pop("pending_webhooks", []):
        threading.Thread(target=_post, args=(url, payload), daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _drop_webhooks(session: Session) -> None:
    session.info.pop("pending_webhooks", None)
