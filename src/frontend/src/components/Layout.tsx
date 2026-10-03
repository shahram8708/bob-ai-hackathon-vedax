import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BatteryCharging,
  Bell,
  CalendarClock,
  Car,
  FileBarChart2,
  Gauge,
  LogOut,
  Map as MapIcon,
  Menu,
  ReceiptText,
  ScrollText,
  Settings2,
  Smartphone,
  Truck,
  Warehouse,
  X,
  Zap,
} from "lucide-react";
import { api } from "@/api/client";
import type { TariffSlot } from "@/api/types";
import { useLiveUpdates } from "@/hooks/useLiveUpdates";
import { useSession } from "@/lib/session";
import { money, relative, time, TARIFF_COLORS, TARIFF_LABEL } from "@/lib/format";
import { cx } from "@/components/ui";
import { useToast } from "@/components/toast";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Gauge;
  perms: string[];
  badge?: number;
}

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cx("flex items-center gap-2", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#1F4D3A" />
        <path d="M9 9h9a5 5 0 0 1 0 10h-4" fill="none" stroke="#F4F2ED" strokeWidth="3" strokeLinecap="round" />
        <path d="M17 15l-4 4 4 4" fill="none" stroke="#C9E86A" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-none">
        <div className="text-[0.9375rem] font-semibold tracking-tight text-ink">ChargeOpt</div>
        <div className="font-mono text-[0.625rem] uppercase tracking-[0.14em] text-ink-3">Fleet charging</div>
      </div>
    </div>
  );
}

function useFleetClock() {
  const { user, can } = useSession();
  const sim = useQuery({
    queryKey: ["simulation"],
    queryFn: () => api.get<{ now: string; enabled: boolean; clock_offset_seconds: number }>("/simulation"),
    enabled: !!user && can("dashboard:view"),
    refetchInterval: 60_000,
  });
  const [tick, setTick] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const offset = (sim.data?.clock_offset_seconds ?? 0) * 1000;
  return { now: new Date(tick + offset), simulated: offset > 0, simEnabled: sim.data?.enabled };
}

export function Layout() {
  const { user, logout, can, stations, station, setStation, config } = useSession();
  const { status, lastAlert } = useLiveUpdates(!!user);
  const toast = useToast();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const clock = useFleetClock();

  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (lastAlert && can("alerts:manage", "dashboard:view")) toast.push({ tone: lastAlert.severity === "critical" ? "error" : "info", title: "New alert", body: lastAlert.title });
  }, [lastAlert]); // eslint-disable-line react-hooks/exhaustive-deps

  const alerts = useQuery({
    queryKey: ["alerts", "count"],
    queryFn: () => api.get<{ total: number }>("/alerts", { status: "active", page_size: 1 }),
    enabled: can("dashboard:view"),
    refetchInterval: 30_000,
  });
  const tariff = useQuery({
    queryKey: ["tariffs", "now"],
    queryFn: () => api.get<{ strip: TariffSlot[] }>("/tariffs/calendar", { hours: 6 }),
    enabled: can("fleet:view"),
    refetchInterval: 5 * 60_000,
  });

  const groups: { label: string; items: NavItem[] }[] = useMemo(
    () => [
      {
        label: "Operate",
        items: [
          { to: "/", label: "Overview", icon: Gauge, perms: ["dashboard:view"] },
          { to: "/schedule", label: "Schedule", icon: CalendarClock, perms: ["fleet:view"] },
          { to: "/operations", label: "Charging ops", icon: BatteryCharging, perms: ["fleet:view"] },
          { to: "/alerts", label: "Alerts", icon: Bell, perms: ["dashboard:view"], badge: alerts.data?.total },
        ],
      },
      {
        label: "Fleet",
        items: [
          { to: "/vehicles", label: "Vehicles", icon: Car, perms: ["fleet:view"] },
          { to: "/trips", label: "Trips & drivers", icon: Truck, perms: ["fleet:view"] },
          { to: "/map", label: "Map", icon: MapIcon, perms: ["fleet:view"] },
        ],
      },
      {
        label: "Energy",
        items: [
          { to: "/energy", label: "Energy & cost", icon: Activity, perms: ["dashboard:view"] },
          { to: "/reports", label: "Reports", icon: FileBarChart2, perms: ["reports:view"] },
        ],
      },
      {
        label: "Configure",
        items: [
          { to: "/infrastructure", label: "Depots & chargers", icon: Warehouse, perms: ["fleet:view"] },
          { to: "/tariffs", label: "Tariffs", icon: ReceiptText, perms: ["fleet:view"] },
          { to: "/settings", label: "Rules & settings", icon: Settings2, perms: ["config:manage", "users:manage", "simulation:control"] },
          { to: "/audit", label: "Audit log", icon: ScrollText, perms: ["audit:view"] },
        ],
      },
      { label: "Driver", items: [{ to: "/driver", label: "My vehicle", icon: Smartphone, perms: ["driver:self"] }] },
    ],
    [alerts.data?.total],
  );

  const strip = tariff.data?.strip ?? [];
  const current = strip[0];
  const next = strip.find((s) => current && (s.kind !== current.kind || s.rate !== current.rate));

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {groups.map((g) => {
        const items = g.items.filter((i) => can(...i.perms));
        if (!items.length) return null;
        return (
          <div key={g.label}>
            <div className="eyebrow mb-1.5 px-2.5">{g.label}</div>
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      cx(
                        "group flex items-center gap-2.5 rounded px-2.5 py-1.5 text-sm transition-colors",
                        isActive ? "bg-surface font-medium text-ink shadow-[inset_2px_0_0_#1F4D3A] ring-1 ring-line" : "text-ink-2 hover:bg-sunken hover:text-ink",
                      )
                    }
                  >
                    <item.icon className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                    <span className="flex-1">{item.label}</span>
                    {!!item.badge && <span className="num rounded bg-critical px-1.5 text-2xs font-medium text-white">{item.badge}</span>}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );

  const userCard = user && (
    <div className="border-t border-line pt-3">
      <div className="flex items-center gap-2.5 px-1">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-ink" aria-hidden>
          {user.full_name
            .split(" ")
            .map((p) => p[0])
            .slice(0, 2)
            .join("")}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{user.full_name}</div>
          <div className="truncate text-xs text-ink-3">{user.role_name}</div>
        </div>
        <button onClick={() => logout()} className="rounded p-1.5 text-ink-3 hover:bg-sunken hover:text-ink" aria-label="Sign out" title="Sign out">
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen flex-col gap-6 border-r border-line bg-paper px-3 py-4 lg:flex">
        <Logo className="px-1.5" />
        <div className="scroll-thin flex-1 overflow-y-auto">{nav}</div>
        {userCard}
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 bg-ink/30 lg:hidden" onClick={() => setMenuOpen(false)}>
          <aside className="flex h-full w-[260px] flex-col gap-6 bg-paper px-3 py-4 shadow-pop" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <Logo className="px-1.5" />
              <button className="rounded p-1.5 hover:bg-sunken" onClick={() => setMenuOpen(false)} aria-label="Close menu">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="scroll-thin flex-1 overflow-y-auto">{nav}</div>
            {userCard}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-paper/90 px-4 backdrop-blur sm:px-6">
          <button className="rounded p-1.5 hover:bg-sunken lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <Logo className="lg:hidden" />
          {can("fleet:view") && stations.length > 1 && (
            <label className="hidden items-center gap-2 text-xs text-ink-3 md:flex">
              <span className="eyebrow">Depot</span>
              <select value={station ?? ""} onChange={(e) => setStation(e.target.value ? Number(e.target.value) : null)} className="rounded border border-line-strong bg-surface px-2 py-1 text-sm text-ink focus:border-brand focus:outline-none">
                <option value="">All depots</option>
                {stations.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="ml-auto flex items-center gap-3 sm:gap-4">
            {current && (
              <div className="hidden items-center gap-2 rounded border border-line bg-surface px-2.5 py-1 sm:flex" title={current.name}>
                <span className="h-2 w-2 rounded-full" style={{ background: TARIFF_COLORS[current.kind] }} aria-hidden />
                <span className="text-xs font-medium">{TARIFF_LABEL[current.kind] ?? current.kind}</span>
                <span className="num text-xs text-ink-2">{money(current.rate, 2)}/kWh</span>
                {next && <span className="hidden text-xs text-ink-3 xl:inline">· {TARIFF_LABEL[next.kind] ?? next.kind} {relative(next.at, clock.now.getTime())}</span>}
              </div>
            )}
            <div className="text-right leading-tight" aria-label="Fleet local time">
              <div className="num text-sm font-medium">{time(clock.now)}</div>
              <div className="font-mono text-[0.625rem] uppercase tracking-wider text-ink-3">{clock.simulated ? "Sim clock" : (config?.timezone ?? "").split("/").pop()?.replace("_", " ")}</div>
            </div>
            <div className="flex items-center gap-1.5" role="status" aria-label={`Live updates ${status}`} title={status === "live" ? "Live updates connected (WebSocket)" : status === "connecting" ? "Connecting to live updates" : "Live updates offline — polling every 30 s"}>
              <span className={cx("h-2 w-2 rounded-full", status === "live" ? "animate-pulsebar bg-good" : status === "connecting" ? "bg-warn" : "bg-critical")} aria-hidden />
              <span className="hidden font-mono text-2xs uppercase tracking-wider text-ink-3 sm:inline">{status === "live" ? "Live" : status === "connecting" ? "…" : "Polling"}</span>
            </div>
            {clock.simEnabled === false && can("dashboard:view") && (
              <span className="hidden items-center gap-1 text-xs text-ink-3 md:flex" title="Charger telemetry simulation is paused">
                <Zap className="h-3.5 w-3.5" aria-hidden /> Paused
              </span>
            )}
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1480px] flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
