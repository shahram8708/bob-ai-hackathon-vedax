import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BatteryCharging, LifeBuoy, LogIn, LogOut, Pencil, PowerOff, Truck } from "lucide-react";
import { api } from "@/api/client";
import type { Reservation, VehicleDetail as VD } from "@/api/types";
import { ReservationDrawer } from "@/components/ReservationDrawer";
import { PriorityBadge, ReadinessBadge, ReservationBadge } from "@/components/status";
import { VehicleForm } from "@/components/VehicleForm";
import { Badge, Button, Callout, DefinitionList, ErrorState, Field, Input, LoadingBlock, Modal, Panel, RuleChip, Select, SocBar, Tabs } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, humanize, kwh, money, num, pct, relative, time } from "@/lib/format";

interface ContingencyOption {
  kind: "fleet_depot" | "public_charging" | "mobile_charging" | "towing";
  name: string;
  distance_km: number;
  reachable: boolean;
  eta_min: number;
  charger?: string;
  connector?: string;
  power_kw?: number | null;
  charge_time_min?: number | null;
  estimated_cost: number;
  tow_distance_km?: number;
  phone?: string;
  directory_sample: boolean;
}

interface ContingencyData {
  current_soc: number;
  estimated_range_km: number;
  energy_to_target_kwh: number;
  target_soc: number;
  rules: string[];
  options: ContingencyOption[];
}

const KIND_LABEL = { fleet_depot: "Fleet depot", public_charging: "Public charger", mobile_charging: "Mobile charging", towing: "Towing" };

function EventModal({ kind, vehicle, onClose }: { kind: "soc" | "arrive" | "depart"; vehicle: VD; onClose: () => void }) {
  const { stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [soc, setSoc] = useState(String(Math.round(vehicle.current_soc)));
  const [stationId, setStationId] = useState(String(vehicle.home_station_id));
  const invalid = kind !== "depart" && (soc === "" || Number(soc) < 0 || Number(soc) > 100);
  const m = useMutation({
    mutationFn: () =>
      kind === "soc"
        ? api.post(`/vehicles/${vehicle.id}/soc`, { soc: Number(soc) })
        : kind === "arrive"
          ? api.post(`/vehicles/${vehicle.id}/arrive`, { station_id: Number(stationId), soc: Number(soc) })
          : api.post(`/vehicles/${vehicle.id}/depart`, { trip_id: vehicle.next_trip?.id }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: kind === "soc" ? "SoC updated" : kind === "arrive" ? `${vehicle.registration} checked in` : `${vehicle.registration} departed`, body: "Schedule recalculated for the new state." });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const title = kind === "soc" ? "Update state of charge" : kind === "arrive" ? "Record arrival at depot" : "Record departure";
  return (
    <Modal
      open
      onClose={onClose}
      title={`${title} · ${vehicle.registration}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={invalid} loading={m.isPending} onClick={() => m.mutate()}>
            Confirm
          </Button>
        </>
      }
    >
      {kind === "depart" ? (
        <div className="space-y-3 text-sm">
          <p>
            {vehicle.next_trip ? (
              <>
                Departing on <strong className="num">{vehicle.next_trip.code}</strong> to {vehicle.next_trip.destination} with <strong className="num">{pct(vehicle.current_soc)}</strong> against a{" "}
                <strong className="num">{pct(vehicle.required_soc)}</strong> requirement.
              </>
            ) : (
              "No trip is assigned — the vehicle will be marked as away from the depot."
            )}
          </p>
          {vehicle.next_trip && vehicle.current_soc < vehicle.required_soc - 0.5 && <Callout tone="critical">The vehicle is below its required SoC. Departing now records a missed requirement and raises a critical alert.</Callout>}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="State of charge %" htmlFor="ev-soc" error={invalid ? "Enter 0–100" : undefined}>
            <Input id="ev-soc" type="number" min={0} max={100} value={soc} onChange={(e) => setSoc(e.target.value)} invalid={invalid} />
          </Field>
          {kind === "arrive" && (
            <Field label="Depot" htmlFor="ev-st">
              <Select id="ev-st" value={stationId} onChange={(e) => setStationId(e.target.value)}>
                {stations.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function VehicleDetail() {
  const { id } = useParams();
  const { can } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"activity" | "contingency">("activity");
  const [editOpen, setEditOpen] = useState(false);
  const [event, setEvent] = useState<"soc" | "arrive" | "depart" | null>(null);
  const [selected, setSelected] = useState<Reservation | null>(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const q = useQuery({ queryKey: ["vehicle", id], queryFn: () => api.get<VD>(`/vehicles/${id}`) });
  const contingency = useQuery({ queryKey: ["vehicle", id, "contingency"], queryFn: () => api.get<ContingencyData>(`/vehicles/${id}/contingency`), enabled: tab === "contingency" });
  const deactivate = useMutation({
    mutationFn: () => api.put(`/vehicles/${id}`, { is_active: !q.data?.is_active }),
    onSuccess: () => {
      qc.invalidateQueries();
      setConfirmDeactivate(false);
      toast.push({ tone: "success", title: q.data?.is_active ? "Vehicle deactivated" : "Vehicle reactivated" });
    },
    onError: (e) => toast.error(e),
  });

  if (q.isLoading) return <LoadingBlock rows={10} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const v = q.data;
  const atDepot = v.availability === "available" || v.availability === "charging";

  return (
    <div>
      <Link to="/vehicles" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink">
        <ArrowLeft className="h-3.5 w-3.5" /> Vehicles
      </Link>
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="eyebrow">
            {v.vehicle_type} · {v.battery_profile}
          </div>
          <h1 className="flex flex-wrap items-center gap-2 text-[1.375rem] font-semibold">
            <span className="num">{v.registration}</span>
            <ReadinessBadge value={v.readiness} />
            {!v.is_active && <Badge>Deactivated</Badge>}
            {v.priority_category === "critical" && <Badge tone="critical">Critical vehicle</Badge>}
          </h1>
          <p className="mt-1 text-sm text-ink-2">
            {v.current_station ? `At ${v.current_station}` : "Away from depot"} · home {v.home_station}
            {v.assigned_driver && ` · driver ${v.assigned_driver}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {can("vehicles:events") && v.is_active && (
            <>
              <Button icon={<BatteryCharging className="h-4 w-4" />} onClick={() => setEvent("soc")}>
                Update SoC
              </Button>
              {atDepot ? (
                <Button icon={<LogOut className="h-4 w-4" />} onClick={() => setEvent("depart")}>
                  Record departure
                </Button>
              ) : (
                <Button icon={<LogIn className="h-4 w-4" />} onClick={() => setEvent("arrive")}>
                  Record arrival
                </Button>
              )}
            </>
          )}
          {can("vehicles:manage") && (
            <>
              <Button icon={<Pencil className="h-4 w-4" />} onClick={() => setEditOpen(true)}>
                Edit
              </Button>
              <Button variant="ghost" icon={<PowerOff className="h-4 w-4" />} onClick={() => setConfirmDeactivate(true)}>
                {v.is_active ? "Deactivate" : "Reactivate"}
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel eyebrow="Battery" title="State of charge" className="lg:col-span-1">
          <div className="num text-[2.5rem] font-medium leading-none">{pct(v.current_soc, 1)}</div>
          <div className="mt-3">
            <SocBar soc={v.current_soc} required={v.required_soc} showLabel={false} />
            <div className="mt-1.5 flex justify-between font-mono text-2xs text-ink-3">
              <span>min {pct(v.min_operating_soc)}</span>
              <span>required {pct(v.required_soc)}</span>
              <span>max {pct(v.max_soc)}</span>
            </div>
          </div>
          <div className="mt-4">
            <DefinitionList
              items={[
                ["Capacity", kwh(v.battery_capacity_kwh, 0)],
                ["To requirement", v.energy_to_requirement_kwh > 0 ? kwh(v.energy_to_requirement_kwh) : "Met"],
                ["Connectors", v.connector_types.join(", ")],
                ["Updated", v.soc_updated_at ? relative(v.soc_updated_at) : "—"],
                ["Charging hold", v.charging_hold_until ? `until ${dayTime(v.charging_hold_until)}` : "None"],
              ]}
            />
          </div>
        </Panel>

        <Panel eyebrow="Next assignment" title={v.next_trip ? v.next_trip.code : "No trip scheduled"} className="lg:col-span-2">
          {v.next_trip ? (
            <div className="grid gap-4 md:grid-cols-2">
              <DefinitionList
                items={[
                  ["Destination", v.next_trip.destination],
                  ["Departure", <span className="num">{dayTime(v.next_trip.departure_at)} <span className="text-ink-3">({relative(v.next_trip.departure_at)})</span></span>],
                  ["Distance", `${num(v.next_trip.distance_km)} km`],
                  ["Trip energy", kwh(v.trip_energy_kwh)],
                  ["Required SoC", pct(v.required_soc)],
                  ["Priority", humanize(v.next_trip.priority)],
                ]}
              />
              <div>
                {v.request ? (
                  <>
                    <div className="mb-2 flex flex-wrap items-center gap-1.5">
                      <PriorityBadge level={v.request.priority_level} />
                      <Badge tone={v.request.status === "at_risk" ? "critical" : "info"}>{humanize(v.request.status)}</Badge>
                      {v.request.rules.map((r) => (
                        <RuleChip key={r} code={r} />
                      ))}
                    </div>
                    <p className="rounded border border-line bg-paper px-3 py-2.5 text-[0.8125rem] leading-relaxed text-ink-2">{v.request.explanation}</p>
                  </>
                ) : (
                  <p className="text-sm text-ink-3">No open charging request — the vehicle meets its requirement or is away.</p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-3">The scheduler keeps this vehicle at its default {pct(v.required_departure_soc)} target using the cheapest available window (P5).</p>
          )}
        </Panel>
      </div>

      <div className="mt-4">
        <Tabs
          label="Vehicle sections"
          value={tab}
          onChange={setTab}
          items={[
            { value: "activity", label: "Schedule & history" },
            { value: "contingency", label: "Contingency options" },
          ]}
        />
      </div>

      {tab === "activity" && (
        <div className="mt-4 grid items-start gap-4 xl:grid-cols-2">
          <Panel eyebrow="Reservations" title="Upcoming charging" bodyClassName="p-0">
            {v.reservations.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-3">No reservations.</p>
            ) : (
              <ul className="divide-y divide-line">
                {v.reservations.map((r) => (
                  <li key={r.id}>
                    <button className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-paper" onClick={() => setSelected(r)}>
                      <span>
                        <span className="num font-medium">{r.charger}</span>
                        <span className="num ml-2 text-sm text-ink-2">
                          {dayTime(r.start_at)} – {time(r.end_at)}
                        </span>
                        <span className="mt-0.5 block text-xs text-ink-3">
                          {kwh(r.planned_energy_kwh)} · {money(r.estimated_cost, 2)} · to {pct(r.target_soc)}
                        </span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        {r.rules.map((c) => (
                          <RuleChip key={c} code={c} />
                        ))}
                        <ReservationBadge value={r.status} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel eyebrow="History" title="Recent charging sessions" bodyClassName="p-0">
            <div className="scroll-thin overflow-x-auto">
              <table className="table-base min-w-[520px]">
                <thead>
                  <tr>
                    <th>Started</th>
                    <th className="text-right">SoC</th>
                    <th className="text-right">Energy</th>
                    <th className="text-right">Cost</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {v.sessions.map((s) => (
                    <tr key={s.id}>
                      <td className="num whitespace-nowrap">{dayTime(s.started_at)}</td>
                      <td className="num text-right">
                        {pct(s.start_soc)} → {pct(s.end_soc)}
                      </td>
                      <td className="num text-right">{kwh(s.energy_kwh)}</td>
                      <td className="num text-right">{money(s.cost, 2)}</td>
                      <td>
                        <Badge tone={s.status === "active" ? "brand" : s.status === "interrupted" ? "critical" : "neutral"}>{humanize(s.status)}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel eyebrow="Trips" title="Trip history" className="xl:col-span-2" bodyClassName="p-0">
            <div className="scroll-thin overflow-x-auto">
              <table className="table-base min-w-[760px]">
                <thead>
                  <tr>
                    <th>Trip</th>
                    <th>Destination</th>
                    <th>Departure</th>
                    <th className="text-right">Required</th>
                    <th className="text-right">Departed with</th>
                    <th className="text-right">Energy used</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {v.trips.map((t) => (
                    <tr key={t.id}>
                      <td className="num">{t.code}</td>
                      <td>{t.destination}</td>
                      <td className="num whitespace-nowrap">{dayTime(t.departure_at)}</td>
                      <td className="num text-right">{pct(t.required_soc)}</td>
                      <td className="num text-right">
                        {t.departure_soc !== null ? pct(t.departure_soc) : "—"}
                        {t.requirement_met === false && <Badge tone="critical" className="ml-1.5">missed</Badge>}
                      </td>
                      <td className="num text-right">{t.actual_energy_kwh !== null ? kwh(t.actual_energy_kwh) : "—"}</td>
                      <td>
                        <Badge tone={t.status === "in_progress" ? "info" : t.status === "completed" ? "good" : "neutral"}>{humanize(t.status)}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      {tab === "contingency" && (
        <div className="mt-4">
          {contingency.isLoading ? (
            <LoadingBlock rows={6} />
          ) : contingency.error ? (
            <ErrorState error={contingency.error} />
          ) : contingency.data ? (
            <Panel eyebrow="Rule-based contingency" title={`Range ≈ ${num(contingency.data.estimated_range_km)} km at ${pct(contingency.data.current_soc)}`} actions={<LifeBuoy className="h-4 w-4 text-ink-3" />} bodyClassName="p-0">
              <div className="space-y-2 px-4 py-3">
                {contingency.data.rules.map((r) => (
                  <Callout key={r} tone={r.startsWith("No compatible") ? "warn" : "info"}>
                    {r}
                  </Callout>
                ))}
                <p className="text-xs text-ink-3">
                  Costs estimate {kwh(contingency.data.energy_to_target_kwh)} to reach {pct(contingency.data.target_soc)}. Third-party entries marked “directory sample” are illustrative records configured by the administrator.
                </p>
              </div>
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[820px]">
                  <thead>
                    <tr>
                      <th>Option</th>
                      <th>Type</th>
                      <th className="text-right">Distance</th>
                      <th>Reachable</th>
                      <th className="text-right">ETA</th>
                      <th className="text-right">Charge time</th>
                      <th className="text-right">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {contingency.data.options.map((o, i) => (
                      <tr key={i}>
                        <td>
                          <div className="font-medium">{o.name}</div>
                          <div className="text-2xs text-ink-3">{o.charger ? `${o.charger} · ${o.connector} · ${num(o.power_kw)} kW` : o.tow_distance_km ? `Tow ${num(o.tow_distance_km)} km to home depot` : o.connector ?? ""}</div>
                        </td>
                        <td>
                          <span className="inline-flex items-center gap-1 text-xs text-ink-2">
                            {o.kind === "towing" ? <Truck className="h-3.5 w-3.5" aria-hidden /> : <BatteryCharging className="h-3.5 w-3.5" aria-hidden />}
                            {KIND_LABEL[o.kind]}
                          </span>
                        </td>
                        <td className="num text-right">{num(o.distance_km, 1)} km</td>
                        <td>{o.reachable ? <Badge tone="good">Yes</Badge> : <Badge tone="critical">Out of range</Badge>}</td>
                        <td className="num text-right">{num(o.eta_min)} min</td>
                        <td className="num text-right">{o.charge_time_min ? `${num(o.charge_time_min)} min` : "—"}</td>
                        <td className="num text-right">{money(o.estimated_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          ) : null}
        </div>
      )}

      <VehicleForm open={editOpen} onClose={() => setEditOpen(false)} vehicle={v} />
      {event && <EventModal kind={event} vehicle={v} onClose={() => setEvent(null)} />}
      {selected && <ReservationDrawer reservation={selected} onClose={() => setSelected(null)} />}
      <Modal
        open={confirmDeactivate}
        onClose={() => setConfirmDeactivate(false)}
        title={v.is_active ? `Deactivate ${v.registration}?` : `Reactivate ${v.registration}?`}
        description={v.is_active ? "Its planned reservations are cancelled and it is excluded from scheduling. History is kept." : "The vehicle returns to scheduling on the next run."}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDeactivate(false)}>
              Cancel
            </Button>
            <Button variant={v.is_active ? "danger" : "primary"} loading={deactivate.isPending} onClick={() => deactivate.mutate()}>
              {v.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">This change is recorded in the audit log.</p>
      </Modal>
    </div>
  );
}
