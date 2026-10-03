import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, ListChecks, Plus, RefreshCw, Scale, ShieldCheck, XCircle } from "lucide-react";
import { ApiError, api } from "@/api/client";
import type { ChargingRequest, Charger, Comparison, Reservation, ScheduleRun, TariffSlot, Vehicle } from "@/api/types";
import { AXIS, ChartTip, GRID } from "@/components/charts";
import { ReservationDrawer } from "@/components/ReservationDrawer";
import { PriorityBadge } from "@/components/status";
import { ScheduleTimeline } from "@/components/Timeline";
import { Badge, Button, Callout, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Panel, RuleChip, Select, SimulatedTag, Tabs, Textarea, Toggle, cx } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, fromLocalInput, humanize, kwh, localInputValue, money, num, pct, time, TARIFF_COLORS, TARIFF_LABEL } from "@/lib/format";

interface ScheduleData {
  as_of: string;
  mode: "baseline" | "rule_based";
  require_approval: boolean;
  latest_run: ScheduleRun | null;
  pending_run: ScheduleRun | null;
  reservations: Reservation[];
}

interface PreviewData {
  mode: string;
  metrics: Comparison["baseline"];
  reservations: (Omit<Reservation, "id" | "run_id" | "request_id" | "override_reason"> & { id?: number })[];
}

type Tab = "timeline" | "decisions" | "compare" | "runs";

function StatRow({ label, a, b, better, hint }: { label: string; a: string; b: string; better?: "a" | "b" | null; hint?: string }) {
  return (
    <tr>
      <td className="text-ink-2">
        {label}
        {hint && <div className="text-2xs text-ink-3">{hint}</div>}
      </td>
      <td className={cx("num text-right", better === "a" && "font-semibold text-good-ink")}>{a}</td>
      <td className={cx("num text-right", better === "b" && "font-semibold text-good-ink")}>{b}</td>
    </tr>
  );
}

function ComparisonView({ data }: { data: Comparison }) {
  const b = data.baseline;
  const r = data.rule_based;
  const lp = data.lp_benchmark;
  const lower = (x: number, y: number) => (x < y ? "a" : y < x ? "b" : null);
  const higher = (x: number, y: number) => (x > y ? "a" : y > x ? "b" : null);
  const chart = [
    { name: "Static baseline", ...Object.fromEntries(["off_peak", "shoulder", "peak", "custom"].map((k) => [k, Math.round(b.energy_by_period[k] ?? 0)])) },
    { name: "Rule-based", ...Object.fromEntries(["off_peak", "shoulder", "peak", "custom"].map((k) => [k, Math.round(r.energy_by_period[k] ?? 0)])) },
  ];
  const kinds = ["off_peak", "shoulder", "peak", "custom"].filter((k) => chart.some((c) => (c as Record<string, number | string>)[k]));
  return (
    <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
      <Panel
        eyebrow="Same fleet snapshot · next 24 h"
        title="Static baseline vs rule-based schedule"
        actions={<SimulatedTag />}
        bodyClassName="p-0"
      >
        <table className="table-base">
          <thead>
            <tr>
              <th>Metric</th>
              <th className="text-right">Static baseline</th>
              <th className="text-right">Rule-based</th>
            </tr>
          </thead>
          <tbody>
            <StatRow label="Projected departure readiness" a={pct(b.projected_readiness_pct, 1)} b={pct(r.projected_readiness_pct, 1)} better={higher(b.projected_readiness_pct, r.projected_readiness_pct)} hint={`${b.departures_in_horizon} departures in horizon`} />
            <StatRow label="Vehicles at risk" a={num(b.at_risk)} b={num(r.at_risk)} better={lower(b.at_risk, r.at_risk)} />
            <StatRow label="Readiness shortfall" a={kwh(b.shortfall_kwh, 0)} b={kwh(r.shortfall_kwh, 0)} better={lower(b.shortfall_kwh, r.shortfall_kwh)} />
            <StatRow label="Planned charging energy" a={kwh(b.planned_energy_kwh, 0)} b={kwh(r.planned_energy_kwh, 0)} better={lower(b.planned_energy_kwh, r.planned_energy_kwh)} hint="Baseline charges to max SoC" />
            <StatRow label="Estimated energy cost" a={money(b.planned_cost)} b={money(r.planned_cost)} better={lower(b.planned_cost, r.planned_cost)} />
            <StatRow label="Average price paid" a={`${money(b.avg_rate_per_kwh, 2)}/kWh`} b={`${money(r.avg_rate_per_kwh, 2)}/kWh`} better={lower(b.avg_rate_per_kwh, r.avg_rate_per_kwh)} />
            <StatRow label="Energy in peak window" a={`${kwh(b.peak_energy_kwh, 0)} · ${pct(b.peak_share_pct)}`} b={`${kwh(r.peak_energy_kwh, 0)} · ${pct(r.peak_share_pct)}`} better={lower(b.peak_energy_kwh, r.peak_energy_kwh)} />
            <StatRow label="Energy in off-peak window" a={pct(b.off_peak_share_pct)} b={pct(r.off_peak_share_pct)} better={higher(b.off_peak_share_pct, r.off_peak_share_pct)} />
            <StatRow label="Peak site load (sum of depots)" a={`${num(b.peak_site_load_kw)} kW`} b={`${num(r.peak_site_load_kw)} kW`} better={lower(b.peak_site_load_kw, r.peak_site_load_kw)} />
            <StatRow label="Demand-charge estimate (monthly)" a={money(b.demand_charge_estimate)} b={money(r.demand_charge_estimate)} better={lower(b.demand_charge_estimate, r.demand_charge_estimate)} hint="Estimate from configured demand rates" />
            <StatRow label="Charger conflicts prevented" a={num(b.conflicts_prevented)} b={num(r.conflicts_prevented)} />
          </tbody>
        </table>
        <p className="px-4 py-3 text-xs text-ink-3">
          Both plans are computed from the same current fleet state, tariff table and charger availability. Values are modelled from simulated telemetry and configured tariffs — they are not measured savings.
        </p>
      </Panel>
      <div className="space-y-4">
        <Panel eyebrow="Planned energy by tariff period" title="Where the kWh land">
          <div className="h-[200px]" role="img" aria-label="Stacked energy by tariff period for each plan">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }} barCategoryGap={18}>
                <CartesianGrid {...GRID} horizontal={false} vertical />
                <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} unit=" kWh" />
                <YAxis type="category" dataKey="name" tick={{ ...AXIS, fontFamily: "IBM Plex Sans", fontSize: 12 }} tickLine={false} axisLine={false} width={104} />
                <Tooltip cursor={{ fill: "#EEEBE4" }} content={<ChartTip formatter={(v) => `${num(v)} kWh`} />} />
                <Legend iconType="square" iconSize={9} wrapperStyle={{ fontSize: 12 }} />
                {kinds.map((k) => (
                  <Bar key={k} dataKey={k} name={TARIFF_LABEL[k]} stackId="e" fill={TARIFF_COLORS[k]} stroke="#FCFCFB" strokeWidth={2} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        {lp && (
          <Panel eyebrow="Advanced optimisation benchmark" title="Linear-programming reference">
            {lp.status === "optimal" ? (
              <>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="eyebrow">LP avg price</div>
                    <div className="num text-lg">{money(lp.avg_rate_per_kwh ?? 0, 2)}</div>
                  </div>
                  <div>
                    <div className="eyebrow">Rule-based gap</div>
                    <div className="num text-lg">{lp.rule_based_gap_pct !== undefined ? pct(lp.rule_based_gap_pct, 1) : "—"}</div>
                  </div>
                  <div>
                    <div className="eyebrow">Solve time</div>
                    <div className="num text-lg">{num(lp.solve_ms)} ms</div>
                  </div>
                </div>
                <p className="mt-3 text-xs text-ink-3">
                  HiGHS solves the continuous relaxation over {num(lp.variables)} variables for {num(lp.vehicles ?? 0)} vehicles (charger counts, site load, solar). It relaxes contiguous blocks and per-charger
                  assignment, so it is a reference for how close the explainable rules come to the mathematical optimum on price per kWh.
                </p>
              </>
            ) : (
              <p className="text-sm text-ink-3">{lp.status === "no_flexible_demand" ? "No schedulable demand right now." : `Solver status: ${lp.status}`}</p>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}

function ManualReservation({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [vehicleId, setVehicleId] = useState<number | "">("");
  const [chargerId, setChargerId] = useState<number | "">("");
  const [start, setStart] = useState(localInputValue(new Date()));
  const [target, setTarget] = useState("80");
  const [reason, setReason] = useState("");
  const [emergency, setEmergency] = useState(false);
  const [preempt, setPreempt] = useState(false);
  const vehicles = useQuery({ queryKey: ["vehicles", "all"], queryFn: () => api.get<{ items: Vehicle[] }>("/vehicles", { page_size: 200 }), enabled: open });
  const chargers = useQuery({ queryKey: ["chargers"], queryFn: () => api.get<Charger[]>("/chargers"), enabled: open });
  const vehicle = vehicles.data?.items.find((v) => v.id === vehicleId);
  const options = (chargers.data ?? []).filter((c) => vehicle && c.station_id === (vehicle.current_station_id ?? vehicle.home_station_id) && vehicle.connector_types.includes(c.connector_type) && c.is_active);
  const create = useMutation({
    mutationFn: () =>
      api.post("/charging-schedules/reservations", { vehicle_id: vehicleId, charger_id: chargerId, start_at: emergency ? undefined : fromLocalInput(start), target_soc: Number(target), reason, emergency, preempt }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Manual reservation created", body: "Other vehicles were re-planned around it." });
      onClose();
    },
    onError: (e) => toast.error(e, "Reservation rejected"),
  });
  const valid = vehicleId && chargerId && reason.trim().length >= 5 && Number(target) > 0 && Number(target) <= 100;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Manual charging reservation"
      description="Creates a fixed override reservation. The deterministic scheduler plans every other vehicle around it."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
            Create reservation
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Vehicle" htmlFor="mr-vehicle" required>
          <Select id="mr-vehicle" value={vehicleId} onChange={(e) => { setVehicleId(Number(e.target.value)); setChargerId(""); }}>
            <option value="">Select…</option>
            {(vehicles.data?.items ?? []).filter((v) => v.availability !== "on_trip").map((v) => (
              <option key={v.id} value={v.id}>
                {v.registration} · {pct(v.current_soc)} · {v.vehicle_type}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Charger" htmlFor="mr-charger" required hint={vehicle && !options.length ? "No compatible charger at this depot" : undefined}>
          <Select id="mr-charger" value={chargerId} onChange={(e) => setChargerId(Number(e.target.value))} disabled={!vehicle}>
            <option value="">Select…</option>
            {options.map((c) => (
              <option key={c.id} value={c.id} disabled={c.status === "fault" || c.status === "maintenance"}>
                {c.code} · {num(c.max_power_kw)} kW · {c.status}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Start (fleet time)" htmlFor="mr-start">
          <Input id="mr-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} disabled={emergency} />
        </Field>
        <Field label="Target SoC %" htmlFor="mr-target">
          <Input id="mr-target" type="number" min={1} max={100} value={target} onChange={(e) => setTarget(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 space-y-3">
        <Field label="Reason" htmlFor="mr-reason" required>
          <Textarea id="mr-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the normal schedule is being overridden" />
        </Field>
        <Toggle checked={emergency} onChange={setEmergency} label="Emergency — start immediately (R8)" />
        <Toggle checked={preempt} onChange={setPreempt} label="Pre-empt an active session on this charger" />
      </div>
    </Modal>
  );
}

export default function Schedule() {
  const { can, station, stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "timeline";
  const setTab = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });
  const [view, setView] = useState<"active" | "baseline" | "rule_based">("active");
  const [selected, setSelected] = useState<Reservation | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [confirmMode, setConfirmMode] = useState<"baseline" | "rule_based" | null>(null);

  const schedule = useQuery({ queryKey: ["schedule", station], queryFn: () => api.get<ScheduleData>("/charging-schedules", { station_id: station }) });
  const chargers = useQuery({ queryKey: ["chargers"], queryFn: () => api.get<Charger[]>("/chargers") });
  const tariff = useQuery({ queryKey: ["tariffs", "strip48"], queryFn: () => api.get<{ strip: TariffSlot[] }>("/tariffs/calendar", { hours: 30 }) });
  const preview = useQuery({ queryKey: ["schedule", "preview", view], queryFn: () => api.get<PreviewData>("/charging-schedules/preview", { mode: view }), enabled: view !== "active", refetchInterval: false, staleTime: 60_000 });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: () => api.get<ChargingRequest[]>("/charging-schedules/decisions"), enabled: tab === "decisions" });
  const comparison = useQuery({ queryKey: ["comparison"], queryFn: () => api.get<Comparison>("/charging-schedules/comparison"), enabled: tab === "compare" && can("reports:view"), refetchInterval: false, staleTime: 60_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.get<ScheduleRun[]>("/charging-schedules/runs"), enabled: tab === "runs" });

  const invalidate = () => qc.invalidateQueries();
  const recalc = useMutation({
    mutationFn: () => api.post<{ run: ScheduleRun }>("/charging-schedules"),
    onSuccess: (r) => {
      invalidate();
      toast.push({ tone: "success", title: `Run #${r.run.id} complete in ${num(r.run.duration_ms)} ms`, body: `${r.run.reservations_created} new · ${r.run.reservations_kept} kept · ${r.run.reservations_superseded} superseded` });
    },
    onError: (e) => toast.error(e),
  });
  const setMode = useMutation({
    mutationFn: (mode: "baseline" | "rule_based") => api.put<{ run: ScheduleRun }>("/charging-schedules/mode", { mode }),
    onSuccess: (r, mode) => {
      invalidate();
      setConfirmMode(null);
      setView("active");
      toast.push({ tone: "success", title: mode === "rule_based" ? "Rule-based scheduler activated" : "Static baseline restored", body: `Run #${r.run.id}: ${r.run.reservations_created} reservations created, ${r.run.reservations_superseded} superseded.` });
    },
    onError: (e) => toast.error(e),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post(`/charging-schedules/runs/${id}/${approve ? "approve" : "reject"}`, approve ? undefined : { reason: "Rejected from schedule view" }),
    onSuccess: (_, v) => {
      invalidate();
      toast.push({ tone: "success", title: v.approve ? "Schedule approved" : "Schedule rejected" });
    },
    onError: (e) => toast.error(e),
  });

  const now = new Date(schedule.data?.as_of ?? Date.now());
  const start = new Date(now.getTime() - 2 * 3600_000);
  const stationNames = Object.fromEntries(stations.map((s) => [s.id, s.name]));
  const visibleChargers = (chargers.data ?? []).filter((c) => c.is_active && (!station || c.station_id === station));
  const timelineReservations: Reservation[] = useMemo(() => {
    if (view === "active") return schedule.data?.reservations ?? [];
    return (preview.data?.reservations ?? []).map((r, i) => ({ ...r, id: -(i + 1), run_id: null, request_id: null, override_reason: null, status: "preview" }) as Reservation);
  }, [view, schedule.data, preview.data]);

  if (schedule.isLoading || chargers.isLoading) return <LoadingBlock rows={10} />;
  if (schedule.error) return <ErrorState error={schedule.error} onRetry={() => schedule.refetch()} />;
  const d = schedule.data!;
  const run = d.latest_run;
  const metrics = view === "active" ? null : preview.data?.metrics;

  return (
    <div>
      <PageHeader
        title="Charging schedule"
        description="Deterministic charger reservations for the next 24 hours. Click any reservation to see the rules behind it or to override it."
        actions={
          <>
            <Badge tone={d.mode === "rule_based" ? "good" : "warn"} icon={d.mode === "rule_based" ? <ShieldCheck className="h-3 w-3" /> : <Scale className="h-3 w-3" />}>
              {d.mode === "rule_based" ? "Rule-based scheduler" : "Static baseline"}
            </Badge>
            {can("schedule:override") && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setManualOpen(true)}>
                Manual reservation
              </Button>
            )}
            {can("schedule:run") && (
              <Button icon={<RefreshCw className="h-4 w-4" />} loading={recalc.isPending} onClick={() => recalc.mutate()}>
                Recalculate
              </Button>
            )}
            {can("schedule:approve") &&
              (d.mode === "baseline" ? (
                <Button variant="primary" icon={<ShieldCheck className="h-4 w-4" />} onClick={() => setConfirmMode("rule_based")}>
                  Activate rule-based scheduler
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => setConfirmMode("baseline")}>
                  Revert to baseline
                </Button>
              ))}
          </>
        }
      />

      {d.pending_run && (
        <div className="mb-4">
          <Callout tone="warn" title={`Schedule run #${d.pending_run.id} is awaiting approval`}>
            {d.pending_run.reservations_created} proposed reservations ({kwh(d.pending_run.planned_energy_kwh, 0)}, est. {money(d.pending_run.planned_cost)}). The previous plan stays in force until approved.
            {can("schedule:approve") && (
              <span className="mt-2 flex gap-2">
                <Button size="sm" variant="primary" icon={<CheckCircle2 className="h-3.5 w-3.5" />} loading={decide.isPending} onClick={() => decide.mutate({ id: d.pending_run!.id, approve: true })}>
                  Approve
                </Button>
                <Button size="sm" icon={<XCircle className="h-3.5 w-3.5" />} onClick={() => decide.mutate({ id: d.pending_run!.id, approve: false })}>
                  Reject
                </Button>
              </span>
            )}
          </Callout>
        </div>
      )}

      {run && (
        <div className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Last run", `#${run.id} · ${time(run.created_at)}`],
            ["Vehicles needing charge", num(run.vehicles_needing_charge)],
            ["Reservations", `${num(run.reservations_created + run.reservations_kept)}`],
            ["At risk", num(run.at_risk_count)],
            ["Conflicts prevented", num(run.conflicts_prevented)],
            ["Recalculation time", `${num(run.duration_ms)} ms`],
          ].map(([k, v]) => (
            <div key={k} className="bg-surface px-3 py-2.5">
              <div className="eyebrow">{k}</div>
              <div className="num mt-0.5 text-sm font-medium">{v}</div>
            </div>
          ))}
        </div>
      )}

      <Tabs<Tab>
        label="Schedule views"
        value={tab}
        onChange={setTab}
        items={[
          { value: "timeline", label: "Timeline" },
          { value: "decisions", label: "Decisions & rules" },
          ...(can("reports:view") ? [{ value: "compare" as Tab, label: "Baseline vs rule-based" }] : []),
          { value: "runs", label: "Run history" },
        ]}
      />

      <div className="mt-4">
        {tab === "timeline" && (
          <Panel
            eyebrow={view === "active" ? "Active reservations" : `Preview · ${view === "baseline" ? "static baseline" : "rule-based"} (not applied)`}
            title={view === "active" ? `${d.reservations.length} reservations` : `${preview.data?.reservations.length ?? "…"} preview reservations`}
            actions={
              <div className="flex items-center gap-1 rounded border border-line bg-paper p-0.5 text-xs" role="radiogroup" aria-label="Timeline source">
                {(["active", "baseline", "rule_based"] as const).map((v) => (
                  <button key={v} role="radio" aria-checked={view === v} onClick={() => setView(v)} className={cx("rounded px-2.5 py-1", view === v ? "bg-surface font-medium shadow-sm ring-1 ring-line" : "text-ink-3 hover:text-ink")}>
                    {v === "active" ? "Active" : v === "baseline" ? "Preview baseline" : "Preview rule-based"}
                  </button>
                ))}
              </div>
            }
          >
            {metrics && (
              <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
                <span>
                  Readiness <strong className="num">{pct(metrics.projected_readiness_pct, 1)}</strong>
                </span>
                <span>
                  Cost <strong className="num">{money(metrics.planned_cost)}</strong>
                </span>
                <span>
                  Peak share <strong className="num">{pct(metrics.peak_share_pct)}</strong>
                </span>
                <span>
                  At risk <strong className="num">{metrics.at_risk}</strong>
                </span>
              </div>
            )}
            {view !== "active" && preview.isLoading ? (
              <LoadingBlock rows={6} />
            ) : visibleChargers.length === 0 ? (
              <EmptyState title="No chargers configured" />
            ) : (
              <ScheduleTimeline chargers={visibleChargers} reservations={timelineReservations} strip={tariff.data?.strip ?? []} start={start} hours={26} now={now} onSelect={(r) => (r.id > 0 ? setSelected(r) : setSelected({ ...r }))} stationNames={stationNames} />
            )}
          </Panel>
        )}

        {tab === "decisions" && (
          <Panel eyebrow="Charging requests" title="Per-vehicle decisions" bodyClassName="p-0" actions={<span className="text-xs text-ink-3">{decisions.data?.length ?? 0} open</span>}>
            {decisions.isLoading ? (
              <div className="p-4">
                <LoadingBlock />
              </div>
            ) : decisions.error ? (
              <div className="p-4">
                <ErrorState error={decisions.error} />
              </div>
            ) : !decisions.data?.length ? (
              <EmptyState title="No vehicles currently need charging" icon={<ListChecks className="h-6 w-6" />} />
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[900px]">
                  <thead>
                    <tr>
                      <th>Vehicle</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>SoC → target</th>
                      <th>Deadline</th>
                      <th>Rules</th>
                      <th className="w-[42%]">Explanation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.data.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/vehicles/${r.vehicle_id}`} className="num font-medium hover:underline">
                            {r.vehicle}
                          </Link>
                          {r.trip_code && <div className="font-mono text-2xs text-ink-3">{r.trip_code}</div>}
                        </td>
                        <td>
                          <PriorityBadge level={r.priority_level} />
                        </td>
                        <td>
                          <Badge tone={r.status === "at_risk" ? "critical" : r.status === "unscheduled" ? "warn" : "info"}>{humanize(r.status)}</Badge>
                          {r.flexible && <div className="mt-0.5 text-2xs text-ink-3">flexible</div>}
                        </td>
                        <td className="num whitespace-nowrap">
                          {pct(r.current_soc)} → {pct(r.target_soc)}
                          {r.projected_soc !== null && <div className="text-2xs text-ink-3">proj. {pct(r.projected_soc)}</div>}
                        </td>
                        <td className="num whitespace-nowrap">{r.deadline_at ? dayTime(r.deadline_at) : "—"}</td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            {r.rules.map((c) => (
                              <RuleChip key={c} code={c} />
                            ))}
                          </div>
                        </td>
                        <td className="text-xs leading-relaxed text-ink-2">{r.explanation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}

        {tab === "compare" && (comparison.isLoading ? <LoadingBlock rows={8} /> : comparison.error ? <ErrorState error={comparison.error} onRetry={() => comparison.refetch()} /> : comparison.data ? <ComparisonView data={comparison.data} /> : null)}

        {tab === "runs" && (
          <Panel eyebrow="Audit trail" title="Recent schedule runs" bodyClassName="p-0">
            {runs.isLoading ? (
              <div className="p-4">
                <LoadingBlock />
              </div>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[860px]">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Time</th>
                      <th>Mode</th>
                      <th>Trigger</th>
                      <th className="text-right">New</th>
                      <th className="text-right">Kept</th>
                      <th className="text-right">Superseded</th>
                      <th className="text-right">At risk</th>
                      <th className="text-right">Duration</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(runs.data ?? []).map((r) => (
                      <tr key={r.id}>
                        <td className="num">#{r.id}</td>
                        <td className="num whitespace-nowrap">{dayTime(r.created_at)}</td>
                        <td>{r.mode === "rule_based" ? "Rule-based" : "Baseline"}</td>
                        <td className="max-w-[280px] truncate text-xs text-ink-2" title={r.trigger}>
                          {r.trigger}
                        </td>
                        <td className="num text-right">{r.reservations_created}</td>
                        <td className="num text-right">{r.reservations_kept}</td>
                        <td className="num text-right">{r.reservations_superseded}</td>
                        <td className="num text-right">{r.at_risk_count}</td>
                        <td className="num text-right">{num(r.duration_ms)} ms</td>
                        <td>
                          <Badge tone={r.status === "pending_approval" ? "warn" : r.status === "rejected" ? "neutral" : "good"}>{humanize(r.status)}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}
      </div>

      {selected && <ReservationDrawer reservation={selected} onClose={() => setSelected(null)} />}
      <ManualReservation open={manualOpen} onClose={() => setManualOpen(false)} />
      <Modal
        open={confirmMode !== null}
        onClose={() => setConfirmMode(null)}
        title={confirmMode === "rule_based" ? "Activate the rule-based scheduler?" : "Revert to the static baseline?"}
        description="The change is recorded in the audit log and a new schedule run starts immediately."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmMode(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={setMode.isPending} onClick={() => confirmMode && setMode.mutate(confirmMode)}>
              {confirmMode === "rule_based" ? "Activate" : "Revert"}
            </Button>
          </>
        }
      >
        {confirmMode === "rule_based" ? (
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
            <li>Vehicles are prioritised P1–P5 (emergency, urgent departure, low SoC, flexible, no trip).</li>
            <li>Flexible charging moves into the cheapest window that still completes before departure.</li>
            <li>Charger capacity, connector compatibility and site load limits are enforced.</li>
            <li>Sessions already in progress and manual overrides are kept.</li>
          </ul>
        ) : (
          <p className="text-sm text-ink-2">Future reservations will be re-planned first-come-first-served, charging each vehicle to its maximum SoC as soon as possible.</p>
        )}
        {setMode.error instanceof ApiError && <p className="mt-3 text-sm text-critical-ink">{setMode.error.message}</p>}
      </Modal>
    </div>
  );
}
