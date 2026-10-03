from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Alert, AuditLog, Charger, ChargingSchedule, ChargingSession, Trip, Vehicle
from app.models.enums import ReservationStatus, SessionStatus, TripStatus, VehicleAvailability
from app.services.config_service import load_config, now
from app.services.simulation import tick
from tests.conftest import PASSWORD, login


def create_vehicle(client, registration="EV-900", soc=30.0, **extra):
    body = {"registration": registration, "battery_profile_id": 1, "current_soc": soc, "home_station_id": 1, **extra}
    r = client.post("/api/vehicles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def create_trip(client, vehicle_id, hours=3.0, required=80, priority="normal"):
    departure = (now() + timedelta(hours=hours)).isoformat()
    r = client.post("/api/trips", json={"vehicle_id": vehicle_id, "origin_station_id": 1, "destination": "Hub", "distance_km": 40, "required_soc": required, "departure_at": departure, "priority": priority})
    assert r.status_code == 201, r.text
    return r.json()


def test_login_me_logout_and_audit(client, db):
    assert client.get("/api/auth/me").status_code == 401
    login(client, "admin")
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and "vehicles:manage" in me["permissions"]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"auth.login", "auth.logout"} <= actions


def test_bad_credentials_are_rejected_and_throttled(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "viewer@test.example", "password": "wrong-password"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "viewer@test.example", "password": PASSWORD})
    assert r.status_code == 429


def test_role_based_access(client):
    login(client, "viewer")
    assert client.get("/api/dashboard/overview").status_code == 200
    assert client.get("/api/reports/metrics").status_code == 200
    assert client.post("/api/vehicles", json={"registration": "EV-1", "battery_profile_id": 1, "current_soc": 50, "home_station_id": 1}).status_code == 403
    login(client, "driver")
    assert client.get("/api/vehicles").status_code == 403
    assert client.get("/api/me/vehicle").status_code == 200
    login(client, "charging_operator")
    assert client.put("/api/config", json={"currency": "USD"}).status_code == 403


def test_vehicle_crud_validation_and_deactivation(client):
    login(client, "admin")
    bad = client.post("/api/vehicles", json={"registration": "EV-901", "battery_profile_id": 1, "current_soc": 50, "home_station_id": 1, "min_operating_soc": 50, "required_departure_soc": 40})
    assert bad.status_code == 422
    v = create_vehicle(client, "ev-901")
    assert v["registration"] == "EV-901" and v["battery_capacity_kwh"] == 60
    assert client.post("/api/vehicles", json={"registration": "EV-901", "battery_profile_id": 1, "current_soc": 50, "home_station_id": 1}).status_code == 409
    r = client.put(f"/api/vehicles/{v['id']}", json={"required_departure_soc": 85, "priority_category": "high"})
    assert r.status_code == 200 and r.json()["required_departure_soc"] == 85
    r = client.put(f"/api/vehicles/{v['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/vehicles").json()["total"] == 0


def test_trip_creation_triggers_schedule_with_explanation(client, db):
    login(client, "admin")
    v = create_vehicle(client)
    create_trip(client, v["id"], hours=2)
    reservations = client.get("/api/charging-schedules").json()["reservations"]
    mine = [r for r in reservations if r["vehicle_id"] == v["id"]]
    assert len(mine) == 1 and mine[0]["status"] == "planned"
    assert "P2" in mine[0]["explanation"] and "R2" in mine[0]["rules"]
    past = client.post("/api/trips", json={"vehicle_id": v["id"], "origin_station_id": 1, "destination": "Depot X", "distance_km": 1, "departure_at": (now() - timedelta(hours=2)).isoformat()})
    assert past.status_code == 400


def test_database_prevents_overlapping_reservations(db, world):
    v = Vehicle(registration="EV-950", vehicle_type="Van", battery_profile_id=1, battery_capacity_kwh=60, current_soc=20, home_station_id=1, current_station_id=1)
    db.add(v)
    db.flush()
    start = now()
    common = dict(vehicle_id=v.id, charger_id=1, power_kw=50, planned_energy_kwh=10, target_soc=80, priority_level=3, status=ReservationStatus.PLANNED)
    db.add(ChargingSchedule(start_at=start, end_at=start + timedelta(hours=1), **common))
    db.flush()
    db.add(ChargingSchedule(start_at=start + timedelta(minutes=30), end_at=start + timedelta(hours=2), **common))
    try:
        db.flush()
        raise AssertionError("overlap was accepted")
    except IntegrityError:
        db.rollback()


def test_charger_fault_interrupts_session_raises_alert_and_reassigns(client, db):
    login(client, "admin")
    v = create_vehicle(client, soc=20)
    create_trip(client, v["id"], hours=2)
    first = client.get("/api/charging-schedules").json()["reservations"][0]
    tick(db, now(), 5, load_config(db))
    db.commit()
    session = db.scalar(select(ChargingSession).where(ChargingSession.vehicle_id == v["id"]))
    assert session is not None and session.status == SessionStatus.ACTIVE
    r = client.post(f"/api/chargers/{first['charger_id']}/status", json={"status": "fault", "note": "ground fault"})
    assert r.status_code == 200 and r.json()["status"] == "fault"
    db.expire_all()
    assert db.get(ChargingSession, session.id).status == SessionStatus.INTERRUPTED
    alerts = {a.type.value for a in db.scalars(select(Alert))}
    assert {"charger_fault", "session_interrupted"} <= alerts
    new = [r for r in client.get("/api/charging-schedules").json()["reservations"] if r["vehicle_id"] == v["id"] and r["status"] == "planned"]
    assert new and new[0]["charger_id"] != first["charger_id"] and "R5" in new[0]["rules"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "charger.status_changed"))


def test_manual_override_records_audit_and_displaces_conflicts(client, db):
    login(client, "admin")
    a = create_vehicle(client, "EV-910", soc=20)
    b = create_vehicle(client, "EV-911", soc=25)
    create_trip(client, a["id"], hours=2)
    create_trip(client, b["id"], hours=2.5)
    res = client.get("/api/charging-schedules").json()["reservations"]
    target = next(r for r in res if r["vehicle_id"] == a["id"])
    login(client, "fleet_manager")
    r = client.post(f"/api/charging-schedules/{target['id']}/override", json={"action": "reschedule", "charger_id": target["charger_id"], "start_at": (now() + timedelta(hours=1)).isoformat(), "reason": "Driver delayed at loading bay"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_override"] and body["rules"] == ["R8"]
    assert db.scalar(select(AuditLog).where(AuditLog.category == "override"))
    login(client, "viewer")
    assert client.post(f"/api/charging-schedules/{body['id']}/override", json={"action": "cancel", "reason": "not allowed"}).status_code == 403


def test_simulation_charges_to_target_and_completes(client, db):
    login(client, "admin")
    v = create_vehicle(client, soc=70)
    create_trip(client, v["id"], hours=2, required=75)
    cfg = load_config(db)
    at = now()
    tick(db, at, 5, cfg)
    db.commit()
    for i in range(1, 30):
        tick(db, at + timedelta(minutes=i), 60, cfg)
        db.commit()
    db.expire_all()
    vehicle = db.get(Vehicle, v["id"])
    session = db.scalar(select(ChargingSession).where(ChargingSession.vehicle_id == v["id"]))
    assert session.status == SessionStatus.COMPLETED and "R7" in session.stop_reason
    assert vehicle.current_soc >= 75 and session.energy_kwh > 0 and session.cost > 0
    assert sum(b["kwh"] for b in session.tariff_breakdown.values()) == round(session.energy_kwh, 4) or abs(sum(b["kwh"] for b in session.tariff_breakdown.values()) - session.energy_kwh) < 0.01


def test_departure_below_requirement_raises_alert(client, db):
    login(client, "operations_manager")
    v = db.get(Vehicle, create_vehicle(login(client, "admin"), soc=30)["id"])
    trip = create_trip(client, v.id, hours=5, required=80)
    login(client, "operations_manager")
    r = client.post(f"/api/vehicles/{v.id}/depart", json={"trip_id": trip["id"]})
    assert r.status_code == 200 and r.json()["availability"] == "on_trip"
    db.expire_all()
    assert db.get(Trip, trip["id"]).requirement_met is False
    assert db.scalar(select(Alert).where(Alert.type == "departed_below_required"))
    r = client.post(f"/api/vehicles/{v.id}/arrive", json={"station_id": 1, "soc": 5})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Trip, trip["id"]).status == TripStatus.COMPLETED
    assert db.scalar(select(Alert).where(Alert.type == "unexpected_consumption"))


def test_missed_slot_is_released_and_rescheduled(client, db):
    login(client, "admin")
    v = create_vehicle(client, soc=20)
    create_trip(client, v["id"], hours=2)
    vehicle = db.get(Vehicle, v["id"])
    vehicle.availability = VehicleAvailability.ON_TRIP
    vehicle.current_station_id = None
    db.commit()
    cfg = load_config(db)
    tick(db, now() + timedelta(minutes=40), 5, cfg)
    db.commit()
    assert db.scalar(select(Alert).where(Alert.type == "missed_slot"))
    assert db.scalar(select(ChargingSchedule).where(ChargingSchedule.status == ReservationStatus.MISSED))


def test_alert_acknowledge_and_resolve(client):
    login(client, "charging_operator")
    r = client.post("/api/alerts", json={"severity": "warning", "title": "Cable damaged", "message": "Bay 3 cable sheath torn"})
    assert r.status_code == 201
    alert_id = r.json()["id"]
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", json={"note": "On it"}).json()["status"] == "acknowledged"
    assert client.post(f"/api/alerts/{alert_id}/resolve", json={"note": ""}).status_code == 422
    assert client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "Cable replaced"}).json()["status"] == "resolved"
    assert client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "again"}).status_code == 400


def test_reports_json_and_csv(client):
    login(client, "viewer")
    for key in ("charging-history", "charger-utilization", "cost-by-period", "readiness", "peak-distribution", "exceptions", "summary-weekly"):
        r = client.get(f"/api/reports/{key}")
        assert r.status_code == 200, (key, r.text)
        assert "columns" in r.json()
    csv = client.get("/api/reports/energy?format=csv&group=station")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("Station")
    assert client.get("/api/reports/unknown").status_code == 404


def test_comparison_and_mode_switch(client):
    login(client, "admin")
    v = create_vehicle(client, soc=25)
    create_trip(client, v["id"], hours=14)
    cmp = client.get("/api/charging-schedules/comparison").json()
    assert {"baseline", "rule_based", "lp_benchmark", "delta"} <= set(cmp)
    login(client, "fleet_manager")
    r = client.put("/api/charging-schedules/mode", json={"mode": "baseline"})
    assert r.status_code == 200 and r.json()["mode"] == "baseline"


def test_schedule_approval_workflow(client, db):
    login(client, "admin")
    assert client.put("/api/config", json={"require_schedule_approval": True}).status_code == 200
    v = create_vehicle(client, soc=25)
    create_trip(client, v["id"], hours=2)
    data = client.get("/api/charging-schedules").json()
    pending = data["pending_run"]
    assert pending is not None
    assert any(r["status"] == "proposed" for r in data["reservations"])
    login(client, "fleet_manager")
    assert client.post(f"/api/charging-schedules/runs/{pending['id']}/approve").json()["status"] == "approved"
    statuses = {r["status"] for r in client.get("/api/charging-schedules").json()["reservations"]}
    assert "planned" in statuses and "proposed" not in statuses


def test_config_validation(client):
    login(client, "admin")
    assert client.put("/api/config", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.put("/api/config", json={"nonsense": 1}).status_code == 400
    r = client.put("/api/config", json={"departure_buffer_minutes": 20})
    assert r.status_code == 200 and "departure_buffer_minutes" in r.json()["changed"]


def test_integration_sync_requires_key(client):
    assert client.post("/api/integrations/fleet-sync", json={}).status_code in (401, 503)


def test_ocpp_charge_point_lifecycle(client, db):
    charger = db.scalar(select(Charger).where(Charger.code == "TST-OCPP"))
    charger.is_active = True
    db.commit()
    login(client, "admin")
    v = create_vehicle(client, soc=30)
    with client.websocket_connect("/api/ocpp/TST-OCPP", subprotocols=["ocpp1.6"]) as ws:
        ws.send_json([2, "1", "BootNotification", {"chargePointVendor": "Test", "chargePointModel": "T1"}])
        assert ws.receive_json()[2]["status"] == "Accepted"
        ws.send_json([2, "2", "StartTransaction", {"connectorId": 1, "idTag": "EV-900", "meterStart": 1000, "timestamp": now().isoformat()}])
        tx = ws.receive_json()[2]["transactionId"]
        assert tx > 0
        ws.send_json([2, "3", "MeterValues", {"connectorId": 1, "transactionId": tx, "meterValue": [{"timestamp": now().isoformat(), "sampledValue": [{"value": "11000", "measurand": "Energy.Active.Import.Register", "unit": "Wh"}]}]}])
        assert ws.receive_json()[0] == 3
        ws.send_json([2, "4", "StopTransaction", {"transactionId": tx, "meterStop": 21000, "timestamp": now().isoformat(), "reason": "Local"}])
        assert ws.receive_json()[2]["idTagInfo"]["status"] == "Accepted"
    db.expire_all()
    session = db.scalar(select(ChargingSession).where(ChargingSession.vehicle_id == v["id"]))
    assert session.source.value == "ocpp" and abs(session.energy_kwh - 20.0) < 0.01
    assert session.status in (SessionStatus.COMPLETED, SessionStatus.STOPPED)
    assert db.get(Vehicle, v["id"]).current_soc > 30


def test_health(client, db):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/health/ready").status_code == 200
    assert db.execute(text("SELECT 1")).scalar() == 1
