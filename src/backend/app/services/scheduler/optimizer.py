"""Linear-programming benchmark for the rule-based schedule.

Solves the continuous relaxation of the fleet charging problem with HiGHS:
minimise energy cost subject to each vehicle's energy requirement before its
deadline, per-slot charger count and site load limits. Because it relaxes
contiguous blocks and per-charger integrality, the optimum is a lower bound on
the cost any feasible schedule can achieve — useful to measure the rule-based
scheduler's optimality gap.
"""

import time as _time
from collections import defaultdict

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from app.services.scheduler.engine import Scheduler

SHORTFALL_PENALTY = 1000.0


def lp_lower_bound(scheduler: Scheduler, now) -> dict:
    started = _time.perf_counter()
    scheduler._build_grid(now)
    n = scheduler.n
    charger_by_id = {c.id: c for c in scheduler.chargers}
    fixed_load = defaultdict(lambda: [0.0] * n)
    fixed_count = defaultdict(lambda: [0] * n)
    locked = {b.vehicle_id for b in scheduler.fixed}
    for b in scheduler.fixed:
        c = charger_by_id.get(b.charger_id)
        if c is None:
            continue
        for i in scheduler._slot_range(b.start, b.end):
            fixed_load[c.station_id][i] += b.power_kw
            fixed_count[c.station_id][i] += 1

    jobs = []
    for v in scheduler.vehicles:
        if v.id in locked:
            continue
        req = scheduler._assess(v, now)
        if req.status != "pending" or req.grid_kwh <= 0:
            continue
        chargers = scheduler._eligible(v)
        if not chargers:
            continue
        power = max(scheduler._power(v, c) for c in chargers)
        jobs.append((v, req, power))

    if not jobs:
        return {"status": "no_flexible_demand", "lower_bound_cost": 0.0, "energy_kwh": 0.0, "shortfall_kwh": 0.0, "solve_ms": 0.0, "variables": 0}

    usable = defaultdict(int)
    for c in scheduler.chargers:
        if c.usable:
            usable[c.station_id] += 1

    var_index: list[tuple[int, int, bool]] = []
    cost: list[float] = []
    upper: list[float] = []
    for j, (v, req, power) in enumerate(jobs):
        sid = v.station_id
        for t in range(n):
            hours = scheduler._usable_hours(t, req.deadline)
            if hours <= 0:
                break
            var_index.append((j, t, False))
            cost.append(scheduler.quotes[sid][t].rate)
            upper.append(power * hours)
            if scheduler.solar_left[sid][t] > 0:
                var_index.append((j, t, True))
                cost.append(0.0)
                upper.append(min(power, scheduler.solar_left[sid][t]) * hours)
    shortfall_offset = len(var_index)
    cost.extend([SHORTFALL_PENALTY] * len(jobs))
    upper.extend([None] * len(jobs))

    eq_rows, eq_cols, eq_vals = [], [], []
    for k, (j, _, _) in enumerate(var_index):
        eq_rows.append(j)
        eq_cols.append(k)
        eq_vals.append(1.0)
    for j in range(len(jobs)):
        eq_rows.append(j)
        eq_cols.append(shortfall_offset + j)
        eq_vals.append(1.0)
    b_eq = [req.grid_kwh for _, req, _ in jobs]

    ub_rows, ub_cols, ub_vals, b_ub = [], [], [], []
    row = 0
    station_rows: dict[tuple[str, int, int], int] = {}
    for k, (j, t, solar) in enumerate(var_index):
        v, _, power = jobs[j]
        sid = v.station_id
        hours = scheduler.durations[t]
        key = ("job", j, t)
        if key not in station_rows:
            station_rows[key] = row
            b_ub.append(power * hours)
            row += 1
        ub_rows.append(station_rows[key])
        ub_cols.append(k)
        ub_vals.append(1.0)
        if solar:
            key = ("solar", sid, t)
            if key not in station_rows:
                station_rows[key] = row
                b_ub.append(scheduler.solar_left[sid][t] * hours)
                row += 1
            ub_rows.append(station_rows[key])
            ub_cols.append(k)
            ub_vals.append(1.0)
        cap = scheduler.stations[sid].max_load_kw if sid in scheduler.stations else None
        if cap is not None:
            key = ("load", sid, t)
            if key not in station_rows:
                station_rows[key] = row
                b_ub.append(max(0.0, cap - fixed_load[sid][t]) * hours)
                row += 1
            ub_rows.append(station_rows[key])
            ub_cols.append(k)
            ub_vals.append(1.0)
        key = ("count", sid, t)
        if key not in station_rows:
            station_rows[key] = row
            b_ub.append(max(0, usable[sid] - fixed_count[sid][t]))
            row += 1
        ub_rows.append(station_rows[key])
        ub_cols.append(k)
        ub_vals.append(1.0 / (power * hours))

    total_vars = len(cost)
    a_eq = coo_matrix((eq_vals, (eq_rows, eq_cols)), shape=(len(jobs), total_vars)).tocsr()
    a_ub = coo_matrix((ub_vals, (ub_rows, ub_cols)), shape=(row, total_vars)).tocsr() if row else None
    result = linprog(
        c=np.array(cost),
        A_ub=a_ub,
        b_ub=np.array(b_ub) if row else None,
        A_eq=a_eq,
        b_eq=np.array(b_eq),
        bounds=[(0, u) for u in upper],
        method="highs",
    )
    elapsed = (_time.perf_counter() - started) * 1000
    if not result.success:
        return {"status": "infeasible", "message": result.message, "lower_bound_cost": None, "energy_kwh": None, "shortfall_kwh": None, "solve_ms": round(elapsed, 1), "variables": total_vars}
    x = result.x
    shortfall = float(x[shortfall_offset:].sum())
    energy_cost = float(np.dot(np.array(cost[:shortfall_offset]), x[:shortfall_offset]))
    mix = defaultdict(float)
    for k, (j, t, _) in enumerate(var_index):
        if x[k] > 1e-6:
            mix[scheduler.quotes[jobs[j][0].station_id][t].kind] += float(x[k])
    energy = float(x[:shortfall_offset].sum())
    return {
        "status": "optimal",
        "lower_bound_cost": round(energy_cost, 2),
        "avg_rate_per_kwh": round(energy_cost / energy, 4) if energy else 0.0,
        "energy_kwh": round(energy, 2),
        "shortfall_kwh": round(shortfall, 2),
        "energy_by_period": {k: round(v, 2) for k, v in mix.items()},
        "peak_share_pct": round(mix.get("peak", 0) / energy * 100, 1) if energy else 0.0,
        "vehicles": len(jobs),
        "variables": total_vars,
        "solve_ms": round(elapsed, 1),
    }
