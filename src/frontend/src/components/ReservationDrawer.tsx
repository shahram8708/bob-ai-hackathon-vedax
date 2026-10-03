import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/api/client";
import type { Charger, Reservation } from "@/api/types";
import { PriorityBadge, ReservationBadge, TariffSwatch } from "@/components/status";
import { Button, Callout, DefinitionList, Drawer, Field, Input, RULES, RuleChip, Select, Textarea, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, fromLocalInput, kwh, localInputValue, money, num, pct, time } from "@/lib/format";

export function ReservationDrawer({ reservation, onClose }: { reservation: Reservation | null; onClose: () => void }) {
  const { can } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [action, setAction] = useState<"reschedule" | "charge_now" | "cancel">("reschedule");
  const [chargerId, setChargerId] = useState<number | "">("");
  const [start, setStart] = useState("");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [preempt, setPreempt] = useState(false);
  const [hold, setHold] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!reservation) return;
    setAction("reschedule");
    setChargerId(reservation.charger_id);
    setStart(localInputValue(new Date(reservation.start_at)));
    setTarget(String(Math.round(reservation.target_soc)));
    setReason("");
    setPreempt(false);
    setHold("");
    setErrors({});
  }, [reservation]);

  const chargers = useQuery({ queryKey: ["chargers"], queryFn: () => api.get<Charger[]>("/chargers"), enabled: !!reservation });
  const options = useMemo(() => (chargers.data ?? []).filter((c) => c.station_id === reservation?.station_id && c.is_active), [chargers.data, reservation]);

  const submit = useMutation({
    mutationFn: () =>
      api.post<Reservation>(`/charging-schedules/${reservation!.id}/override`, {
        action,
        charger_id: action === "cancel" ? undefined : chargerId || undefined,
        start_at: action === "reschedule" && start ? fromLocalInput(start) : undefined,
        target_soc: action === "cancel" || !target ? undefined : Number(target),
        reason,
        preempt,
        hold_hours: action === "cancel" && hold ? Number(hold) : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Override applied", body: "Recorded in the audit log; the schedule was recalculated around it." });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e, "Override rejected");
    },
  });

  if (!reservation) return null;
  const r = reservation;
  const editable = ["planned", "proposed", "active"].includes(r.status) && r.status !== "preview";
  const mix = Object.entries(r.tariff_mix ?? {});
  const validate = () => {
    const errs: Record<string, string> = {};
    if (reason.trim().length < 5) errs.reason = "Give a reason of at least 5 characters";
    if (action === "reschedule" && !start) errs.start_at = "Choose a start time";
    if (target && (Number(target) <= 0 || Number(target) > 100)) errs.target_soc = "Target must be 1–100%";
    setErrors(errs);
    return !Object.keys(errs).length;
  };

  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <span className="num">{r.vehicle}</span> on <span className="num">{r.charger}</span>
        </span>
      }
      subtitle={
        <span className="flex flex-wrap items-center gap-1.5">
          <ReservationBadge value={r.status} />
          <PriorityBadge level={r.priority_level} />
          {r.is_override && <span className="text-serious-ink">Manual override</span>}
        </span>
      }
      footer={
        editable && can("schedule:override") ? (
          <>
            <Button variant="ghost" onClick={onClose}>
              Close
            </Button>
            <Button variant={action === "cancel" ? "danger" : "primary"} loading={submit.isPending} onClick={() => validate() && submit.mutate()}>
              {action === "cancel" ? "Cancel reservation" : action === "charge_now" ? "Charge now (R8)" : "Apply override"}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className="space-y-5">
        <DefinitionList
          items={[
            ["Window", <span className="num">{dayTime(r.start_at)} – {time(r.end_at)}</span>],
            ["Power", <span className="num">{num(r.power_kw)} kW</span>],
            ["Planned energy", <span className="num">{kwh(r.planned_energy_kwh)}</span>],
            ["Estimated cost", <span className="num">{money(r.estimated_cost, 2)}</span>],
            ["Target SoC", <span className="num">{pct(r.target_soc)}</span>],
            ["Vehicle", <Link to={`/vehicles/${r.vehicle_id}`} className="text-brand hover:underline">Open vehicle</Link>],
          ]}
        />
        {mix.length > 0 && (
          <div>
            <div className="eyebrow mb-1.5">Tariff mix</div>
            <div className="flex h-2.5 overflow-hidden rounded-[3px] bg-sunken" role="img" aria-label={mix.map(([k, v]) => `${k} ${v.toFixed(1)} kWh`).join(", ")}>
              {mix.map(([k, v]) => (
                <div key={k} className="h-full border-r-2 border-surface last:border-r-0" style={{ width: `${(v / r.planned_energy_kwh) * 100}%`, background: { off_peak: "#2A78D6", shoulder: "#1BAF7A", peak: "#EB6834", custom: "#4A3AA7" }[k] }} />
              ))}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-3">
              {mix.map(([k, v]) => (
                <TariffSwatch key={k} kind={k} label={`${k.replace("_", "-")} ${v.toFixed(1)} kWh`} />
              ))}
            </div>
          </div>
        )}
        <div>
          <div className="eyebrow mb-1.5">Why this decision</div>
          {r.rules.length > 0 && (
            <ul className="mb-2 space-y-1">
              {r.rules.map((code) => (
                <li key={code} className="flex items-start gap-2 text-xs text-ink-2">
                  <RuleChip code={code} />
                  <span>{RULES[code]}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="rounded border border-line bg-paper px-3 py-2.5 text-[0.8125rem] leading-relaxed text-ink-2">{r.explanation || r.override_reason || "No explanation recorded."}</p>
        </div>

        {editable && can("schedule:override") && (
          <div className="space-y-3 border-t border-line pt-4">
            <div className="eyebrow">Manual override</div>
            <Field label="Action" htmlFor="ov-action">
              <Select id="ov-action" value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
                <option value="reschedule">Move to another time or charger</option>
                <option value="charge_now">Charge now — emergency override (R8)</option>
                {r.status !== "active" && <option value="cancel">Cancel this reservation</option>}
              </Select>
            </Field>
            {action !== "cancel" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Charger" htmlFor="ov-charger" error={errors.charger_id}>
                  <Select id="ov-charger" value={chargerId} onChange={(e) => setChargerId(Number(e.target.value))}>
                    {options.map((c) => (
                      <option key={c.id} value={c.id} disabled={c.status === "fault" || c.status === "maintenance"}>
                        {c.code} · {c.connector_type} {num(c.max_power_kw)} kW {c.status !== "available" ? `(${c.status})` : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Target SoC %" htmlFor="ov-target" error={errors.target_soc}>
                  <Input id="ov-target" type="number" min={1} max={100} value={target} onChange={(e) => setTarget(e.target.value)} invalid={!!errors.target_soc} />
                </Field>
                {action === "reschedule" && (
                  <Field label="Start (fleet time)" htmlFor="ov-start" error={errors.start_at}>
                    <Input id="ov-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} invalid={!!errors.start_at} />
                  </Field>
                )}
              </div>
            )}
            {action === "cancel" && (
              <Field label="Hold charging for (hours)" htmlFor="ov-hold" hint="Optional. Without a hold the scheduler will plan the vehicle again on the next run.">
                <Input id="ov-hold" type="number" min={0.5} max={72} step={0.5} value={hold} onChange={(e) => setHold(e.target.value)} />
              </Field>
            )}
            <Field label="Reason (recorded in the audit log)" htmlFor="ov-reason" error={errors.reason} required>
              <Textarea id="ov-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Driver reassigned to an earlier emergency run" aria-invalid={!!errors.reason || undefined} />
            </Field>
            {action !== "cancel" && <Toggle checked={preempt} onChange={setPreempt} label="Pre-empt an active session" description="Stops another vehicle charging on this charger if the window overlaps it." />}
            {action === "charge_now" && (
              <Callout tone="warn">Emergency charging ignores tariff optimisation and may displace other reservations. Displaced vehicles are rescheduled automatically and a conflict alert is raised.</Callout>
            )}
          </div>
        )}
      </div>
    </Drawer>
  );
}
