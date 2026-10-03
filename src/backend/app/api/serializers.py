from app.core.permissions import permissions_for
from app.models import (
    Alert,
    AuditLog,
    BatteryProfile,
    Charger,
    ChargingRequest,
    ChargingSchedule,
    ChargingSession,
    Driver,
    PriceSignal,
    ScheduleRun,
    ServiceProvider,
    Station,
    TariffPeriod,
    Trip,
    User,
    Vehicle,
)


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role_code,
        "role_name": u.role.name if u.role else u.role_code,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
        "permissions": sorted(p.value for p in permissions_for(u.role_code)),
        "driver_id": u.driver.id if u.driver else None,
    }


def station_out(s: Station) -> dict:
    return {
        "id": s.id,
        "code": s.code,
        "name": s.name,
        "address": s.address,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "max_load_kw": s.max_load_kw,
        "solar_capacity_kw": s.solar_capacity_kw,
        "battery_capacity_kwh": s.battery_capacity_kwh,
        "battery_power_kw": s.battery_power_kw,
        "is_active": s.is_active,
    }


def profile_out(p: BatteryProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "vehicle_type": p.vehicle_type,
        "capacity_kwh": p.capacity_kwh,
        "max_ac_kw": p.max_ac_kw,
        "max_dc_kw": p.max_dc_kw,
        "charging_efficiency": p.charging_efficiency,
        "consumption_kwh_per_km": p.consumption_kwh_per_km,
        "connector_types": p.connector_types,
    }


def trip_brief(t: Trip | None) -> dict | None:
    if t is None:
        return None
    return {
        "id": t.id,
        "code": t.code,
        "destination": t.destination,
        "departure_at": t.departure_at,
        "return_at": t.return_at,
        "required_soc": t.required_soc,
        "energy_kwh": t.energy_kwh,
        "distance_km": t.distance_km,
        "priority": t.priority.value,
        "status": t.status.value,
    }


def request_out(r: ChargingRequest | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id,
        "vehicle_id": r.vehicle_id,
        "trip_id": r.trip_id,
        "status": r.status.value,
        "priority_level": r.priority_level,
        "flexible": r.flexible,
        "current_soc": r.current_soc,
        "target_soc": r.target_soc,
        "required_soc": r.required_soc,
        "energy_needed_kwh": r.energy_needed_kwh,
        "deadline_at": r.deadline_at,
        "projected_soc": r.projected_soc,
        "shortfall_kwh": r.shortfall_kwh,
        "rules": r.rules,
        "explanation": r.explanation,
        "updated_at": r.updated_at,
    }


def readiness_state(v: Vehicle, required: float, request: ChargingRequest | None, charging: bool) -> str:
    if v.availability.value in ("on_trip", "maintenance", "out_of_service"):
        return v.availability.value
    if v.current_soc >= required - 0.5:
        return "ready"
    if request is not None and request.status.value in ("at_risk", "unscheduled") and request.trip_id is not None:
        return "at_risk"
    if charging:
        return "charging"
    return "needs_charge"


def vehicle_out(v: Vehicle, trip: Trip | None = None, request: ChargingRequest | None = None, last_session: ChargingSession | None = None, charging: bool = False) -> dict:
    if request is not None and request.trip_id is not None and request.required_soc is not None:
        required = request.required_soc
    elif trip is not None and trip.required_soc is not None:
        required = trip.required_soc
    elif request is not None and request.trip_id is None:
        required = min(request.target_soc, v.required_departure_soc)
    else:
        required = v.required_departure_soc
    energy = max(0.0, (required - v.current_soc) / 100 * v.battery_capacity_kwh)
    trip_energy = None
    if trip is not None:
        trip_energy = trip.energy_kwh if trip.energy_kwh is not None else round(trip.distance_km * v.battery_profile.consumption_kwh_per_km, 1)
    return {
        "id": v.id,
        "registration": v.registration,
        "vehicle_type": v.vehicle_type,
        "battery_profile_id": v.battery_profile_id,
        "battery_profile": v.battery_profile.name,
        "connector_types": v.battery_profile.connector_types,
        "battery_capacity_kwh": v.battery_capacity_kwh,
        "current_soc": v.current_soc,
        "min_operating_soc": v.min_operating_soc,
        "required_departure_soc": v.required_departure_soc,
        "max_soc": v.max_soc,
        "required_soc": required,
        "home_station_id": v.home_station_id,
        "current_station_id": v.current_station_id,
        "latitude": v.latitude,
        "longitude": v.longitude,
        "availability": v.availability.value,
        "priority_category": v.priority_category.value,
        "assigned_driver_id": v.assigned_driver_id,
        "assigned_driver": v.assigned_driver.full_name if v.assigned_driver else None,
        "is_active": v.is_active,
        "soc_updated_at": v.soc_updated_at,
        "charging_hold_until": v.charging_hold_until,
        "notes": v.notes,
        "external_ref": v.external_ref,
        "next_trip": trip_brief(trip),
        "departure_at": trip.departure_at if trip else None,
        "trip_energy_kwh": trip_energy,
        "energy_to_requirement_kwh": round(energy, 1),
        "last_session": {
            "id": last_session.id,
            "started_at": last_session.started_at,
            "ended_at": last_session.ended_at,
            "energy_kwh": round(last_session.energy_kwh, 2),
            "end_soc": last_session.end_soc,
            "status": last_session.status.value,
        }
        if last_session
        else None,
        "request": request_out(request),
        "readiness": readiness_state(v, required, request, charging),
    }


def driver_out(d: Driver) -> dict:
    return {
        "id": d.id,
        "full_name": d.full_name,
        "phone": d.phone,
        "license_number": d.license_number,
        "home_station_id": d.home_station_id,
        "user_id": d.user_id,
        "user_email": d.user.email if d.user else None,
        "is_active": d.is_active,
    }


def trip_out(t: Trip) -> dict:
    return {
        **trip_brief(t),
        "vehicle_id": t.vehicle_id,
        "vehicle": t.vehicle.registration if t.vehicle else None,
        "driver_id": t.driver_id,
        "driver": t.driver.full_name if t.driver else None,
        "origin_station_id": t.origin_station_id,
        "origin_station": t.origin_station.name if t.origin_station else None,
        "destination_latitude": t.destination_latitude,
        "destination_longitude": t.destination_longitude,
        "departed_at": t.departed_at,
        "departure_soc": t.departure_soc,
        "requirement_met": t.requirement_met,
        "arrived_at": t.arrived_at,
        "arrival_soc": t.arrival_soc,
        "actual_energy_kwh": t.actual_energy_kwh,
        "external_ref": t.external_ref,
        "created_at": t.created_at,
    }


def charger_out(c: Charger) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "station_id": c.station_id,
        "station": c.station.name if c.station else None,
        "connector_type": c.connector_type,
        "max_power_kw": c.max_power_kw,
        "power_limit_kw": c.power_limit_kw,
        "effective_power_kw": c.effective_power_kw,
        "status": c.status.value,
        "status_note": c.status_note,
        "status_changed_at": c.status_changed_at,
        "current_vehicle_id": c.current_vehicle_id,
        "current_vehicle": c.current_vehicle.registration if c.current_vehicle else None,
        "availability_schedule": c.availability_schedule,
        "bidirectional": c.bidirectional,
        "ocpp_identity": c.ocpp_identity,
        "ocpp_connected": c.ocpp_connected,
        "last_heartbeat_at": c.last_heartbeat_at,
        "is_active": c.is_active,
    }


def tariff_out(t: TariffPeriod) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind.value,
        "start_time": t.start_time.strftime("%H:%M"),
        "end_time": t.end_time.strftime("%H:%M"),
        "rate_per_kwh": t.rate_per_kwh,
        "demand_charge_per_kw": t.demand_charge_per_kw,
        "days_of_week": t.days_of_week,
        "station_id": t.station_id,
        "is_active": t.is_active,
    }


def signal_out(s: PriceSignal) -> dict:
    return {"id": s.id, "station_id": s.station_id, "starts_at": s.starts_at, "ends_at": s.ends_at, "rate_per_kwh": s.rate_per_kwh, "source": s.source}


def reservation_out(r: ChargingSchedule) -> dict:
    return {
        "id": r.id,
        "run_id": r.run_id,
        "request_id": r.request_id,
        "vehicle_id": r.vehicle_id,
        "vehicle": r.vehicle.registration if r.vehicle else None,
        "charger_id": r.charger_id,
        "charger": r.charger.code if r.charger else None,
        "station_id": r.charger.station_id if r.charger else None,
        "start_at": r.start_at,
        "end_at": r.end_at,
        "power_kw": r.power_kw,
        "planned_energy_kwh": r.planned_energy_kwh,
        "estimated_cost": r.estimated_cost,
        "target_soc": r.target_soc,
        "priority_level": r.priority_level,
        "status": r.status.value,
        "is_override": r.is_override,
        "override_reason": r.override_reason,
        "rules": r.rules,
        "explanation": r.explanation,
        "tariff_mix": r.tariff_mix,
        "created_at": r.created_at,
    }


def run_out(r: ScheduleRun) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at,
        "trigger": r.trigger,
        "mode": r.mode.value,
        "status": r.status.value,
        "triggered_by_id": r.triggered_by_id,
        "approved_by_id": r.approved_by_id,
        "approved_at": r.approved_at,
        "duration_ms": r.duration_ms,
        "vehicles_evaluated": r.vehicles_evaluated,
        "vehicles_needing_charge": r.vehicles_needing_charge,
        "reservations_created": r.reservations_created,
        "reservations_kept": r.reservations_kept,
        "reservations_superseded": r.reservations_superseded,
        "conflicts_prevented": r.conflicts_prevented,
        "at_risk_count": r.at_risk_count,
        "planned_energy_kwh": r.planned_energy_kwh,
        "planned_cost": r.planned_cost,
        "summary": r.summary,
    }


def session_out(s: ChargingSession) -> dict:
    return {
        "id": s.id,
        "schedule_id": s.schedule_id,
        "vehicle_id": s.vehicle_id,
        "vehicle": s.vehicle.registration if s.vehicle else None,
        "charger_id": s.charger_id,
        "charger": s.charger.code if s.charger else None,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "start_soc": s.start_soc,
        "end_soc": s.end_soc,
        "current_soc": s.vehicle.current_soc if s.vehicle and s.status.value == "active" else s.end_soc,
        "target_soc": s.target_soc,
        "power_kw": s.power_kw,
        "energy_kwh": round(s.energy_kwh, 3),
        "cost": round(s.cost, 2),
        "tariff_breakdown": s.tariff_breakdown,
        "status": s.status.value,
        "stop_reason": s.stop_reason,
        "source": s.source.value,
        "scheduled_end_at": s.schedule.end_at if s.schedule else None,
    }


def alert_out(a: Alert) -> dict:
    return {
        "id": a.id,
        "type": a.type.value,
        "severity": a.severity.value,
        "status": a.status.value,
        "title": a.title,
        "message": a.message,
        "vehicle_id": a.vehicle_id,
        "vehicle": a.vehicle.registration if a.vehicle else None,
        "charger_id": a.charger_id,
        "charger": a.charger.code if a.charger else None,
        "station_id": a.station_id,
        "trip_id": a.trip_id,
        "schedule_id": a.schedule_id,
        "details": a.details,
        "created_at": a.created_at,
        "acknowledged_at": a.acknowledged_at,
        "acknowledged_by_id": a.acknowledged_by_id,
        "resolved_at": a.resolved_at,
        "resolved_by_id": a.resolved_by_id,
        "resolution_note": a.resolution_note,
    }


def audit_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "created_at": a.created_at,
        "actor": a.actor,
        "user_id": a.user_id,
        "action": a.action,
        "category": a.category,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "summary": a.summary,
        "details": a.details,
        "ip_address": a.ip_address,
    }


def provider_out(p: ServiceProvider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind.value,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "phone": p.phone,
        "connector_types": p.connector_types,
        "max_power_kw": p.max_power_kw,
        "rate_per_kwh": p.rate_per_kwh,
        "callout_fee": p.callout_fee,
        "per_km_fee": p.per_km_fee,
        "avg_response_min": p.avg_response_min,
        "is_directory_sample": p.is_directory_sample,
    }
