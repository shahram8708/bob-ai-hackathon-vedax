import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Pencil, Plus, Search, UserPlus } from "lucide-react";
import { ApiError, api } from "@/api/client";
import type { Driver, Page, Trip, Vehicle } from "@/api/types";
import { Badge, Button, EmptyState, ErrorState, Field, Input, LoadingBlock, Modal, PageHeader, Pagination, Panel, Select, Tabs } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";
import { dayTime, fromLocalInput, humanize, kwh, localInputValue, num, pct } from "@/lib/format";

const STATUS_TONE: Record<string, "info" | "good" | "neutral" | "warn" | "brand"> = { unassigned: "warn", assigned: "info", in_progress: "brand", completed: "good", cancelled: "neutral" };

function TripForm({ trip, onClose }: { trip: Trip | null; onClose: () => void }) {
  const { stations, station } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!trip;
  const [f, setF] = useState(() => ({
    vehicle_id: trip?.vehicle_id ? String(trip.vehicle_id) : "",
    origin_station_id: String(trip?.origin_station_id ?? station ?? stations[0]?.id ?? ""),
    destination: trip?.destination ?? "",
    distance_km: trip ? String(trip.distance_km) : "",
    energy_kwh: trip?.energy_kwh != null ? String(trip.energy_kwh) : "",
    required_soc: trip?.required_soc != null ? String(trip.required_soc) : "80",
    departure_at: localInputValue(trip ? new Date(trip.departure_at) : new Date(Date.now() + 4 * 3600_000)),
    return_at: trip?.return_at ? localInputValue(new Date(trip.return_at)) : "",
    priority: trip?.priority ?? "normal",
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const vehicles = useQuery({ queryKey: ["vehicles", "all"], queryFn: () => api.get<Page<Vehicle>>("/vehicles", { page_size: 200 }) });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  function validate() {
    const e: Record<string, string> = {};
    if (f.destination.trim().length < 2) e.destination = "Enter a destination";
    if (f.distance_km === "" || Number(f.distance_km) < 0) e.distance_km = "Enter a distance ≥ 0";
    if (f.required_soc && (Number(f.required_soc) <= 0 || Number(f.required_soc) > 100)) e.required_soc = "1–100";
    if (!f.departure_at) e.departure_at = "Choose a departure time";
    else if (!editing && new Date(fromLocalInput(f.departure_at)).getTime() < Date.now() - 5 * 60_000) e.departure_at = "Departure is in the past";
    if (f.return_at && f.departure_at && new Date(fromLocalInput(f.return_at)) <= new Date(fromLocalInput(f.departure_at))) e.return_at = "Return must be after departure";
    setErrors(e);
    return !Object.keys(e).length;
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        destination: f.destination.trim(),
        distance_km: Number(f.distance_km),
        energy_kwh: f.energy_kwh ? Number(f.energy_kwh) : null,
        required_soc: f.required_soc ? Number(f.required_soc) : null,
        departure_at: fromLocalInput(f.departure_at),
        return_at: f.return_at ? fromLocalInput(f.return_at) : null,
        priority: f.priority,
      };
      if (editing) return api.put<Trip>(`/trips/${trip!.id}`, { ...body, ...(f.vehicle_id ? { vehicle_id: Number(f.vehicle_id) } : { unassign: true }) });
      return api.post<Trip>("/trips", { ...body, origin_station_id: Number(f.origin_station_id), vehicle_id: f.vehicle_id ? Number(f.vehicle_id) : null });
    },
    onSuccess: (t) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: editing ? `${t.code} updated` : `${t.code} created`, body: t.vehicle ? `Charging for ${t.vehicle} re-planned.` : "Assign a vehicle to schedule charging." });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e, "Could not save trip");
    },
  });

  const vehicleOptions = (vehicles.data?.items ?? []).filter((v) => editing || !f.origin_station_id || v.home_station_id === Number(f.origin_station_id));

  return (
    <Modal
      open
      onClose={onClose}
      width="max-w-2xl"
      title={editing ? `Edit ${trip!.code}` : "New trip"}
      description="The scheduler uses the operator-defined required SoC when set; otherwise trip energy plus the configured safety reserve."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => validate() && save.mutate()}>
            {editing ? "Save" : "Create trip"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {!editing && (
          <Field label="Origin depot" htmlFor="tf-o" required>
            <Select id="tf-o" value={f.origin_station_id} onChange={set("origin_station_id")}>
              {stations.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Vehicle" htmlFor="tf-v" hint="Leave unassigned to plan later">
          <Select id="tf-v" value={f.vehicle_id} onChange={set("vehicle_id")}>
            <option value="">Unassigned</option>
            {vehicleOptions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.registration} · {pct(v.current_soc)} · {v.vehicle_type}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Destination" htmlFor="tf-d" error={errors.destination} required>
          <Input id="tf-d" value={f.destination} onChange={set("destination")} invalid={!!errors.destination} />
        </Field>
        <Field label="Estimated distance (km)" htmlFor="tf-km" error={errors.distance_km} required>
          <Input id="tf-km" type="number" min={0} value={f.distance_km} onChange={set("distance_km")} invalid={!!errors.distance_km} />
        </Field>
        <Field label="Expected energy (kWh)" htmlFor="tf-e" hint="Optional — derived from distance if empty">
          <Input id="tf-e" type="number" min={0} value={f.energy_kwh} onChange={set("energy_kwh")} />
        </Field>
        <Field label="Required departure SoC %" htmlFor="tf-r" error={errors.required_soc}>
          <Input id="tf-r" type="number" min={1} max={100} value={f.required_soc} onChange={set("required_soc")} invalid={!!errors.required_soc} />
        </Field>
        <Field label="Departure (fleet time)" htmlFor="tf-dep" error={errors.departure_at} required>
          <Input id="tf-dep" type="datetime-local" value={f.departure_at} onChange={set("departure_at")} invalid={!!errors.departure_at} />
        </Field>
        <Field label="Return (optional)" htmlFor="tf-ret" error={errors.return_at}>
          <Input id="tf-ret" type="datetime-local" value={f.return_at} onChange={set("return_at")} invalid={!!errors.return_at} />
        </Field>
        <Field label="Priority / urgency" htmlFor="tf-p">
          <Select id="tf-p" value={f.priority} onChange={set("priority")}>
            <option value="emergency">Emergency (P1)</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </Select>
        </Field>
      </div>
    </Modal>
  );
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ created: string[]; errors: { line: number; error: string }[] } | null>(null);
  const m = useMutation({
    mutationFn: () => api.upload<{ created: string[]; errors: { line: number; error: string }[] }>("/trips/import", file!),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries();
      toast.push({ tone: r.errors.length ? "info" : "success", title: `${r.created.length} trips imported`, body: r.errors.length ? `${r.errors.length} rows rejected` : undefined });
    },
    onError: (e) => toast.error(e, "Import failed"),
  });
  const template = () => {
    const csv = "code,vehicle,origin_station,destination,distance_km,energy_kwh,required_soc,departure_at,return_at,priority\n,EV-027,PNY,Electronic City,110,,75,2030-01-01T07:30,2030-01-01T16:00,normal\n";
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "chargeopt_trip_import_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="Import trips from CSV"
      description="Times without an offset are read in fleet local time. Each row is validated independently."
      footer={
        <>
          <Button variant="ghost" icon={<Download className="h-4 w-4" />} onClick={template}>
            Template
          </Button>
          <Button variant="primary" disabled={!file} loading={m.isPending} onClick={() => m.mutate()}>
            Import
          </Button>
        </>
      }
    >
      <Field label="CSV file (max 1 MB)" htmlFor="imp-file">
        <input id="imp-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:rounded file:border file:border-line-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm" />
      </Field>
      {result && (
        <div className="mt-4 space-y-2 text-sm">
          <p>
            <strong>{result.created.length}</strong> created{result.created.length ? `: ${result.created.slice(0, 6).join(", ")}${result.created.length > 6 ? "…" : ""}` : ""}
          </p>
          {result.errors.length > 0 && (
            <ul className="max-h-40 space-y-1 overflow-y-auto rounded border border-critical/30 bg-critical-soft p-2 text-xs text-critical-ink">
              {result.errors.map((er) => (
                <li key={er.line}>
                  Line {er.line}: {er.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Modal>
  );
}

function DriverForm({ driver, onClose }: { driver: Driver | null; onClose: () => void }) {
  const { stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ full_name: driver?.full_name ?? "", phone: driver?.phone ?? "", license_number: driver?.license_number ?? "", home_station_id: String(driver?.home_station_id ?? stations[0]?.id ?? ""), is_active: driver?.is_active ?? true });
  const valid = f.full_name.trim().length >= 2 && f.license_number.trim().length >= 4;
  const m = useMutation({
    mutationFn: () => {
      const body = { ...f, home_station_id: f.home_station_id ? Number(f.home_station_id) : null };
      return driver ? api.put(`/drivers/${driver.id}`, body) : api.post("/drivers", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["drivers"] });
      toast.push({ tone: "success", title: driver ? "Driver updated" : "Driver added" });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={driver ? `Edit ${driver.full_name}` : "Add driver"}
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
        <Field label="Full name" htmlFor="df-n" required>
          <Input id="df-n" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        </Field>
        <Field label="Licence number" htmlFor="df-l" required>
          <Input id="df-l" value={f.license_number} onChange={(e) => setF({ ...f, license_number: e.target.value })} />
        </Field>
        <Field label="Phone" htmlFor="df-p">
          <Input id="df-p" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        </Field>
        <Field label="Home depot" htmlFor="df-s">
          <Select id="df-s" value={f.home_station_id} onChange={(e) => setF({ ...f, home_station_id: e.target.value })}>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Status" htmlFor="df-a">
          <Select id="df-a" value={f.is_active ? "1" : "0"} onChange={(e) => setF({ ...f, is_active: e.target.value === "1" })}>
            <option value="1">Active</option>
            <option value="0">Inactive</option>
          </Select>
        </Field>
      </div>
    </Modal>
  );
}

export default function Trips() {
  const { can, stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"upcoming" | "all" | "drivers">("upcoming");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Trip | null | "new">(null);
  const [importOpen, setImportOpen] = useState(false);
  const [driverEdit, setDriverEdit] = useState<Driver | null | "new">(null);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search), 250);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(1), [debounced, tab]);
  const trips = useQuery({ queryKey: ["trips", tab, debounced, page], queryFn: () => api.get<Page<Trip>>("/trips", { upcoming: tab === "upcoming", search: debounced, page, page_size: 25 }), enabled: tab !== "drivers", placeholderData: (p) => p });
  const drivers = useQuery({ queryKey: ["drivers"], queryFn: () => api.get<Driver[]>("/drivers"), enabled: tab === "drivers" });
  const cancel = useMutation({
    mutationFn: (t: Trip) => api.put(`/trips/${t.id}`, { status: "cancelled" }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: "Trip cancelled", body: "Its charging requirement was released." });
    },
    onError: (e) => toast.error(e),
  });
  const station = (id: number | null) => stations.find((s) => s.id === id)?.code ?? "—";

  return (
    <div>
      <PageHeader
        title="Trips & drivers"
        description="Scheduled departures and their charging requirements. Changing a trip immediately re-plans the affected vehicle."
        actions={
          tab === "drivers"
            ? can("drivers:manage") && (
                <Button variant="primary" icon={<UserPlus className="h-4 w-4" />} onClick={() => setDriverEdit("new")}>
                  Add driver
                </Button>
              )
            : can("trips:manage") && (
                <>
                  <Button icon={<FileUp className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
                    Import CSV
                  </Button>
                  <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>
                    New trip
                  </Button>
                </>
              )
        }
      />
      <Tabs
        label="Trip views"
        value={tab}
        onChange={setTab}
        items={[
          { value: "upcoming", label: "Upcoming & active" },
          { value: "all", label: "All trips" },
          { value: "drivers", label: "Drivers" },
        ]}
      />
      <div className="mt-4">
        {tab !== "drivers" ? (
          <Panel bodyClassName="p-0">
            <div className="border-b border-line p-3">
              <div className="relative max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" aria-hidden />
                <Input aria-label="Search trips" placeholder="Trip code, vehicle or destination" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
              </div>
            </div>
            {trips.isLoading ? (
              <div className="p-4">
                <LoadingBlock rows={8} />
              </div>
            ) : trips.error ? (
              <div className="p-4">
                <ErrorState error={trips.error} onRetry={() => trips.refetch()} />
              </div>
            ) : !trips.data?.items.length ? (
              <EmptyState title="No trips found" />
            ) : (
              <>
                <div className="scroll-thin overflow-x-auto">
                  <table className="table-base min-w-[1040px]">
                    <thead>
                      <tr>
                        <th>Trip</th>
                        <th>Vehicle</th>
                        <th>Route</th>
                        <th>Departure</th>
                        <th className="text-right">Distance</th>
                        <th className="text-right">Energy</th>
                        <th className="text-right">Required</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {trips.data.items.map((t) => (
                        <tr key={t.id}>
                          <td className="num font-medium">{t.code}</td>
                          <td>{t.vehicle ? <Link to={`/vehicles/${t.vehicle_id}`} className="num hover:underline">{t.vehicle}</Link> : <Badge tone="warn">Unassigned</Badge>}</td>
                          <td className="text-xs">
                            <span className="font-mono">{station(t.origin_station_id)}</span> → {t.destination}
                          </td>
                          <td className="num whitespace-nowrap">{dayTime(t.departure_at)}</td>
                          <td className="num text-right">{num(t.distance_km)} km</td>
                          <td className="num text-right">{t.energy_kwh != null ? kwh(t.energy_kwh) : <span className="text-ink-3">derived</span>}</td>
                          <td className="num text-right">
                            {pct(t.required_soc)}
                            {t.requirement_met === false && <div className="text-2xs text-critical-ink">missed ({pct(t.departure_soc)})</div>}
                          </td>
                          <td className="text-xs">{t.priority === "emergency" ? <Badge tone="critical">Emergency</Badge> : humanize(t.priority)}</td>
                          <td>
                            <Badge tone={STATUS_TONE[t.status] ?? "neutral"}>{humanize(t.status)}</Badge>
                          </td>
                          <td className="whitespace-nowrap text-right">
                            {can("trips:manage") && ["unassigned", "assigned"].includes(t.status) && (
                              <>
                                <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(t)} aria-label={`Edit ${t.code}`} />
                                <Button size="sm" variant="ghost" onClick={() => cancel.mutate(t)}>
                                  Cancel
                                </Button>
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination page={page} pageSize={25} total={trips.data.total} onPage={setPage} />
              </>
            )}
          </Panel>
        ) : (
          <Panel bodyClassName="p-0">
            {drivers.isLoading ? (
              <div className="p-4">
                <LoadingBlock rows={8} />
              </div>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="table-base min-w-[760px]">
                  <thead>
                    <tr>
                      <th>Driver</th>
                      <th>Licence</th>
                      <th>Phone</th>
                      <th>Home depot</th>
                      <th>Vehicle</th>
                      <th>App access</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {(drivers.data ?? []).map((d) => (
                      <tr key={d.id} className={d.is_active ? "" : "opacity-50"}>
                        <td className="font-medium">{d.full_name}</td>
                        <td className="font-mono text-xs">{d.license_number}</td>
                        <td className="num text-xs">{d.phone}</td>
                        <td className="font-mono text-xs">{station(d.home_station_id)}</td>
                        <td className="num">{d.vehicle ?? <span className="text-ink-3">—</span>}</td>
                        <td className="text-xs">{d.user_email ? <Badge tone="good">{d.user_email}</Badge> : <span className="text-ink-3">No login</span>}</td>
                        <td className="text-right">
                          {can("drivers:manage") && <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setDriverEdit(d)} aria-label={`Edit ${d.full_name}`} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}
      </div>
      {editing && <TripForm trip={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
      {driverEdit && <DriverForm driver={driverEdit === "new" ? null : driverEdit} onClose={() => setDriverEdit(null)} />}
    </div>
  );
}
