"""Demo data for the hackathon scenario (PRD §27).

All generated history and telemetry is flagged as simulated. The current fleet state
is generated relative to the moment of seeding so departures, tariff windows and
risk situations line up with the clock.
"""

import logging
import random
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import ROLE_INFO, ROLE_PERMISSIONS
from app.core.security import hash_password
from app.models import (
    Alert,
    BatteryProfile,
    Charger,
    ChargingRequest,
    ChargingSchedule,
    ChargingSession,
    Driver,
    EnergyReading,
    PriceSignal,
    ReadinessSnapshot,
    Role,
    ScheduleRun,
    ServiceProvider,
    Station,
    TariffPeriod,
    Trip,
    User,
    Vehicle,
)
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    ChargerStatus,
    ProviderKind,
    RoleCode,
    SchedulerMode,
    SessionSource,
    SessionStatus,
    TariffKind,
    TripPriority,
    TripStatus,
    VehicleAvailability,
    VehiclePriority,
)
from app.services import audit
from app.services.config_service import OperationalConfig, load_config, now, save_config
from app.services.tariffs import load_calendar

log = logging.getLogger("chargeopt.seed")

STATIONS = [
    ("PNY", "Peenya Depot", "Peenya Industrial Area, Bengaluru", 13.0285, 77.5197, 600.0, 0.0, 0.0, 0.0),
    ("WFD", "Whitefield Depot", "ITPL Main Road, Whitefield, Bengaluru", 12.9855, 77.7300, 320.0, 40.0, 0.0, 0.0),
    ("APH", "Airport Logistics Hub", "Cargo Terminal Road, Devanahalli", 13.1986, 77.7066, 260.0, 80.0, 200.0, 100.0),
]

PROFILES = [
    ("Urban delivery van 60", "Delivery van", 60, 11, 50, 0.92, 0.22, ["CCS2", "Type2"]),
    ("Cargo truck 120", "Cargo truck 7.5t", 120, 22, 100, 0.91, 0.65, ["CCS2", "Type2"]),
    ("City bus 300", "City bus 12m", 300, 22, 150, 0.93, 1.20, ["CCS2"]),
    ("Staff shuttle 90", "Staff shuttle", 90, 11, 60, 0.92, 0.35, ["CCS2", "Type2"]),
    ("Service car 40", "Service car", 40, 7.4, 50, 0.90, 0.15, ["CCS2", "Type2"]),
]

DESTINATIONS = [
    ("Electronic City", 12.8452, 77.6602),
    ("Hebbal", 13.0358, 77.5970),
    ("Koramangala", 12.9352, 77.6245),
    ("Yelahanka", 13.1007, 77.5963),
    ("Jayanagar", 12.9250, 77.5938),
    ("Marathahalli", 12.9569, 77.7011),
    ("Hosur Road Warehouse", 12.8890, 77.6400),
    ("Tumakuru Road DC", 13.0600, 77.4700),
    ("KR Puram", 13.0076, 77.6950),
    ("Majestic Bus Terminal", 12.9767, 77.5713),
    ("Hoskote Logistics Park", 13.0707, 77.7982),
    ("Kempegowda Airport T2", 13.1989, 77.7068),
]

FIRST = ["Arjun", "Priya", "Ravi", "Meera", "Karthik", "Ananya", "Suresh", "Divya", "Imran", "Lakshmi", "Vikram", "Neha",
         "Rahul", "Kavya", "Manoj", "Sneha", "Farhan", "Pooja", "Naveen", "Shruti"]
LAST = ["Rao", "Iyer", "Kumar", "Nair", "Reddy", "Shetty", "Gowda", "Khan", "Menon", "Pillai", "Hegde", "Joshi"]

DEMO_USERS = [
    ("admin@chargeopt.example", "Aditi Sharma", RoleCode.ADMIN),
    ("manager@chargeopt.example", "Rohan Mehta", RoleCode.FLEET_MANAGER),
    ("ops@chargeopt.example", "Sana Qureshi", RoleCode.OPERATIONS_MANAGER),
    ("operator@chargeopt.example", "Vivek Patil", RoleCode.CHARGING_OPERATOR),
    ("driver@chargeopt.example", "Ravi Kumar", RoleCode.DRIVER),
    ("viewer@chargeopt.example", "Leena D'Souza", RoleCode.VIEWER),
]


def sync_roles(db: Session) -> None:
    for code, perms in ROLE_PERMISSIONS.items():
        name, description = ROLE_INFO[code]
        role = db.get(Role, code.value)
        if role is None:
            db.add(Role(code=code.value, name=name, description=description, permissions=sorted(p.value for p in perms)))
        else:
            role.name, role.description, role.permissions = name, description, sorted(p.value for p in perms)
    db.flush()


def _local(at: datetime, cfg: OperationalConfig, hh: int, mm: int, min_ahead: timedelta) -> datetime:
    local = at.astimezone(cfg.tz)
    candidate = datetime.combine(local.date(), time(hh, mm), cfg.tz)
    while candidate - local < min_ahead:
        candidate += timedelta(days=1)
    return candidate


def seed_master_data(db: Session, password: str) -> None:
    settings = get_settings()
    cfg = OperationalConfig(
        timezone=settings.fleet_timezone,
        currency=settings.currency,
        scheduler_mode=SchedulerMode.BASELINE,
        default_rate_per_kwh=8.20,
        v2g_export_rate_per_kwh=9.50,
        simulation_enabled=False,
    )
    save_config(db, cfg, None)

    stations = {}
    for code, name, addr, lat, lon, load, solar, batt, batt_kw in STATIONS:
        st = Station(code=code, name=name, address=addr, latitude=lat, longitude=lon, max_load_kw=load, solar_capacity_kw=solar, battery_capacity_kwh=batt, battery_power_kw=batt_kw)
        db.add(st)
        stations[code] = st
    db.flush()

    for name, vtype, cap, ac, dc, eff, cons, conns in PROFILES:
        db.add(BatteryProfile(name=name, vehicle_type=vtype, capacity_kwh=cap, max_ac_kw=ac, max_dc_kw=dc, charging_efficiency=eff, consumption_kwh_per_km=cons, connector_types=conns))

    night_only = [{"days": list(range(7)), "start": "18:00", "end": "08:00"}]
    charger_specs = [
        *[("PNY", f"PNY-C{i:02d}", "CCS2", 60, False, None, None) for i in range(1, 9)],
        ("PNY", "PNY-C09", "CCS2", 120, False, None, None),
        ("PNY", "PNY-C10", "CCS2", 120, False, None, None),
        ("PNY", "PNY-C11", "Type2", 22, False, None, None),
        ("PNY", "PNY-C12", "Type2", 22, False, None, None),
        ("WFD", "WFD-C01", "CCS2", 60, True, None, None),
        ("WFD", "WFD-C02", "CCS2", 60, True, None, None),
        ("WFD", "WFD-C03", "CCS2", 60, False, None, None),
        ("WFD", "WFD-C04", "CCS2", 60, False, None, None),
        ("WFD", "WFD-C05", "Type2", 22, False, night_only, None),
        ("WFD", "WFD-C06", "Type2", 22, False, night_only, None),
        ("APH", "APH-C01", "CCS2", 120, False, None, None),
        ("APH", "APH-C02", "CCS2", 120, False, None, None),
        ("APH", "APH-C03", "CCS2", 60, False, None, None),
        ("APH", "APH-C04", "CCS2", 60, False, None, "APH-C04"),
    ]
    for st, code, conn, kw, bidi, sched, ocpp in charger_specs:
        db.add(Charger(code=code, station_id=stations[st].id, connector_type=conn, max_power_kw=kw, bidirectional=bidi, availability_schedule=sched, ocpp_identity=ocpp, status=ChargerStatus.AVAILABLE))

    tariffs = [
        ("Off-peak night", TariffKind.OFF_PEAK, time(0, 0), time(6, 0), 5.60, None),
        ("Day shoulder", TariffKind.SHOULDER, time(6, 0), time(18, 0), 8.20, 210.0),
        ("Evening peak", TariffKind.PEAK, time(18, 0), time(22, 0), 11.40, 420.0),
        ("Late shoulder", TariffKind.SHOULDER, time(22, 0), time(0, 0), 8.20, 210.0),
    ]
    for name, kind, start, end, rate, demand in tariffs:
        db.add(TariffPeriod(name=name, kind=kind, start_time=start, end_time=end, rate_per_kwh=rate, demand_charge_per_kw=demand, days_of_week=list(range(7))))

    providers = [
        ("Hebbal Public Fast Charge (directory sample)", ProviderKind.PUBLIC_CHARGING, 13.0450, 77.5920, ["CCS2"], 60, 18.0, None, None, None),
        ("Electronic City Charging Plaza (directory sample)", ProviderKind.PUBLIC_CHARGING, 12.8460, 77.6650, ["CCS2", "Type2"], 120, 19.5, None, None, None),
        ("Hoskote Highway Chargers (directory sample)", ProviderKind.PUBLIC_CHARGING, 13.0700, 77.7900, ["CCS2"], 150, 21.0, None, None, None),
        ("Mobile Charge Van North (directory sample)", ProviderKind.MOBILE_CHARGING, 13.0600, 77.6000, ["CCS2"], 30, 24.0, 1500.0, 25.0, 35),
        ("Mobile Charge Van South (directory sample)", ProviderKind.MOBILE_CHARGING, 12.9100, 77.6300, ["CCS2", "Type2"], 30, 24.0, 1500.0, 25.0, 40),
        ("Flatbed Recovery Services (directory sample)", ProviderKind.TOWING, 12.9700, 77.6000, [], None, None, 2500.0, 60.0, 45),
        ("Heavy Vehicle Towing (directory sample)", ProviderKind.TOWING, 13.0300, 77.5100, [], None, None, 4500.0, 95.0, 60),
    ]
    for name, kind, lat, lon, conns, kw, rate, callout, per_km, resp in providers:
        db.add(ServiceProvider(name=name, kind=kind, latitude=lat, longitude=lon, phone="+91 80 0000 0000", connector_types=conns, max_power_kw=kw, rate_per_kwh=rate, callout_fee=callout, per_km_fee=per_km, avg_response_min=resp, is_directory_sample=True))

    pw_hash = hash_password(password)
    users = {}
    for email, name, role in DEMO_USERS:
        u = User(email=email, full_name=name, role_code=role.value, password_hash=pw_hash)
        db.add(u)
        users[role] = u
    db.flush()

    rng = random.Random(7)
    station_cycle = ["PNY"] * 30 + ["WFD"] * 18 + ["APH"] * 12
    for i in range(60):
        name = "Ravi Kumar" if i == 26 else f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
        d = Driver(full_name=name, phone=f"+91 98{rng.randint(10000000, 99999999)}", license_number=f"KA{rng.randint(10, 99)}-2019-{100000 + i:06d}", home_station_id=stations[station_cycle[i]].id)
        if i == 26:
            d.user_id = users[RoleCode.DRIVER].id
        db.add(d)
    db.flush()
    audit.record(db, actor=None, action="system.seeded", category="config", summary="Initial master data seeded: 3 depots, 22 chargers, 4 tariff periods, 6 users")


def _session_breakdown(calendar, station_id: int, start: datetime, power: float, energy: float) -> tuple[dict, float, datetime]:
    remaining = energy
    t = start
    breakdown: dict[str, dict] = defaultdict(lambda: {"kwh": 0.0, "cost": 0.0})
    cost = 0.0
    while remaining > 1e-6:
        step_end = t + timedelta(minutes=15 - t.minute % 15) - timedelta(seconds=t.second)
        hours = (step_end - t).total_seconds() / 3600
        take = min(power * hours, remaining)
        q = calendar.quote(t, station_id)
        breakdown[q.kind]["kwh"] = round(breakdown[q.kind]["kwh"] + take, 4)
        breakdown[q.kind]["cost"] = round(breakdown[q.kind]["cost"] + take * q.rate, 4)
        cost += take * q.rate
        remaining -= take
        t = t + timedelta(hours=take / power)
    return dict(breakdown), round(cost, 4), t


def reset_operational_data(db: Session, user: User | None = None, simulation_enabled: bool | None = None, scheduler_mode: SchedulerMode = SchedulerMode.BASELINE, history_days: int = 30) -> dict:
    for model in (EnergyReading, ChargingSession, Alert, ChargingSchedule, ChargingRequest, ScheduleRun, ReadinessSnapshot, PriceSignal):
        db.execute(delete(model))
    db.execute(update(Charger).values(current_vehicle_id=None, power_limit_kw=None, status_note=""))
    db.execute(delete(Trip))
    db.execute(update(Vehicle).values(assigned_driver_id=None))
    db.execute(delete(Vehicle))
    db.flush()

    cfg = load_config(db)
    cfg.clock_offset_seconds = 0
    cfg.scheduler_mode = scheduler_mode
    if simulation_enabled is not None:
        cfg.simulation_enabled = simulation_enabled
    save_config(db, cfg, user.id if user else None)
    at = now()

    stations = {s.code: s for s in db.scalars(select(Station))}
    profiles = {p.vehicle_type: p for p in db.scalars(select(BatteryProfile))}
    chargers = list(db.scalars(select(Charger).order_by(Charger.code)))
    drivers = list(db.scalars(select(Driver).order_by(Driver.id)))
    calendar = load_calendar(db, cfg.tz, cfg.default_rate_per_kwh)
    rng = random.Random(2026)

    for c in chargers:
        c.status = ChargerStatus.AVAILABLE
        c.status_changed_at = at
    fault = next(c for c in chargers if c.code == "PNY-C05")
    fault.status, fault.status_note = ChargerStatus.FAULT, "Insulation monitoring fault reported by site technician"
    maint = next(c for c in chargers if c.code == "PNY-C12")
    maint.status, maint.status_note = ChargerStatus.MAINTENANCE, "Scheduled cable replacement"

    type_plan = ["Delivery van"] * 40 + ["Cargo truck 7.5t"] * 15 + ["City bus 12m"] * 10 + ["Staff shuttle"] * 15 + ["Service car"] * 20
    rng.shuffle(type_plan)
    overrides = {
        27: "Delivery van", 61: "Delivery van", 42: "Service car", 88: "City bus 12m", 15: "Cargo truck 7.5t", 73: "Staff shuttle",
        81: "City bus 12m", 82: "City bus 12m", 83: "City bus 12m", 84: "City bus 12m",
        89: "Staff shuttle", 90: "Delivery van", 91: "Cargo truck 7.5t", 44: "Delivery van", 47: "Staff shuttle", 62: "Delivery van", 63: "Delivery van",
    }
    vehicles: dict[int, Vehicle] = {}
    for i in range(1, 101):
        vtype = overrides.get(i, type_plan[i - 1])
        home = "PNY" if i <= 50 else ("WFD" if i <= 80 else "APH")
        p = profiles[vtype]
        v = Vehicle(
            registration=f"EV-{i:03d}",
            vehicle_type=vtype,
            battery_profile_id=p.id,
            battery_capacity_kwh=p.capacity_kwh,
            current_soc=round(rng.uniform(55, 95), 1),
            min_operating_soc=20 if vtype != "City bus 12m" else 25,
            required_departure_soc=80,
            max_soc=90 if vtype != "Service car" else 95,
            home_station_id=stations[home].id,
            current_station_id=stations[home].id,
            latitude=stations[home].latitude,
            longitude=stations[home].longitude,
            availability=VehicleAvailability.AVAILABLE,
            priority_category=VehiclePriority.HIGH if vtype == "City bus 12m" else VehiclePriority.STANDARD,
            assigned_driver_id=drivers[i - 1].id if i <= len(drivers) else None,
            soc_updated_at=at,
        )
        db.add(v)
        vehicles[i] = v
    db.flush()

    trip_no = [1000]

    def new_trip(v: Vehicle, departure: datetime, required: float | None, distance: float, priority=TripPriority.NORMAL, status=TripStatus.ASSIGNED, ret_hours: float | None = 9) -> Trip:
        trip_no[0] += 1
        dest = DESTINATIONS[trip_no[0] % len(DESTINATIONS)]
        t = Trip(
            code=f"TRP-{trip_no[0]}",
            vehicle_id=v.id,
            driver_id=v.assigned_driver_id,
            origin_station_id=v.home_station_id,
            destination=dest[0],
            destination_latitude=dest[1],
            destination_longitude=dest[2],
            distance_km=round(distance, 1),
            energy_kwh=round(distance * profiles[v.vehicle_type].consumption_kwh_per_km, 1),
            required_soc=required,
            departure_at=departure,
            return_at=departure + timedelta(hours=ret_hours) if ret_hours else None,
            priority=priority,
            status=status,
        )
        db.add(t)
        return t

    urgent = {89: (30, 70, 160), 90: (25, 75, 180), 91: (35, 70, 170), 44: (28, 75, 150), 47: (33, 70, 190), 62: (22, 70, 165), 63: (30, 72, 180)}
    overnight_buses = {81: 18, 82: 22, 83: 16, 84: 25}
    v2g_ready = {67: 88.0, 69: 87.0, 74: 89.0}
    special = {27, 61, 42, 88, 15, 73} | set(urgent) | set(overnight_buses) | set(v2g_ready)
    on_trip = [5, 12, 19, 33, 46, 52, 58, 66, 71, 77, 84, 93, 97, 64, 39]
    maintenance = [8, 55, 99]

    for i, v in vehicles.items():
        if i in special:
            continue
        p = profiles[v.vehicle_type]
        if i in maintenance:
            v.availability = VehicleAvailability.MAINTENANCE
            v.current_soc = round(rng.uniform(30, 70), 1)
            continue
        if i in on_trip:
            v.availability = VehicleAvailability.ON_TRIP
            v.current_station_id = None
            dest = DESTINATIONS[i % len(DESTINATIONS)]
            home = db.get(Station, v.home_station_id)
            frac = rng.uniform(0.3, 0.8)
            v.latitude = home.latitude + (dest[1] - home.latitude) * frac
            v.longitude = home.longitude + (dest[2] - home.longitude) * frac
            v.current_soc = round(rng.uniform(25, 60), 1)
            depart_at = at - timedelta(hours=rng.uniform(1, 5))
            t = new_trip(v, depart_at, 75, rng.uniform(40, 120), status=TripStatus.IN_PROGRESS, ret_hours=None)
            t.return_at = at + timedelta(hours=rng.uniform(0.7, 6))
            t.departed_at = depart_at
            t.departure_soc = min(90, v.current_soc + 30)
            t.requirement_met = True
            continue
        roll = rng.random()
        if roll < 0.82:
            hour = rng.choice([5, 5, 6, 6, 6, 7, 7, 7, 8, 8, 9, 10, 13, 15])
            minute = rng.choice([0, 15, 30, 45])
            departure = _local(at, cfg, hour, minute, timedelta(hours=2, minutes=30))
            required = float(rng.choice([60, 65, 70, 75, 80, 85]))
            needs = rng.random() < 0.55
            v.current_soc = round(rng.uniform(max(12, required - 45), required - 4) if needs else rng.uniform(required + 1, min(v.max_soc, required + 20)), 1)
            distance = (required - 15) / 100 * p.capacity_kwh / p.consumption_kwh_per_km
            new_trip(v, departure, required, distance, priority=TripPriority.HIGH if v.vehicle_type == "City bus 12m" else TripPriority.NORMAL)
        else:
            v.current_soc = round(rng.uniform(40, 92), 1)

    v = vehicles[27]
    v.current_soc = 42
    new_trip(v, _local(at, cfg, 7, 30, timedelta(hours=6)), 72, 110)
    v = vehicles[61]
    v.current_soc = 75
    new_trip(v, _local(at, cfg, 10, 0, timedelta(hours=3)), 65, 120)
    v = vehicles[42]
    v.current_soc = 18
    v.priority_category = VehiclePriority.CRITICAL
    new_trip(v, at + timedelta(minutes=35), 45, 30, priority=TripPriority.EMERGENCY, ret_hours=3)
    v = vehicles[88]
    v.current_soc = 14
    new_trip(v, at + timedelta(minutes=95), 80, 160, priority=TripPriority.HIGH)
    v = vehicles[15]
    v.current_soc = 11
    new_trip(v, at + timedelta(minutes=70), 85, 150, priority=TripPriority.HIGH)
    v = vehicles[73]
    v.current_soc = 9
    new_trip(v, at + timedelta(minutes=50), 80, 170)
    for i, (soc, required, minutes) in urgent.items():
        v = vehicles[i]
        v.current_soc = soc
        p = profiles[v.vehicle_type]
        new_trip(v, at + timedelta(minutes=minutes), required, (required - 20) / 100 * p.capacity_kwh / p.consumption_kwh_per_km)
    for i, soc in v2g_ready.items():
        v = vehicles[i]
        v.current_soc = min(soc, v.max_soc)
        new_trip(v, _local(at, cfg, 7, 0, timedelta(hours=8)), 60, 90)
    for i, soc in overnight_buses.items():
        v = vehicles[i]
        v.current_soc = soc
        new_trip(v, _local(at, cfg, 6, 0, timedelta(hours=6)), 85, 180, priority=TripPriority.HIGH)
    db.flush()

    charger_by_code = {c.code: c for c in chargers}
    for i, code in ((3, "PNY-C01"), (21, "PNY-C02"), (36, "PNY-C03"), (49, "PNY-C09"), (57, "WFD-C03"), (79, "WFD-C04")):
        v = vehicles[i]
        charger = charger_by_code[code]
        if v.availability != VehicleAvailability.AVAILABLE:
            continue
        p = profiles[v.vehicle_type]
        v.current_soc = round(rng.uniform(35, 55), 1)
        started = at - timedelta(minutes=rng.randint(10, 40))
        power = min(charger.max_power_kw, p.max_dc_kw)
        energy = power * (at - started).total_seconds() / 3600
        breakdown, cost, _ = _session_breakdown(calendar, charger.station_id, started, power, energy)
        db.add(
            ChargingSession(
                vehicle_id=v.id,
                charger_id=charger.id,
                started_at=started,
                start_soc=round(v.current_soc - energy * p.charging_efficiency / p.capacity_kwh * 100, 1),
                target_soc=v.max_soc,
                power_kw=power,
                energy_kwh=round(energy, 3),
                cost=cost,
                tariff_breakdown=breakdown,
                status=SessionStatus.ACTIVE,
                source=SessionSource.SIMULATED,
                last_reading_at=at,
                stop_reason=None,
            )
        )
        v.availability = VehicleAvailability.CHARGING
        charger.status = ChargerStatus.CHARGING
        charger.current_vehicle_id = v.id
    db.flush()

    _seed_history(db, cfg, calendar, at, vehicles, chargers, stations, profiles, rng, history_days, new_trip)
    audit.record(db, actor=user, action="simulation.reset", category="simulation", summary=f"Demo scenario generated: 100 vehicles, {history_days} days of simulated history, scheduler mode {scheduler_mode.value}")
    db.flush()
    return {"vehicles": len(vehicles), "history_days": history_days, "as_of": at}


def _seed_history(db, cfg, calendar, at, vehicles, chargers, stations, profiles, rng, days, new_trip) -> None:
    by_station = defaultdict(list)
    for c in chargers:
        by_station[c.station_id].append(c)
    alert_types = [
        (AlertType.MISSED_SLOT, AlertSeverity.WARNING, "{reg} missed its reserved slot", "Reservation released and rescheduled (R6)."),
        (AlertType.CHARGER_FAULT, AlertSeverity.CRITICAL, "Charger fault: {chg}", "Ground fault detected; affected sessions reassigned (R5)."),
        (AlertType.SESSION_INTERRUPTED, AlertSeverity.WARNING, "Charging interrupted: {reg} on {chg}", "Connector unplugged before target SoC."),
        (AlertType.PEAK_APPROACHING, AlertSeverity.WARNING, "Peak tariff approaching with charging incomplete", "3 vehicles still below target at 17:30."),
        (AlertType.UNEXPECTED_CONSUMPTION, AlertSeverity.WARNING, "Unexpected energy consumption: {reg}", "Trip used 31% more energy than expected."),
        (AlertType.BELOW_REQUIRED_SOC, AlertSeverity.CRITICAL, "{reg} at risk of missing departure SoC", "Projected SoC below requirement two hours before departure."),
    ]
    resolver = db.scalar(select(User).where(User.role_code == RoleCode.FLEET_MANAGER.value))
    sessions = []
    snaps = []
    alerts = []
    vlist = [v for v in vehicles.values()]
    for d in range(days, 0, -1):
        day_local = (at - timedelta(days=d)).astimezone(cfg.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        for v in vlist:
            if rng.random() > 0.62:
                continue
            p = profiles[v.vehicle_type]
            station_chargers = [c for c in by_station[v.home_station_id] if c.connector_type in p.connector_types]
            if not station_chargers:
                continue
            charger = rng.choice(station_chargers)
            start_hour = rng.choice([14, 16, 17, 18, 19, 19, 20, 21, 22, 23, 24, 25, 26, 27])
            started = day_local + timedelta(hours=start_hour, minutes=rng.choice([0, 10, 20, 30, 40, 50]))
            if started >= at - timedelta(hours=2):
                continue
            is_dc = charger.max_power_kw > 22
            power = min(charger.max_power_kw, p.max_dc_kw if is_dc else p.max_ac_kw)
            start_soc = rng.uniform(15, 55)
            end_soc = min(v.max_soc, start_soc + rng.uniform(20, 50))
            energy = (end_soc - start_soc) / 100 * p.capacity_kwh / p.charging_efficiency
            breakdown, cost, ended = _session_breakdown(calendar, charger.station_id, started, power, energy)
            interrupted = rng.random() < 0.02
            sessions.append(
                ChargingSession(
                    vehicle_id=v.id,
                    charger_id=charger.id,
                    started_at=started,
                    ended_at=ended,
                    start_soc=round(start_soc, 1),
                    end_soc=round(end_soc, 1),
                    target_soc=round(end_soc if not interrupted else end_soc + 10, 1),
                    power_kw=power,
                    energy_kwh=round(energy, 3),
                    cost=cost,
                    tariff_breakdown=breakdown,
                    status=SessionStatus.INTERRUPTED if interrupted else SessionStatus.COMPLETED,
                    stop_reason="connector unplugged" if interrupted else "target SoC reached (R7)",
                    source=SessionSource.SIMULATED,
                )
            )
        for v in vlist:
            if rng.random() > 0.7:
                continue
            p = profiles[v.vehicle_type]
            departure = day_local + timedelta(hours=rng.choice([5, 6, 6, 7, 7, 8, 9, 13]), minutes=rng.choice([0, 15, 30, 45]))
            if departure >= at - timedelta(hours=12):
                continue
            required = float(rng.choice([60, 65, 70, 75, 80, 85]))
            met = rng.random() > 0.06
            dep_soc = round(rng.uniform(required, min(98, required + 15)) if met else rng.uniform(required - 18, required - 2), 1)
            distance = (required - 15) / 100 * p.capacity_kwh / p.consumption_kwh_per_km
            t = new_trip(v, departure, required, distance, status=TripStatus.COMPLETED, ret_hours=rng.uniform(6, 10))
            t.departed_at = departure
            t.departure_soc = dep_soc
            t.requirement_met = met
            t.arrived_at = t.return_at
            used = t.energy_kwh * rng.uniform(0.85, 1.15)
            t.actual_energy_kwh = round(used, 1)
            t.arrival_soc = round(max(5, dep_soc - used / p.capacity_kwh * 100), 1)
        for h in range(24):
            ts = day_local + timedelta(hours=h)
            if ts >= at:
                break
            pct = round(min(100, max(70, rng.gauss(93 - (6 if 17 <= h <= 21 else 0), 3))), 1)
            total = rng.randint(55, 75)
            ready = round(total * pct / 100)
            snaps.append(ReadinessSnapshot(recorded_at=ts, vehicles_with_trip=total, ready_count=max(0, ready - rng.randint(5, 15)), projected_ready_count=ready, at_risk_count=total - ready, readiness_pct=pct))
        for _ in range(rng.randint(1, 4)):
            kind, sev, title, msg = rng.choice(alert_types)
            v = rng.choice(vlist)
            c = rng.choice(chargers)
            created = day_local + timedelta(hours=rng.uniform(0, 23))
            if created >= at:
                continue
            resolved = created + timedelta(minutes=rng.randint(8, 180))
            alerts.append(
                Alert(
                    type=kind,
                    severity=sev,
                    status=AlertStatus.RESOLVED,
                    title=title.format(reg=v.registration, chg=c.code),
                    message=msg,
                    vehicle_id=v.id if "{reg}" in title else None,
                    charger_id=c.id if "{chg}" in title else None,
                    created_at=created,
                    acknowledged_at=created + timedelta(minutes=rng.randint(2, 8)),
                    acknowledged_by_id=resolver.id if resolver else None,
                    resolved_at=resolved,
                    resolved_by_id=resolver.id if resolver else None,
                    resolution_note=rng.choice(["Vehicle re-plugged; schedule recalculated.", "Technician reset charger.", "Confirmed with driver; no action needed.", "Rescheduled to off-peak window."]),
                    details={"simulated_history": True},
                )
            )
    db.add_all(sessions)
    db.add_all(snaps)
    db.add_all(alerts)


def bootstrap(db: Session) -> None:
    settings = get_settings()
    sync_roles(db)
    load_config(db)
    has_users = (db.scalar(select(func.count()).select_from(User)) or 0) > 0
    if has_users or not settings.seed_demo_data:
        db.commit()
        return
    if not settings.demo_user_password:
        log.error("SEED_DEMO_DATA is enabled but DEMO_USER_PASSWORD is not set — no users were created.")
        db.commit()
        return
    log.info("Seeding demo master data and fleet scenario")
    seed_master_data(db, settings.demo_user_password)
    reset_operational_data(db)
    db.commit()
