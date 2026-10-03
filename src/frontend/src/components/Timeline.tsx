import { useMemo } from "react";
import type { Charger, Reservation, TariffSlot } from "@/api/types";
import { cx } from "@/components/ui";
import { time, TARIFF_COLORS } from "@/lib/format";

const HOUR = 3600_000;

export function ScheduleTimeline({
  chargers,
  reservations,
  strip,
  start,
  hours,
  now,
  onSelect,
  stationNames,
}: {
  chargers: Charger[];
  reservations: Reservation[];
  strip: TariffSlot[];
  start: Date;
  hours: number;
  now: Date;
  onSelect: (r: Reservation) => void;
  stationNames: Record<number, string>;
}) {
  const t0 = start.getTime();
  const span = hours * HOUR;
  const pos = (t: number) => ((t - t0) / span) * 100;
  const byCharger = useMemo(() => {
    const m = new Map<number, Reservation[]>();
    for (const r of reservations) {
      const list = m.get(r.charger_id) ?? [];
      list.push(r);
      m.set(r.charger_id, list);
    }
    return m;
  }, [reservations]);
  const groups = useMemo(() => {
    const g = new Map<number, Charger[]>();
    for (const c of chargers) g.set(c.station_id, [...(g.get(c.station_id) ?? []), c]);
    return [...g.entries()];
  }, [chargers]);
  const ticks = Array.from({ length: hours * 4 + 4 }, (_, i) => new Date(Math.ceil(t0 / (15 * 60_000)) * 15 * 60_000 + i * 15 * 60_000)).filter(
    (t) => t.getTime() <= t0 + span && time(t).endsWith(":00"),
  );
  const bands = strip
    .map((s, i) => {
      const a = new Date(s.at).getTime();
      const b = strip[i + 1] ? new Date(strip[i + 1].at).getTime() : a + 30 * 60_000;
      return { kind: s.kind, a: Math.max(a, t0), b: Math.min(b, t0 + span) };
    })
    .filter((x) => x.b > x.a);

  return (
    <div className="scroll-thin overflow-x-auto">
      <div className="min-w-[960px]">
        <div className="grid grid-cols-[112px_1fr]">
          <div />
          <div className="relative h-7 border-b border-line">
            {ticks.map((t, i) => (
              <span key={t.getTime()} className={cx("absolute top-1 -translate-x-1/2 font-mono text-2xs text-ink-3", i % 2 && hours > 14 ? "hidden md:block" : "")} style={{ left: `${pos(t.getTime())}%` }}>
                {time(t)}
              </span>
            ))}
          </div>
          <div className="eyebrow flex items-center pr-2">Tariff</div>
          <div className="relative h-3">
            {bands.map((b, i) => (
              <div key={i} className="absolute top-0.5 h-2 border-r border-surface" style={{ left: `${pos(b.a)}%`, width: `${pos(b.b) - pos(b.a)}%`, background: TARIFF_COLORS[b.kind] }} title={b.kind} />
            ))}
          </div>
        </div>

        {groups.map(([stationId, list]) => (
          <div key={stationId} className="mt-3">
            <div className="eyebrow mb-1">{stationNames[stationId] ?? `Station ${stationId}`}</div>
            {list.map((c) => {
              const rows = (byCharger.get(c.id) ?? []).filter((r) => new Date(r.end_at).getTime() > t0 && new Date(r.start_at).getTime() < t0 + span);
              const down = c.status === "fault" || c.status === "maintenance";
              return (
                <div key={c.id} className="grid grid-cols-[112px_1fr] items-center">
                  <div className="truncate pr-2 font-mono text-xs text-ink-2" title={`${c.code} · ${c.connector_type} ${c.max_power_kw} kW`}>
                    {c.code}
                    <span className="ml-1 text-ink-3">{c.max_power_kw}kW</span>
                  </div>
                  <div className={cx("relative h-9 border-b border-line/70", down && "bg-[repeating-linear-gradient(135deg,#EEEBE4_0,#EEEBE4_4px,transparent_4px,transparent_8px)]")}>
                    {bands.map((b, i) => (
                      <div key={i} className="absolute inset-y-0" style={{ left: `${pos(b.a)}%`, width: `${pos(b.b) - pos(b.a)}%`, background: TARIFF_COLORS[b.kind], opacity: 0.045 }} aria-hidden />
                    ))}
                    {down && <span className="absolute left-2 top-2 text-2xs font-medium uppercase tracking-wide text-ink-3">{c.status}</span>}
                    {rows.map((r) => {
                      const a = Math.max(new Date(r.start_at).getTime(), t0);
                      const b = Math.min(new Date(r.end_at).getTime(), t0 + span);
                      const width = Math.max(pos(b) - pos(a), 0.6);
                      const urgent = r.priority_level <= 2;
                      return (
                        <button
                          key={`${r.id}-${r.start_at}`}
                          onClick={() => onSelect(r)}
                          title={`${r.vehicle} · ${time(r.start_at)}–${time(r.end_at)} · P${r.priority_level} · ${r.rules.join(" ")}`}
                          className={cx(
                            "absolute top-1.5 flex h-6 items-center gap-1 overflow-hidden rounded-[4px] border px-1.5 text-left text-2xs font-medium transition-shadow hover:z-10 hover:shadow-pop focus-visible:z-10",
                            r.status === "active"
                              ? "border-brand bg-brand text-white"
                              : r.status === "proposed"
                                ? "border-dashed border-warn-ink bg-warn-soft text-warn-ink"
                                : r.status === "preview"
                                  ? "border-ink-3 bg-surface text-ink"
                                  : r.is_override
                                    ? "border-serious-ink bg-serious-soft text-serious-ink"
                                    : urgent
                                      ? "border-critical/50 bg-critical-soft text-critical-ink"
                                      : "border-brand/40 bg-brand-soft text-brand-ink",
                          )}
                          style={{ left: `${pos(a)}%`, width: `${width}%` }}
                        >
                          {width > 2.2 && <span className="num truncate">{width > 4.5 ? r.vehicle : r.vehicle?.replace(/^EV-/, "")}</span>}
                          {width > 6 && <span className="truncate font-mono opacity-70">P{r.priority_level}</span>}
                        </button>
                      );
                    })}
                    {now.getTime() >= t0 && now.getTime() <= t0 + span && <div className="pointer-events-none absolute inset-y-0 w-[2px] bg-ink/70" style={{ left: `${pos(now.getTime())}%` }} aria-hidden />}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-2">
          {[
            ["border-brand bg-brand", "Charging now"],
            ["border-brand/40 bg-brand-soft", "Planned"],
            ["border-critical/50 bg-critical-soft", "Urgent (P1–P2)"],
            ["border-serious-ink bg-serious-soft", "Manual override"],
            ["border-dashed border-warn-ink bg-warn-soft", "Awaiting approval"],
          ].map(([cls, label]) => (
            <span key={label} className="flex items-center gap-1.5">
              <span className={cx("h-3 w-5 rounded-[3px] border", cls)} aria-hidden />
              {label}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-[2px] bg-ink/70" aria-hidden />
            Now
          </span>
          {["off_peak", "shoulder", "peak"].map((k) => (
            <span key={k} className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-[2px]" style={{ background: TARIFF_COLORS[k] }} aria-hidden />
              {k === "off_peak" ? "Off-peak" : k.charAt(0).toUpperCase() + k.slice(1)} tariff
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
