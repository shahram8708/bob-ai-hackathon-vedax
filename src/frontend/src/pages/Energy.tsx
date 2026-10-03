import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api/client";
import type { ReportData } from "@/api/types";
import { AXIS, ChartTip, GRID } from "@/components/charts";
import { TariffSwatch } from "@/components/status";
import { Badge, ErrorState, Kpi, LoadingBlock, PageHeader, Panel, SimulatedTag, Tabs, cx } from "@/components/ui";
import { dayTime, kwh, money, num, pct, time, TARIFF_COLORS, TARIFF_LABEL } from "@/lib/format";

interface EnergyData {
  as_of: string;
  currency: string;
  cost: ReportData & { summary: { energy_kwh: number; energy_cost: number; demand_charge_estimate_monthly: number; demand_by_station: { station: string; peak_kw: number; demand_charge_estimate: number }[]; solar_offset_estimate: number; storage_offset_estimate: number } };
  trend: ReportData;
  by_station: ReportData;
  load_profile: { at: string; planned_kw: number | null; measured_kw: number | null; rate: number; kind: string; solar_kw: number }[];
  v2g: {
    enabled: boolean;
    peak_window?: { start: string; end: string };
    opportunities: { vehicle_id: number; registration: string; current_soc: number; soc_floor: number; window_start: string; window_end: string; exportable_kwh: number; power_kw: number; estimated_value: number; rule: string }[];
    total_exportable_kwh: number;
    total_value: number;
    note?: string;
  };
}

export default function Energy() {
  const [days, setDays] = useState<"7" | "14" | "30">("14");
  const q = useQuery({ queryKey: ["dashboard", "energy", days], queryFn: () => api.get<EnergyData>("/dashboard/energy", { days }) });
  if (q.isLoading) return <LoadingBlock rows={10} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const s = d.cost.summary;
  const peakRow = d.cost.rows.find((r) => r.period === "Peak");
  const profile = d.load_profile.map((p) => ({ ...p, label: time(p.at) }));
  const profileTicks = profile.filter((p) => p.label.endsWith(":00") && Number(p.label.slice(0, 2)) % 3 === 0).map((p) => p.at);
  const nowIndex = profile.findIndex((p) => new Date(p.at).getTime() > new Date(d.as_of).getTime()) - 1;
  const trendKinds = ["off_peak", "shoulder", "peak", "custom"].filter((k) => d.trend.series.some((r) => Number(r[`${k}_kwh`] ?? 0) > 0));

  return (
    <div>
      <PageHeader
        title="Energy & cost"
        description="Charging energy priced at the applicable tariff period, with peak-period exposure and modelled demand, solar and storage effects."
        actions={
          <>
            <SimulatedTag />
            <Tabs
              label="Period"
              value={days}
              onChange={setDays}
              items={[
                { value: "7", label: "7 days" },
                { value: "14", label: "14 days" },
                { value: "30", label: "30 days" },
              ]}
            />
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Energy charged" value={num(s.energy_kwh)} sub="kWh in period" />
        <Kpi label="Energy cost" value={money(s.energy_cost)} sub={s.energy_kwh ? `${money(s.energy_cost / s.energy_kwh, 2)}/kWh avg` : undefined} />
        <Kpi label="Peak-period share" value={pct(Number(peakRow?.share_pct ?? 0), 1)} tone={Number(peakRow?.share_pct ?? 0) > 20 ? "warn" : "good"} sub={`${kwh(Number(peakRow?.energy_kwh ?? 0), 0)} in peak`} />
        <Kpi label="Demand charge" value={money(s.demand_charge_estimate_monthly)} sub="monthly estimate" />
        <Kpi label="Solar offset" value={money(s.solar_offset_estimate)} sub="modelled clear-sky" />
        <Kpi label="Storage offset" value={money(s.storage_offset_estimate)} sub="modelled peak shaving" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Panel eyebrow="Depot load · past 6 h and next 24 h" title="Charging load profile" className="xl:col-span-2">
          <div className="h-[260px]" role="img" aria-label="Planned and measured charging load in kilowatts over time">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={profile} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="at" ticks={profileTicks} tickFormatter={(v: string) => time(v)} tick={AXIS} tickLine={false} axisLine={{ stroke: "#CFCAC0" }} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} unit=" kW" width={64} />
                <Tooltip content={<ChartTip formatter={(v) => `${num(v)} kW`} labelFormatter={(l) => dayTime(String(l))} />} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                <Area type="stepAfter" dataKey="planned_kw" name="Scheduled load" stroke="#2A78D6" strokeWidth={2} fill="#2A78D6" fillOpacity={0.12} connectNulls={false} isAnimationActive={false} />
                <Line type="stepAfter" dataKey="measured_kw" name="Measured (telemetry)" stroke="#16181D" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="solar_kw" name="Solar available" stroke="#1BAF7A" strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="ml-[56px] mr-2 mt-1 flex h-2 overflow-hidden rounded-[2px]" aria-hidden>
            {profile.map((p, i) => (
              <div key={p.at} className={cx("h-full flex-1", i === nowIndex && "outline outline-2 outline-ink")} style={{ background: TARIFF_COLORS[p.kind] }} />
            ))}
          </div>
          <div className="ml-[56px] mt-2 flex flex-wrap gap-3">
            {["off_peak", "shoulder", "peak"].map((k) => (
              <TariffSwatch key={k} kind={k} />
            ))}
            <span className="text-xs text-ink-3">· tariff period under each interval</span>
          </div>
        </Panel>

        <Panel eyebrow="Tariff periods" title="Cost by tariff period" bodyClassName="p-0">
          <table className="table-base">
            <thead>
              <tr>
                <th>Period</th>
                <th className="text-right">kWh</th>
                <th className="text-right">Share</th>
                <th className="text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {d.cost.rows.map((r) => {
                const kind = Object.entries(TARIFF_LABEL).find(([, l]) => l === r.period)?.[0] ?? "custom";
                return (
                  <tr key={String(r.period)}>
                    <td>
                      <TariffSwatch kind={kind} label={String(r.period)} />
                    </td>
                    <td className="num text-right">{num(Number(r.energy_kwh))}</td>
                    <td className="num text-right">{pct(Number(r.share_pct), 1)}</td>
                    <td className="num text-right">{money(Number(r.energy_cost))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="space-y-1.5 border-t border-line px-4 py-3 text-xs text-ink-2">
            <div className="eyebrow mb-1">Demand charge by depot (estimate)</div>
            {s.demand_by_station.map((x) => (
              <div key={x.station} className="flex justify-between">
                <span>{x.station}</span>
                <span className="num">
                  {num(x.peak_kw)} kW peak · {money(x.demand_charge_estimate)}
                </span>
              </div>
            ))}
            <p className="pt-1 text-ink-3">Energy cost and demand-charge estimates are reported separately, as configured in the tariff table.</p>
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Panel eyebrow="Historical trend" title="Daily charging energy by tariff period" className="xl:col-span-2">
          <div className="h-[240px]" role="img" aria-label="Daily energy stacked by tariff period">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.trend.series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barCategoryGap="22%">
                <CartesianGrid {...GRID} />
                <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: "#CFCAC0" }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} unit=" kWh" width={72} />
                <Tooltip cursor={{ fill: "#EEEBE4" }} content={<ChartTip formatter={(v) => `${num(v)} kWh`} />} />
                <Legend iconType="square" iconSize={9} wrapperStyle={{ fontSize: 12 }} />
                {trendKinds.map((k, i) => (
                  <Bar key={k} dataKey={`${k}_kwh`} name={TARIFF_LABEL[k]} stackId="d" fill={TARIFF_COLORS[k]} stroke="#FCFCFB" strokeWidth={1} radius={i === trendKinds.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel eyebrow="Consumption" title="Energy by depot" bodyClassName="p-0">
          <table className="table-base">
            <thead>
              <tr>
                <th>Depot</th>
                <th className="text-right">Sessions</th>
                <th className="text-right">kWh</th>
                <th className="text-right">Avg price</th>
              </tr>
            </thead>
            <tbody>
              {d.by_station.rows.map((r) => (
                <tr key={String(r.name)}>
                  <td>{String(r.name)}</td>
                  <td className="num text-right">{num(Number(r.sessions))}</td>
                  <td className="num text-right">{num(Number(r.energy_kwh))}</td>
                  <td className="num text-right">{money(Number(r.avg_cost_per_kwh), 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-line px-4 py-3 text-xs">
            <Link to="/reports" className="font-medium text-brand hover:underline">
              Detailed reports & CSV export →
            </Link>
          </div>
        </Panel>
      </div>

      <div className="mt-4">
        <Panel
          eyebrow="Vehicle-to-grid rules · advisory"
          title={d.v2g.enabled ? `V2G export opportunities${d.v2g.peak_window ? ` for peak ${time(d.v2g.peak_window.start)}–${time(d.v2g.peak_window.end)}` : ""}` : "V2G rules disabled"}
          actions={d.v2g.enabled && <Badge tone="info">{kwh(d.v2g.total_exportable_kwh, 0)} · {money(d.v2g.total_value)}</Badge>}
          bodyClassName="p-0"
        >
          {!d.v2g.enabled ? (
            <p className="px-4 py-5 text-sm text-ink-3">Enable V2G rules in Rules & settings to evaluate export opportunities.</p>
          ) : d.v2g.opportunities.length === 0 ? (
            <p className="px-4 py-5 text-sm text-ink-3">{d.v2g.note ?? "No vehicle currently has surplus SoC, enough dwell time across the peak and a bidirectional charger."}</p>
          ) : (
            <div className="scroll-thin overflow-x-auto">
              <table className="table-base min-w-[900px]">
                <thead>
                  <tr>
                    <th>Vehicle</th>
                    <th className="text-right">SoC</th>
                    <th className="text-right">Floor</th>
                    <th>Window</th>
                    <th className="text-right">Exportable</th>
                    <th className="text-right">Value</th>
                    <th>Rule evaluation</th>
                  </tr>
                </thead>
                <tbody>
                  {d.v2g.opportunities.map((o) => (
                    <tr key={o.vehicle_id}>
                      <td>
                        <Link to={`/vehicles/${o.vehicle_id}`} className="num font-medium hover:underline">
                          {o.registration}
                        </Link>
                      </td>
                      <td className="num text-right">{pct(o.current_soc)}</td>
                      <td className="num text-right">{pct(o.soc_floor)}</td>
                      <td className="num whitespace-nowrap">
                        {dayTime(o.window_start)} – {time(o.window_end)}
                      </td>
                      <td className="num text-right">{kwh(o.exportable_kwh)}</td>
                      <td className="num text-right">{money(o.estimated_value)}</td>
                      <td className="text-xs text-ink-2">{o.rule}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-line px-4 py-2.5 text-xs text-ink-3">Recommendations only — ChargeOpt never discharges a vehicle automatically, and the SoC floor always keeps the next departure requirement plus a buffer.</p>
        </Panel>
      </div>
    </div>
  );
}
