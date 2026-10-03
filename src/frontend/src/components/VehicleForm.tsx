import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/api/client";
import type { BatteryProfile, Driver, Vehicle } from "@/api/types";
import { Button, Field, Input, Modal, Select, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useSession } from "@/lib/session";

interface FormState {
  registration: string;
  battery_profile_id: string;
  current_soc: string;
  min_operating_soc: string;
  required_departure_soc: string;
  max_soc: string;
  home_station_id: string;
  priority_category: string;
  assigned_driver_id: string;
  notes: string;
}

const EMPTY: FormState = { registration: "", battery_profile_id: "", current_soc: "50", min_operating_soc: "20", required_departure_soc: "80", max_soc: "90", home_station_id: "", priority_category: "standard", assigned_driver_id: "", notes: "" };

export function VehicleForm({ open, onClose, vehicle, onSaved }: { open: boolean; onClose: () => void; vehicle?: Vehicle | null; onSaved?: (v: Vehicle) => void }) {
  const { stations } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<BatteryProfile[]>("/battery-profiles"), enabled: open });
  const drivers = useQuery({ queryKey: ["drivers"], queryFn: () => api.get<Driver[]>("/drivers"), enabled: open });

  useEffect(() => {
    if (!open) return;
    setErrors({});
    setF(
      vehicle
        ? {
            registration: vehicle.registration,
            battery_profile_id: String(vehicle.battery_profile_id),
            current_soc: String(vehicle.current_soc),
            min_operating_soc: String(vehicle.min_operating_soc),
            required_departure_soc: String(vehicle.required_departure_soc),
            max_soc: String(vehicle.max_soc),
            home_station_id: String(vehicle.home_station_id),
            priority_category: vehicle.priority_category,
            assigned_driver_id: vehicle.assigned_driver_id ? String(vehicle.assigned_driver_id) : "",
            notes: vehicle.notes,
          }
        : { ...EMPTY, home_station_id: stations[0] ? String(stations[0].id) : "" },
    );
  }, [open, vehicle, stations]);

  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  function validate() {
    const e: Record<string, string> = {};
    if (!vehicle && !/^[A-Za-z0-9][A-Za-z0-9-]{1,31}$/.test(f.registration.trim())) e.registration = "2–32 letters, digits or hyphens";
    if (!f.battery_profile_id) e.battery_profile_id = "Choose a battery profile";
    if (!f.home_station_id) e.home_station_id = "Choose a home depot";
    const n = (k: keyof FormState) => Number(f[k]);
    for (const k of ["current_soc", "min_operating_soc", "required_departure_soc", "max_soc"] as const) if (f[k] === "" || n(k) < 0 || n(k) > 100) e[k] = "0–100";
    if (!e.min_operating_soc && !e.required_departure_soc && !e.max_soc && !(n("min_operating_soc") <= n("required_departure_soc") && n("required_departure_soc") <= n("max_soc"))) e.required_departure_soc = "Must satisfy minimum ≤ required ≤ maximum";
    setErrors(e);
    return !Object.keys(e).length;
  }

  const save = useMutation({
    mutationFn: () => {
      const common = {
        battery_profile_id: Number(f.battery_profile_id),
        min_operating_soc: Number(f.min_operating_soc),
        required_departure_soc: Number(f.required_departure_soc),
        max_soc: Number(f.max_soc),
        home_station_id: Number(f.home_station_id),
        priority_category: f.priority_category,
        notes: f.notes,
      };
      if (vehicle) {
        return api.put<Vehicle>(`/vehicles/${vehicle.id}`, { ...common, ...(f.assigned_driver_id ? { assigned_driver_id: Number(f.assigned_driver_id) } : { clear_driver: true }) });
      }
      return api.post<Vehicle>("/vehicles", { ...common, registration: f.registration.trim(), current_soc: Number(f.current_soc), assigned_driver_id: f.assigned_driver_id ? Number(f.assigned_driver_id) : null });
    },
    onSuccess: (v) => {
      qc.invalidateQueries();
      toast.push({ tone: "success", title: vehicle ? `${v.registration} updated` : `${v.registration} added to the fleet`, body: "The schedule was recalculated." });
      onSaved?.(v);
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fieldErrors());
      toast.error(e, "Could not save vehicle");
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      width="max-w-2xl"
      title={vehicle ? `Edit ${vehicle.registration}` : "Add vehicle"}
      description="SoC limits drive the scheduler: it never charges above the maximum and protects the minimum operating level."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => validate() && save.mutate()}>
            {vehicle ? "Save changes" : "Add vehicle"}
          </Button>
        </>
      }
    >
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (validate()) save.mutate(); }} noValidate>
        <Field label="Registration / vehicle ID" htmlFor="vf-reg" error={errors.registration} required>
          <Input id="vf-reg" value={f.registration} onChange={set("registration")} disabled={!!vehicle} invalid={!!errors.registration} placeholder="EV-101" />
        </Field>
        <Field label="Battery profile" htmlFor="vf-prof" error={errors.battery_profile_id} required>
          <Select id="vf-prof" value={f.battery_profile_id} onChange={set("battery_profile_id")} invalid={!!errors.battery_profile_id}>
            <option value="">Select…</option>
            {(profiles.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.capacity_kwh} kWh · {p.connector_types.join("/")}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Home depot" htmlFor="vf-st" error={errors.home_station_id} required>
          <Select id="vf-st" value={f.home_station_id} onChange={set("home_station_id")}>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Priority category" htmlFor="vf-pri">
          <Select id="vf-pri" value={f.priority_category} onChange={set("priority_category")}>
            <option value="critical">Critical (always P1)</option>
            <option value="high">High</option>
            <option value="standard">Standard</option>
            <option value="low">Low</option>
          </Select>
        </Field>
        {!vehicle && (
          <Field label="Current SoC %" htmlFor="vf-soc" error={errors.current_soc} required>
            <Input id="vf-soc" type="number" min={0} max={100} value={f.current_soc} onChange={set("current_soc")} invalid={!!errors.current_soc} />
          </Field>
        )}
        <Field label="Minimum operating SoC %" htmlFor="vf-min" error={errors.min_operating_soc}>
          <Input id="vf-min" type="number" min={0} max={100} value={f.min_operating_soc} onChange={set("min_operating_soc")} invalid={!!errors.min_operating_soc} />
        </Field>
        <Field label="Default required departure SoC %" htmlFor="vf-req" error={errors.required_departure_soc}>
          <Input id="vf-req" type="number" min={0} max={100} value={f.required_departure_soc} onChange={set("required_departure_soc")} invalid={!!errors.required_departure_soc} />
        </Field>
        <Field label="Maximum permitted SoC %" htmlFor="vf-max" error={errors.max_soc}>
          <Input id="vf-max" type="number" min={0} max={100} value={f.max_soc} onChange={set("max_soc")} invalid={!!errors.max_soc} />
        </Field>
        <Field label="Assigned driver" htmlFor="vf-drv">
          <Select id="vf-drv" value={f.assigned_driver_id} onChange={set("assigned_driver_id")}>
            <option value="">Unassigned</option>
            {(drivers.data ?? []).filter((d) => d.is_active).map((d) => (
              <option key={d.id} value={d.id}>
                {d.full_name}
                {d.vehicle && d.vehicle !== vehicle?.registration ? ` (drives ${d.vehicle})` : ""}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Notes" htmlFor="vf-notes">
            <Textarea id="vf-notes" value={f.notes} onChange={set("notes")} maxLength={2000} />
          </Field>
        </div>
        <button type="submit" className="hidden" />
      </form>
    </Modal>
  );
}
