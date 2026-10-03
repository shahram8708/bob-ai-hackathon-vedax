# Screenshots

Screenshots of ChargeOpt running locally on the seeded 100-vehicle demo scenario (three Bengaluru depots, 22 chargers, tariffs in INR). Desktop shots are 1440 × 900. The comparison and driver views are shown at phone width (390 px). Every value is simulated, and the app labels it that way.

Most shots were taken while the **static baseline** was still active, which is the "before" state the demo starts in. That's why several vehicles are shown at risk and most charging falls in the evening peak. The comparison screenshot (03) puts the baseline next to the rule-based plan on the same snapshot.

| File | What it shows |
|---|---|
| `01-fleet-overview.png` | Overview: fleet KPIs, departures at risk with the reason for each, 24-hour tariff strip, last scheduler run. |
| `02-schedule-decisions-and-rules.png` | Schedule → Decisions & rules: one row per vehicle with priority, status, SoC → target, deadline, rules fired and the explanation. |
| `03-baseline-vs-rule-based.png` | Schedule → Baseline vs rule-based: both strategies on the same fleet snapshot (projected readiness 86.2% vs 93.8% at the time of capture). |
| `04-energy-and-cost.png` | Energy & cost: kWh and cost by tariff period, peak share, demand-charge estimate per depot, solar and storage offsets, depot load profile. |
| `05-alerts-and-exceptions.png` | Alerts: at-risk departures, peak-approaching and fleet-readiness alerts, with acknowledge and resolve. |
| `06-charging-operations.png` | Charging ops: live charger states (including a fault and an OCPP charger), start and status controls. |
| `07-tariff-configuration.png` | Tariffs: off-peak / shoulder / peak periods with demand charges, and the effective price for the next 24 h. |
| `08-fleet-map.png` | Fleet map: depots with free-charger counts, vehicles coloured by readiness, vehicles on trips. |
| `09-reports-and-success-metrics.png` | Reports: the PRD's success metrics over 30 days and 13 downloadable CSV reports. |
| `10-driver-view-mobile.png` | Driver view on a phone: EV-027's charge against its trip requirement, and where and when to plug in. |

## Naming Convention

Screenshots are numbered so they appear in a logical order: what a user sees first, then the main feature, then the results.

## Requirements (from the template)

- Minimum: 3 screenshots
- Format: PNG or JPG
- Show the application running with real (or realistic mock) data
