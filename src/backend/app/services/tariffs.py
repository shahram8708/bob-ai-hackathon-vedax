import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceSignal, Station, TariffPeriod
from app.models.enums import TariffKind


@dataclass(frozen=True)
class PeriodRule:
    id: int
    name: str
    kind: str
    start: time
    end: time
    rate: float
    demand_charge: float | None
    days: frozenset[int]
    station_id: int | None

    def matches(self, local: datetime) -> bool:
        t, wd = local.time(), local.weekday()
        if self.start < self.end:
            return self.start <= t < self.end and wd in self.days
        if t >= self.start:
            return wd in self.days
        if t < self.end:
            return (wd - 1) % 7 in self.days
        return False


@dataclass(frozen=True)
class Quote:
    rate: float
    kind: str
    name: str
    demand_charge: float
    source: str


@dataclass(frozen=True)
class Signal:
    start: datetime
    end: datetime
    rate: float
    station_id: int | None
    source: str


class TariffCalendar:
    def __init__(
        self,
        periods: list[PeriodRule],
        tz: ZoneInfo,
        default_rate: float,
        signals: list[Signal] | None = None,
        solar_capacity: dict[int, float] | None = None,
    ):
        self.tz = tz
        self.default_rate = default_rate
        self.periods = sorted(periods, key=lambda p: (p.station_id is None, p.kind != TariffKind.CUSTOM, p.id))
        self.signals = sorted(signals or [], key=lambda s: s.start)
        self._signal_starts = [s.start for s in self.signals]
        self.solar_capacity = solar_capacity or {}

    def _period(self, local: datetime, station_id: int | None) -> PeriodRule | None:
        for p in self.periods:
            if (p.station_id is None or p.station_id == station_id) and p.matches(local):
                return p
        return None

    def _signal(self, at: datetime, station_id: int | None) -> Signal | None:
        idx = bisect_right(self._signal_starts, at)
        for s in reversed(self.signals[max(0, idx - 48) : idx]):
            if s.start <= at < s.end and (s.station_id is None or s.station_id == station_id):
                return s
        return None

    def quote(self, at: datetime, station_id: int | None = None) -> Quote:
        local = at.astimezone(self.tz)
        period = self._period(local, station_id)
        kind = period.kind if period else TariffKind.SHOULDER.value
        name = period.name if period else "Default rate"
        rate = period.rate if period else self.default_rate
        demand = float(period.demand_charge or 0) if period else 0.0
        signal = self._signal(at, station_id)
        if signal:
            return Quote(signal.rate, kind, f"{name} · {signal.source}", demand, "price_feed")
        return Quote(float(rate), kind, name, demand, "tariff")

    def solar_kw(self, at: datetime, station_id: int) -> float:
        capacity = self.solar_capacity.get(station_id, 0.0)
        if capacity <= 0:
            return 0.0
        local = at.astimezone(self.tz)
        hour = local.hour + local.minute / 60
        if not 6 <= hour <= 18:
            return 0.0
        return round(capacity * math.sin(math.pi * (hour - 6) / 12), 3)

    def next_change(self, at: datetime, station_id: int | None = None, step_minutes: int = 15, horizon_hours: int = 48) -> tuple[datetime, Quote] | None:
        current = self.quote(at, station_id)
        probe = at.replace(second=0, microsecond=0)
        probe -= timedelta(minutes=probe.minute % step_minutes)
        for _ in range(int(horizon_hours * 60 / step_minutes)):
            probe += timedelta(minutes=step_minutes)
            q = self.quote(probe, station_id)
            if (q.kind, q.rate) != (current.kind, current.rate):
                return probe, q
        return None

    def next_kind_start(self, at: datetime, kind: str, station_id: int | None = None, horizon_hours: int = 30) -> datetime | None:
        probe = at.replace(second=0, microsecond=0)
        probe -= timedelta(minutes=probe.minute % 15)
        in_kind = self.quote(at, station_id).kind == kind
        for _ in range(horizon_hours * 4):
            probe += timedelta(minutes=15)
            q_kind = self.quote(probe, station_id).kind
            if q_kind == kind and not in_kind:
                return probe
            in_kind = q_kind == kind
        return None


def period_rule(p: TariffPeriod) -> PeriodRule:
    return PeriodRule(
        id=p.id,
        name=p.name,
        kind=p.kind.value if hasattr(p.kind, "value") else str(p.kind),
        start=p.start_time,
        end=p.end_time,
        rate=float(p.rate_per_kwh),
        demand_charge=float(p.demand_charge_per_kw) if p.demand_charge_per_kw is not None else None,
        days=frozenset(p.days_of_week or range(7)),
        station_id=p.station_id,
    )


def load_calendar(db: Session, tz: ZoneInfo, default_rate: float, window_start: datetime | None = None, window_end: datetime | None = None) -> TariffCalendar:
    periods = [period_rule(p) for p in db.scalars(select(TariffPeriod).where(TariffPeriod.is_active.is_(True)))]
    q = select(PriceSignal)
    if window_start is not None:
        q = q.where(PriceSignal.ends_at > window_start)
    if window_end is not None:
        q = q.where(PriceSignal.starts_at < window_end)
    signals = [Signal(s.starts_at, s.ends_at, float(s.rate_per_kwh), s.station_id, s.source) for s in db.scalars(q)]
    solar = {s.id: s.solar_capacity_kw for s in db.scalars(select(Station))}
    return TariffCalendar(periods, tz, default_rate, signals, solar)


def coverage_gaps(periods: list[PeriodRule], tz: ZoneInfo) -> list[str]:
    calendar = TariffCalendar(periods, tz, 0)
    gaps: list[str] = []
    base = datetime(2024, 1, 1, tzinfo=tz)
    for day in range(7):
        for quarter in range(96):
            local = base + timedelta(days=day, minutes=15 * quarter)
            if calendar._period(local, None) is None:
                gaps.append(local.strftime("%a %H:%M"))
    return gaps
