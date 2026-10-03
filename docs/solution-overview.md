# Solution Overview

## What We Built

ChargeOpt is a web platform that plans and runs charging for an EV fleet. You give it the things a depot already knows: which vehicles are where, their current charge, which trips are coming up, which chargers exist and what electricity costs at each hour. It produces a concrete plan of the form "EV-083 goes on charger APH-C01 from 00:00 to 01:51 at 120 kW", and it keeps that plan up to date as the night goes on.

Its main job is to make sure every vehicle has enough charge for its next trip. Once that is covered, it uses any spare time to move charging into cheaper hours and to keep depot load down. Operators can see the plan on a timeline, override it, get alerts when something is at risk, and pull reports on what was spent.

The scheduling core is deliberately **rule-based and deterministic**. It doesn't learn from history or guess. Given the same fleet state, it will always produce the same plan, and it can always tell you which rule led to each decision.

## How It Works

Every time the plan needs refreshing, the engine (`src/backend/app/services/scheduler/engine.py`) takes a snapshot of the fleet and goes through these steps:

1. **Work out each vehicle's target.** The target SoC is either set by the operator on the trip, or derived from the trip's energy plus a configurable safety reserve (a percentage or a fixed kWh). It is capped at the vehicle's maximum permitted SoC. If the vehicle already meets its target, rule **R1** applies and nothing is scheduled.
2. **Convert that into energy.** The engine calculates the kWh needed to reach the target, then the kWh to draw from the grid after allowing for charging efficiency.
3. **Find the deadline.** This is the departure time minus a buffer (15 minutes by default). Vehicles without a trip are planned within a 24-hour horizon.
4. **Filter chargers.** A charger is eligible if it is at the same depot, in a usable state, has a compatible connector, is inside its availability window and has headroom under the depot load limit. Power is the lower of what the charger and the vehicle can handle, for AC and DC separately.
5. **Rank vehicles.** P1 emergency or critical, P2 departing within the urgent window with insufficient SoC, P3 below minimum SoC with a trip, P4 flexible with a trip, P5 no trip. Ties go to the earliest departure, then the lowest SoC, then the oldest request. The tie-break order is configurable.
6. **Choose the window.** The engine compares the time available with the time needed to charge. If there's at least an hour of slack (also configurable), the vehicle counts as flexible, and the engine scans every contiguous slot on every eligible charger for the cheapest one that still finishes before the deadline (**R4**). Urgent vehicles get the earliest-finishing slot instead and skip tariff optimisation (**R2**). Readiness always comes before cost.
7. **Reserve the slot.** The slot is marked busy on that charger and its power is added to the depot's load profile, so lower-priority vehicles can't take it. If a vehicle's preferred slot was already held by a higher-priority one, the engine records the conflict it avoided (**R3**). The database enforces the same thing again with an exclusion constraint.
8. **Explain the decision.** Each decision is turned into a sentence. Here is a real one from the demo fleet:

   > *P3 low SoC with a scheduled trip. Needs 69.0% (207.0 kWh to battery, 222.6 kWh from grid) to reach 85% by 05:45 (departure 06:00 − 15 min buffer). 11h 09m available vs 1h 51m charging at 120 kW → flexible. R4: shifted to off-peak window — est. 1246.45 INR vs 2537.42 INR if charged immediately. Reserved APH-C01 00:00–01:51 at 120 kW (222.6 kWh, est. 1246.45 INR).*

The persistence layer (`scheduler/service.py`) compares the new plan with existing reservations. Unchanged ones are kept, changed ones are superseded, and each run is logged with its trigger, duration and counts.

### Keeping the plan current

A background loop runs every few seconds. It starts sessions when their slot begins, advances simulated charging, releases reservations for vehicles that didn't turn up (**R6**), completes sessions once they reach target (**R7**) and re-evaluates alerts. The plan is rebuilt whenever something meaningful changes:

- a vehicle arrives, departs or reports a new SoC
- a trip is created, edited or imported
- a charger faults or goes into maintenance (**R5**: its sessions are interrupted, an alert is raised and affected vehicles are moved to another compatible charger)
- an operator makes a manual reservation or emergency override (**R8**, recorded in the audit log)
- tariffs or configuration change
- plus a periodic re-check every 15 minutes

If approval mode is on, a new plan waits as "pending" and the previous one stays in force until a fleet manager approves it.

## What Makes It Different

**Readiness is a hard constraint, cost is not.** A naive "charge off-peak only" timer saves money until a vehicle with an early departure gets stranded. ChargeOpt only shifts a vehicle when the slack is real, and an urgent vehicle never waits for a cheaper hour. In the demo this is why readiness goes *up* (87.9% → 93.9%) while cost goes *down* (−58.5%).

**It charges to what's needed, not to full.** The baseline charges everyone to the maximum. ChargeOpt charges to the trip requirement plus a reserve, which cut grid energy by 32% in the demo scenario. It also frees charger time and keeps batteries at high SoC for less time.

**It measures itself.** It's easy to say a heuristic is "near-optimal". We built a separate LP model (`scheduler/optimizer.py`) that relaxes the same problem (per-slot charger counts, site load limits, per-vehicle energy before deadline) and solves it with HiGHS. Its optimum is a lower bound on the cost of *any* feasible schedule. On the demo fleet, the rule-based plan costs ₹15,602 against a bound of ₹15,116, a **3.2% gap**, and the operator can see this on the *Baseline vs rule-based* tab.

**Every decision can be audited.** Each reservation stores the rules that fired and the sentence explaining them. An operator who asks why a vehicle wasn't charged gets an answer in the UI, not a model score.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Deterministic rules instead of an ML model | Our PRD set this as a requirement, and it suits the domain. Operators have to trust the plan and be able to defend it, and an explainable rule set is easier to validate, test and change. It also needs no training data, which a new EV fleet doesn't have. |
| Pure engine, separate persistence | The engine takes immutable dataclasses and returns a plan, with no database access. That makes it easy to unit-test (15 engine tests), lets the same code drive the live plan, the preview and the baseline comparison, and lets the LP benchmark reuse its feasibility logic. |
| Greedy priority order with a full window scan per vehicle | It runs fast enough to replan on every event (well under a few seconds for 100 vehicles), and the LP benchmark shows the remaining cost gap is small. A full MILP would be slower and harder to explain. |
| Discrete time slots (15 min default) over a rolling 24 h horizon | Matches how tariffs and charger bookings work in practice, keeps the search bounded, and partial first and last slots are handled exactly. |
| Conflict prevention in both the engine and PostgreSQL | The engine avoids conflicts by design. The `EXCLUDE USING gist` constraint on `(charger_id, time range)` guarantees that a manual edit or a race between two workers can't double-book a charger either. |
| Operator-defined required SoC by default | It's transparent and easy to check, as the PRD recommends. Rule-based targets (trip kWh + reserve) are available as a configuration option. |
| Simulated telemetry with OCPP as a real path | Nobody has a depot of real chargers at a hackathon. The simulator makes the system demonstrable end to end, and every simulated value is labelled `source = simulated`. Chargers connected over OCPP 1.6-J are controlled for real. |
| Baseline mode built into the same engine | So "before vs after" is a fair comparison on the same snapshot with the same chargers and tariffs, not two separate code paths. |

## What the User Experience Looks Like

- **Fleet manager**, on the **Overview** page: KPIs for fleet size, ready vehicles, vehicles needing charge, charging now, at-risk departures, free chargers, today's energy and cost, and active reservations. There's a list of departures at risk with a one-line reason for each, a 24-hour tariff strip, and the status of the last scheduler run. Everything updates over WebSocket.
- **Operator**, on the **Schedule** page: a per-charger timeline of reservations. Clicking a reservation shows its rules and explanation, with options to override or cancel it. The *Decisions & rules* tab lists every vehicle's decision, *Baseline vs rule-based* shows the comparison and LP gap, and *Run history* lists every recalculation with its trigger and timing.
- **Charging operator**, on **Charging ops**: live charger states, sessions and session history, with start/stop, status changes and power limits sent over OCPP when a charger is connected.
- **Alerts & exceptions**: all eight alert types from our PRD (below required SoC, session interrupted, charger fault, missed slot, reservation conflict, unexpected consumption, peak approaching with charging incomplete, fleet readiness below threshold), each of which can be acknowledged and resolved with a note.
- **Driver**, on a phone: "My vehicle" shows current charge against what the next trip needs, and tells them exactly where and when to plug in.
- **Management**: Energy & cost (cost by tariff period, demand-charge estimates per depot, solar and storage offsets), 13 CSV reports, a fleet map and a full audit log.

## IBM Technologies Used

- **IBM Bob:** the team used IBM Bob as its AI development partner while building ChargeOpt. Bob is a development tool, not a runtime dependency, so the running application doesn't call it. This fits our PRD, which requires the production decision engine to be deterministic and free of AI/ML.
- **IBM Plex:** the UI uses IBM's open-source Plex Sans and Plex Mono typefaces, self-hosted, for the dashboard's tabular and numeric data.

## How It Maps to Problem A3

| A3 asks for… | ChargeOpt answer |
|---|---|
| Avoid "charging anxiety" (vehicles not charged when needed) | Readiness is a hard constraint; P1/P2 vehicles bypass tariff optimisation; at-risk vehicles are flagged with alerts as soon as they're detected; projected readiness 87.9% → 93.9% in the demo. |
| Reduce peak demand charges | Flexible charging is moved out of peak hours (peak share 82% → 22%); depot load caps; demand-charge estimates per depot; peak site load −214 kW in the demo. |
| Use grid tariff windows | Configurable tariff periods per depot, with midnight wrap-around, demand charges and dynamic price feeds (JSON/CSV). |
| Account for route demand | Uses each vehicle's next scheduled trip (required SoC, or trip energy + reserve) from manual entry, CSV import or the fleet/ERP integration API. No ML forecasting, by design. |
| Account for battery degradation | Charges to what the trip needs rather than to the maximum, respects each vehicle's max permitted SoC, and lowers total throughput (−32% energy in the demo). We don't model degradation itself. See the README's Known Limitations. |
| Work at 100-vehicle scale | The demo runs a 100-vehicle fleet across 3 depots and 22 chargers. A full recalculation, including persistence, completes in about 0.1–2.4 s in our runs. |
