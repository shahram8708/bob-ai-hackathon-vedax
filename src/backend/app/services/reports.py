import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Alert,
    AuditLog,
    Charger,
    ChargingSession,
    ReadinessSnapshot,
    ScheduleRun,
    Station,
    Trip,
    Vehicle,
)
from app.models.enums import AlertStatus, TripStatus
from app.services import monitoring
from app.services.config_service import OperationalConfig
from app.services.tariffs import TariffCalendar

KIND_LABEL = {"peak": "Peak", "shoulder": "Shoulder", "off_peak": "Off-peak", "custom": "Custom"}


@dataclass
class Report:
    key: str
    title: str
    description: str
    columns: list[tuple[str, str]]
    rows: list[dict]
    summary: dict = field(default_factory=dict)
    series: list[dict] = field(default_factory=list)
    simulated: bool = True

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "columns": [{"key": k, "label": label} for k, label in self.columns],
            "rows": self.rows,
            "summary": self.summary,
            "series": self.series,
            "simulated": self.simulated,
        }

    def as_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([label for _, label in self.columns])
        for row in self.rows:
            writer.writerow([_csv_value(row.get(k)) for k, _ in self.columns])
        return buf.getvalue()


def _csv_value(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


@dataclass
class Range:
    start: datetime
    end: datetime
    start_date: date
    end_date: date

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def make_range(cfg: OperationalConfig, start: date | None, end: date | None, at: datetime) -> Range:
    today = at.astimezone(cfg.tz).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end:
        start, end = end, start
    s = datetime.combine(start, time.min, cfg.tz)
    e = min(datetime.combine(end + timedelta(days=1), time.min, cfg.tz), at)
    return Range(s, e, start, end)


def _sessions(db: Session, r: Range, vehicle_id: int | None = None, station_id: int | None = None) -> list[ChargingSession]:
    q = (
        select(ChargingSession)
        .where(ChargingSession.started_at >= r.start, ChargingSession.started_at < r.end)
        .options(selectinload(ChargingSession.vehicle), selectinload(ChargingSession.charger), selectinload(ChargingSession.schedule))
        .order_by(ChargingSession.started_at.desc())
    )
    if vehicle_id:
        q = q.where(ChargingSession.vehicle_id == vehicle_id)
    if station_id:
        q = q.join(Charger, Charger.id == ChargingSession.charger_id).where(Charger.station_id == station_id)
    return list(db.scalars(q))


def _session_end(s: ChargingSession, at: datetime) -> datetime:
    return s.ended_at or at


def charging_history(db: Session, r: Range, cfg: OperationalConfig, vehicle_id: int | None = None, station_id: int | None = None) -> Report:
    rows = []
    for s in _sessions(db, r, vehicle_id, station_id):
        rows.append(
            {
                "session_id": s.id,
                "vehicle": s.vehicle.registration,
                "charger": s.charger.code,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "start_soc": round(s.start_soc, 1),
                "end_soc": round(s.end_soc if s.end_soc is not None else s.vehicle.current_soc, 1),
                "energy_kwh": round(s.energy_kwh, 2),
                "cost": round(s.cost, 2),
                "status": s.status.value,
                "source": s.source.value,
                "stop_reason": s.stop_reason or "",
            }
        )
    return Report(
        "charging-history",
        "Vehicle charging history",
        "Every charging session in the period with energy, cost and outcome.",
        [("session_id", "Session"), ("vehicle", "Vehicle"), ("charger", "Charger"), ("started_at", "Started"), ("ended_at", "Ended"),
         ("start_soc", "Start SoC %"), ("end_soc", "End SoC %"), ("energy_kwh", "Energy kWh"), ("cost", f"Cost {cfg.currency}"),
         ("status", "Status"), ("source", "Source"), ("stop_reason", "Stop reason")],
        rows,
        {"sessions": len(rows), "energy_kwh": round(sum(x["energy_kwh"] for x in rows), 1), "cost": round(sum(x["cost"] for x in rows), 2)},
    )


def charger_utilization(db: Session, r: Range, cfg: OperationalConfig, at: datetime) -> Report:
    chargers = list(db.scalars(select(Charger).options(selectinload(Charger.station)).order_by(Charger.code)))
    stats = defaultdict(lambda: {"sessions": 0, "hours": 0.0, "energy": 0.0, "cost": 0.0})
    for s in _sessions(db, r):
        end = min(_session_end(s, at), r.end)
        st = stats[s.charger_id]
        st["sessions"] += 1
        st["hours"] += max(0.0, (end - max(s.started_at, r.start)).total_seconds() / 3600)
        st["energy"] += s.energy_kwh
        st["cost"] += s.cost
    rows = []
    for c in chargers:
        st = stats[c.id]
        rows.append(
            {
                "charger": c.code,
                "station": c.station.name,
                "connector": c.connector_type,
                "max_power_kw": c.max_power_kw,
                "status": c.status.value,
                "sessions": st["sessions"],
                "charging_hours": round(st["hours"], 1),
                "utilization_pct": round(st["hours"] / r.hours * 100, 1) if r.hours else 0.0,
                "energy_kwh": round(st["energy"], 1),
                "load_factor_pct": round(st["energy"] / (c.max_power_kw * r.hours) * 100, 1) if r.hours else 0.0,
            }
        )
    avg = sum(x["utilization_pct"] for x in rows) / len(rows) if rows else 0
    return Report(
        "charger-utilization",
        "Charger utilization",
        "Share of the period each charger spent charging, with delivered energy.",
        [("charger", "Charger"), ("station", "Station"), ("connector", "Connector"), ("max_power_kw", "Max kW"), ("status", "Status"),
         ("sessions", "Sessions"), ("charging_hours", "Charging h"), ("utilization_pct", "Utilization %"), ("energy_kwh", "Energy kWh"), ("load_factor_pct", "Load factor %")],
        rows,
        {"average_utilization_pct": round(avg, 1), "chargers": len(rows)},
    )


def energy_consumption(db: Session, r: Range, cfg: OperationalConfig, group: str = "vehicle") -> Report:
    sessions = _sessions(db, r)
    stations = {s.id: s for s in db.scalars(select(Station))}
    agg = defaultdict(lambda: {"sessions": 0, "energy": 0.0, "cost": 0.0, "peak": 0.0})
    daily = defaultdict(lambda: defaultdict(float))
    for s in sessions:
        key = s.vehicle.registration if group == "vehicle" else stations[s.charger.station_id].name
        a = agg[key]
        a["sessions"] += 1
        a["energy"] += s.energy_kwh
        a["cost"] += s.cost
        a["peak"] += (s.tariff_breakdown or {}).get("peak", {}).get("kwh", 0.0)
        day = s.started_at.astimezone(cfg.tz).date().isoformat()
        for kind, b in (s.tariff_breakdown or {}).items():
            daily[day][kind] += b.get("kwh", 0.0)
    rows = [
        {
            "name": k,
            "sessions": v["sessions"],
            "energy_kwh": round(v["energy"], 1),
            "peak_kwh": round(v["peak"], 1),
            "cost": round(v["cost"], 2),
            "avg_cost_per_kwh": round(v["cost"] / v["energy"], 4) if v["energy"] else 0,
        }
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["energy"])
    ]
    series = []
    day = r.start_date
    while day <= r.end_date:
        d = daily.get(day.isoformat(), {})
        series.append({"date": day.isoformat(), **{k: round(d.get(k, 0.0), 1) for k in ("off_peak", "shoulder", "peak", "custom")}})
        day += timedelta(days=1)
    label = "Vehicle" if group == "vehicle" else "Station"
    return Report(
        f"energy-by-{group}",
        f"Energy consumption by {group}",
        f"Charging energy per {group} with peak-period share, plus a daily trend by tariff period.",
        [("name", label), ("sessions", "Sessions"), ("energy_kwh", "Energy kWh"), ("peak_kwh", "Peak kWh"), ("cost", f"Cost {cfg.currency}"), ("avg_cost_per_kwh", f"Avg {cfg.currency}/kWh")],
        rows,
        {"energy_kwh": round(sum(x["energy_kwh"] for x in rows), 1), "entities": len(rows)},
        series,
    )


def _station_peak_kw(sessions: list[ChargingSession], at: datetime, bucket_minutes: int = 15) -> dict[int, dict[datetime, float]]:
    loads: dict[int, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    for s in sessions:
        end = _session_end(s, at)
        hours = max((end - s.started_at).total_seconds() / 3600, 1 / 60)
        power = s.energy_kwh / hours
        t = s.started_at.replace(second=0, microsecond=0)
        t -= timedelta(minutes=t.minute % bucket_minutes)
        while t < end:
            loads[s.charger.station_id][t] += power
            t += timedelta(minutes=bucket_minutes)
    return loads


def cost_by_period(db: Session, r: Range, cfg: OperationalConfig, calendar: TariffCalendar, at: datetime) -> Report:
    sessions = _sessions(db, r)
    totals = defaultdict(lambda: {"kwh": 0.0, "cost": 0.0})
    for s in sessions:
        for kind, b in (s.tariff_breakdown or {}).items():
            totals[kind]["kwh"] += b.get("kwh", 0.0)
            totals[kind]["cost"] += b.get("cost", 0.0)
    energy_total = sum(v["kwh"] for v in totals.values())
    energy_cost = sum(v["cost"] for v in totals.values())
    rows = [
        {
            "period": KIND_LABEL.get(k, k),
            "energy_kwh": round(v["kwh"], 1),
            "share_pct": round(v["kwh"] / energy_total * 100, 1) if energy_total else 0,
            "energy_cost": round(v["cost"], 2),
            "avg_rate": round(v["cost"] / v["kwh"], 4) if v["kwh"] else 0,
        }
        for k, v in sorted(totals.items(), key=lambda kv: ["off_peak", "shoulder", "peak", "custom"].index(kv[0]) if kv[0] in KIND_LABEL else 9)
    ]

    stations = {s.id: s for s in db.scalars(select(Station))}
    loads = _station_peak_kw(sessions, at)
    demand_rows = []
    demand_total = 0.0
    solar_total = 0.0
    storage_total = 0.0
    for sid, buckets in loads.items():
        station = stations[sid]
        best_charge = 0.0
        peak_kw = 0.0
        peak_kwh_by_day = defaultdict(float)
        for t, kw in buckets.items():
            q = calendar.quote(t, sid)
            peak_kw = max(peak_kw, kw)
            best_charge = max(best_charge, kw * q.demand_charge)
            solar_total += min(kw, calendar.solar_kw(t + timedelta(minutes=7), sid)) * 0.25 * q.rate
            if q.kind == "peak":
                peak_kwh_by_day[t.astimezone(cfg.tz).date()] += kw * 0.25
        demand_total += best_charge
        if station.battery_capacity_kwh > 0:
            usable = station.battery_capacity_kwh * 0.9
            peak_rate = max((p.rate for p in calendar.periods if p.kind == "peak"), default=0)
            off_rate = min((p.rate for p in calendar.periods if p.kind == "off_peak"), default=0)
            for _, kwh in peak_kwh_by_day.items():
                shaved = min(kwh, usable)
                storage_total += shaved * (peak_rate - off_rate / cfg.storage_round_trip_efficiency)
        demand_rows.append({"station": station.name, "peak_kw": round(peak_kw, 1), "demand_charge_estimate": round(best_charge, 2)})

    return Report(
        "cost-by-period",
        "Energy cost by tariff period",
        "Measured/simulated session energy priced at the applicable tariff period. Demand charges, on-site solar and battery storage offsets are modelled estimates shown separately.",
        [("period", "Tariff period"), ("energy_kwh", "Energy kWh"), ("share_pct", "Share %"), ("energy_cost", f"Energy cost {cfg.currency}"), ("avg_rate", f"Avg {cfg.currency}/kWh")],
        rows,
        {
            "energy_kwh": round(energy_total, 1),
            "energy_cost": round(energy_cost, 2),
            "demand_charge_estimate_monthly": round(demand_total, 2),
            "demand_by_station": demand_rows,
            "solar_offset_estimate": round(solar_total, 2),
            "storage_offset_estimate": round(storage_total, 2),
            "currency": cfg.currency,
        },
    )


def missed_requirements(db: Session, r: Range, cfg: OperationalConfig, at: datetime) -> Report:
    rows = []
    trips = db.scalars(
        select(Trip)
        .where(Trip.departed_at >= r.start, Trip.departed_at < r.end, Trip.requirement_met.is_(False))
        .options(selectinload(Trip.vehicle))
        .order_by(Trip.departed_at.desc())
    )
    for t in trips:
        rows.append(
            {
                "kind": "Missed",
                "vehicle": t.vehicle.registration if t.vehicle else "",
                "trip": t.code,
                "departure_at": t.departure_at,
                "soc": t.departure_soc,
                "required_soc": t.required_soc,
                "detail": f"Departed at {t.departure_soc:.0f}%",
            }
        )
    for item in monitoring.readiness(db, at, cfg)["at_risk"]:
        rows.append(
            {
                "kind": "At risk",
                "vehicle": item["registration"],
                "trip": item["trip_code"],
                "departure_at": item["departure_at"],
                "soc": item["current_soc"],
                "required_soc": item["required_soc"],
                "detail": item["reason"][:240],
            }
        )
    return Report(
        "missed-at-risk",
        "Missed or at-risk charging requirements",
        "Departures that left below their required SoC in the period, plus upcoming departures currently at risk.",
        [("kind", "Type"), ("vehicle", "Vehicle"), ("trip", "Trip"), ("departure_at", "Departure"), ("soc", "SoC %"), ("required_soc", "Required %"), ("detail", "Detail")],
        rows,
        {"missed": sum(1 for x in rows if x["kind"] == "Missed"), "at_risk": sum(1 for x in rows if x["kind"] == "At risk")},
    )


def scheduled_vs_actual(db: Session, r: Range, cfg: OperationalConfig, at: datetime) -> Report:
    rows = []
    for s in _sessions(db, r):
        if s.schedule is None:
            continue
        sched_h = (s.schedule.end_at - s.schedule.start_at).total_seconds() / 3600
        actual_h = (_session_end(s, at) - s.started_at).total_seconds() / 3600
        rows.append(
            {
                "vehicle": s.vehicle.registration,
                "charger": s.charger.code,
                "scheduled_start": s.schedule.start_at,
                "actual_start": s.started_at,
                "start_delay_min": round((s.started_at - s.schedule.start_at).total_seconds() / 60, 1),
                "scheduled_hours": round(sched_h, 2),
                "actual_hours": round(actual_h, 2),
                "scheduled_kwh": round(s.schedule.planned_energy_kwh, 2),
                "actual_kwh": round(s.energy_kwh, 2),
                "variance_pct": round((s.energy_kwh / s.schedule.planned_energy_kwh - 1) * 100, 1) if s.schedule.planned_energy_kwh else 0,
            }
        )
    delays = [x["start_delay_min"] for x in rows]
    return Report(
        "scheduled-vs-actual",
        "Scheduled versus actual charging time",
        "Reserved slot compared with the session that actually ran.",
        [("vehicle", "Vehicle"), ("charger", "Charger"), ("scheduled_start", "Scheduled start"), ("actual_start", "Actual start"), ("start_delay_min", "Delay min"),
         ("scheduled_hours", "Scheduled h"), ("actual_hours", "Actual h"), ("scheduled_kwh", "Scheduled kWh"), ("actual_kwh", "Actual kWh"), ("variance_pct", "Variance %")],
        rows,
        {"sessions": len(rows), "avg_start_delay_min": round(sum(delays) / len(delays), 1) if delays else 0},
    )


def readiness_report(db: Session, r: Range, cfg: OperationalConfig, at: datetime) -> Report:
    by_day = defaultdict(lambda: {"departures": 0, "met": 0})
    for t in db.scalars(select(Trip).where(Trip.departed_at >= r.start, Trip.departed_at < r.end, Trip.requirement_met.is_not(None))):
        d = by_day[t.departed_at.astimezone(cfg.tz).date().isoformat()]
        d["departures"] += 1
        d["met"] += 1 if t.requirement_met else 0
    snaps = defaultdict(list)
    for s in db.scalars(select(ReadinessSnapshot).where(ReadinessSnapshot.recorded_at >= r.start, ReadinessSnapshot.recorded_at < r.end)):
        snaps[s.recorded_at.astimezone(cfg.tz).date().isoformat()].append(s.readiness_pct)
    rows = []
    day = r.start_date
    while day <= r.end_date:
        key = day.isoformat()
        d = by_day.get(key, {"departures": 0, "met": 0})
        values = snaps.get(key, [])
        rows.append(
            {
                "date": key,
                "departures": d["departures"],
                "met": d["met"],
                "missed": d["departures"] - d["met"],
                "met_pct": round(d["met"] / d["departures"] * 100, 1) if d["departures"] else None,
                "avg_projected_readiness_pct": round(sum(values) / len(values), 1) if values else None,
                "min_projected_readiness_pct": round(min(values), 1) if values else None,
            }
        )
        day += timedelta(days=1)
    total = sum(x["departures"] for x in rows)
    met = sum(x["met"] for x in rows)
    current = monitoring.readiness(db, at, cfg)
    return Report(
        "readiness",
        "Fleet readiness report",
        "Departures meeting their required SoC per day, with hourly projected readiness snapshots.",
        [("date", "Date"), ("departures", "Departures"), ("met", "Met"), ("missed", "Missed"), ("met_pct", "Met %"),
         ("avg_projected_readiness_pct", "Avg projected %"), ("min_projected_readiness_pct", "Min projected %")],
        rows,
        {
            "departures": total,
            "met_pct": round(met / total * 100, 1) if total else None,
            "current_projected_readiness_pct": current["readiness_pct"],
            "current_at_risk": len(current["at_risk"]),
        },
        [{"date": x["date"], "met_pct": x["met_pct"], "projected": x["avg_projected_readiness_pct"]} for x in rows],
    )


def peak_distribution(db: Session, r: Range, cfg: OperationalConfig) -> Report:
    by_day = defaultdict(lambda: defaultdict(float))
    for s in _sessions(db, r):
        day = s.started_at.astimezone(cfg.tz).date().isoformat()
        for kind, b in (s.tariff_breakdown or {}).items():
            by_day[day][kind] += b.get("kwh", 0.0)
    rows = []
    day = r.start_date
    while day <= r.end_date:
        d = by_day.get(day.isoformat(), {})
        total = sum(d.values())
        rows.append(
            {
                "date": day.isoformat(),
                "off_peak_kwh": round(d.get("off_peak", 0), 1),
                "shoulder_kwh": round(d.get("shoulder", 0), 1),
                "peak_kwh": round(d.get("peak", 0), 1),
                "custom_kwh": round(d.get("custom", 0), 1),
                "peak_share_pct": round(d.get("peak", 0) / total * 100, 1) if total else 0,
            }
        )
        day += timedelta(days=1)
    total = sum(x["off_peak_kwh"] + x["shoulder_kwh"] + x["peak_kwh"] + x["custom_kwh"] for x in rows)
    peak = sum(x["peak_kwh"] for x in rows)
    off = sum(x["off_peak_kwh"] for x in rows)
    return Report(
        "peak-distribution",
        "Peak versus off-peak charging distribution",
        "Daily charging energy split by tariff period.",
        [("date", "Date"), ("off_peak_kwh", "Off-peak kWh"), ("shoulder_kwh", "Shoulder kWh"), ("peak_kwh", "Peak kWh"), ("custom_kwh", "Custom kWh"), ("peak_share_pct", "Peak share %")],
        rows,
        {"energy_kwh": round(total, 1), "peak_share_pct": round(peak / total * 100, 1) if total else 0, "off_peak_share_pct": round(off / total * 100, 1) if total else 0},
        rows,
    )


def exception_history(db: Session, r: Range, cfg: OperationalConfig) -> Report:
    alerts = db.scalars(
        select(Alert).where(Alert.created_at >= r.start, Alert.created_at < r.end).options(selectinload(Alert.vehicle), selectinload(Alert.charger)).order_by(Alert.created_at.desc())
    )
    rows = []
    for a in alerts:
        rows.append(
            {
                "id": a.id,
                "created_at": a.created_at,
                "type": a.type.value.replace("_", " "),
                "severity": a.severity.value,
                "status": a.status.value,
                "vehicle": a.vehicle.registration if a.vehicle else "",
                "charger": a.charger.code if a.charger else "",
                "title": a.title,
                "resolved_at": a.resolved_at,
                "resolution_note": a.resolution_note or "",
                "time_to_resolve_min": round((a.resolved_at - a.created_at).total_seconds() / 60) if a.resolved_at else None,
            }
        )
    by_type = defaultdict(int)
    for x in rows:
        by_type[x["type"]] += 1
    return Report(
        "exceptions",
        "Exception and fault history",
        "Alerts raised in the period, how they were handled and how long resolution took.",
        [("id", "ID"), ("created_at", "Raised"), ("type", "Type"), ("severity", "Severity"), ("status", "Status"), ("vehicle", "Vehicle"), ("charger", "Charger"),
         ("title", "Title"), ("resolved_at", "Resolved"), ("time_to_resolve_min", "Minutes to resolve"), ("resolution_note", "Resolution")],
        rows,
        {"total": len(rows), "unresolved": sum(1 for x in rows if x["status"] != "resolved"), "by_type": dict(by_type)},
    )


def summary(db: Session, cfg: OperationalConfig, period: str, at: datetime, buckets: int = 8) -> Report:
    today = at.astimezone(cfg.tz).date()
    spans: list[tuple[str, date, date]] = []
    for i in range(buckets - 1, -1, -1):
        if period == "daily":
            d = today - timedelta(days=i)
            spans.append((d.isoformat(), d, d))
        elif period == "weekly":
            start = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
            spans.append((f"Week of {start.isoformat()}", start, start + timedelta(days=6)))
        else:
            y, m = today.year, today.month - i
            while m <= 0:
                m += 12
                y -= 1
            start = date(y, m, 1)
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            spans.append((start.strftime("%B %Y"), start, nxt - timedelta(days=1)))
    rows = []
    for label, s, e in spans:
        rng = make_range(cfg, s, e, at)
        if rng.end <= rng.start:
            continue
        sessions = _sessions(db, rng)
        energy = sum(x.energy_kwh for x in sessions)
        cost = sum(x.cost for x in sessions)
        peak = sum((x.tariff_breakdown or {}).get("peak", {}).get("kwh", 0.0) for x in sessions)
        off = sum((x.tariff_breakdown or {}).get("off_peak", {}).get("kwh", 0.0) for x in sessions)
        departures = list(db.scalars(select(Trip).where(Trip.departed_at >= rng.start, Trip.departed_at < rng.end, Trip.requirement_met.is_not(None))))
        met = sum(1 for t in departures if t.requirement_met)
        alerts = db.scalar(select(func.count()).select_from(Alert).where(Alert.created_at >= rng.start, Alert.created_at < rng.end)) or 0
        rows.append(
            {
                "period": label,
                "sessions": len(sessions),
                "energy_kwh": round(energy, 1),
                "cost": round(cost, 2),
                "avg_rate": round(cost / energy, 4) if energy else 0,
                "peak_share_pct": round(peak / energy * 100, 1) if energy else 0,
                "off_peak_share_pct": round(off / energy * 100, 1) if energy else 0,
                "departures": len(departures),
                "readiness_met_pct": round(met / len(departures) * 100, 1) if departures else None,
                "alerts": alerts,
            }
        )
    return Report(
        f"summary-{period}",
        f"{period.capitalize()} fleet charging summary",
        f"{period.capitalize()} totals for sessions, energy, cost, tariff mix, readiness and exceptions.",
        [("period", "Period"), ("sessions", "Sessions"), ("energy_kwh", "Energy kWh"), ("cost", f"Cost {cfg.currency}"), ("avg_rate", f"Avg {cfg.currency}/kWh"),
         ("peak_share_pct", "Peak %"), ("off_peak_share_pct", "Off-peak %"), ("departures", "Departures"), ("readiness_met_pct", "Readiness met %"), ("alerts", "Alerts")],
        rows,
        {"periods": len(rows)},
        rows,
    )


def success_metrics(db: Session, cfg: OperationalConfig, at: datetime, days: int = 30) -> dict:
    start = at - timedelta(days=days)
    departures = list(db.scalars(select(Trip).where(Trip.departed_at >= start, Trip.requirement_met.is_not(None))))
    met = sum(1 for t in departures if t.requirement_met)
    sessions = list(db.scalars(select(ChargingSession).where(ChargingSession.started_at >= start)))
    energy = sum(s.energy_kwh for s in sessions)
    cost = sum(s.cost for s in sessions)
    lower = sum((s.tariff_breakdown or {}).get("off_peak", {}).get("kwh", 0.0) for s in sessions)
    peak = sum((s.tariff_breakdown or {}).get("peak", {}).get("kwh", 0.0) for s in sessions)
    chargers = db.scalar(select(func.count()).select_from(Charger).where(Charger.is_active.is_(True))) or 1
    charging_hours = sum(((s.ended_at or at) - s.started_at).total_seconds() / 3600 for s in sessions)
    runs = list(db.scalars(select(ScheduleRun).order_by(ScheduleRun.id.desc()).limit(200)))
    durations = sorted(r.duration_ms for r in runs)
    latest = runs[0] if runs else None
    completed_trips = db.scalar(select(func.count()).select_from(Trip).where(Trip.status == TripStatus.COMPLETED, Trip.arrived_at >= start)) or 0
    interventions = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.category == "override", AuditLog.created_at >= start)) or 0
    unresolved = db.scalar(select(func.count()).select_from(Alert).where(Alert.status != AlertStatus.RESOLVED)) or 0
    vehicles = db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.is_active.is_(True))) or 1
    conflicts_total = sum(r.conflicts_prevented for r in runs if r.reservations_created)
    return {
        "window_days": days,
        "departures": len(departures),
        "departures_meeting_soc_pct": round(met / len(departures) * 100, 1) if departures else None,
        "missed_requirements": len(departures) - met,
        "lower_cost_energy_pct": round(lower / energy * 100, 1) if energy else None,
        "peak_energy_pct": round(peak / energy * 100, 1) if energy else None,
        "charger_utilization_pct": round(charging_hours / (chargers * days * 24) * 100, 1),
        "conflicts_prevented_latest_run": latest.conflicts_prevented if latest else 0,
        "conflicts_prevented_total": conflicts_total,
        "energy_cost_per_vehicle": round(cost / vehicles, 2),
        "energy_cost_per_trip": round(cost / completed_trips, 2) if completed_trips else None,
        "manual_interventions": interventions,
        "recalc_ms_median": durations[len(durations) // 2] if durations else None,
        "recalc_ms_p95": durations[min(len(durations) - 1, math.ceil(len(durations) * 0.95) - 1)] if durations else None,
        "unresolved_alerts": unresolved,
        "currency": cfg.currency,
    }
