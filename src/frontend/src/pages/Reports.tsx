import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download, FileSpreadsheet } from "lucide-react";
import { api } from "@/api/client";
import type { ReportData } from "@/api/types";
import { AXIS, ChartTip, GRID } from "@/components/charts";
import { EmptyState, ErrorState, Field, Input, LoadingBlock, PageHeader, Panel, SimulatedTag, cx } from "@/components/ui";
import { dateTime, humanize, money, num, pct, TARIFF_COLORS } from "@/lib/format";

interface Metrics {
  window_days: number;
  departures: number;
  departures_meeting_soc_pct: number | null;
  missed_requirements: number;
  lower_cost_energy_pct: number | null;
  peak_energy_pct: number | null;
  charger_utilization_pct: number;
  conflicts_prevented_latest_run: number;
  conflicts_prevented_total: number;
  energy_cost_per_vehicle: number;
  energy_cost_per_trip: number | null;
  manual_interventions: number;
  recalc_ms_median: number | null;
  recalc_ms_p95: number | null;
  unresolved_alerts: number;
}

function isoDay(d: Date) {
  return d.toISOString().slice(0, 10);
}

function cell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? num(v) : num(v, 2);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return dateTime(v);
  return String(v);
}

function ReportChart({ report }: { report: ReportData }) {
  if (report.key === "readiness") {
    return (
      <div className="h-[220px]" role="img" aria-label="Daily readiness percentage">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={report.series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={AXIS} tickLine={false} tickFormatter={(v: string) => v.slice(5)} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} domain={[50, 100]} unit="%" width={48} />
            <Tooltip content={<ChartTip formatter={(v) => pct(v, 1)} />} />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            <Line dataKey="met_pct" name="Departures meeting SoC" stroke="#2A78D6" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            <Line dataKey="projected" name="Avg projected readiness" stroke="#16181D" strokeWidth={2} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (report.key === "peak-distribution") {
    const kinds = ["off_peak", "shoulder", "peak"];
    return (
      <div className="h-[220px]" role="img" aria-label="Daily energy by tariff period">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={report.series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={AXIS} tickLine={false} tickFormatter={(v: string) => v.slice(5)} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} />
            <Tooltip cursor={{ fill: "#EEEBE4" }} content={<ChartTip formatter={(v) => `${num(v)} kWh`} />} />
            <Legend iconType="square" iconSize={9} wrapperStyle={{ fontSize: 12 }} />
            {kinds.map((k, i) => (
              <Bar key={k} dataKey={`${k}_kwh`} name={humanize(k).replace("Off peak", "Off-peak")} stackId="p" fill={TARIFF_COLORS[k]} stroke="#FCFCFB" strokeWidth={1} radius={i === kinds.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (report.key.startsWith("summary-")) {
    return (
      <div className="h-[220px]" role="img" aria-label="Energy per period">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={report.series} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="period" tick={AXIS} tickLine={false} tickFormatter={(v: string) => v.replace("Week of ", "").slice(0, 10)} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={64} />
            <Tooltip cursor={{ fill: "#EEEBE4" }} content={<ChartTip formatter={(v) => `${num(v)} kWh`} />} />
            <Bar dataKey="energy_kwh" name="Energy" fill="#2A78D6" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  return null;
}

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const key = params.get("r") ?? "summary-daily";
  const today = new Date();
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 6 * 86400000)));
  const [end, setEnd] = useState(isoDay(today));
  const catalog = useQuery({ queryKey: ["reports", "catalog"], queryFn: () => api.get<{ key: string; title: string }[]>("/reports"), staleTime: Infinity });
  const metrics = useQuery({ queryKey: ["reports", "metrics"], queryFn: () => api.get<Metrics>("/reports/metrics") });
  const rangeInvalid = start > end;
  const report = useQuery({ queryKey: ["reports", key, start, end], queryFn: () => api.get<ReportData>(`/reports/${key}`, { start, end }), enabled: !rangeInvalid, placeholderData: (p) => p });
  const csvUrl = useMemo(() => api.url(`/reports/${key}`, { start, end, format: "csv" }), [key, start, end]);
  const m = metrics.data;

  return (
    <div>
      <PageHeader title="Reports" description="Operational reports for readiness, energy, cost and exceptions. Every report can be downloaded as CSV." actions={<SimulatedTag />} />

      <Panel eyebrow={`Success metrics · last ${m?.window_days ?? 30} days`} title="How the fleet is performing" bodyClassName="p-0">
        {metrics.isLoading ? (
          <div className="p-4">
            <LoadingBlock rows={2} />
          </div>
        ) : m ? (
          <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Departures meeting SoC", pct(m.departures_meeting_soc_pct, 1), `${num(m.departures)} departures`],
              ["Missed requirements", num(m.missed_requirements), "departed below required"],
              ["Lower-cost energy", pct(m.lower_cost_energy_pct, 1), `peak ${pct(m.peak_energy_pct, 1)}`],
              ["Charger utilization", pct(m.charger_utilization_pct, 1), "time charging"],
              ["Conflicts prevented", num(m.conflicts_prevented_latest_run), "in latest schedule run"],
              ["Cost per trip", money(m.energy_cost_per_trip), `${money(m.energy_cost_per_vehicle)} per vehicle`],
              ["Manual interventions", num(m.manual_interventions), "overrides & manual starts"],
              ["Recalculation time", m.recalc_ms_median !== null ? `${num(m.recalc_ms_median)} ms` : "—", `p95 ${m.recalc_ms_p95 !== null ? num(m.recalc_ms_p95) : "—"} ms`],
              ["Unresolved alerts", num(m.unresolved_alerts), "open or acknowledged"],
            ].map(([label, value, sub]) => (
              <div key={label} className="bg-surface px-4 py-3">
                <div className="eyebrow">{label}</div>
                <div className="num mt-1 text-lg font-medium">{value}</div>
                <div className="text-2xs text-ink-3">{sub}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-4">
            <ErrorState error={metrics.error} />
          </div>
        )}
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-[260px_1fr]">
        <nav aria-label="Report list" className="panel h-fit p-2">
          <ul className="space-y-0.5">
            {(catalog.data ?? []).map((r) => (
              <li key={r.key}>
                <button onClick={() => setParams({ r: r.key })} className={cx("w-full rounded px-2.5 py-2 text-left text-sm", r.key === key ? "bg-brand-soft font-medium text-brand-ink" : "text-ink-2 hover:bg-sunken")} aria-current={r.key === key ? "page" : undefined}>
                  {r.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-4">
          <Panel
            eyebrow="Report"
            title={report.data?.title ?? catalog.data?.find((c) => c.key === key)?.title ?? "Report"}
            actions={
              <a
                href={rangeInvalid ? undefined : csvUrl}
                download
                aria-disabled={rangeInvalid}
                className={cx("inline-flex h-9 items-center gap-1.5 rounded border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken", rangeInvalid && "pointer-events-none opacity-50")}
              >
                <Download className="h-4 w-4" aria-hidden /> Download CSV
              </a>
            }
          >
            <div className="flex flex-wrap items-end gap-3">
              {!key.startsWith("summary-") && (
                <>
                  <Field label="From" htmlFor="rp-from" error={rangeInvalid ? "Start must be before end" : undefined}>
                    <Input id="rp-from" type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} className="w-auto" invalid={rangeInvalid} />
                  </Field>
                  <Field label="To" htmlFor="rp-to">
                    <Input id="rp-to" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="w-auto" />
                  </Field>
                </>
              )}
              <p className="max-w-xl pb-2 text-xs text-ink-3">{report.data?.description}</p>
            </div>
            {report.data && Object.keys(report.data.summary).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(report.data.summary)
                  .filter(([, v]) => typeof v !== "object" || v === null)
                  .map(([k, v]) => (
                    <span key={k} className="rounded border border-line bg-paper px-2 py-1 text-xs">
                      <span className="text-ink-3">{humanize(k)}:</span> <span className="num font-medium">{cell(v)}</span>
                    </span>
                  ))}
              </div>
            )}
            {report.data && <div className="mt-4"><ReportChart report={report.data} /></div>}
          </Panel>
          <Panel bodyClassName="p-0">
            {report.isLoading ? (
              <div className="p-4">
                <LoadingBlock rows={8} />
              </div>
            ) : report.error ? (
              <div className="p-4">
                <ErrorState error={report.error} onRetry={() => report.refetch()} />
              </div>
            ) : !report.data?.rows.length ? (
              <EmptyState title="No rows for this range" icon={<FileSpreadsheet className="h-6 w-6" />} />
            ) : (
              <div className="scroll-thin max-h-[560px] overflow-auto">
                <table className="table-base min-w-[760px]">
                  <thead>
                    <tr>
                      {report.data.columns.map((c) => (
                        <th key={c.key}>{c.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.data.rows.slice(0, 500).map((row, i) => (
                      <tr key={i}>
                        {report.data!.columns.map((c) => (
                          <td key={c.key} className={cx(typeof row[c.key] === "number" && "num text-right", "max-w-[320px] truncate")} title={typeof row[c.key] === "string" ? String(row[c.key]) : undefined}>
                            {cell(row[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {report.data.rows.length > 500 && <p className="px-4 py-2 text-xs text-ink-3">Showing 500 of {report.data.rows.length} rows — download the CSV for the full report.</p>}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
