import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, Upload } from "lucide-react";
import { ApiError, api } from "@/api/client";
import type { TariffPeriod, TariffSlot } from "@/api/types";
import { TariffStrip } from "@/components/charts";
import { TariffSwatch } from "@/components/status";
import { Badge, Button, Callout, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Panel, Select, Toggle, cx } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, money, time, TARIFF_COLORS } from "@/lib/format";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface TariffList {
  periods: TariffPeriod[];
  coverage_gaps: string[];
  gap_count: number;
  default_rate_per_kwh: number;
  currency: string;
  timezone: string;
}

function minutes(t: string) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function DayRibbon({ periods }: { periods: TariffPeriod[] }) {
  const active = periods.filter((p) => p.is_active && p.station_id === null);
  const segs: { left: number; width: number; p: TariffPeriod }[] = [];
  for (const p of active) {
    const a = minutes(p.start_time);
    const b = minutes(p.end_time) || 1440;
    if (a < b) segs.push({ left: a, width: b - a, p });
    else {
      segs.push({ left: a, width: 1440 - a, p });
      if (b > 0 && minutes(p.end_time) !== 0) segs.push({ left: 0, width: b, p });
    }
  }
  return (
    <div>
      <div className="relative h-10 overflow-hidden rounded border border-line bg-sunken" role="img" aria-label={active.map((p) => `${p.name} ${p.start_time}–${p.end_time} ${p.rate_per_kwh}/kWh`).join("; ")}>
        {segs.map((s, i) => (
          <div key={i} className="absolute inset-y-0 flex items-center justify-center overflow-hidden border-r-2 border-surface text-2xs font-medium text-white" style={{ left: `${(s.left / 1440) * 100}%`, width: `${(s.width / 1440) * 100}%`, background: TARIFF_COLORS[s.p.kind] }} title={`${s.p.name} · ${s.p.start_time}–${s.p.end_time}`}>
            {s.width >= 180 && <span className="truncate px-1">{money(s.p.rate_per_kwh, 2)}</span>}
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-2xs text-ink-3">
        {["00:00", "06:00", "12:00", "18:00", "24:00"].map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </div>
  );
}

function PeriodForm({ period, onClose }: { period: TariffPeriod | null; onClose: () => void }) {
  const { stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({
    name: period?.name ?? "",
    kind: period?.kind ?? "custom",
    start_time: period?.start_time ?? "11:00",
    end_time: period?.end_time ?? "14:00",
    rate_per_kwh: String(period?.rate_per_kwh ?? ""),
    demand_charge_per_kw: period?.demand_charge_per_kw != null ? String(period.demand_charge_per_kw) : "",
    days_of_week: period?.days_of_week ?? [0, 1, 2, 3, 4, 5, 6],
    station_id: period?.station_id ? String(period.station_id) : "",
    is_active: period?.is_active ?? true,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => {
      const body = { ...f, rate_per_kwh: Number(f.rate_per_kwh), demand_charge_per_kw: f.demand_charge_per_kw ? Number(f.demand_charge_per_kw) : null, station_id: f.station_id ? Number(f.station_id) : null };
      return period ? api.put(`/tariffs/${period.id}`, body) : api.post("/tariffs", body);
    },
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: period ? "Tariff period updated" : "Tariff period added", body: "The schedule was recalculated with the new prices." });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e);
    },
  });
  const invalid = f.name.trim().length < 2 || f.rate_per_kwh === "" || Number(f.rate_per_kwh) < 0 || f.start_time === f.end_time || !f.days_of_week.length;
  return (
    <Modal
      open
      onClose={onClose}
      width="max-w-xl"
      title={period ? `Edit ${period.name}` : "New tariff period"}
      description="Custom and depot-specific periods take precedence over general ones where they overlap. Windows may wrap past midnight."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={invalid} loading={m.isPending} onClick={() => m.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" htmlFor="tp-n" error={errors.name} required>
          <Input id="tp-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Type" htmlFor="tp-k">
          <Select id="tp-k" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as TariffPeriod["kind"] })}>
            <option value="off_peak">Off-peak</option>
            <option value="shoulder">Shoulder</option>
            <option value="peak">Peak</option>
            <option value="custom">Custom</option>
          </Select>
        </Field>
        <Field label="Start" htmlFor="tp-s" error={f.start_time === f.end_time ? "Start and end must differ" : undefined}>
          <Input id="tp-s" type="time" value={f.start_time} onChange={(e) => setF({ ...f, start_time: e.target.value })} />
        </Field>
        <Field label="End" htmlFor="tp-e">
          <Input id="tp-e" type="time" value={f.end_time} onChange={(e) => setF({ ...f, end_time: e.target.value })} />
        </Field>
        <Field label="Rate per kWh" htmlFor="tp-r" error={errors.rate_per_kwh} required>
          <Input id="tp-r" type="number" min={0} step="0.01" value={f.rate_per_kwh} onChange={(e) => setF({ ...f, rate_per_kwh: e.target.value })} />
        </Field>
        <Field label="Demand charge per kW (optional)" htmlFor="tp-d">
          <Input id="tp-d" type="number" min={0} step="1" value={f.demand_charge_per_kw} onChange={(e) => setF({ ...f, demand_charge_per_kw: e.target.value })} />
        </Field>
        <Field label="Applies to depot" htmlFor="tp-st">
          <Select id="tp-st" value={f.station_id} onChange={(e) => setF({ ...f, station_id: e.target.value })}>
            <option value="">All depots</option>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <div>
          <span className="mb-1 block text-xs font-medium text-ink-2">Days</span>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Days of week">
            {DAYS.map((d, i) => {
              const on = f.days_of_week.includes(i);
              return (
                <button key={d} type="button" aria-pressed={on} onClick={() => setF({ ...f, days_of_week: on ? f.days_of_week.filter((x) => x !== i) : [...f.days_of_week, i].sort() })} className={cx("rounded border px-2 py-1 text-xs", on ? "border-brand bg-brand-soft text-brand-ink" : "border-line-strong text-ink-3")}>
                  {d}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <div className="mt-4">
        <Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label="Active" />
      </div>
    </Modal>
  );
}

function FeedUpload({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation({
    mutationFn: () => api.upload<{ loaded: number }>("/tariffs/price-feed/csv", file!),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: `${r.loaded} price intervals loaded`, body: "Dynamic prices override the static tariff for their windows." });
      onClose();
    },
    onError: (e) => toast.error(e, "Price feed rejected"),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="Load dynamic utility prices"
      description="CSV columns: starts_at, ends_at, rate_per_kwh, station (optional depot code). Times without an offset are fleet local time."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!file} loading={m.isPending} onClick={() => m.mutate()}>
            Load prices
          </Button>
        </>
      }
    >
      <input type="file" accept=".csv,text/csv" aria-label="Price feed CSV" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:rounded file:border file:border-line-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm" />
      <p className="mt-3 text-xs text-ink-3">Utilities can also push prices to <code className="font-mono">POST /api/tariffs/price-feed</code> as JSON.</p>
    </Modal>
  );
}

export default function Tariffs() {
  const { can } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [edit, setEdit] = useState<TariffPeriod | null | "new">(null);
  const [feedOpen, setFeedOpen] = useState(false);
  const list = useQuery({ queryKey: ["tariffs", "list"], queryFn: () => api.get<TariffList>("/tariffs") });
  const strip = useQuery({ queryKey: ["tariffs", "strip"], queryFn: () => api.get<{ strip: TariffSlot[] }>("/tariffs/calendar", { hours: 24 }) });
  const feed = useQuery({ queryKey: ["tariffs", "feed"], queryFn: () => api.get<{ id: number; starts_at: string; ends_at: string; rate_per_kwh: number; source: string; station_id: number | null }[]>("/tariffs/price-feed") });
  const clear = useMutation({
    mutationFn: () => api.del("/tariffs/price-feed"),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Price feed cleared" });
    },
    onError: (e) => toast.error(e),
  });
  const admin = can("tariffs:manage");

  if (list.isLoading) return <LoadingBlock rows={8} />;
  if (list.error || !list.data) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  const d = list.data;

  return (
    <div>
      <PageHeader
        title="Tariffs"
        description={`Electricity pricing periods in ${d.timezone} (${d.currency}). The scheduler prefers cheaper windows only when departure readiness is not threatened.`}
        actions={
          admin && (
            <>
              <Button icon={<Upload className="h-4 w-4" />} onClick={() => setFeedOpen(true)}>
                Load price feed
              </Button>
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit("new")}>
                Add period
              </Button>
            </>
          )
        }
      />
      {d.gap_count > 0 && (
        <div className="mb-4">
          <Callout tone="warn" title={`${d.gap_count} quarter-hours have no tariff period`}>
            Uncovered times are priced at the default rate of {money(d.default_rate_per_kwh, 2)}/kWh. First gaps: {d.coverage_gaps.slice(0, 6).join(", ")}.
          </Callout>
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel eyebrow="Daily pattern · all depots" title="Tariff day">
          <DayRibbon periods={d.periods} />
          <div className="mt-3 flex flex-wrap gap-3">
            {["off_peak", "shoulder", "peak", "custom"].map((k) => (
              <TariffSwatch key={k} kind={k} />
            ))}
          </div>
        </Panel>
        <Panel eyebrow="Effective prices · next 24 h" title="Including dynamic price feed">
          <div className="pt-4">{strip.data ? <TariffStrip strip={strip.data.strip} /> : <LoadingBlock rows={2} />}</div>
        </Panel>
      </div>
      <div className="mt-4">
        <Panel eyebrow="Configuration" title="Tariff periods" bodyClassName="p-0">
          <div className="scroll-thin overflow-x-auto">
            <table className="table-base min-w-[820px]">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Type</th>
                  <th>Window</th>
                  <th>Days</th>
                  <th className="text-right">Rate</th>
                  <th className="text-right">Demand charge</th>
                  <th>Scope</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.periods.map((p) => (
                  <tr key={p.id} className={p.is_active ? "" : "opacity-50"}>
                    <td className="font-medium">{p.name}</td>
                    <td>
                      <TariffSwatch kind={p.kind} />
                    </td>
                    <td className="num">
                      {p.start_time}–{p.end_time}
                    </td>
                    <td className="text-xs">{p.days_of_week.length === 7 ? "Every day" : p.days_of_week.map((x) => DAYS[x]).join(", ")}</td>
                    <td className="num text-right">{money(p.rate_per_kwh, 2)}/kWh</td>
                    <td className="num text-right">{p.demand_charge_per_kw != null ? `${money(p.demand_charge_per_kw)}/kW` : "—"}</td>
                    <td className="text-xs">{p.station_id ? <Badge tone="info">Depot-specific</Badge> : "All depots"}</td>
                    <td className="text-right">{admin && <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEdit(p)} aria-label={`Edit ${p.name}`} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="mt-4">
        <Panel
          eyebrow="Dynamic utility prices"
          title={`Price feed (${feed.data?.length ?? 0} intervals)`}
          actions={
            admin &&
            !!feed.data?.length && (
              <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} loading={clear.isPending} onClick={() => clear.mutate()}>
                Clear feed
              </Button>
            )
          }
          bodyClassName="p-0"
        >
          {!feed.data?.length ? (
            <p className="px-4 py-5 text-sm text-ink-3">No dynamic prices loaded — the static tariff periods above apply.</p>
          ) : (
            <div className="scroll-thin max-h-72 overflow-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th className="text-right">Rate</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {feed.data.map((s) => (
                    <tr key={s.id}>
                      <td className="num">{dayTime(s.starts_at)}</td>
                      <td className="num">{time(s.ends_at)}</td>
                      <td className="num text-right">{money(s.rate_per_kwh, 2)}</td>
                      <td className="text-xs text-ink-2">{s.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
      {edit && <PeriodForm period={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
      {feedOpen && <FeedUpload onClose={() => setFeedOpen(false)} />}
    </div>
  );
}
