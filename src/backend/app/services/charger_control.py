from sqlalchemy.orm import Session

from app.models import Charger, ChargingSchedule, ChargingSession, User, Vehicle
from app.models.enums import ChargerStatus, SessionSource, SessionStatus
from app.services import audit
from app.services.charging import finish_session, start_session
from app.services.ocpp.central import registry


def is_remote(charger: Charger) -> bool:
    return charger.ocpp_connected and registry.connected(charger.ocpp_identity)


def command_start(db: Session, charger: Charger, vehicle: Vehicle, schedule: ChargingSchedule | None, user: User | None = None) -> ChargingSession | None:
    if is_remote(charger):
        payload = {"connectorId": 1, "idTag": vehicle.registration}
        if schedule is not None:
            payload["chargingProfile"] = {
                "chargingProfileId": schedule.id,
                "stackLevel": 1,
                "chargingProfilePurpose": "TxProfile",
                "chargingProfileKind": "Absolute",
                "chargingSchedule": {"chargingRateUnit": "W", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": schedule.power_kw * 1000}]},
            }
        registry.send_command(charger.ocpp_identity, "RemoteStartTransaction", payload)
        charger.status = ChargerStatus.RESERVED
        return None
    return start_session(db, vehicle=vehicle, charger=charger, source=SessionSource.SIMULATED, schedule=schedule, user=user)


def command_stop(db: Session, session: ChargingSession, reason: str, user: User | None = None) -> None:
    charger = db.get(Charger, session.charger_id)
    if session.source == SessionSource.OCPP and is_remote(charger) and session.ocpp_transaction_id:
        registry.send_command(charger.ocpp_identity, "RemoteStopTransaction", {"transactionId": session.ocpp_transaction_id})
        if user is not None:
            audit.record(db, actor=user, action="session.stop_requested", category="session", summary=f"Remote stop sent to {charger.code}: {reason}", entity_type="charging_session", entity_id=session.id)
        return
    finish_session(db, session, status=SessionStatus.STOPPED, reason=reason, user=user)


def command_power_limit(db: Session, charger: Charger, limit_kw: float | None, user: User) -> Charger:
    previous = charger.power_limit_kw
    charger.power_limit_kw = limit_kw
    if is_remote(charger):
        registry.send_command(
            charger.ocpp_identity,
            "SetChargingProfile",
            {
                "connectorId": 1,
                "csChargingProfiles": {
                    "chargingProfileId": 1,
                    "stackLevel": 0,
                    "chargingProfilePurpose": "ChargePointMaxProfile",
                    "chargingProfileKind": "Absolute",
                    "chargingSchedule": {"chargingRateUnit": "W", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": (limit_kw or charger.max_power_kw) * 1000}]},
                },
            },
        )
    audit.record(db, actor=user, action="charger.power_limit", category="charger", summary=f"{charger.code} power limit {previous or charger.max_power_kw:g} → {limit_kw or charger.max_power_kw:g} kW", entity_type="charger", entity_id=charger.id)
    return charger


def command_availability(charger: Charger, operative: bool) -> None:
    if is_remote(charger):
        registry.send_command(charger.ocpp_identity, "ChangeAvailability", {"connectorId": 0, "type": "Operative" if operative else "Inoperative"})
