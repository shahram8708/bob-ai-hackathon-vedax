import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save, UserPlus } from "lucide-react";
import { ApiError, api } from "@/api/client";
import type { OperationalConfig, Role, User } from "@/api/types";
import { Badge, Button, Callout, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Panel, RULES, RuleChip, Select, Tabs, Toggle } from "@/components/ui";
import { PRIORITY, PriorityBadge } from "@/components/status";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime } from "@/lib/format";

type Tab = "rules" | "monitoring" | "energy" | "integrations" | "users" | "simulation";

function NumberField({ label, value, onChange, hint, min, max, step, suffix, error }: { label: string; value: number; onChange: (v: number) => void; hint?: string; min?: number; max?: number; step?: number; suffix?: string; error?: string }) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <Field label={suffix ? `${label} (${suffix})` : label} htmlFor={id} hint={hint} error={error}>
      <Input id={id} type="number" value={Number.isFinite(value) ? value : ""} min={min} max={max} step={step ?? 1} onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} invalid={!!error} />
    </Field>
  );
}

function Section({ title, children, description }: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="grid gap-4 border-b border-line py-5 first:pt-0 last:border-b-0 lg:grid-cols-[260px_1fr]">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {description && <p className="mt-1 text-xs text-ink-3">{description}</p>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </div>
  );
}

function ConfigEditor({ tab }: { tab: Exclude<Tab, "users" | "simulation"> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useSession();
  const q = useQuery({ queryKey: ["config"], queryFn: () => api.get<{ config: OperationalConfig }>("/config") });
  const [draft, setDraft] = useState<OperationalConfig | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    if (q.data) setDraft(q.data.config);
  }, [q.data]);
  const save = useMutation({
    mutationFn: (changes: Partial<OperationalConfig>) => api.put<{ changed: string[] }>("/config", changes),
    onSuccess: (r) => {
      qc.invalidateQueries();
      setErrors({});
      toast.push({ tone: "success", title: r.changed.length ? `Saved ${r.changed.length} setting(s)` : "No changes", body: r.changed.length ? "Recorded in the audit log; the schedule was recalculated." : undefined });
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(Object.fromEntries(Object.entries(e.fieldErrors()).map(([k, v]) => [k.split(".").pop() ?? k, v])));
      toast.error(e, "Settings not saved");
    },
  });
  if (q.isLoading || !draft) return <LoadingBlock rows={8} />;
  if (q.error) return <ErrorState error={q.error} />;
  const original = q.data!.config;
  const set = <K extends keyof OperationalConfig>(k: K, v: OperationalConfig[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const changes = Object.fromEntries(Object.entries(draft).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(original[k as keyof OperationalConfig]))) as Partial<OperationalConfig>;
  const dirty = Object.keys(changes).length > 0;
  const editable = can("config:manage");

  return (
    <Panel
      title={tab === "rules" ? "Scheduling rules" : tab === "monitoring" ? "Alerts & monitoring" : tab === "energy" ? "Energy, tariffs & V2G" : "Integrations"}
      actions={
        editable && (
          <>
            <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} disabled={!dirty} onClick={() => { setDraft(original); setErrors({}); }}>
              Discard
            </Button>
            <Button size="sm" variant="primary" icon={<Save className="h-3.5 w-3.5" />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(changes)}>
              Save changes
            </Button>
          </>
        )
      }
    >
      <fieldset disabled={!editable}>
        {tab === "rules" && (
          <>
            <Section title="Planning grid" description="The deterministic scheduler evaluates the horizon in fixed slots.">
              <NumberField label="Slot length" suffix="min" value={draft.slot_minutes} onChange={(v) => set("slot_minutes", v)} min={5} max={60} error={errors.slot_minutes} />
              <NumberField label="Planning horizon" suffix="h" value={draft.horizon_hours} onChange={(v) => set("horizon_hours", v)} min={6} max={72} error={errors.horizon_hours} />
              <NumberField label="Departure buffer" suffix="min" hint="Charging must finish this long before departure" value={draft.departure_buffer_minutes} onChange={(v) => set("departure_buffer_minutes", v)} min={0} max={120} error={errors.departure_buffer_minutes} />
              <NumberField label="Automatic re-evaluation" suffix="min" value={draft.auto_recalc_minutes} onChange={(v) => set("auto_recalc_minutes", v)} min={1} max={240} error={errors.auto_recalc_minutes} />
            </Section>
            <Section title="Priority rules" description="Priority 1–5 is assigned deterministically; ties are broken in the order below.">
              <NumberField label="Urgent departure window" suffix="h" hint="Departures within this window with insufficient SoC become P2" value={draft.urgent_window_hours} onChange={(v) => set("urgent_window_hours", v)} min={0.25} max={24} step={0.25} error={errors.urgent_window_hours} />
              <Field label="Tie-breaker order" htmlFor="tb">
                <Select id="tb" value={draft.tie_breakers.join(",")} onChange={(e) => set("tie_breakers", e.target.value.split(","))}>
                  <option value="departure,soc,created">Earliest departure → lowest SoC → first request</option>
                  <option value="soc,departure,created">Lowest SoC → earliest departure → first request</option>
                  <option value="departure,created,soc">Earliest departure → first request → lowest SoC</option>
                </Select>
              </Field>
              <div className="space-y-1.5 sm:col-span-2">
                {[1, 2, 3, 4, 5].map((p) => (
                  <div key={p} className="flex items-center gap-2 text-xs text-ink-2">
                    <PriorityBadge level={p} /> {PRIORITY[p]}
                  </div>
                ))}
              </div>
              <div className="sm:col-span-2">
                <Toggle checked={draft.emergency_override} onChange={(v) => set("emergency_override", v)} label="Emergency vehicles always P1" description="Critical vehicles and emergency trips bypass tariff optimisation (R2/R8)." />
              </div>
            </Section>
            <Section title="Tariff optimisation" description="Flexible charging moves to cheaper windows only if it still completes before departure (R4).">
              <div className="sm:col-span-2">
                <Toggle checked={draft.tariff_optimization} onChange={(v) => set("tariff_optimization", v)} label="Shift flexible charging to lower-cost windows" />
              </div>
              <NumberField label="Minimum slack to treat as flexible" suffix="min" value={draft.flex_slack_minutes} onChange={(v) => set("flex_slack_minutes", v)} min={0} max={720} error={errors.flex_slack_minutes} />
            </Section>
            <Section title="Required SoC" description="Operator-defined targets are recommended for transparency. Rule-based uses trip energy plus a safety reserve.">
              <Field label="Required SoC source" htmlFor="rsm">
                <Select id="rsm" value={draft.required_soc_mode} onChange={(e) => set("required_soc_mode", e.target.value as OperationalConfig["required_soc_mode"])}>
                  <option value="operator">Operator-defined target per trip</option>
                  <option value="rule">Trip energy + safety reserve</option>
                </Select>
              </Field>
              <Field label="Reserve type" htmlFor="rt">
                <Select id="rt" value={draft.safety_reserve_type} onChange={(e) => set("safety_reserve_type", e.target.value as OperationalConfig["safety_reserve_type"])}>
                  <option value="percent">Percent of battery</option>
                  <option value="kwh">Fixed kWh</option>
                </Select>
              </Field>
              <NumberField label="Safety reserve" suffix={draft.safety_reserve_type === "percent" ? "%" : "kWh"} value={draft.safety_reserve_value} onChange={(v) => set("safety_reserve_value", v)} min={0} max={100} error={errors.safety_reserve_value} />
            </Section>
            <Section title="Approval" description="When enabled, each new plan is proposed and the previous plan stays in force until a fleet manager approves it.">
              <div className="sm:col-span-2">
                <Toggle checked={draft.require_schedule_approval} onChange={(v) => set("require_schedule_approval", v)} label="Require fleet-manager approval for new schedules" />
              </div>
            </Section>
            <Section title="Rule set" description="The rules the engine cites in every explanation.">
              <ul className="space-y-1.5 sm:col-span-2">
                {Object.entries(RULES).map(([code, text]) => (
                  <li key={code} className="flex items-start gap-2 text-xs text-ink-2">
                    <RuleChip code={code} /> {text}
                  </li>
                ))}
              </ul>
            </Section>
          </>
        )}
        {tab === "monitoring" && (
          <>
            <Section title="Readiness" description="Fleet readiness = departures projected to meet their required SoC.">
              <NumberField label="Readiness alert threshold" suffix="%" value={draft.readiness_threshold_pct} onChange={(v) => set("readiness_threshold_pct", v)} min={0} max={100} error={errors.readiness_threshold_pct} />
              <NumberField label="Readiness window" suffix="h" value={draft.readiness_window_hours} onChange={(v) => set("readiness_window_hours", v)} min={1} max={72} error={errors.readiness_window_hours} />
              <NumberField label="At-risk warning lead time" suffix="h" value={draft.at_risk_warning_hours} onChange={(v) => set("at_risk_warning_hours", v)} min={0.25} max={24} step={0.25} error={errors.at_risk_warning_hours} />
            </Section>
            <Section title="Exceptions">
              <NumberField label="Missed-slot grace period" suffix="min" value={draft.missed_slot_grace_minutes} onChange={(v) => set("missed_slot_grace_minutes", v)} min={1} max={120} error={errors.missed_slot_grace_minutes} />
              <NumberField label="Peak approaching warning" suffix="min" value={draft.peak_warning_minutes} onChange={(v) => set("peak_warning_minutes", v)} min={5} max={240} error={errors.peak_warning_minutes} />
              <NumberField label="Unexpected consumption threshold" suffix="% over expected" value={draft.unexpected_consumption_pct} onChange={(v) => set("unexpected_consumption_pct", v)} min={1} max={200} error={errors.unexpected_consumption_pct} />
            </Section>
          </>
        )}
        {tab === "energy" && (
          <>
            <Section title="Pricing" description="Used when no tariff period covers a time slot.">
              <NumberField label="Default rate" suffix={`${draft.currency}/kWh`} value={draft.default_rate_per_kwh} onChange={(v) => set("default_rate_per_kwh", v)} min={0} step={0.01} error={errors.default_rate_per_kwh} />
              <NumberField label="Storage round-trip efficiency" value={draft.storage_round_trip_efficiency} onChange={(v) => set("storage_round_trip_efficiency", v)} min={0.1} max={1} step={0.01} error={errors.storage_round_trip_efficiency} />
            </Section>
            <Section title="Vehicle-to-grid rules" description="Advisory only. Vehicles are never discharged automatically.">
              <div className="sm:col-span-2">
                <Toggle checked={draft.v2g_enabled} onChange={(v) => set("v2g_enabled", v)} label="Evaluate V2G export opportunities" />
              </div>
              <NumberField label="SoC buffer above requirement" suffix="%" value={draft.v2g_soc_buffer} onChange={(v) => set("v2g_soc_buffer", v)} min={0} max={80} error={errors.v2g_soc_buffer} />
              <NumberField label="Minimum dwell across peak" suffix="h" value={draft.v2g_min_dwell_hours} onChange={(v) => set("v2g_min_dwell_hours", v)} min={0.5} max={24} step={0.5} error={errors.v2g_min_dwell_hours} />
              <NumberField label="Export value" suffix={`${draft.currency}/kWh`} value={draft.v2g_export_rate_per_kwh} onChange={(v) => set("v2g_export_rate_per_kwh", v)} min={0} step={0.01} error={errors.v2g_export_rate_per_kwh} />
            </Section>
          </>
        )}
        {tab === "integrations" && (
          <>
            <Section title="Alert webhook" description="New alerts are POSTed as JSON to this URL (fleet-management, ERP or chat tools). Private network addresses are rejected.">
              <div className="sm:col-span-2">
                <Field label="Webhook URL" htmlFor="wh" error={errors.webhook_url}>
                  <Input id="wh" type="url" placeholder="https://erp.example.com/hooks/chargeopt" value={draft.webhook_url ?? ""} onChange={(e) => set("webhook_url", e.target.value || null)} invalid={!!errors.webhook_url} />
                </Field>
              </div>
            </Section>
            <Section title="Fleet & ERP sync" description="Server-to-server endpoints authenticated with the X-Integration-Key header (configured on the server).">
              <ul className="space-y-2 text-xs text-ink-2 sm:col-span-2">
                <li>
                  <code className="font-mono text-ink">POST /api/integrations/fleet-sync</code> — upsert vehicles and trips by external reference.
                </li>
                <li>
                  <code className="font-mono text-ink">GET /api/integrations/schedule-export</code> — current reservations for dispatch systems.
                </li>
                <li>
                  <code className="font-mono text-ink">POST /api/tariffs/price-feed</code> — dynamic utility prices (authenticated user with tariff permission).
                </li>
                <li>
                  <code className="font-mono text-ink">ws /api/ocpp/&#123;charge-point-id&#125;</code> — OCPP 1.6-J charge point connection (subprotocol <code className="font-mono">ocpp1.6</code>).
                </li>
              </ul>
            </Section>
          </>
        )}
      </fieldset>
    </Panel>
  );
}

function Users() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user: me } = useSession();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<{ code: Role; name: string; description: string }[]>("/roles") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", full_name: "", role: "viewer" as Role, password: "" });
  const create = useMutation({
    mutationFn: () => api.post("/users", f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      setF({ email: "", full_name: "", role: "viewer", password: "" });
      toast.push({ tone: "success", title: "User created" });
    },
    onError: (e) => toast.error(e),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.put(`/users/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.push({ tone: "success", title: "User updated" });
    },
    onError: (e) => toast.error(e),
  });
  const valid = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(f.email) && f.full_name.trim().length >= 2 && f.password.length >= 10;
  if (users.isLoading) return <LoadingBlock rows={6} />;
  return (
    <Panel
      title="Users & roles"
      actions={
        <Button size="sm" variant="primary" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>
          Add user
        </Button>
      }
      bodyClassName="p-0"
    >
      <div className="scroll-thin overflow-x-auto">
        <table className="table-base min-w-[760px]">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Last sign-in</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.id}>
                <td>
                  <div className="font-medium">{u.full_name}</div>
                  <div className="text-xs text-ink-3">{u.email}</div>
                </td>
                <td>
                  <Select aria-label={`Role for ${u.full_name}`} value={u.role} disabled={u.id === me?.id} onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })} className="w-auto py-1">
                    {(roles.data ?? []).map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.name}
                      </option>
                    ))}
                  </Select>
                </td>
                <td className="num text-xs">{u.last_login_at ? dayTime(u.last_login_at) : "Never"}</td>
                <td>
                  {u.id === me?.id ? (
                    <Badge tone="brand">You</Badge>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                      {u.is_active ? <Badge tone="good">Active</Badge> : <Badge>Disabled</Badge>}
                      <span className="text-xs text-ink-3">{u.is_active ? "Disable" : "Enable"}</span>
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-line px-4 py-3">
        <div className="eyebrow mb-2">Role permissions</div>
        <ul className="grid gap-1.5 text-xs text-ink-2 md:grid-cols-2">
          {(roles.data ?? []).map((r) => (
            <li key={r.code}>
              <strong className="text-ink">{r.name}:</strong> {r.description}
            </li>
          ))}
        </ul>
      </div>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add user"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
              Create user
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Full name" htmlFor="u-n" required>
            <Input id="u-n" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          </Field>
          <Field label="Email" htmlFor="u-e" required>
            <Input id="u-e" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </Field>
          <Field label="Role" htmlFor="u-r">
            <Select id="u-r" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
              {(roles.data ?? []).map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Initial password" htmlFor="u-p" hint="At least 10 characters" required>
            <Input id="u-p" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </Field>
        </div>
      </Modal>
    </Panel>
  );
}

function Simulation() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useSession();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"baseline" | "rule_based">("baseline");
  const [paused, setPaused] = useState(true);
  const reset = useMutation({
    mutationFn: () => api.post<{ vehicles: number }>("/simulation/reset", { scheduler_mode: mode, simulation_enabled: !paused, history_days: 30 }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      setOpen(false);
      toast.push({ tone: "success", title: "Demo scenario regenerated", body: `${r.vehicles} vehicles with fresh departures relative to now.` });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Panel title="Simulation & demo data">
      <div className="space-y-4">
        <Callout tone="info" title="What is simulated">
          Chargers without an OCPP connection use simulated telemetry: sessions draw their reserved power, SoC rises accordingly and vehicles depart and return on their trip times. All such data is labelled “simulated”. Real charge points connect over OCPP 1.6-J and report
          their own meter values.
        </Callout>
        <p className="text-sm text-ink-2">Pause, resume or fast-forward the simulation from the Overview page.</p>
        {user?.role === "admin" && (
          <div className="rounded border border-line p-4">
            <h3 className="text-sm font-semibold">Regenerate the demo scenario</h3>
            <p className="mt-1 text-xs text-ink-3">Rebuilds the 100-vehicle fleet, trips, sessions and 30 days of simulated history relative to the current time. Depots, chargers, tariffs and users are kept. The reset is recorded in the audit log.</p>
            <Button className="mt-3" variant="danger" icon={<RotateCcw className="h-4 w-4" />} onClick={() => setOpen(true)}>
              Regenerate scenario…
            </Button>
          </div>
        )}
      </div>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Regenerate demo scenario?"
        description="Operational data (vehicles, trips, sessions, alerts, schedules) is replaced."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={reset.isPending} onClick={() => reset.mutate()}>
              Regenerate
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Start with scheduler" htmlFor="rs-mode">
            <Select id="rs-mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="baseline">Static baseline (demo starting point)</option>
              <option value="rule_based">Rule-based</option>
            </Select>
          </Field>
          <Toggle checked={paused} onChange={setPaused} label="Start with telemetry paused" />
          {reset.error instanceof ApiError && <p className="text-sm text-critical-ink">{reset.error.message}</p>}
        </div>
      </Modal>
    </Panel>
  );
}

export default function Settings() {
  const { can } = useSession();
  const tabs: { value: Tab; label: string }[] = [
    ...(can("config:manage") ? ([
      { value: "rules", label: "Scheduling rules" },
      { value: "monitoring", label: "Alerts & monitoring" },
      { value: "energy", label: "Energy & V2G" },
      { value: "integrations", label: "Integrations" },
    ] as const) : []),
    ...(can("users:manage") ? ([{ value: "users", label: "Users" }] as const) : []),
    ...(can("simulation:control") ? ([{ value: "simulation", label: "Simulation" }] as const) : []),
  ];
  const [tab, setTab] = useState<Tab>(tabs[0]?.value ?? "simulation");
  return (
    <div>
      <PageHeader title="Rules & settings" description="Deterministic rule parameters, thresholds and integrations. Every change is audited and immediately re-plans the fleet." />
      <Tabs<Tab> label="Settings sections" value={tab} onChange={setTab} items={tabs} />
      <div className="mt-4">
        {tab === "users" ? <Users /> : tab === "simulation" ? <Simulation /> : <ConfigEditor tab={tab} />}
      </div>
    </div>
  );
}
