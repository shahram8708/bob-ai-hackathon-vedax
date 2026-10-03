# Problem Statement

**Selected problem: A3, EV Charging Optimisation Engine (Automobile & Mobility)**

> EV fleet operators face "charging anxiety" (vehicles not charged when needed) and peak demand charges that can add 30–50% to electricity costs. Current charging schedules are static and ignore grid tariff windows, route demand forecasts, and battery degradation profiles. For a 100-vehicle EV fleet, unoptimised charging adds $150,000–$300,000 per year in unnecessary energy costs and reduces battery lifespan by 15–20% through suboptimal charge cycles.
>
> *VGEC x IBM Bob AI Hackathon Problem Statements, 2026*

## Background

Delivery companies, logistics hubs, city bus operators and corporate shuttle services are moving to electric vehicles quickly. In India, last-mile delivery and intra-city logistics are leading the way. A typical depot has a few dozen vehicles, far fewer chargers than vehicles, a grid connection with a fixed capacity, and an electricity contract with time-of-day pricing plus a demand charge on the highest load drawn in the month.

With diesel vans, "refuelling" took ten minutes and could happen whenever it suited. With EVs it takes hours, has to fit between trips, competes for a limited number of chargers, and costs very different amounts depending on the time of day. Charging stops being a background chore and turns into a scheduling problem.

## The Problem

Most depots still deal with this using a static routine: when a vehicle comes back, someone plugs it in and it charges to full. That causes four separate problems:

1. **Charging piles up in the most expensive hours.** Vehicles return in the late afternoon and evening, which is exactly when peak tariffs apply. In the demo tariff we use (₹11.40/kWh peak against ₹5.60/kWh off-peak), our seeded 100-vehicle scenario bought **82% of its charging energy at the peak rate** under a static schedule.
2. **The wrong vehicle gets the charger.** First-come-first-served means a car that isn't needed until tomorrow afternoon can hold a charger while a van leaving at 06:00 waits. In the same scenario, **8 of 66 departures** in the next 24 hours were projected to leave below their required state of charge (SoC).
3. **Vehicles are charged more than they need.** Charging every vehicle to 90–100% when its next trip needs 60% wastes energy and charger time, and keeps batteries at high SoC for longer than necessary, which is one of the main drivers of calendar ageing.
4. **Everyone stacks up on the grid connection at once.** When every returning vehicle starts charging at the same moment, depot load spikes. That spike sets the month's demand charge, and on a busy evening it can exceed what the site connection allows.

On top of all this, nothing in a static routine reacts to change. If a charger faults at 23:00 or a trip gets moved earlier, nobody re-plans until a driver finds a half-charged vehicle in the morning.

## Who is Affected

- **Fleet and depot managers** are responsible for vehicles being ready for service and for the electricity bill. Today they plan charging on spreadsheets, a whiteboard or from memory.
- **Charging operators and night-shift staff** decide which vehicle goes on which charger, by hand, often with incomplete information about the next day's trips.
- **Drivers** arrive for a shift to find their vehicle under-charged, which means delays, cancelled trips or a detour to a public charger.
- **Finance teams** see energy costs and demand charges climb with every EV added and can't tell how much of it could have been avoided.

## Why It Matters

The A3 brief puts unoptimised charging at **$150,000–$300,000 a year** for a 100-vehicle fleet, with demand charges alone adding **30–50%** to electricity costs and battery life shortened by **15–20%**. Batteries are the most expensive part of an EV, so that last figure matters as much as the energy bill.

There is also an operational cost that doesn't show up on any invoice. A vehicle that misses its departure SoC means a missed delivery, a cancelled route or an emergency top-up at public-charger prices. When this keeps happening, operators lose confidence in EVs and slow down electrification. That makes it a sustainability problem as well as a cost problem.

It matters **now** because fleets are passing the size where manual coordination still works. Ten vans and four chargers can be managed by a careful supervisor. A hundred vehicles across three depots with twenty-two chargers can't, and that is roughly the scale many Indian logistics operators are reaching.

## Why Existing Solutions Fall Short

| What fleets use today | Why it isn't enough |
|---|---|
| **Plug-in-and-charge-to-full routines** | Ignores tariffs, trip timing and charger contention entirely. This is the baseline we measure against. |
| **Charger timers / "off-peak only" settings** | Saves money on flexible vehicles but can strand urgent ones. A blanket rule like "only charge after midnight" breaks the moment a vehicle has a 05:30 departure and needs three hours of charging. |
| **Charge-point operator (CPO) portals** | Good at monitoring chargers and billing sessions, but they don't know the fleet's trip schedule, so they can't tell which vehicle should charge first. |
| **Spreadsheets and manual planning** | Workable for a handful of vehicles, but they go stale as soon as anything changes and leave no record of why a decision was made. |
| **Black-box "AI optimisation" products** | Often expensive, and their decisions are hard to audit. An operator can't easily answer "why did my 06:00 van not get charged?" Our PRD explicitly asked for decisions that can be explained in terms of the rules that produced them. |

What's missing is something that combines trip requirements, live SoC, charger availability, site capacity and tariff windows in one plan, re-plans automatically when reality changes, and can explain every decision it makes. That is what we set out to build.
