import { useQuery } from "@tanstack/react-query";
import { CalendarClock, MapPin, PlugZap } from "lucide-react";
import { api } from "@/api/client";
import type { Driver as DriverT, Reservation, Vehicle } from "@/api/types";
import { ReadinessBadge, ReservationBadge } from "@/components/status";
import { EmptyState, ErrorState, LoadingBlock, Panel, SocBar } from "@/components/ui";
import { dayTime, kwh, pct, relative, time } from "@/lib/format";

interface MyVehicle {
  driver: DriverT;
  vehicle: Vehicle | null;
  home_station?: string;
  reservations?: Reservation[];
  instructions?: string[];
}

export default function Driver() {
  const q = useQuery({ queryKey: ["me-vehicle"], queryFn: () => api.get<MyVehicle>("/me/vehicle"), refetchInterval: 20_000 });
  if (q.isLoading) return <LoadingBlock rows={6} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const { driver, vehicle, reservations = [], instructions = [], home_station } = q.data;

  return (
    <div className="mx-auto max-w-2xl">
      <div className="eyebrow">Hello, {driver.full_name.split(" ")[0]}</div>
      <h1 className="text-[1.375rem] font-semibold">My vehicle</h1>
      {!vehicle ? (
        <div className="panel mt-5">
          <EmptyState title="No vehicle is assigned to you">Ask your operations manager to assign a vehicle.</EmptyState>
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          <Panel eyebrow={`${vehicle.vehicle_type} · ${home_station ?? ""}`} title={vehicle.registration} actions={<ReadinessBadge value={vehicle.readiness} />}>
            <div className="flex items-end justify-between gap-4">
              <div>
                <div className="eyebrow">Current charge</div>
                <div className="num text-[2.75rem] font-medium leading-none">{pct(vehicle.current_soc)}</div>
              </div>
              <div className="text-right">
                <div className="eyebrow">Required for next trip</div>
                <div className="num text-2xl">{pct(vehicle.required_soc)}</div>
              </div>
            </div>
            <div className="mt-4">
              <SocBar soc={vehicle.current_soc} required={vehicle.required_soc} showLabel={false} />
            </div>
            {vehicle.energy_to_requirement_kwh > 0 && <p className="mt-2 text-xs text-ink-3">{kwh(vehicle.energy_to_requirement_kwh)} still needed to reach the requirement.</p>}
          </Panel>

          <Panel eyebrow="What to do" title="Charging instructions">
            <ul className="space-y-3">
              {instructions.map((t, i) => (
                <li key={i} className="flex gap-3 text-[0.9375rem] leading-relaxed">
                  <PlugZap className="mt-1 h-4 w-4 shrink-0 text-brand" aria-hidden />
                  {t}
                </li>
              ))}
            </ul>
          </Panel>

          {vehicle.next_trip && (
            <Panel eyebrow="Next trip" title={vehicle.next_trip.code}>
              <div className="grid gap-3 text-sm sm:grid-cols-2">
                <div className="flex items-center gap-2">
                  <CalendarClock className="h-4 w-4 text-ink-3" aria-hidden />
                  <span className="num">{dayTime(vehicle.next_trip.departure_at)}</span>
                  <span className="text-ink-3">({relative(vehicle.next_trip.departure_at)})</span>
                </div>
                <div className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-ink-3" aria-hidden />
                  {vehicle.next_trip.destination} · {vehicle.next_trip.distance_km} km
                </div>
              </div>
            </Panel>
          )}

          {reservations.length > 0 && (
            <Panel eyebrow="Reserved chargers" title="Charging slots" bodyClassName="p-0">
              <ul className="divide-y divide-line">
                {reservations.map((r) => (
                  <li key={r.id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <div className="num font-medium">{r.charger}</div>
                      <div className="num text-sm text-ink-2">
                        {dayTime(r.start_at)} – {time(r.end_at)} · to {pct(r.target_soc)}
                      </div>
                    </div>
                    <ReservationBadge value={r.status} />
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
