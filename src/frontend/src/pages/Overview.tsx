import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BatteryCharging, CalendarClock, FastForward, Pause, Play, PlugZap, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import type { TariffSlot } from "@/api/types";
import { SocHistogram, TariffStrip } from "@/components/charts";
import { ChargerStatusBadge, SeverityBadge } from "@/components/status";
import { Badge, Button, Callout, ErrorState, Kpi, LoadingBlock, Panel, SimulatedTag, SocBar, cx } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, humanize, kwh, money, num, pct, relative, time } from "@/lib/format";

interface ChargerView {
  id: number;
  code: string;
  station_id: number;
  station_code: string;
  connector_type: string;
  max_power_kw: number;
  status: string;
  status_note: string;
  ocpp_connected: boolean;
  session: { id: number; vehicle_id: number; registration: string; soc: number; target_soc: number; power_kw: number; energy_kwh: number; cost: number; ends_at: string | null; source: string } | null;
  next_reservation: { vehicle_id: number; start_at: string; end_at: string } | null;
}

interface OverviewData {
  as_of: string;
  currency: string;
  kpis: Record<string, number>;
  soc_distribution: { range: string; count: number }[];
  charger_status: Record<string, number>;
  chargers: ChargerView[];
  at_risk: { vehicle_id: number; registration: string; trip_code: string; departure_at: string; current_soc: number; required_soc: number; projected_soc: number | null; reason: string }[];
  recent_alerts: { id: number; severity: string; title: string; created_at: string; status: string }[];
  queue: { vehicle_id: number; registration: string; status: string; priority_level: number; target_soc: number; current_soc: number; deadline_at: string | null }[];
  tariff: { current: { kind: string; name: string; rate: number }; next_change: { at: string; kind: string; rate: number } | null; next_peak_at: string | null; strip: TariffSlot[] };
  scheduler: { mode: string; last_run: { id: number; created_at: string; trigger: string; duration_ms: number; at_risk: number; conflicts_prevented: number } | null };
  simulation: { enabled: boolean; clock_offset_seconds: number };
}

function SimulationBar({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const toggle = useMutation({
    mutationFn: (v: boolean) => api.put("/simulation", { enabled: v }),
    onSuccess: (_, v) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: v ? "Telemetry simulation resumed" : "Telemetry simulation paused" });
    },
    onError: (e) => toast.error(e),
  });
  const advance = useMutation({
    mutationFn: (minutes: number) => api.post<{ from: string; to: string }>("/simulation/advance", { minutes }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Simulation clock advanced", body: `${time(r.from)} → ${time(r.to)}` });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded border border-dashed border-line-strong bg-surface/60 px-3 py-2">
      <span className="eyebrow">Charger telemetry simulation</span>
      <Badge tone={enabled ? "good" : "neutral"}>{enabled ? "Running" : "Paused"}</Badge>
      <div className="ml-auto flex flex-wrap gap-2">
        <Button size="sm" icon={enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} loading={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
          {enabled ? "Pause" : "Resume"}
        </Button>
        {[15, 60].map((m) => (
          <Button key={m} size="sm" disabled={!enabled} loading={advance.isPending && advance.variables === m} icon={<FastForward className="h-3.5 w-3.5" />} onClick={() => advance.mutate(m)}>
            +{m} min
          </Button>
        ))}
      </div>
    </div>
  );
}

function ChargerTile({ c }: { c: ChargerView }) {
  const s = c.session;
  return (
    <div className={cx("rounded border bg-surface p-3", c.status === "fault" ? "border-critical/40" : c.status === "charging" ? "border-brand/30" : "border-line")}>
      <div className="flex items-center justify-between gap-2">
        <span className="num text-sm font-medium">{c.code}</span>
        <ChargerStatusBadge value={c.status} />
      </div>
      <div className="mt-0.5 font-mono text-2xs text-ink-3">
        {c.connector_type} · {num(c.max_power_kw)} kW{c.ocpp_connected ? " · OCPP" : ""}
      </div>
      <div className="mt-2.5 min-h-[38px]">
        {s ? (
          <>
            <div className="flex items-center justify-between text-xs">
              <Link to={`/vehicles/${s.vehicle_id}`} className="font-medium text-ink hover:underline">
                {s.registration}
              </Link>
              <span className="num text-ink-2">
                {num(s.power_kw)} kW · {s.ends_at ? `→ ${time(s.ends_at)}` : "open"}
              </span>
            </div>
            <div className="mt-1">
              <SocBar soc={s.soc} target={s.target_soc} size="sm" />
            </div>
          </>
        ) : c.status === "fault" || c.status === "maintenance" ? (
          <p className="line-clamp-2 text-xs text-ink-3">{c.status_note || humanize(c.status)}</p>
        ) : c.next_reservation ? (
          <p className="text-xs text-ink-2">
            Next: <span className="num">{time(c.next_reservation.start_at)}–{time(c.next_reservation.end_at)}</span>
          </p>
        ) : (
          <p className="text-xs text-ink-3">No reservation in horizon</p>
        )}
      </div>
    </div>
  );
}

export default function Overview() {
  const { station, can, stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["dashboard", "overview", station],
    queryFn: () => api.get<OverviewData>("/dashboard/overview", { station_id: station }),
    refetchInterval: 15_000,
  });
  const recalc = useMutation({
    mutationFn: () => api.post<{ run: { id: number; duration_ms: number; reservations_created: number } }>("/charging-schedules"),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: `Schedule recalculated (run #${r.run.id})`, body: `${r.run.reservations_created} new reservations in ${num(r.run.duration_ms)} ms` });
    },
    onError: (e) => toast.error(e),
  });

  if (q.isLoading) return <LoadingBlock rows={8} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const k = d.kpis;
  const stationName = stations.find((s) => s.id === station)?.name;
  const byStation = d.chargers.reduce<Record<string, ChargerView[]>>((acc, c) => {
    (acc[c.station_code] ??= []).push(c);
    return acc;
  }, {});

  return (
    <div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="eyebrow">{stationName ?? "All depots"}</div>
          <h1 className="text-[1.375rem] font-semibold">Fleet overview</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink-2">
            Readiness, charger status and energy at a glance — updated live.
            <SimulatedTag />
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/schedule" className="inline-flex h-9 items-center gap-1.5 rounded border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken">
            <CalendarClock className="h-4 w-4" aria-hidden /> Open schedule
          </Link>
          {can("schedule:run") && (
            <Button variant="primary" icon={<RefreshCw className="h-4 w-4" />} loading={recalc.isPending} onClick={() => recalc.mutate()}>
              Recalculate
            </Button>
          )}
        </div>
      </div>

      {can("simulation:control") && <SimulationBar enabled={d.simulation.enabled} />}

      {d.scheduler.mode === "baseline" && (
        <div className="mb-4">
          <Callout tone="warn" title="Static baseline schedule is active">
            Vehicles are charged first-come-first-served to their maximum SoC as soon as they plug in, with no tariff, priority or site-load coordination.{" "}
            <Link to="/schedule" className="font-medium underline">
              Compare and activate the rule-based scheduler
            </Link>
            .
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Fleet" value={num(k.total_vehicles)} sub={`${num(k.vehicles_on_trip)} on trip`} />
        <Kpi label="Ready" value={num(k.ready_vehicles)} tone="good" sub="meet next requirement" />
        <Kpi label="Need charge" value={num(k.vehicles_requiring_charge)} tone="warn" sub="open requests" />
        <Kpi label="Charging" value={num(k.vehicles_charging)} tone="brand" sub={`${num(k.current_power_kw)} kW now`} />
        <Kpi label="At risk" value={num(k.vehicles_at_risk)} tone={k.vehicles_at_risk ? "critical" : undefined} sub={`readiness ${pct(k.readiness_pct)}`} />
        <Kpi label="Chargers free" value={`${num(k.available_chargers)}/${num(k.total_chargers)}`} sub={`${num(k.fault_chargers)} fault · ${num(k.maintenance_chargers)} maint.`} />
        <Kpi label="Energy today" value={num(k.energy_today_kwh)} sub={`kWh · ${money(k.cost_today)}`} />
        <Kpi label="Reservations" value={num(k.active_reservations)} sub={`${kwh(k.scheduled_energy_kwh, 0)} planned`} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Panel
            id="risk"
            eyebrow="Readiness"
            title={`Departures at risk (${d.at_risk.length})`}
            actions={
              <Link to="/vehicles?readiness=at_risk" className="text-xs font-medium text-brand hover:underline">
                View vehicles
              </Link>
            }
            bodyClassName="p-0"
          >
            {d.at_risk.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-3">All departures in the readiness window are projected to meet their required SoC.</p>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[640px]">
                  <thead>
                    <tr>
                      <th>Vehicle</th>
                      <th>Departure</th>
                      <th className="w-[200px]">SoC vs required</th>
                      <th>Projected</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.at_risk.slice(0, 8).map((r) => (
                      <tr key={r.vehicle_id}>
                        <td>
                          <Link to={`/vehicles/${r.vehicle_id}`} className="num font-medium hover:underline">
                            {r.registration}
                          </Link>
                          <div className="font-mono text-2xs text-ink-3">{r.trip_code}</div>
                        </td>
                        <td>
                          <div className="num">{time(r.departure_at)}</div>
                          <div className="text-2xs text-ink-3">{relative(r.departure_at)}</div>
                        </td>
                        <td>
                          <SocBar soc={r.current_soc} required={r.required_soc} />
                        </td>
                        <td className="num">{pct(r.projected_soc ?? r.current_soc)}</td>
                        <td className="max-w-[260px] text-xs text-ink-2">
                          <span className="line-clamp-2" title={r.reason}>
                            {r.reason.split(". ").slice(-2).join(". ")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel
            id="chargers"
            eyebrow="Charging operations"
            title="Charger board"
            actions={
              <div className="hidden gap-1.5 sm:flex">
                {Object.entries(d.charger_status)
                  .filter(([, n]) => n > 0)
                  .map(([s, n]) => (
                    <span key={s} className="flex items-center gap-1 text-xs text-ink-3">
                      <ChargerStatusBadge value={s} />
                      <span className="num">{n}</span>
                    </span>
                  ))}
              </div>
            }
          >
            <div className="space-y-4">
              {Object.entries(byStation).map(([code, list]) => (
                <div key={code}>
                  <div className="eyebrow mb-2">{stations.find((s) => s.code === code)?.name ?? code}</div>
                  <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                    {list.map((c) => (
                      <ChargerTile key={c.id} c={c} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel id="tariff" eyebrow="Tariff calendar · next 24 h" title={`${d.tariff.current.name} · ${money(d.tariff.current.rate, 2)}/kWh`}>
            <div className="pt-4">
              <TariffStrip strip={d.tariff.strip} />
            </div>
            <p className="mt-3 text-xs text-ink-2">
              {d.tariff.next_change && (
                <>
                  Changes to <strong>{humanize(d.tariff.next_change.kind)}</strong> at <span className="num">{time(d.tariff.next_change.at)}</span> ({money(d.tariff.next_change.rate, 2)}/kWh).{" "}
                </>
              )}
              {d.tariff.next_peak_at && <>Next peak {relative(d.tariff.next_peak_at)}.</>}
            </p>
          </Panel>

          <Panel id="scheduler" eyebrow="Scheduler" title={d.scheduler.mode === "rule_based" ? "Rule-based scheduler active" : "Static baseline active"}>
            {d.scheduler.last_run ? (
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="eyebrow">Last run</dt>
                  <dd className="num">
                    #{d.scheduler.last_run.id} · {time(d.scheduler.last_run.created_at)}
                  </dd>
                </div>
                <div>
                  <dt className="eyebrow">Compute time</dt>
                  <dd className="num">{num(d.scheduler.last_run.duration_ms)} ms</dd>
                </div>
                <div>
                  <dt className="eyebrow">Conflicts prevented</dt>
                  <dd className="num">{num(d.scheduler.last_run.conflicts_prevented)}</dd>
                </div>
                <div>
                  <dt className="eyebrow">At risk</dt>
                  <dd className="num">{num(d.scheduler.last_run.at_risk)}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="eyebrow">Trigger</dt>
                  <dd className="truncate text-xs text-ink-2" title={d.scheduler.last_run.trigger}>
                    {d.scheduler.last_run.trigger}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-ink-3">No schedule has been generated yet.</p>
            )}
          </Panel>

          <Panel id="soc" eyebrow="Fleet" title="State-of-charge distribution">
            <SocHistogram data={d.soc_distribution} />
          </Panel>

          <Panel
            id="alerts"
            eyebrow="Exceptions"
            title={`Open alerts (${k.open_alerts})`}
            actions={
              <Link to="/alerts" className="text-xs font-medium text-brand hover:underline">
                All alerts
              </Link>
            }
            bodyClassName="p-0"
          >
            {d.recent_alerts.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-3">No open alerts.</p>
            ) : (
              <ul className="divide-y divide-line">
                {d.recent_alerts.map((a) => (
                  <li key={a.id} className="flex items-start gap-2.5 px-4 py-2.5">
                    <SeverityBadge value={a.severity} />
                    <div className="min-w-0">
                      <p className="text-sm leading-snug">{a.title}</p>
                      <p className="text-2xs text-ink-3">
                        {dayTime(a.created_at)} · {humanize(a.status)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {d.queue.length > 0 && (
            <Panel id="queue" eyebrow="Queue" title="Waiting for a charger" bodyClassName="p-0">
              <ul className="divide-y divide-line">
                {d.queue.map((r) => (
                  <li key={r.vehicle_id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                    <Link to={`/vehicles/${r.vehicle_id}`} className="num font-medium hover:underline">
                      {r.registration}
                    </Link>
                    <span className="flex items-center gap-2 text-xs text-ink-3">
                      <PlugZap className="h-3.5 w-3.5" aria-hidden /> P{r.priority_level} · {pct(r.current_soc)} → {pct(r.target_soc)}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
      <p className="mt-6 flex items-center gap-1.5 text-xs text-ink-3">
        <BatteryCharging className="h-3.5 w-3.5" aria-hidden /> As of {dayTime(d.as_of)}. Costs use the configured tariff table; energy is simulated charger telemetry unless a charger reports via OCPP.
      </p>
    </div>
  );
}
