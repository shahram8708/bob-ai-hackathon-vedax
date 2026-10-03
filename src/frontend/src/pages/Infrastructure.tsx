import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Sun, BatteryFull } from "lucide-react";
import { ApiError, api } from "@/api/client";
import type { Charger, Station } from "@/api/types";
import { ChargerStatusBadge } from "@/components/status";
import { Badge, Button, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Panel, Select, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { num } from "@/lib/format";

const CONNECTORS = ["CCS2", "Type2", "CHAdeMO", "GB/T"];

function StationForm({ station, onClose }: { station: Station | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({
    code: station?.code ?? "",
    name: station?.name ?? "",
    address: station?.address ?? "",
    latitude: String(station?.latitude ?? ""),
    longitude: String(station?.longitude ?? ""),
    max_load_kw: station?.max_load_kw ? String(station.max_load_kw) : "",
    solar_capacity_kw: String(station?.solar_capacity_kw ?? 0),
    battery_capacity_kwh: String(station?.battery_capacity_kwh ?? 0),
    battery_power_kw: String(station?.battery_power_kw ?? 0),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));
  const m = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        address: f.address,
        latitude: Number(f.latitude),
        longitude: Number(f.longitude),
        max_load_kw: f.max_load_kw ? Number(f.max_load_kw) : null,
        solar_capacity_kw: Number(f.solar_capacity_kw || 0),
        battery_capacity_kwh: Number(f.battery_capacity_kwh || 0),
        battery_power_kw: Number(f.battery_power_kw || 0),
      };
      return station ? api.put(`/stations/${station.id}`, body) : api.post("/stations", { ...body, code: f.code });
    },
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: station ? "Depot updated" : "Depot created" });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e);
    },
  });
  const valid = f.name.trim().length >= 2 && f.latitude !== "" && f.longitude !== "" && (station || f.code.trim().length >= 2);
  return (
    <Modal
      open
      onClose={onClose}
      width="max-w-2xl"
      title={station ? `Edit ${station.name}` : "New depot / charging station"}
      description="The site load limit caps simultaneous charging power. Solar and storage feed the cost model and the scheduler's slot pricing."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={m.isPending} onClick={() => m.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {!station && (
          <Field label="Code" htmlFor="sf-code" error={errors.code} required>
            <Input id="sf-code" value={f.code} onChange={set("code")} placeholder="HSR" />
          </Field>
        )}
        <Field label="Name" htmlFor="sf-name" error={errors.name} required>
          <Input id="sf-name" value={f.name} onChange={set("name")} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Address" htmlFor="sf-addr">
            <Input id="sf-addr" value={f.address} onChange={set("address")} />
          </Field>
        </div>
        <Field label="Latitude" htmlFor="sf-lat" error={errors.latitude} required>
          <Input id="sf-lat" type="number" step="0.0001" value={f.latitude} onChange={set("latitude")} />
        </Field>
        <Field label="Longitude" htmlFor="sf-lon" error={errors.longitude} required>
          <Input id="sf-lon" type="number" step="0.0001" value={f.longitude} onChange={set("longitude")} />
        </Field>
        <Field label="Max station load (kW)" htmlFor="sf-load" hint="Empty = no site limit" error={errors.max_load_kw}>
          <Input id="sf-load" type="number" min={1} value={f.max_load_kw} onChange={set("max_load_kw")} />
        </Field>
        <Field label="On-site solar (kWp)" htmlFor="sf-solar">
          <Input id="sf-solar" type="number" min={0} value={f.solar_capacity_kw} onChange={set("solar_capacity_kw")} />
        </Field>
        <Field label="Battery storage (kWh)" htmlFor="sf-batt">
          <Input id="sf-batt" type="number" min={0} value={f.battery_capacity_kwh} onChange={set("battery_capacity_kwh")} />
        </Field>
        <Field label="Battery power (kW)" htmlFor="sf-bkw">
          <Input id="sf-bkw" type="number" min={0} value={f.battery_power_kw} onChange={set("battery_power_kw")} />
        </Field>
      </div>
    </Modal>
  );
}

function ChargerForm({ charger, stationId, onClose }: { charger: Charger | null; stationId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const w = charger?.availability_schedule?.[0];
  const [f, setF] = useState({
    code: charger?.code ?? "",
    connector_type: charger?.connector_type ?? "CCS2",
    max_power_kw: String(charger?.max_power_kw ?? 60),
    bidirectional: charger?.bidirectional ?? false,
    ocpp_identity: charger?.ocpp_identity ?? "",
    is_active: charger?.is_active ?? true,
    window: !!w,
    start: w?.start ?? "18:00",
    end: w?.end ?? "08:00",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => {
      const schedule = f.window ? [{ days: [0, 1, 2, 3, 4, 5, 6], start: f.start, end: f.end }] : null;
      const body = {
        connector_type: f.connector_type,
        max_power_kw: Number(f.max_power_kw),
        bidirectional: f.bidirectional,
        ocpp_identity: f.ocpp_identity || null,
        is_active: f.is_active,
        ...(schedule ? { availability_schedule: schedule } : charger ? { clear_availability_schedule: true } : {}),
      };
      return charger ? api.put(`/chargers/${charger.id}`, body) : api.post("/chargers", { ...body, code: f.code, station_id: stationId, availability_schedule: schedule });
    },
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: charger ? `${charger.code} updated` : "Charger created" });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e);
    },
  });
  const power = Number(f.max_power_kw);
  const valid = (charger || f.code.trim().length >= 2) && power > 0 && power <= 500 && (!f.window || (f.start && f.end && f.start !== f.end));
  return (
    <Modal
      open
      onClose={onClose}
      title={charger ? `Edit ${charger.code}` : "New charger"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={m.isPending} onClick={() => m.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {!charger && (
          <Field label="Charger ID" htmlFor="cf-code" error={errors.code} required>
            <Input id="cf-code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} placeholder="PNY-C13" />
          </Field>
        )}
        <Field label="Connector type" htmlFor="cf-conn">
          <Select id="cf-conn" value={f.connector_type} onChange={(e) => setF({ ...f, connector_type: e.target.value })}>
            {CONNECTORS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
        <Field label="Maximum power (kW)" htmlFor="cf-kw" error={errors.max_power_kw ?? (power <= 0 || power > 500 ? "1–500 kW" : undefined)}>
          <Input id="cf-kw" type="number" min={1} max={500} value={f.max_power_kw} onChange={(e) => setF({ ...f, max_power_kw: e.target.value })} />
        </Field>
        <Field label="OCPP charge point identity" htmlFor="cf-ocpp" hint="Optional — enables remote control over OCPP 1.6-J" error={errors.ocpp_identity}>
          <Input id="cf-ocpp" value={f.ocpp_identity} onChange={(e) => setF({ ...f, ocpp_identity: e.target.value })} />
        </Field>
      </div>
      <div className="mt-4 space-y-3">
        <Toggle checked={f.bidirectional} onChange={(v) => setF({ ...f, bidirectional: v })} label="Bidirectional (V2G capable)" />
        <Toggle checked={f.window} onChange={(v) => setF({ ...f, window: v })} label="Restricted availability window" description="The scheduler only books this charger inside the window." />
        {f.window && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Available from" htmlFor="cf-ws">
              <Input id="cf-ws" type="time" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />
            </Field>
            <Field label="Until" htmlFor="cf-we">
              <Input id="cf-we" type="time" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} />
            </Field>
          </div>
        )}
        {charger && <Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label="Active" description="Inactive chargers are excluded from scheduling." />}
      </div>
    </Modal>
  );
}

export default function Infrastructure() {
  const { can } = useSession();
  const [stationEdit, setStationEdit] = useState<Station | null | "new">(null);
  const [chargerEdit, setChargerEdit] = useState<{ charger: Charger | null; stationId: number } | null>(null);
  const stations = useQuery({ queryKey: ["stations"], queryFn: () => api.get<Station[]>("/stations") });
  const chargers = useQuery({ queryKey: ["chargers"], queryFn: () => api.get<Charger[]>("/chargers") });
  const admin = can("infrastructure:manage");

  if (stations.isLoading || chargers.isLoading) return <LoadingBlock rows={8} />;
  if (stations.error) return <ErrorState error={stations.error} onRetry={() => stations.refetch()} />;

  return (
    <div>
      <PageHeader
        title="Depots & chargers"
        description="Charging sites, their load limits and energy assets, and the chargers at each site."
        actions={
          admin && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setStationEdit("new")}>
              New depot
            </Button>
          )
        }
      />
      <div className="space-y-4">
        {(stations.data ?? []).map((s) => {
          const list = (chargers.data ?? []).filter((c) => c.station_id === s.id);
          const installed = list.filter((c) => c.is_active).reduce((a, c) => a + c.max_power_kw, 0);
          return (
            <Panel
              key={s.id}
              eyebrow={s.code}
              title={s.name}
              actions={
                admin && (
                  <>
                    <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setStationEdit(s)}>
                      Edit depot
                    </Button>
                    <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setChargerEdit({ charger: null, stationId: s.id })}>
                      Add charger
                    </Button>
                  </>
                )
              }
              bodyClassName="p-0"
            >
              <div className="flex flex-wrap gap-x-6 gap-y-1 border-b border-line px-4 py-2.5 text-xs text-ink-2">
                <span>{s.address}</span>
                <span>
                  Installed <strong className="num">{num(installed)} kW</strong>
                </span>
                <span>
                  Site limit <strong className="num">{s.max_load_kw ? `${num(s.max_load_kw)} kW` : "none"}</strong>
                </span>
                {s.solar_capacity_kw > 0 && (
                  <span className="flex items-center gap-1">
                    <Sun className="h-3.5 w-3.5" aria-hidden /> <span className="num">{num(s.solar_capacity_kw)} kWp</span> solar
                  </span>
                )}
                {s.battery_capacity_kwh > 0 && (
                  <span className="flex items-center gap-1">
                    <BatteryFull className="h-3.5 w-3.5" aria-hidden /> <span className="num">{num(s.battery_capacity_kwh)} kWh / {num(s.battery_power_kw)} kW</span> storage
                  </span>
                )}
              </div>
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[760px]">
                  <thead>
                    <tr>
                      <th>Charger</th>
                      <th>Connector</th>
                      <th className="text-right">Max power</th>
                      <th>Availability</th>
                      <th>Capabilities</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((c) => (
                      <tr key={c.id} className={c.is_active ? "" : "opacity-50"}>
                        <td className="num font-medium">{c.code}</td>
                        <td className="font-mono text-xs">{c.connector_type}</td>
                        <td className="num text-right">{num(c.max_power_kw)} kW</td>
                        <td className="text-xs">{c.availability_schedule ? c.availability_schedule.map((w) => `${w.start}–${w.end}`).join(", ") : "24/7"}</td>
                        <td className="space-x-1">
                          {c.bidirectional && <Badge tone="info">V2G</Badge>}
                          {c.ocpp_identity && <Badge tone={c.ocpp_connected ? "good" : "neutral"}>OCPP {c.ocpp_identity}</Badge>}
                          {!c.is_active && <Badge>Inactive</Badge>}
                        </td>
                        <td>
                          <ChargerStatusBadge value={c.status} />
                        </td>
                        <td className="text-right">{admin && <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setChargerEdit({ charger: c, stationId: s.id })} aria-label={`Edit ${c.code}`} />}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          );
        })}
      </div>
      {stationEdit && <StationForm station={stationEdit === "new" ? null : stationEdit} onClose={() => setStationEdit(null)} />}
      {chargerEdit && <ChargerForm charger={chargerEdit.charger} stationId={chargerEdit.stationId} onClose={() => setChargerEdit(null)} />}
    </div>
  );
}
