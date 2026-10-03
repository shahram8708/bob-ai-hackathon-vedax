import { AlertTriangle, BatteryCharging, CheckCircle2, CircleDashed, Clock, OctagonAlert, Plug, Route, Wrench, Zap, ZapOff } from "lucide-react";
import { Badge, type Tone } from "@/components/ui";
import { TARIFF_COLORS, TARIFF_LABEL } from "@/lib/format";

const READINESS: Record<string, [Tone, string, typeof CheckCircle2]> = {
  ready: ["good", "Ready", CheckCircle2],
  charging: ["brand", "Charging", BatteryCharging],
  needs_charge: ["warn", "Needs charge", Clock],
  at_risk: ["critical", "At risk", OctagonAlert],
  on_trip: ["info", "On trip", Route],
  maintenance: ["neutral", "Maintenance", Wrench],
  out_of_service: ["neutral", "Out of service", ZapOff],
};

export function ReadinessBadge({ value }: { value: string }) {
  const [tone, label, Icon] = READINESS[value] ?? ["neutral", value, CircleDashed];
  return (
    <Badge tone={tone} icon={<Icon className="h-3 w-3" aria-hidden />}>
      {label}
    </Badge>
  );
}

const CHARGER: Record<string, [Tone, string, typeof Plug]> = {
  available: ["good", "Available", Plug],
  charging: ["brand", "Charging", Zap],
  reserved: ["info", "Reserved", Clock],
  fault: ["critical", "Fault", OctagonAlert],
  maintenance: ["warn", "Maintenance", Wrench],
};

export function ChargerStatusBadge({ value }: { value: string }) {
  const [tone, label, Icon] = CHARGER[value] ?? ["neutral", value, CircleDashed];
  return (
    <Badge tone={tone} icon={<Icon className="h-3 w-3" aria-hidden />}>
      {label}
    </Badge>
  );
}

export function SeverityBadge({ value }: { value: string }) {
  if (value === "critical")
    return (
      <Badge tone="critical" icon={<OctagonAlert className="h-3 w-3" aria-hidden />}>
        Critical
      </Badge>
    );
  if (value === "warning")
    return (
      <Badge tone="warn" icon={<AlertTriangle className="h-3 w-3" aria-hidden />}>
        Warning
      </Badge>
    );
  return <Badge tone="info">Info</Badge>;
}

const RESERVATION: Record<string, Tone> = {
  planned: "info",
  proposed: "warn",
  active: "brand",
  completed: "good",
  missed: "critical",
  interrupted: "serious",
  cancelled: "neutral",
  superseded: "neutral",
  preview: "neutral",
};

export function ReservationBadge({ value }: { value: string }) {
  return <Badge tone={RESERVATION[value] ?? "neutral"}>{value.charAt(0).toUpperCase() + value.slice(1)}</Badge>;
}

export function PriorityBadge({ level }: { level: number }) {
  const tone: Tone = level === 1 ? "critical" : level === 2 ? "serious" : level === 3 ? "warn" : "neutral";
  return (
    <Badge tone={tone} className="font-mono text-2xs" title={PRIORITY[level]}>
      P{level}
    </Badge>
  );
}

export const PRIORITY: Record<number, string> = {
  1: "Emergency or operationally critical",
  2: "Earliest departure with insufficient SoC",
  3: "Low SoC with a scheduled trip",
  4: "Later departure, flexible requirement",
  5: "No immediate trip requirement",
};

export function TariffSwatch({ kind, label }: { kind: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
      <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: TARIFF_COLORS[kind] ?? "#86837B" }} aria-hidden />
      {label ?? TARIFF_LABEL[kind] ?? kind}
    </span>
  );
}
