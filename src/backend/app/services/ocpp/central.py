"""Minimal OCPP 1.6-J central system.

Supports BootNotification, Heartbeat, StatusNotification, Authorize, StartTransaction,
MeterValues and StopTransaction from charge points, and RemoteStartTransaction,
RemoteStopTransaction, ChangeAvailability and SetChargingProfile commands to them.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.models import Charger, ChargingSchedule, ChargingSession, Vehicle
from app.models.enums import ChargerStatus, ReservationStatus, SessionSource, SessionStatus
from app.services import audit
from app.services.charging import accrue, finish_session, record_reading, start_session
from app.services.config_service import load_config, now
from app.services.events import hub
from app.services.operations import set_charger_status
from app.services.scheduler.service import recalc_if_needed
from app.services.tariffs import load_calendar

log = logging.getLogger("chargeopt.ocpp")

CALL, CALLRESULT, CALLERROR = 2, 3, 4

STATUS_MAP = {
    "Available": ChargerStatus.AVAILABLE,
    "Preparing": ChargerStatus.RESERVED,
    "Reserved": ChargerStatus.RESERVED,
    "Charging": ChargerStatus.CHARGING,
    "SuspendedEV": ChargerStatus.CHARGING,
    "SuspendedEVSE": ChargerStatus.CHARGING,
    "Finishing": ChargerStatus.CHARGING,
    "Faulted": ChargerStatus.FAULT,
    "Unavailable": ChargerStatus.MAINTENANCE,
}


class ChargePointLink:
    def __init__(self, identity: str, socket: WebSocket):
        self.identity = identity
        self.socket = socket
        self.pending: dict[str, asyncio.Future] = {}


class OcppRegistry:
    def __init__(self) -> None:
        self.links: dict[str, ChargePointLink] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def connected(self, identity: str | None) -> bool:
        return bool(identity) and identity in self.links

    async def call(self, identity: str, action: str, payload: dict, timeout: float = 15) -> dict:
        link = self.links.get(identity)
        if link is None:
            raise ConnectionError(f"Charge point {identity} is not connected")
        message_id = uuid.uuid4().hex[:16]
        future = asyncio.get_running_loop().create_future()
        link.pending[message_id] = future
        await link.socket.send_text(json.dumps([CALL, message_id, action, payload]))
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            link.pending.pop(message_id, None)

    def send_command(self, identity: str, action: str, payload: dict) -> None:
        if self.loop is None or identity not in self.links:
            return

        async def _run() -> None:
            try:
                result = await self.call(identity, action, payload)
                log.info("OCPP %s -> %s: %s", action, identity, result)
            except Exception as exc:  # noqa: BLE001
                log.warning("OCPP %s to %s failed: %s", action, identity, exc)

        asyncio.run_coroutine_threadsafe(_run(), self.loop)


registry = OcppRegistry()


def _charger(db: Session, identity: str) -> Charger | None:
    return db.scalar(select(Charger).where(Charger.ocpp_identity == identity))


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return now()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return now()


def _boot(identity: str, payload: dict) -> dict:
    with session_scope() as db:
        charger = _charger(db, identity)
        if charger is None:
            return {"status": "Rejected", "currentTime": now().isoformat(), "interval": 300}
        charger.ocpp_connected = True
        charger.last_heartbeat_at = now()
        audit.record(db, actor=None, action="ocpp.boot", category="charger", summary=f"{charger.code} connected via OCPP ({payload.get('chargePointVendor', '?')} {payload.get('chargePointModel', '')})".strip(), entity_type="charger", entity_id=charger.id)
    hub.publish("charger.updated", {"identity": identity})
    return {"status": "Accepted", "currentTime": now().isoformat(), "interval": 60}


def _heartbeat(identity: str, _: dict) -> dict:
    with session_scope() as db:
        charger = _charger(db, identity)
        if charger:
            charger.last_heartbeat_at = now()
    return {"currentTime": now().isoformat()}


def _status(identity: str, payload: dict) -> dict:
    status = STATUS_MAP.get(payload.get("status", ""))
    with session_scope() as db:
        charger = _charger(db, identity)
        if charger is None or status is None:
            return {}
        if status in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE, ChargerStatus.AVAILABLE) and charger.status != status:
            if not (status == ChargerStatus.AVAILABLE and charger.status == ChargerStatus.CHARGING):
                set_charger_status(db, charger, status, f"OCPP StatusNotification {payload.get('errorCode', '')}".strip(), None)
        elif status == ChargerStatus.RESERVED and charger.status == ChargerStatus.AVAILABLE:
            charger.status = ChargerStatus.RESERVED
            charger.status_changed_at = now()
        recalc_if_needed(db)
    hub.publish("charger.updated", {"identity": identity})
    return {}


def _start(identity: str, payload: dict) -> dict:
    with session_scope() as db:
        charger = _charger(db, identity)
        id_tag = str(payload.get("idTag", ""))
        vehicle = db.scalar(select(Vehicle).where(Vehicle.registration == id_tag))
        if charger is None or vehicle is None:
            return {"transactionId": 0, "idTagInfo": {"status": "Invalid"}}
        schedule = db.scalar(
            select(ChargingSchedule)
            .where(ChargingSchedule.vehicle_id == vehicle.id, ChargingSchedule.charger_id == charger.id, ChargingSchedule.status == ReservationStatus.PLANNED)
            .order_by(ChargingSchedule.start_at)
        )
        tx_id = (db.scalar(select(func.max(ChargingSession.ocpp_transaction_id))) or 1000) + 1
        try:
            start_session(db, vehicle=vehicle, charger=charger, source=SessionSource.OCPP, schedule=schedule, at=_parse_ts(payload.get("timestamp")), ocpp_transaction_id=tx_id, meter_start_wh=float(payload.get("meterStart", 0)))
        except Exception as exc:  # noqa: BLE001
            log.warning("OCPP StartTransaction rejected for %s: %s", identity, exc)
            return {"transactionId": 0, "idTagInfo": {"status": "Blocked"}}
    return {"transactionId": tx_id, "idTagInfo": {"status": "Accepted"}}


def _meter(identity: str, payload: dict) -> dict:
    tx_id = payload.get("transactionId")
    if not tx_id:
        return {}
    with session_scope() as db:
        session = db.scalar(select(ChargingSession).where(ChargingSession.ocpp_transaction_id == tx_id, ChargingSession.status == SessionStatus.ACTIVE))
        if session is None:
            return {}
        vehicle = db.get(Vehicle, session.vehicle_id)
        charger = db.get(Charger, session.charger_id)
        cfg = load_config(db)
        calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh)
        for mv in payload.get("meterValue", []):
            ts = _parse_ts(mv.get("timestamp"))
            power = None
            for sv in mv.get("sampledValue", []):
                measurand = sv.get("measurand", "Energy.Active.Import.Register")
                value = float(sv.get("value", 0))
                if sv.get("unit") in ("kWh", "kW"):
                    value *= 1000
                if measurand == "Energy.Active.Import.Register":
                    total_kwh = (value - (session.meter_start_wh or 0)) / 1000
                    accrue(session, vehicle, max(0.0, total_kwh - session.energy_kwh), ts, calendar, charger.station_id)
                elif measurand == "Power.Active.Import":
                    power = value / 1000
                elif measurand == "SoC":
                    vehicle.current_soc = float(sv.get("value", vehicle.current_soc))
            record_reading(db, session, vehicle, ts, power if power is not None else session.power_kw)
        if vehicle.current_soc >= session.target_soc - 0.05:
            registry.send_command(identity, "RemoteStopTransaction", {"transactionId": tx_id})
    hub.publish("session.updated", {"transaction_id": tx_id})
    return {}


def _stop(identity: str, payload: dict) -> dict:
    tx_id = payload.get("transactionId")
    with session_scope() as db:
        session = db.scalar(select(ChargingSession).where(ChargingSession.ocpp_transaction_id == tx_id, ChargingSession.status == SessionStatus.ACTIVE))
        if session is not None:
            vehicle = db.get(Vehicle, session.vehicle_id)
            charger = db.get(Charger, session.charger_id)
            cfg = load_config(db)
            calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh)
            total_kwh = (float(payload.get("meterStop", 0)) - (session.meter_start_wh or 0)) / 1000
            accrue(session, vehicle, max(0.0, total_kwh - session.energy_kwh), _parse_ts(payload.get("timestamp")), calendar, charger.station_id)
            reason = payload.get("reason", "Local")
            status = SessionStatus.INTERRUPTED if reason in ("EmergencyStop", "PowerLoss", "Other", "EVDisconnected") and vehicle.current_soc < session.target_soc - 1 else SessionStatus.COMPLETED
            finish_session(db, session, status=status, reason=f"OCPP stop: {reason}", at=_parse_ts(payload.get("timestamp")))
            recalc_if_needed(db)
    return {"idTagInfo": {"status": "Accepted"}}


HANDLERS = {
    "BootNotification": _boot,
    "Heartbeat": _heartbeat,
    "StatusNotification": _status,
    "Authorize": lambda identity, payload: {"idTagInfo": {"status": "Accepted"}},
    "StartTransaction": _start,
    "MeterValues": _meter,
    "StopTransaction": _stop,
}


async def serve(identity: str, socket: WebSocket) -> None:
    link = ChargePointLink(identity, socket)
    registry.links[identity] = link
    try:
        while True:
            raw = await socket.receive_text()
            try:
                message = json.loads(raw)
                kind = message[0]
            except (ValueError, IndexError, TypeError):
                continue
            if kind == CALL:
                _, message_id, action, payload = message
                handler = HANDLERS.get(action)
                if handler is None:
                    await socket.send_text(json.dumps([CALLERROR, message_id, "NotImplemented", f"{action} not supported", {}]))
                    continue
                try:
                    result = await asyncio.to_thread(handler, identity, payload or {})
                    await socket.send_text(json.dumps([CALLRESULT, message_id, result]))
                except Exception:  # noqa: BLE001
                    log.exception("OCPP handler %s failed for %s", action, identity)
                    await socket.send_text(json.dumps([CALLERROR, message_id, "InternalError", "Handler failed", {}]))
            elif kind in (CALLRESULT, CALLERROR):
                future = link.pending.get(message[1])
                if future and not future.done():
                    future.set_result(message[2] if kind == CALLRESULT else {"error": message[2:]})
    finally:
        registry.links.pop(identity, None)
        await asyncio.to_thread(_mark_disconnected, identity)


def _mark_disconnected(identity: str) -> None:
    with session_scope() as db:
        charger = _charger(db, identity)
        if charger:
            charger.ocpp_connected = False
            audit.record(db, actor=None, action="ocpp.disconnected", category="charger", summary=f"{charger.code} OCPP connection closed", entity_type="charger", entity_id=charger.id)
    hub.publish("charger.updated", {"identity": identity})
