from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.scheduler.engine import ChargerState, EngineConfig, FixedBooking, Scheduler, StationState, TripRequirement, VehicleState
from app.services.scheduler.optimizer import lp_lower_bound
from app.services.tariffs import PeriodRule, TariffCalendar, coverage_gaps

TZ = ZoneInfo("Asia/Kolkata")
ALL_DAYS = frozenset(range(7))
PERIODS = [
    PeriodRule(1, "Off-peak", "off_peak", time(0), time(6), 5.0, None, ALL_DAYS, None),
    PeriodRule(2, "Shoulder", "shoulder", time(6), time(18), 8.0, None, ALL_DAYS, None),
    PeriodRule(3, "Peak", "peak", time(18), time(22), 12.0, 100.0, ALL_DAYS, None),
    PeriodRule(4, "Late", "shoulder", time(22), time(0), 8.0, None, ALL_DAYS, None),
]
NOW = datetime(2026, 10, 3, 16, 0, tzinfo=TZ)
CREATED = datetime(2026, 1, 1, tzinfo=TZ)


def calendar() -> TariffCalendar:
    return TariffCalendar(PERIODS, TZ, 8.0)


def vehicle(vid: int, soc: float, trip: TripRequirement | None = None, category: str = "standard", capacity: float = 60, station: int = 1) -> VehicleState:
    return VehicleState(
        id=vid, registration=f"EV-{vid:03d}", station_id=station, schedulable=True, availability="available", current_soc=soc,
        capacity_kwh=capacity, min_soc=20, default_target_soc=80, max_soc=90, priority_category=category,
        connectors=frozenset({"CCS2"}), max_ac_kw=11, max_dc_kw=50, efficiency=0.9, created_at=CREATED, trip=trip,
    )


def trip(tid: int, departure: datetime, required: float, priority: str = "normal") -> TripRequirement:
    return TripRequirement(tid, f"T{tid}", departure, required, None, priority)


def chargers(n: int, power: float = 50, station: int = 1, availability=None) -> list[ChargerState]:
    return [ChargerState(i, f"C{i:02d}", station, "CCS2", power, True, availability) for i in range(1, n + 1)]


def plan(vehicles, charger_list, mode="rule_based", load=None, fixed=(), **cfg):
    engine = Scheduler(EngineConfig(mode=mode, **cfg), calendar(), vehicles, charger_list, [StationState(1, "S1", load)], fixed)
    return engine.plan(NOW)


def test_prd_example_ev027_shifts_to_off_peak_and_meets_departure():
    departure = datetime(2026, 10, 4, 7, 30, tzinfo=TZ)
    result = plan([vehicle(27, 42, trip(1, departure, 72))], chargers(2))
    d = result.decisions[0]
    r = d.reservation
    assert d.status == "scheduled" and "R4" in d.rules
    assert r.start.astimezone(TZ).hour < 6 and r.end <= departure - timedelta(minutes=15)
    assert set(r.tariff_mix) == {"off_peak"}
    assert d.projected_soc >= 72


def test_prd_example_ev061_already_ready_is_not_scheduled():
    result = plan([vehicle(61, 75, trip(2, datetime(2026, 10, 4, 10, 0, tzinfo=TZ), 65))], chargers(2))
    d = result.decisions[0]
    assert d.status == "satisfied" and d.rules == ["R1"] and d.reservation is None


def test_prd_example_ev042_emergency_overrides_tariff_and_charges_immediately():
    v = vehicle(42, 18, trip(3, NOW + timedelta(minutes=45), 45, priority="emergency"), category="critical")
    d = plan([v], chargers(2)).decisions[0]
    assert d.priority_level == 1 and "R2" in d.rules
    assert d.reservation.start == NOW


def test_priority_rules_give_urgent_vehicle_the_only_charger():
    flexible = vehicle(1, 30, trip(1, NOW + timedelta(hours=14), 80))
    urgent = vehicle(2, 30, trip(2, NOW + timedelta(hours=2), 70))
    result = plan([flexible, urgent], chargers(1), tariff_optimization=False)
    by_id = {d.vehicle_id: d for d in result.decisions}
    assert by_id[2].priority_level == 2 and by_id[2].reservation.start == NOW
    assert by_id[1].reservation.start >= by_id[2].reservation.end
    assert by_id[1].conflict_prevented and "R3" in by_id[1].rules


def test_tie_breakers_prefer_earliest_departure_then_lowest_soc():
    a = vehicle(1, 40, trip(1, NOW + timedelta(hours=2), 70))
    b = vehicle(2, 30, trip(2, NOW + timedelta(hours=2, minutes=30), 70))
    c = vehicle(3, 25, trip(3, NOW + timedelta(hours=2), 70))
    result = plan([a, b, c], chargers(1))
    order = sorted((d.reservation.start, d.registration) for d in result.decisions if d.reservation)
    assert [reg for _, reg in order] == ["EV-003", "EV-001", "EV-002"]


def test_no_charger_is_double_booked_and_site_load_cap_is_respected():
    fleet = [vehicle(i, 20 + i, trip(i, NOW + timedelta(hours=3 + i % 9), 80)) for i in range(1, 25)]
    result = plan(fleet, chargers(4), load=120)
    by_charger = {}
    for r in result.reservations:
        by_charger.setdefault(r.charger_id, []).append((r.start, r.end))
    for windows in by_charger.values():
        windows.sort()
        for (s1, e1), (s2, _) in zip(windows, windows[1:]):
            assert s2 >= e1 - timedelta(seconds=1)
    assert max(result.station_load[1]) <= 120 + 1e-6


def test_readiness_is_never_sacrificed_for_tariff():
    departure = NOW + timedelta(hours=3)
    d = plan([vehicle(1, 20, trip(1, departure, 85))], chargers(1)).decisions[0]
    assert d.status == "scheduled"
    assert d.reservation.end <= departure - timedelta(minutes=15)
    assert "R4" not in d.rules


def test_infeasible_requirement_is_flagged_at_risk():
    d = plan([vehicle(1, 10, trip(1, NOW + timedelta(minutes=40), 90), capacity=300)], chargers(1)).decisions[0]
    assert d.status == "at_risk" and d.shortfall_kwh > 0


def test_fixed_bookings_block_charger_time():
    booking = FixedBooking(99, 1, NOW, NOW + timedelta(hours=2), 50, 0, "session", 80)
    d = plan([vehicle(1, 30, trip(1, NOW + timedelta(hours=4), 70))], chargers(1), fixed=[booking]).decisions[0]
    assert d.reservation.start >= NOW + timedelta(hours=2)


def test_charger_availability_window_is_respected():
    night = ((ALL_DAYS, time(22), time(6)),)
    d = plan([vehicle(1, 30, trip(1, datetime(2026, 10, 4, 8, 0, tzinfo=TZ), 70))], chargers(1, availability=night), tariff_optimization=False).decisions[0]
    assert d.reservation.start.astimezone(TZ).time() >= time(22)


def test_rule_based_required_soc_uses_trip_energy_plus_reserve():
    t = TripRequirement(1, "T1", NOW + timedelta(hours=10), None, 30.0, "normal")
    d = plan([vehicle(1, 20, t)], chargers(1), required_soc_mode="rule", safety_reserve_type="kwh", safety_reserve_value=6).decisions[0]
    assert abs(d.target_soc - 60.0) < 0.01


def test_baseline_charges_immediately_to_max_and_ignores_tariffs():
    v = vehicle(27, 42, trip(1, datetime(2026, 10, 4, 7, 30, tzinfo=TZ), 72))
    d = plan([v], chargers(1), mode="baseline").decisions[0]
    assert d.reservation.start == NOW and d.target_soc == 90
    assert "off_peak" not in d.reservation.tariff_mix


def test_rule_based_beats_baseline_on_cost_and_peak_share():
    fleet = [vehicle(i, 25 + i, trip(i, datetime(2026, 10, 4, 6, 30, tzinfo=TZ) + timedelta(minutes=10 * i), 75)) for i in range(1, 9)]
    base = plan(fleet, chargers(4), mode="baseline").metrics
    rule = plan(fleet, chargers(4)).metrics
    assert rule["planned_cost"] < base["planned_cost"]
    assert rule["peak_share_pct"] <= base["peak_share_pct"]
    assert rule["off_peak_share_pct"] > base["off_peak_share_pct"]
    assert rule["projected_readiness_pct"] >= base["projected_readiness_pct"]


def test_lp_benchmark_is_optimal_and_close_to_rule_based_price():
    fleet = [vehicle(i, 25 + i, trip(i, datetime(2026, 10, 4, 6, 30, tzinfo=TZ), 75)) for i in range(1, 7)]
    rule = plan(fleet, chargers(3)).metrics
    engine = Scheduler(EngineConfig(), calendar(), fleet, chargers(3), [StationState(1, "S1", None)])
    lp = lp_lower_bound(engine, NOW)
    assert lp["status"] == "optimal"
    assert lp["avg_rate_per_kwh"] <= rule["avg_rate_per_kwh"] + 1e-6


def test_tariff_calendar_handles_midnight_wrap_and_gaps():
    cal = calendar()
    assert cal.quote(datetime(2026, 10, 3, 23, 30, tzinfo=TZ)).name == "Late"
    assert cal.quote(datetime(2026, 10, 4, 1, 0, tzinfo=TZ)).kind == "off_peak"
    assert coverage_gaps(PERIODS, TZ) == []
    assert len(coverage_gaps(PERIODS[:3], TZ)) == 7 * 8
