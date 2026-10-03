"""Rule-based advisory features: contingency suggestions and V2G opportunities.

Both are deterministic recommendations for operators; neither controls vehicles.
"""

import math
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Charger, ServiceProvider, Station, Vehicle
from app.models.enums import ChargerStatus, ProviderKind, VehicleAvailability
from app.services.config_service import OperationalConfig
from app.services.scheduler.service import next_trips
from app.services.tariffs import TariffCalendar

AVG_ROAD_SPEED_KMH = 35.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def contingency(db: Session, vehicle: Vehicle, calendar: TariffCalendar, at: datetime, cfg: OperationalConfig) -> dict:
    lat, lon = vehicle.latitude, vehicle.longitude
    if lat is None or lon is None:
        station = vehicle.current_station or vehicle.home_station
        lat, lon = station.latitude, station.longitude
    profile = vehicle.battery_profile
    target = vehicle.required_departure_soc
    need_kwh = max(0.0, (target - vehicle.current_soc) / 100 * vehicle.battery_capacity_kwh) / profile.charging_efficiency
    range_km = vehicle.current_soc / 100 * vehicle.battery_capacity_kwh / profile.consumption_kwh_per_km
    connectors = set(profile.connector_types)

    options: list[dict] = []
    for st in db.scalars(select(Station).where(Station.is_active.is_(True))):
        compatible = [
            c for c in st.chargers
            if c.is_active and c.connector_type in connectors and c.status in (ChargerStatus.AVAILABLE, ChargerStatus.RESERVED)
        ]
        if not compatible:
            continue
        distance = haversine_km(lat, lon, st.latitude, st.longitude)
        best = max(compatible, key=lambda c: c.effective_power_kw)
        power = min(best.effective_power_kw, profile.max_dc_kw if best.max_power_kw > 22 else profile.max_ac_kw)
        rate = calendar.quote(at, st.id).rate
        options.append(
            {
                "kind": "fleet_depot",
                "name": st.name,
                "distance_km": round(distance, 1),
                "reachable": distance <= range_km,
                "eta_min": round(distance / AVG_ROAD_SPEED_KMH * 60),
                "charger": best.code,
                "connector": best.connector_type,
                "power_kw": power,
                "charge_time_min": round(need_kwh / power * 60) if power else None,
                "estimated_cost": round(need_kwh * rate, 2),
                "latitude": st.latitude,
                "longitude": st.longitude,
                "directory_sample": False,
            }
        )
    for p in db.scalars(select(ServiceProvider).where(ServiceProvider.is_active.is_(True))):
        distance = haversine_km(lat, lon, p.latitude, p.longitude)
        entry = {
            "name": p.name,
            "phone": p.phone,
            "distance_km": round(distance, 1),
            "latitude": p.latitude,
            "longitude": p.longitude,
            "directory_sample": p.is_directory_sample,
        }
        if p.kind == ProviderKind.PUBLIC_CHARGING:
            if not connectors & set(p.connector_types):
                continue
            power = min(p.max_power_kw or 50, profile.max_dc_kw)
            entry.update(
                kind="public_charging",
                reachable=distance <= range_km,
                eta_min=round(distance / AVG_ROAD_SPEED_KMH * 60),
                connector=", ".join(sorted(connectors & set(p.connector_types))),
                power_kw=power,
                charge_time_min=round(need_kwh / power * 60) if power else None,
                estimated_cost=round(need_kwh * (p.rate_per_kwh or 0), 2),
            )
        elif p.kind == ProviderKind.MOBILE_CHARGING:
            entry.update(
                kind="mobile_charging",
                reachable=True,
                eta_min=(p.avg_response_min or 0) + round(distance / AVG_ROAD_SPEED_KMH * 60),
                power_kw=p.max_power_kw,
                charge_time_min=round(need_kwh / (p.max_power_kw or 30) * 60),
                estimated_cost=round((p.callout_fee or 0) + need_kwh * (p.rate_per_kwh or 0) + distance * (p.per_km_fee or 0), 2),
            )
        else:
            depot = vehicle.home_station
            tow_km = haversine_km(lat, lon, depot.latitude, depot.longitude)
            entry.update(
                kind="towing",
                reachable=True,
                eta_min=(p.avg_response_min or 0) + round(distance / AVG_ROAD_SPEED_KMH * 60),
                tow_distance_km=round(tow_km, 1),
                estimated_cost=round((p.callout_fee or 0) + (tow_km + distance) * (p.per_km_fee or 0), 2),
            )
        options.append(entry)

    def rank(o: dict) -> tuple:
        order = {"fleet_depot": 0, "public_charging": 1, "mobile_charging": 2, "towing": 3}[o["kind"]]
        return (not o.get("reachable", True), order, o.get("eta_min") or 0, o.get("estimated_cost") or 0)

    options.sort(key=rank)
    rules = []
    if any(o["kind"] in ("fleet_depot", "public_charging") and o["reachable"] for o in options):
        rules.append("Nearest reachable compatible charger is preferred (depot first, then public network).")
    if not any(o.get("reachable") and o["kind"] in ("fleet_depot", "public_charging") for o in options):
        rules.append("No compatible charger is within remaining range — mobile charging or towing recommended.")
    return {
        "vehicle_id": vehicle.id,
        "registration": vehicle.registration,
        "current_soc": vehicle.current_soc,
        "estimated_range_km": round(range_km, 1),
        "energy_to_target_kwh": round(need_kwh, 1),
        "target_soc": target,
        "position": {"latitude": lat, "longitude": lon},
        "rules": rules,
        "options": options,
        "currency": cfg.currency,
    }


def v2g_opportunities(db: Session, calendar: TariffCalendar, at: datetime, cfg: OperationalConfig) -> dict:
    if not cfg.v2g_enabled:
        return {"enabled": False, "opportunities": [], "total_exportable_kwh": 0, "total_value": 0}
    peak_start = calendar.next_kind_start(at, "peak") if calendar.quote(at).kind != "peak" else at
    if peak_start is None:
        return {"enabled": True, "opportunities": [], "total_exportable_kwh": 0, "total_value": 0, "note": "No peak window in the next 30 hours"}
    peak_end = peak_start
    while calendar.quote(peak_end).kind == "peak" and peak_end - peak_start < timedelta(hours=12):
        peak_end += timedelta(minutes=15)
    trips = next_trips(db, at)
    bidirectional = {}
    for c in db.scalars(select(Charger).where(Charger.bidirectional.is_(True), Charger.is_active.is_(True))):
        if c.status not in (ChargerStatus.FAULT, ChargerStatus.MAINTENANCE):
            bidirectional.setdefault(c.station_id, []).append(c)
    rate_peak = calendar.quote(peak_start).rate
    results = []
    for v in db.scalars(
        select(Vehicle).where(Vehicle.is_active.is_(True), Vehicle.availability.in_((VehicleAvailability.AVAILABLE,)), Vehicle.current_station_id.is_not(None))
    ):
        chargers = bidirectional.get(v.current_station_id)
        if not chargers:
            continue
        trip = trips.get(v.id)
        floor = (trip.required_soc if trip and trip.required_soc else v.required_departure_soc) + cfg.v2g_soc_buffer
        if v.current_soc <= floor:
            continue
        free_until = trip.departure_at - timedelta(hours=1) if trip else at + timedelta(hours=cfg.horizon_hours)
        window_end = min(peak_end, free_until)
        dwell_h = (window_end - max(peak_start, at)).total_seconds() / 3600
        if dwell_h < cfg.v2g_min_dwell_hours:
            continue
        power = min(max(c.effective_power_kw for c in chargers), v.battery_profile.max_dc_kw)
        exportable = min((v.current_soc - floor) / 100 * v.battery_capacity_kwh, power * dwell_h)
        if exportable < 5:
            continue
        results.append(
            {
                "vehicle_id": v.id,
                "registration": v.registration,
                "station_id": v.current_station_id,
                "current_soc": v.current_soc,
                "soc_floor": round(floor, 1),
                "next_departure_at": trip.departure_at if trip else None,
                "window_start": max(peak_start, at),
                "window_end": window_end,
                "exportable_kwh": round(exportable, 1),
                "power_kw": power,
                "estimated_value": round(exportable * cfg.v2g_export_rate_per_kwh, 2),
                "avoided_peak_import_value": round(exportable * rate_peak, 2),
                "rule": f"SoC {v.current_soc:.0f}% exceeds requirement + {cfg.v2g_soc_buffer:.0f}% buffer, dwell {dwell_h:.1f} h overlaps peak, bidirectional charger available.",
            }
        )
    results.sort(key=lambda r: -r["exportable_kwh"])
    return {
        "enabled": True,
        "peak_window": {"start": peak_start, "end": peak_end},
        "opportunities": results,
        "total_exportable_kwh": round(sum(r["exportable_kwh"] for r in results), 1),
        "total_value": round(sum(r["estimated_value"] for r in results), 2),
        "export_rate_per_kwh": cfg.v2g_export_rate_per_kwh,
    }
