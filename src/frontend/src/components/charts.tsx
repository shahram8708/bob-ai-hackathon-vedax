import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import type { TariffSlot } from "@/api/types";
import { money, time, TARIFF_COLORS, TARIFF_LABEL } from "@/lib/format";
import { TariffSwatch } from "@/components/status";

export const AXIS = { fill: "#86837B", fontSize: 11, fontFamily: "IBM Plex Mono" };
export const GRID = { stroke: "#E2DED5", strokeDasharray: "0", vertical: false };

export function ChartTip({ active, payload, label, formatter, labelFormatter }: TooltipProps<number, string> & { formatter?: (v: number, name: string) => string; labelFormatter?: (l: unknown) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      <div className="mb-1 font-medium text-ink">{labelFormatter ? labelFormatter(label) : String(label)}</div>
      {payload
        .filter((p) => p.value !== null && p.value !== undefined)
        .map((p) => (
          <div key={String(p.dataKey)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-ink-2">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: p.color }} aria-hidden />
              {p.name}
            </span>
            <span className="num text-ink">{formatter ? formatter(Number(p.value), String(p.name)) : p.value}</span>
          </div>
        ))}
    </div>
  );
}

export function TariffStrip({ strip, nowLabel = "Now", height = 34 }: { strip: TariffSlot[]; nowLabel?: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!strip.length) return null;
  const maxRate = Math.max(...strip.map((s) => s.rate));
  const w = 100 / strip.length;
  const kinds = Array.from(new Set(strip.map((s) => s.kind)));
  const slot = hover !== null ? strip[hover] : null;
  return (
    <div>
      <div className="relative" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }} role="img" aria-label="Tariff periods for the next 24 hours">
          {strip.map((s, i) => {
            const h = 8 + (s.rate / maxRate) * (height - 10);
            return (
              <rect
                key={s.at}
                x={i * w + 0.08}
                y={height - h}
                width={w - 0.16}
                height={h}
                rx={0.4}
                fill={TARIFF_COLORS[s.kind] ?? "#86837B"}
                opacity={hover === null || hover === i ? 0.92 : 0.45}
                onMouseEnter={() => setHover(i)}
              />
            );
          })}
        </svg>
        <div className="pointer-events-none absolute -top-1 bottom-0 left-0 w-[2px] bg-ink" aria-hidden />
        <span className="pointer-events-none absolute -top-5 left-0 font-mono text-2xs text-ink">{nowLabel}</span>
        {slot && (
          <div className="pointer-events-none absolute -top-14 z-10 whitespace-nowrap rounded border border-line bg-surface px-2.5 py-1.5 text-xs shadow-pop" style={{ left: `min(calc(${(hover! / strip.length) * 100}% ), calc(100% - 170px))` }}>
            <div className="font-medium">
              {time(slot.at)} · {TARIFF_LABEL[slot.kind] ?? slot.kind}
            </div>
            <div className="num text-ink-2">
              {money(slot.rate, 2)}/kWh {slot.source === "price_feed" ? "· price feed" : ""}
            </div>
          </div>
        )}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-2xs text-ink-3">
        {[0, 0.25, 0.5, 0.75].map((f) => (
          <span key={f}>{time(strip[Math.floor(f * strip.length)]?.at)}</span>
        ))}
        <span>{time(new Date(new Date(strip[strip.length - 1].at).getTime() + 30 * 60000))}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {kinds.map((k) => (
          <TariffSwatch key={k} kind={k} />
        ))}
      </div>
    </div>
  );
}

export function SocHistogram({ data }: { data: { range: string; count: number }[] }) {
  return (
    <div className="h-[180px]" role="img" aria-label={`State of charge distribution: ${data.map((d) => `${d.range} ${d.count}`).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 4, left: -24, bottom: 0 }} barCategoryGap={2}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="range" tick={AXIS} tickLine={false} axisLine={{ stroke: "#CFCAC0" }} interval={1} tickFormatter={(v: string) => `${v.split("–")[0]}%`} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip cursor={{ fill: "#EEEBE4" }} content={<ChartTip formatter={(v) => `${v} vehicles`} />} />
          <Bar dataKey="count" name="Vehicles" fill="#2A78D6" radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
