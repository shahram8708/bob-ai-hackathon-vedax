import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, Play, Square, Wrench } from "lucide-react";
import { api } from "@/api/client";
import type { Charger, Page, Session, Vehicle } from "@/api/types";
import { ChargerStatusBadge } from "@/components/status";
import { Badge, Button, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Pagination, Panel, Select, SimulatedTag, SocBar, Tabs, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, humanize, kwh, money, num, pct, relative, time } from "@/lib/format";

type Tab = "chargers" | "live" | "history";

function StatusModal({ charger, onClose }: { charger: Charger; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState(charger.status === "charging" ? "fault" : charger.status === "available" ? "fault" : "available");
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: () => api.post<Charger>(`/chargers/${charger.id}/status`, { status, note }),
    onSuccess: (c) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: `${c.code} is now ${c.status}`, body: status === "fault" || status === "maintenance" ? "Affected reservations were reassigned (R5)." : undefined });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`Change status · ${charger.code}`}
      description="Status changes are recorded in the audit log and trigger a schedule recalculation."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={status === "fault" ? "danger" : "primary"} loading={m.isPending} onClick={() => m.mutate()}>
            Set {humanize(status).toLowerCase()}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="New status" htmlFor="cs-status">
          <Select id="cs-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="available">Available</option>
            <option value="reserved">Reserved</option>
            <option value="fault">Fault</option>
            <option value="maintenance">Maintenance</option>
          </Select>
        </Field>
        <Field label="Note" htmlFor="cs-note" hint="Visible on the charger board, e.g. the fault code or work order.">
          <Textarea id="cs-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} />
        </Field>
        {charger.current_vehicle && (status === "fault" || status === "maintenance") && (
          <p className="rounded border border-warn/40 bg-warn-soft px-3 py-2 text-xs text-warn-ink">{charger.current_vehicle} is charging here. Its session will be marked interrupted and the vehicle re-planned on a compatible charger.</p>
        )}
      </div>
    </Modal>
  );
}

function PowerModal({ charger, onClose }: { charger: Charger; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [limit, setLimit] = useState(charger.power_limit_kw ? String(charger.power_limit_kw) : "");
  const invalid = limit !== "" && (Number(limit) <= 0 || Number(limit) > charger.max_power_kw);
  const m = useMutation({
    mutationFn: () => api.post(`/chargers/${charger.id}/power-limit`, { limit_kw: limit === "" ? null : Number(limit) }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: `Power limit updated on ${charger.code}`, body: charger.ocpp_connected ? "SetChargingProfile sent over OCPP." : "Applied to the simulated charger." });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`Power limit · ${charger.code}`}
      description={`Rated ${num(charger.max_power_kw)} kW. Leave empty to remove the limit.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={invalid} loading={m.isPending} onClick={() => m.mutate()}>
            Apply
          </Button>
        </>
      }
    >
      <Field label="Limit (kW)" htmlFor="pl" error={invalid ? `Enter a value between 1 and ${charger.max_power_kw}` : undefined}>
        <Input id="pl" type="number" min={1} max={charger.max_power_kw} value={limit} onChange={(e) => setLimit(e.target.value)} invalid={invalid} />
      </Field>
    </Modal>
  );
}

function StartModal({ charger, onClose }: { charger: Charger; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [vehicleId, setVehicleId] = useState<number | "">("");
  const [target, setTarget] = useState("");
  const vehicles = useQuery({ queryKey: ["vehicles", "station", charger.station_id], queryFn: () => api.get<Page<Vehicle>>("/vehicles", { station_id: charger.station_id, page_size: 200 }) });
  const eligible = (vehicles.data?.items ?? []).filter((v) => v.current_station_id === charger.station_id && v.availability === "available" && v.connector_types.includes(charger.connector_type));
  const m = useMutation({
    mutationFn: () => api.post("/charging-sessions", { vehicle_id: vehicleId, charger_id: charger.id, target_soc: target ? Number(target) : undefined }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: `Charging started on ${charger.code}` });
      onClose();
    },
    onError: (e) => toast.error(e, "Could not start session"),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={`Start session · ${charger.code}`}
      description="Manual starts are logged as operator interventions."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!vehicleId} loading={m.isPending} onClick={() => m.mutate()}>
            Start charging
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Vehicle at this depot" htmlFor="ss-v">
          <Select id="ss-v" value={vehicleId} onChange={(e) => setVehicleId(Number(e.target.value))}>
            <option value="">Select…</option>
            {eligible.map((v) => (
              <option key={v.id} value={v.id}>
                {v.registration} · {pct(v.current_soc)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Target SoC % (optional)" htmlFor="ss-t">
          <Input id="ss-t" type="number" min={1} max={100} value={target} onChange={(e) => setTarget(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

export default function Operations() {
  const { can, station, stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("chargers");
  const [page, setPage] = useState(1);
  const [statusFor, setStatusFor] = useState<Charger | null>(null);
  const [powerFor, setPowerFor] = useState<Charger | null>(null);
  const [startFor, setStartFor] = useState<Charger | null>(null);
  const chargers = useQuery({ queryKey: ["chargers", station], queryFn: () => api.get<Charger[]>("/chargers", { station_id: station }) });
  const live = useQuery({ queryKey: ["sessions", "live"], queryFn: () => api.get<Page<Session>>("/charging-sessions", { active: true, page_size: 100 }), refetchInterval: 10_000 });
  const history = useQuery({ queryKey: ["sessions", "history", page], queryFn: () => api.get<Page<Session>>("/charging-sessions", { active: false, page, page_size: 20 }), enabled: tab === "history" });
  const stop = useMutation({
    mutationFn: (s: Session) => api.post(`/charging-sessions/${s.id}/stop`, { reason: "Stopped by operator" }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Session stopped" });
    },
    onError: (e) => toast.error(e),
  });
  const stationName = (id: number) => stations.find((s) => s.id === id)?.name ?? "";
  const liveRows = (live.data?.items ?? []).filter((s) => !station || chargers.data?.some((c) => c.id === s.charger_id));

  return (
    <div>
      <PageHeader title="Charging operations" description="Charger states, live sessions and session history. Charger control commands go over OCPP when a charger is connected; otherwise the simulator applies them." actions={<SimulatedTag />} />
      <Tabs<Tab>
        label="Operations views"
        value={tab}
        onChange={setTab}
        items={[
          { value: "chargers", label: "Chargers", count: chargers.data?.length },
          { value: "live", label: "Live sessions", count: liveRows.length },
          { value: "history", label: "Session history" },
        ]}
      />
      <div className="mt-4">
        {tab === "chargers" &&
          (chargers.isLoading ? (
            <LoadingBlock rows={8} />
          ) : chargers.error ? (
            <ErrorState error={chargers.error} onRetry={() => chargers.refetch()} />
          ) : (
            <Panel bodyClassName="p-0">
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[980px]">
                  <thead>
                    <tr>
                      <th>Charger</th>
                      <th>Depot</th>
                      <th>Connector</th>
                      <th className="text-right">Power</th>
                      <th>Status</th>
                      <th>Vehicle</th>
                      <th>Link</th>
                      <th className="text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(chargers.data ?? []).map((c) => (
                      <tr key={c.id} className={c.is_active ? "" : "opacity-50"}>
                        <td>
                          <div className="num font-medium">{c.code}</div>
                          {c.availability_schedule && <div className="text-2xs text-ink-3">Window {c.availability_schedule.map((w) => `${w.start}–${w.end}`).join(", ")}</div>}
                        </td>
                        <td className="text-ink-2">{stationName(c.station_id)}</td>
                        <td className="font-mono text-xs">
                          {c.connector_type}
                          {c.bidirectional && <Badge tone="info" className="ml-1.5">V2G</Badge>}
                        </td>
                        <td className="num text-right">
                          {num(c.effective_power_kw)} kW
                          {c.power_limit_kw && <div className="text-2xs text-ink-3">limited from {num(c.max_power_kw)}</div>}
                        </td>
                        <td>
                          <ChargerStatusBadge value={c.status} />
                          {c.status_note && <div className="mt-0.5 max-w-[200px] truncate text-2xs text-ink-3" title={c.status_note}>{c.status_note}</div>}
                        </td>
                        <td>{c.current_vehicle ? <Link to={`/vehicles/${c.current_vehicle_id}`} className="num hover:underline">{c.current_vehicle}</Link> : <span className="text-ink-3">—</span>}</td>
                        <td className="text-xs">{c.ocpp_identity ? <Badge tone={c.ocpp_connected ? "good" : "neutral"}>{c.ocpp_connected ? "OCPP online" : "OCPP offline"}</Badge> : <span className="text-ink-3">Simulated</span>}</td>
                        <td>
                          <div className="flex justify-end gap-1.5">
                            {can("sessions:manage") && c.status !== "charging" && c.status !== "fault" && c.status !== "maintenance" && c.is_active && (
                              <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => setStartFor(c)}>
                                Start
                              </Button>
                            )}
                            {can("chargers:state") && (
                              <>
                                <Button size="sm" icon={<Wrench className="h-3.5 w-3.5" />} onClick={() => setStatusFor(c)}>
                                  Status
                                </Button>
                                <Button size="sm" variant="ghost" icon={<Gauge className="h-3.5 w-3.5" />} onClick={() => setPowerFor(c)} aria-label={`Set power limit for ${c.code}`} />
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          ))}

        {tab === "live" && (
          <Panel bodyClassName="p-0">
            {live.isLoading ? (
              <div className="p-4">
                <LoadingBlock />
              </div>
            ) : liveRows.length === 0 ? (
              <EmptyState title="No vehicles are charging right now">Sessions start automatically at their reserved slot when the vehicle is at the depot.</EmptyState>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[980px]">
                  <thead>
                    <tr>
                      <th>Vehicle</th>
                      <th>Charger</th>
                      <th>Started</th>
                      <th className="w-[200px]">SoC → target</th>
                      <th className="text-right">Power</th>
                      <th className="text-right">Energy</th>
                      <th className="text-right">Cost</th>
                      <th>Ends</th>
                      <th>Source</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {liveRows.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <Link to={`/vehicles/${s.vehicle_id}`} className="num font-medium hover:underline">
                            {s.vehicle}
                          </Link>
                        </td>
                        <td className="num">{s.charger}</td>
                        <td className="num whitespace-nowrap">
                          {time(s.started_at)}
                          <div className="text-2xs text-ink-3">{relative(s.started_at)}</div>
                        </td>
                        <td>
                          <SocBar soc={s.current_soc ?? s.start_soc} target={s.target_soc} />
                        </td>
                        <td className="num text-right">{num(s.power_kw)} kW</td>
                        <td className="num text-right">{kwh(s.energy_kwh)}</td>
                        <td className="num text-right">{money(s.cost, 2)}</td>
                        <td className="num">{s.scheduled_end_at ? time(s.scheduled_end_at) : "at target"}</td>
                        <td>
                          <Badge tone={s.source === "ocpp" ? "good" : "neutral"}>{s.source === "ocpp" ? "OCPP" : humanize(s.source)}</Badge>
                        </td>
                        <td className="text-right">
                          {can("sessions:manage") && (
                            <Button size="sm" variant="ghost" icon={<Square className="h-3.5 w-3.5" />} loading={stop.isPending && stop.variables?.id === s.id} onClick={() => stop.mutate(s)}>
                              Stop
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}

        {tab === "history" && (
          <Panel bodyClassName="p-0">
            {history.isLoading ? (
              <div className="p-4">
                <LoadingBlock />
              </div>
            ) : history.error ? (
              <div className="p-4">
                <ErrorState error={history.error} />
              </div>
            ) : (
              <>
                <div className="scroll-thin overflow-x-auto">
                  <table className="table-base min-w-[900px]">
                    <thead>
                      <tr>
                        <th>Session</th>
                        <th>Vehicle</th>
                        <th>Charger</th>
                        <th>Window</th>
                        <th className="text-right">SoC</th>
                        <th className="text-right">Energy</th>
                        <th className="text-right">Cost</th>
                        <th>Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(history.data?.items ?? []).map((s) => (
                        <tr key={s.id}>
                          <td className="num text-ink-3">#{s.id}</td>
                          <td className="num font-medium">{s.vehicle}</td>
                          <td className="num">{s.charger}</td>
                          <td className="num whitespace-nowrap text-xs">
                            {dayTime(s.started_at)} – {time(s.ended_at)}
                          </td>
                          <td className="num text-right">
                            {pct(s.start_soc)} → {pct(s.end_soc)}
                          </td>
                          <td className="num text-right">{kwh(s.energy_kwh)}</td>
                          <td className="num text-right">{money(s.cost, 2)}</td>
                          <td>
                            <Badge tone={s.status === "completed" ? "good" : s.status === "interrupted" ? "critical" : "neutral"}>{humanize(s.status)}</Badge>
                            {s.stop_reason && <div className="mt-0.5 max-w-[220px] truncate text-2xs text-ink-3">{s.stop_reason}</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination page={page} pageSize={20} total={history.data?.total ?? 0} onPage={setPage} />
              </>
            )}
          </Panel>
        )}
      </div>
      {statusFor && <StatusModal charger={statusFor} onClose={() => setStatusFor(null)} />}
      {powerFor && <PowerModal charger={powerFor} onClose={() => setPowerFor(null)} />}
      {startFor && <StartModal charger={startFor} onClose={() => setStartFor(null)} />}
    </div>
  );
}
