"""Deterministic rule-based charging scheduler.

The engine is pure: it receives a snapshot of fleet state and returns a plan.
It never learns from history and never makes probabilistic predictions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Iterable

from app.services.tariffs import TariffCalendar

EPS = 1e-6
FAR_FUTURE = datetime.max.replace(year=9000)

RULE_TEXT = {
    "R1": "Vehicle already meets required SoC — no charging scheduled",
    "R2": "Departure is urgent and SoC is insufficient — prioritised immediately",
    "R3": "Multiple vehicles competed for a charger — priority and earliest departure decided",
    "R4": "Flexible charging — shifted to the configured lower-cost window",
    "R5": "Charger became unavailable — reassigned to a compatible charger",
    "R6": "Vehicle missed its reserved slot — reservation released and rescheduled",
    "R7": "Vehicle reached target SoC — session completed and charger freed",
    "R8": "Manual emergency override — supersedes the normal schedule",
}

PRIORITY_TEXT = {
    1: "P1 emergency / operationally critical",
    2: "P2 earliest departure with insufficient SoC",
    3: "P3 low SoC with a scheduled trip",
    4: "P4 later departure, flexible requirement",
    5: "P5 no immediate trip requirement",
}


@dataclass(frozen=True)
class TripRequirement:
    trip_id: int
    code: str
    departure_at: datetime
    required_soc: float | None
    energy_kwh: float | None
    priority: str


@dataclass(frozen=True)
class VehicleState:
    id: int
    registration: str
    station_id: int | None
    schedulable: bool
    availability: str
    current_soc: float
    capacity_kwh: float
    min_soc: float
    default_target_soc: float
    max_soc: float
    priority_category: str
    connectors: frozenset[str]
    max_ac_kw: float
    max_dc_kw: float
    efficiency: float
    created_at: datetime
    trip: TripRequirement | None = None
    request_created_at: datetime | None = None


@dataclass(frozen=True)
class ChargerState:
    id: int
    code: str
    station_id: int
    connector: str
    power_kw: float
    usable: bool
    availability: tuple[tuple[frozenset[int], time, time], ...] | None = None

    @property
    def is_dc(self) -> bool:
        return self.power_kw > 22 or self.connector in {"CCS2", "CHAdeMO", "GB/T"}


@dataclass(frozen=True)
class StationState:
    id: int
    code: str
    max_load_kw: float | None


@dataclass(frozen=True)
class FixedBooking:
    vehicle_id: int
    charger_id: int
    start: datetime
    end: datetime
    power_kw: float
    energy_kwh: float
    kind: str
    target_soc: float
    reservation_id: int | None = None


@dataclass(frozen=True)
class EngineConfig:
    mode: str = "rule_based"
    slot_minutes: int = 15
    horizon_hours: int = 24
    departure_buffer_minutes: int = 15
    urgent_window_hours: float = 3
    flex_slack_minutes: int = 60
    tariff_optimization: bool = True
    emergency_override: bool = True
    tie_breakers: tuple[str, ...] = ("departure", "soc", "created")
    required_soc_mode: str = "operator"
    safety_reserve_type: str = "percent"
    safety_reserve_value: float = 10
    currency: str = "USD"


@dataclass
class PlannedReservation:
    vehicle_id: int
    registration: str
    charger_id: int
    charger_code: str
    station_id: int
    start: datetime
    end: datetime
    power_kw: float
    energy_kwh: float
    cost: float
    target_soc: float
    priority_level: int
    rules: list[str]
    explanation: str
    tariff_mix: dict[str, float]
    request_key: int


@dataclass
class Decision:
    vehicle_id: int
    registration: str
    trip_id: int | None
    station_id: int | None
    status: str
    needs_charge: bool
    priority_level: int
    flexible: bool
    current_soc: float
    target_soc: float
    required_soc: float | None
    battery_kwh: float
    grid_kwh: float
    deadline: datetime | None
    departure_at: datetime | None
    projected_soc: float
    shortfall_kwh: float
    rules: list[str]
    explanation: str
    conflict_prevented: bool = False
    reservation: PlannedReservation | None = None


@dataclass
class PlanResult:
    mode: str
    planning_time: datetime
    slot_times: list[datetime]
    decisions: list[Decision]
    reservations: list[PlannedReservation]
    metrics: dict
    station_load: dict[int, list[float]] = field(default_factory=dict)


@dataclass
class _Window:
    charger: ChargerState
    start_idx: int
    end_idx: int
    start: datetime
    end: datetime
    energy: float
    cost: float
    mix: dict[str, float]
    solar_kwh: float


@dataclass
class _Requirement:
    vehicle: VehicleState
    status: str
    target: float
    required: float | None
    battery_kwh: float
    grid_kwh: float
    deadline: datetime | None
    departure: datetime | None
    priority: int
    rules: list[str]
    notes: list[str]
    overdue: bool = False
    readiness_deadline: datetime | None = None


def _hm(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def _duration(hours: float) -> str:
    minutes = max(0, int(round(hours * 60)))
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


class Scheduler:
    def __init__(
        self,
        config: EngineConfig,
        calendar: TariffCalendar,
        vehicles: Iterable[VehicleState],
        chargers: Iterable[ChargerState],
        stations: Iterable[StationState],
        fixed: Iterable[FixedBooking] = (),
    ):
        self.cfg = config
        self.cal = calendar
        self.tz = calendar.tz
        self.vehicles = list(vehicles)
        self.chargers = [c for c in chargers]
        self.stations = {s.id: s for s in stations}
        self.fixed = list(fixed)
        self.baseline = config.mode == "baseline"

    # ------------------------------------------------------------------ grid
    def _build_grid(self, now: datetime) -> None:
        step = timedelta(minutes=self.cfg.slot_minutes)
        end = now + timedelta(hours=self.cfg.horizon_hours)
        first = now.replace(second=0, microsecond=0)
        boundary = first - timedelta(minutes=first.minute % self.cfg.slot_minutes) + step
        times = [now]
        t = boundary
        while t < end:
            times.append(t)
            t += step
        times.append(end)
        self.times = times
        self.n = len(times) - 1
        self.horizon_end = end
        self.durations = [(times[i + 1] - times[i]).total_seconds() / 3600 for i in range(self.n)]
        mids = [times[i] + (times[i + 1] - times[i]) / 2 for i in range(self.n)]
        station_ids = set(self.stations) | {c.station_id for c in self.chargers}
        self.quotes = {sid: [self.cal.quote(m, sid) for m in mids] for sid in station_ids}
        self.solar_left = {sid: [self.cal.solar_kw(m, sid) for m in mids] for sid in station_ids}
        self.load = {sid: [0.0] * self.n for sid in station_ids}
        self.busy = {c.id: [None] * self.n for c in self.chargers}
        self.avail = {}
        for c in self.chargers:
            if c.availability is None:
                self.avail[c.id] = [True] * self.n
                continue
            flags = []
            for m in mids:
                local = m.astimezone(self.tz)
                flags.append(
                    any(
                        local.weekday() in days and (s <= local.time() < e if s < e else (local.time() >= s or local.time() < e))
                        for days, s, e in c.availability
                    )
                )
            self.avail[c.id] = flags

    def _slot_range(self, start: datetime, end: datetime) -> range:
        lo = 0
        while lo < self.n and self.times[lo + 1] <= start:
            lo += 1
        hi = lo
        while hi < self.n and self.times[hi] < end:
            hi += 1
        return range(lo, hi)

    # ----------------------------------------------------------- assessment
    def _target(self, v: VehicleState) -> tuple[float, float | None, list[str]]:
        notes: list[str] = []
        trip = v.trip
        if trip is None:
            return (v.max_soc if self.baseline else v.default_target_soc), None, notes
        use_rule = self.cfg.required_soc_mode == "rule" or trip.required_soc is None
        if use_rule and trip.energy_kwh is not None:
            reserve = (
                v.capacity_kwh * self.cfg.safety_reserve_value / 100
                if self.cfg.safety_reserve_type == "percent"
                else self.cfg.safety_reserve_value
            )
            target = (trip.energy_kwh + reserve) / v.capacity_kwh * 100
            notes.append(f"rule-based target: {trip.energy_kwh:.1f} kWh trip + {reserve:.1f} kWh reserve")
        elif trip.required_soc is not None:
            target = trip.required_soc
        else:
            target = v.default_target_soc
        target = round(max(target, v.min_soc), 1)
        if target > v.max_soc:
            notes.append(f"required {target:.0f}% exceeds max permitted {v.max_soc:.0f}% — capped")
            target = v.max_soc
        if self.baseline:
            return v.max_soc, target, []
        return target, target, notes

    def _assess(self, v: VehicleState, now: datetime) -> _Requirement:
        target, required, notes = self._target(v)
        trip = v.trip
        departure = trip.departure_at if trip else None
        if departure is not None and departure > self.horizon_end:
            departure = None
        if not v.schedulable:
            return _Requirement(v, "away", target, required, 0, 0, None, departure, 5, [], [f"vehicle is {v.availability.replace('_', ' ')}"])
        battery_kwh = max(0.0, (target - v.current_soc) / 100 * v.capacity_kwh)
        grid_kwh = battery_kwh / v.efficiency if battery_kwh > EPS else 0.0
        if departure is not None:
            deadline = departure - timedelta(minutes=self.cfg.departure_buffer_minutes)
        else:
            deadline = self.horizon_end
        overdue = deadline <= now
        readiness_deadline = deadline if departure is not None and not overdue else None
        if overdue:
            notes.append("departure deadline has already passed — charging as soon as possible")
            deadline = self.horizon_end
        if battery_kwh <= EPS:
            return _Requirement(v, "satisfied", target, required, 0, 0, deadline, departure, 5, ["R1"], notes, overdue, readiness_deadline)
        if self.baseline:
            return _Requirement(v, "pending", target, required, battery_kwh, grid_kwh, self.horizon_end, departure, 5, [], notes, overdue, readiness_deadline)

        emergency = v.priority_category == "critical" or (trip is not None and trip.priority == "emergency")
        hours_to_departure = (trip.departure_at - now).total_seconds() / 3600 if trip else None
        if emergency and self.cfg.emergency_override:
            priority, rules = 1, ["R2"]
        elif trip is not None and (overdue or hours_to_departure <= self.cfg.urgent_window_hours):
            priority, rules = 2, ["R2"]
        elif trip is not None and v.current_soc < v.min_soc:
            priority, rules = 3, []
        elif trip is not None and departure is not None:
            priority, rules = 4, []
        else:
            priority, rules = 5, []
        return _Requirement(v, "pending", target, required, battery_kwh, grid_kwh, deadline, departure, priority, rules, notes, overdue, readiness_deadline)

    def _order_key(self, r: _Requirement) -> tuple:
        v = r.vehicle
        if self.baseline:
            return (v.registration,)
        parts: list = [r.priority]
        for tb in self.cfg.tie_breakers:
            if tb == "departure":
                parts.append(r.departure or FAR_FUTURE.replace(tzinfo=r.deadline.tzinfo if r.deadline else None))
            elif tb == "soc":
                parts.append(v.current_soc)
            elif tb == "created":
                parts.append(v.request_created_at or v.created_at)
        parts.append(v.registration)
        return tuple(parts)

    # -------------------------------------------------------------- windows
    def _power(self, v: VehicleState, c: ChargerState) -> float:
        return round(min(c.power_kw, v.max_dc_kw if c.is_dc else v.max_ac_kw), 2)

    def _eligible(self, v: VehicleState) -> list[ChargerState]:
        return [
            c
            for c in self.chargers
            if c.usable and c.station_id == v.station_id and c.connector in v.connectors and self._power(v, c) > 0
        ]

    def _usable_hours(self, i: int, deadline: datetime) -> float:
        if self.times[i] >= deadline:
            return 0.0
        return min(self.durations[i], (deadline - self.times[i]).total_seconds() / 3600)

    def _scan(self, c: ChargerState, power: float, energy: float, deadline: datetime, ignore_busy: bool, allow_partial: bool):
        sid = c.station_id
        cap = None if self.baseline else self.stations.get(sid, StationState(sid, "", None)).max_load_kw
        busy, avail, load = self.busy[c.id], self.avail[c.id], self.load[sid]
        quotes, solar = self.quotes[sid], self.solar_left[sid]
        for s in range(self.n):
            if self.times[s] >= deadline:
                break
            if (busy[s] is not None and not ignore_busy) or not avail[s]:
                continue
            if cap is not None and load[s] + power > cap + EPS:
                continue
            acc = cost = solar_used = 0.0
            mix: dict[str, float] = defaultdict(float)
            e = s
            end_time = self.times[s]
            while e < self.n:
                hours = self._usable_hours(e, deadline)
                if hours <= 0:
                    break
                if (busy[e] is not None and not ignore_busy) or not avail[e]:
                    break
                if cap is not None and load[e] + power > cap + EPS:
                    break
                take = min(power * hours, energy - acc)
                covered = min(take, solar[e] * hours)
                cost += (take - covered) * quotes[e].rate
                solar_used += covered
                mix[quotes[e].kind] += take
                acc += take
                end_time = self.times[e] + timedelta(hours=take / power)
                e += 1
                if acc >= energy - EPS:
                    break
            complete = acc >= energy - EPS
            if complete or (allow_partial and acc > EPS):
                yield _Window(c, s, e, self.times[s], end_time, acc, cost, dict(mix), solar_used)

    def _best_window(self, v: VehicleState, req: _Requirement, chargers: list[ChargerState], flexible: bool, ignore_busy: bool = False) -> tuple[_Window | None, _Window | None]:
        best = asap = None
        for c in chargers:
            power = self._power(v, c)
            for w in self._scan(c, power, req.grid_kwh, req.deadline, ignore_busy, False):
                if asap is None or (w.end, w.cost, c.code) < (asap.end, asap.cost, asap.charger.code):
                    asap = w
                if not flexible:
                    break
                key = (round(w.cost, 4), w.start, c.code)
                if best is None or key < (round(best.cost, 4), best.start, best.charger.code):
                    best = w
        return (best if flexible else asap), asap

    def _is_free(self, w: _Window) -> bool:
        busy = self.busy[w.charger.id]
        return all(busy[i] is None for i in range(w.start_idx, w.end_idx))

    def _partial_window(self, v: VehicleState, req: _Requirement, chargers: list[ChargerState]) -> _Window | None:
        best = None
        for c in chargers:
            for w in self._scan(c, self._power(v, c), req.grid_kwh, req.deadline, False, True):
                if best is None or (w.energy, -w.start.timestamp()) > (best.energy, -best.start.timestamp()):
                    best = w
        return best

    def _occupy(self, w: _Window, power: float, owner: str) -> None:
        sid = w.charger.station_id
        for i in range(w.start_idx, w.end_idx):
            self.busy[w.charger.id][i] = owner
            self.load[sid][i] += power
            self.solar_left[sid][i] = max(0.0, self.solar_left[sid][i] - power)

    # ----------------------------------------------------------------- plan
    def plan(self, now: datetime) -> PlanResult:
        self._build_grid(now)
        charger_by_id = {c.id: c for c in self.chargers}
        vehicles_by_id = {v.id: v for v in self.vehicles}
        locked: dict[int, list[FixedBooking]] = defaultdict(list)
        for b in self.fixed:
            locked[b.vehicle_id].append(b)
            c = charger_by_id.get(b.charger_id)
            if c is None:
                continue
            owner = vehicles_by_id[b.vehicle_id].registration if b.vehicle_id in vehicles_by_id else "booked"
            for i in self._slot_range(b.start, b.end):
                self.busy[c.id][i] = owner
                self.load[c.station_id][i] += b.power_kw

        decisions: list[Decision] = []
        reservations: list[PlannedReservation] = []
        pending: list[_Requirement] = []
        for v in self.vehicles:
            req = self._assess(v, now)
            if v.id in locked:
                decisions.append(self._locked_decision(v, req, locked[v.id], now, charger_by_id))
            elif req.status in ("away", "satisfied"):
                decisions.append(self._static_decision(req))
            else:
                pending.append(req)

        competition = defaultdict(int)
        for r in pending:
            competition[r.vehicle.station_id] += 1
        usable_per_station = defaultdict(int)
        for c in self.chargers:
            if c.usable:
                usable_per_station[c.station_id] += 1

        for req in sorted(pending, key=self._order_key):
            decision = self._schedule_vehicle(req, now, competition, usable_per_station)
            decisions.append(decision)
            if decision.reservation:
                reservations.append(decision.reservation)

        decisions.sort(key=lambda d: (d.priority_level, d.deadline or self.horizon_end, d.registration))
        return PlanResult(
            mode=self.cfg.mode,
            planning_time=now,
            slot_times=self.times,
            decisions=decisions,
            reservations=reservations,
            metrics=self._metrics(decisions, reservations),
            station_load=self.load,
        )

    def _static_decision(self, req: _Requirement) -> Decision:
        v = req.vehicle
        if req.status == "away":
            explanation = f"{v.registration}: {req.notes[0]} — will be evaluated again when it is back at a depot."
        else:
            deadline_text = f" for departure {_hm(req.departure, self.tz)}" if req.departure else ""
            explanation = (
                f"{v.registration}: R1 — current SoC {v.current_soc:.0f}% already meets the {req.target:.0f}% target"
                f"{deadline_text}. No charging scheduled."
            )
        return Decision(
            vehicle_id=v.id,
            registration=v.registration,
            trip_id=v.trip.trip_id if v.trip else None,
            station_id=v.station_id,
            status=req.status,
            needs_charge=False,
            priority_level=5,
            flexible=False,
            current_soc=v.current_soc,
            target_soc=req.target,
            required_soc=req.required,
            battery_kwh=0,
            grid_kwh=0,
            deadline=req.deadline if req.departure else None,
            departure_at=req.departure,
            projected_soc=v.current_soc,
            shortfall_kwh=0,
            rules=req.rules,
            explanation=explanation,
        )

    def _locked_decision(self, v: VehicleState, req: _Requirement, bookings: list[FixedBooking], now: datetime, chargers: dict) -> Decision:
        deadline = req.readiness_deadline or req.deadline or self.horizon_end
        delivered = 0.0
        for b in bookings:
            span = max(0.0, (min(b.end, deadline) - max(b.start, now)).total_seconds() / 3600)
            delivered += span * b.power_kw
        projected = min(v.max_soc, v.current_soc + delivered * v.efficiency / v.capacity_kwh * 100)
        first = min(bookings, key=lambda b: b.start)
        kinds = {b.kind for b in bookings}
        charger_code = chargers[first.charger_id].code if first.charger_id in chargers else f"#{first.charger_id}"
        if "override" in kinds:
            rules, lead = ["R8"], f"Manual override in force on {charger_code} {_hm(first.start, self.tz)}–{_hm(first.end, self.tz)}"
        else:
            rules, lead = [], f"Charging in progress on {charger_code} until {_hm(first.end, self.tz)}"
        need = req.required if (v.trip is not None and req.required is not None and req.status != "away") else None
        short = max(0.0, (need - projected) / 100 * v.capacity_kwh) if need is not None else 0.0
        status = "locked" if short <= 0.05 else "at_risk"
        tail = "" if status == "locked" else f" Projected {projected:.0f}% at departure is below the {need:.0f}% requirement."
        return Decision(
            vehicle_id=v.id,
            registration=v.registration,
            trip_id=v.trip.trip_id if v.trip else None,
            station_id=v.station_id,
            status=status,
            needs_charge=req.grid_kwh > EPS,
            priority_level=req.priority if status == "at_risk" else min(req.priority, 5),
            flexible=False,
            current_soc=v.current_soc,
            target_soc=req.target,
            required_soc=req.required,
            battery_kwh=req.battery_kwh,
            grid_kwh=req.grid_kwh,
            deadline=req.deadline if req.departure else None,
            departure_at=req.departure,
            projected_soc=round(projected, 1),
            shortfall_kwh=round(short, 2),
            rules=rules,
            explanation=f"{v.registration}: {lead} (target {first.target_soc:.0f}%).{tail}",
        )

    def _schedule_vehicle(self, req: _Requirement, now: datetime, competition: dict, usable: dict) -> Decision:
        v = req.vehicle
        chargers = self._eligible(v)
        available_h = (req.deadline - now).total_seconds() / 3600
        best_power = max((self._power(v, c) for c in chargers), default=0)
        charge_h = req.grid_kwh / best_power if best_power else math.inf
        flexible = (
            not self.baseline
            and self.cfg.tariff_optimization
            and req.priority >= 3
            and available_h * 60 >= charge_h * 60 + self.cfg.flex_slack_minutes
        )
        rules = list(req.rules)
        parts: list[str] = []
        if self.baseline:
            parts.append(
                f"Static baseline — first-come-first-served, charging immediately to max permitted {req.target:.0f}% "
                "with no tariff, priority or site-load coordination."
            )
        else:
            deadline_txt = (
                f"by {_hm(req.deadline, self.tz)} (departure {_hm(req.departure, self.tz)} − {self.cfg.departure_buffer_minutes} min buffer)"
                if req.departure
                else "within the planning horizon (no trip scheduled)"
            )
            parts.append(
                f"{PRIORITY_TEXT[req.priority]}. Needs {req.target - v.current_soc:.1f}% "
                f"({req.battery_kwh:.1f} kWh to battery, {req.grid_kwh:.1f} kWh from grid) to reach {req.target:.0f}% {deadline_txt}."
            )
            if math.isfinite(charge_h):
                parts.append(
                    f"{_duration(available_h)} available vs {_duration(charge_h)} charging at {best_power:.0f} kW → "
                    f"{'flexible' if flexible else 'not flexible'}."
                )
        parts.extend(n[0].upper() + n[1:] + "." for n in req.notes)

        if not chargers:
            if competition.get(v.station_id, 0) > usable.get(v.station_id, 0):
                rules.append("R3")
            parts.append("No usable charger with a compatible connector at this depot.")
            return self._unscheduled(req, rules, parts, flexible)

        conflict = False
        if self.baseline:
            window, asap = self._best_window(v, req, chargers, flexible)
        else:
            ideal, ideal_asap = self._best_window(v, req, chargers, flexible, ignore_busy=True)
            if ideal is not None and self._is_free(ideal):
                window = ideal
                asap = ideal_asap if ideal_asap is not None and self._is_free(ideal_asap) else self._best_window(v, req, chargers, False)[1]
            else:
                window, asap = self._best_window(v, req, chargers, flexible)
            if ideal is not None and (window is None or (ideal.charger.id, ideal.start_idx) != (window.charger.id, window.start_idx)):
                holders = {self.busy[ideal.charger.id][i] for i in range(ideal.start_idx, ideal.end_idx)} - {None}
                if holders:
                    conflict = True
                    if "R3" not in rules:
                        rules.append("R3")
                    parts.append(
                        f"R3: preferred slot on {ideal.charger.code} {_hm(ideal.start, self.tz)} is held by "
                        f"{', '.join(sorted(holders)[:3])} (higher priority); conflict avoided."
                    )

        status = "scheduled"
        if window is None:
            window = self._partial_window(v, req, chargers)
            if window is None:
                parts.append("Every compatible charger is booked until the deadline.")
                d = self._unscheduled(req, rules, parts, flexible)
                d.conflict_prevented = conflict
                return d
            status = "at_risk"
            parts.append(
                f"Only {window.energy:.1f} of {req.grid_kwh:.1f} kWh fits before the deadline — vehicle flagged at risk."
            )

        if flexible and status == "scheduled" and asap is not None and window.cost + 0.005 < asap.cost:
            rules.append("R4")
            dominant = max(window.mix, key=window.mix.get).replace("_", "-")
            parts.append(
                f"R4: shifted to {dominant} window — "
                f"est. {window.cost:.2f} {self.cfg.currency} vs {asap.cost:.2f} {self.cfg.currency} if charged immediately."
            )
        elif req.priority <= 2 and not self.baseline:
            parts.append("R2: tariff optimisation bypassed — earliest completing slot selected.")
        if window.solar_kwh > 0.05:
            parts.append(f"{window.solar_kwh:.1f} kWh expected from on-site solar.")
        if req.overdue and "R2" not in rules and not self.baseline:
            rules.append("R2")

        power = self._power(v, window.charger)
        self._occupy(window, power, v.registration)
        projected = min(v.max_soc, v.current_soc + window.energy * v.efficiency / v.capacity_kwh * 100)
        if req.readiness_deadline is not None:
            overlap_h = max(0.0, (min(window.end, req.readiness_deadline) - window.start).total_seconds() / 3600)
            delivered = min(window.energy, overlap_h * power)
            projected_at_departure = min(v.max_soc, v.current_soc + delivered * v.efficiency / v.capacity_kwh * 100)
        else:
            projected_at_departure = projected
        shortfall = 0.0
        if req.required is not None and req.departure is not None:
            shortfall = max(0.0, (req.required - projected_at_departure) / 100 * v.capacity_kwh)
            if shortfall > 0.05 or req.overdue:
                if status != "at_risk" and self.baseline:
                    parts.append(
                        f"Reaches only {projected_at_departure:.0f}% by departure {_hm(req.departure, self.tz)} against the {req.required:.0f}% requirement."
                    )
                status = "at_risk"
        parts.append(
            f"Reserved {window.charger.code} {_hm(window.start, self.tz)}–{_hm(window.end, self.tz)} at {power:.0f} kW "
            f"({window.energy:.1f} kWh, est. {window.cost:.2f} {self.cfg.currency})."
        )
        explanation = " ".join(parts)
        reservation = PlannedReservation(
            vehicle_id=v.id,
            registration=v.registration,
            charger_id=window.charger.id,
            charger_code=window.charger.code,
            station_id=window.charger.station_id,
            start=window.start,
            end=window.end,
            power_kw=power,
            energy_kwh=round(window.energy, 3),
            cost=round(window.cost, 4),
            target_soc=round(projected, 1) if status == "at_risk" else req.target,
            priority_level=req.priority,
            rules=sorted(set(rules)),
            explanation=explanation,
            tariff_mix={k: round(val, 3) for k, val in window.mix.items()},
            request_key=v.id,
        )
        return Decision(
            vehicle_id=v.id,
            registration=v.registration,
            trip_id=v.trip.trip_id if v.trip else None,
            station_id=v.station_id,
            status=status,
            needs_charge=True,
            priority_level=req.priority,
            flexible=flexible,
            current_soc=v.current_soc,
            target_soc=req.target,
            required_soc=req.required,
            battery_kwh=round(req.battery_kwh, 3),
            grid_kwh=round(req.grid_kwh, 3),
            deadline=req.deadline if req.departure else None,
            departure_at=req.departure,
            projected_soc=round(projected_at_departure, 1),
            shortfall_kwh=round(shortfall, 2),
            rules=sorted(set(rules)),
            explanation=explanation,
            conflict_prevented=conflict,
            reservation=reservation,
        )

    def _unscheduled(self, req: _Requirement, rules: list[str], parts: list[str], flexible: bool) -> Decision:
        v = req.vehicle
        shortfall = max(0.0, ((req.required or req.target) - v.current_soc) / 100 * v.capacity_kwh) if v.trip else 0.0
        return Decision(
            vehicle_id=v.id,
            registration=v.registration,
            trip_id=v.trip.trip_id if v.trip else None,
            station_id=v.station_id,
            status="unscheduled" if not v.trip else "at_risk",
            needs_charge=True,
            priority_level=req.priority,
            flexible=flexible,
            current_soc=v.current_soc,
            target_soc=req.target,
            required_soc=req.required,
            battery_kwh=round(req.battery_kwh, 3),
            grid_kwh=round(req.grid_kwh, 3),
            deadline=req.deadline if req.departure else None,
            departure_at=req.departure,
            projected_soc=v.current_soc,
            shortfall_kwh=round(shortfall, 2),
            rules=sorted(set(r for r in rules if r)),
            explanation=f"{v.registration}: " + " ".join(parts),
        )

    def _metrics(self, decisions: list[Decision], reservations: list[PlannedReservation]) -> dict:
        energy = sum(r.energy_kwh for r in reservations)
        cost = sum(r.cost for r in reservations)
        mix: dict[str, float] = defaultdict(float)
        for r in reservations:
            for k, val in r.tariff_mix.items():
                mix[k] += val
        with_trip = [d for d in decisions if d.departure_at is not None and d.status != "away"]
        ready_projected = [d for d in with_trip if d.shortfall_kwh <= 0.05 and d.status != "at_risk"]
        ready_now = [d for d in with_trip if d.required_soc is not None and d.current_soc >= d.required_soc - EPS]
        peak_load = 0.0
        demand_charge = 0.0
        for sid, loads in self.load.items():
            if not loads:
                continue
            station_peak = max(loads)
            peak_load += station_peak
            rates = self.quotes.get(sid, [])
            demand_charge += max((loads[i] * rates[i].demand_charge for i in range(len(loads))), default=0.0)
        return {
            "vehicles_evaluated": len(decisions),
            "vehicles_needing_charge": sum(1 for d in decisions if d.needs_charge),
            "scheduled": sum(1 for d in decisions if d.status == "scheduled"),
            "at_risk": sum(1 for d in decisions if d.status == "at_risk"),
            "unscheduled": sum(1 for d in decisions if d.status == "unscheduled"),
            "satisfied": sum(1 for d in decisions if d.status == "satisfied"),
            "locked": sum(1 for d in decisions if d.status == "locked"),
            "away": sum(1 for d in decisions if d.status == "away"),
            "reservations": len(reservations),
            "planned_energy_kwh": round(energy, 2),
            "planned_cost": round(cost, 2),
            "avg_rate_per_kwh": round(cost / energy, 4) if energy else 0.0,
            "shortfall_kwh": round(sum(d.shortfall_kwh for d in decisions), 1),
            "energy_by_period": {k: round(val, 2) for k, val in mix.items()},
            "peak_energy_kwh": round(mix.get("peak", 0.0), 2),
            "peak_share_pct": round(mix.get("peak", 0.0) / energy * 100, 1) if energy else 0.0,
            "off_peak_share_pct": round(mix.get("off_peak", 0.0) / energy * 100, 1) if energy else 0.0,
            "departures_in_horizon": len(with_trip),
            "ready_now": len(ready_now),
            "projected_ready": len(ready_projected),
            "projected_readiness_pct": round(len(ready_projected) / len(with_trip) * 100, 1) if with_trip else 100.0,
            "missed_requirements": len(with_trip) - len(ready_projected),
            "conflicts_prevented": sum(1 for d in decisions if d.conflict_prevented),
            "peak_site_load_kw": round(peak_load, 1),
            "demand_charge_estimate": round(demand_charge, 2),
        }
