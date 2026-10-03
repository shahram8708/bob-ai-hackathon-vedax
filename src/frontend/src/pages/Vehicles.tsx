import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Car, Plus, Search } from "lucide-react";
import { api } from "@/api/client";
import type { Page, Vehicle } from "@/api/types";
import { ReadinessBadge } from "@/components/status";
import { VehicleForm } from "@/components/VehicleForm";
import { Button, EmptyState, ErrorState, Input, LoadingBlock, PageHeader, Pagination, Panel, SocBar, Tabs } from "@/components/ui";
import { useSession } from "@/lib/session";
import { dayTime, humanize, kwh, relative } from "@/lib/format";

const FILTERS = ["all", "ready", "needs_charge", "charging", "at_risk", "on_trip", "maintenance"] as const;
type Filter = (typeof FILTERS)[number];

export default function Vehicles() {
  const { can, station, stations } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const readiness = (params.get("readiness") as Filter) || "all";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [debounced, setDebounced] = useState(search);
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search), 250);
    return () => window.clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(1), [debounced, readiness, station]);

  const q = useQuery({
    queryKey: ["vehicles", "list", debounced, readiness, station, page],
    queryFn: () => api.get<Page<Vehicle> & { readiness_counts: Record<string, number> }>("/vehicles", { search: debounced, readiness: readiness === "all" ? undefined : readiness, station_id: station, page, page_size: 25 }),
    placeholderData: (prev) => prev,
  });
  const counts = useQuery({
    queryKey: ["vehicles", "counts", station],
    queryFn: () => api.get<{ total: number; readiness_counts: Record<string, number> }>("/vehicles", { station_id: station, page_size: 1 }),
  });
  const stationName = (id: number | null) => stations.find((s) => s.id === id)?.code ?? "—";

  return (
    <div>
      <PageHeader
        title="Vehicles"
        description="Every vehicle with its state of charge against the requirement for its next assignment."
        actions={
          can("vehicles:manage") && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setFormOpen(true)}>
              Add vehicle
            </Button>
          )
        }
      />
      <Panel bodyClassName="p-0">
        <div className="flex flex-col gap-3 border-b border-line p-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full lg:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" aria-hidden />
            <Input aria-label="Search vehicles" placeholder="Search registration, type or driver" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
          </div>
          <Tabs<Filter>
            label="Readiness filter"
            value={readiness}
            onChange={(v) => setParams((p) => { if (v === "all") p.delete("readiness"); else p.set("readiness", v); return p; })}
            items={FILTERS.map((f) => ({ value: f, label: f === "all" ? "All" : humanize(f), count: f === "all" ? counts.data?.total : counts.data?.readiness_counts?.[f] ?? 0 }))}
          />
        </div>
        {q.isLoading ? (
          <div className="p-4">
            <LoadingBlock rows={10} />
          </div>
        ) : q.error ? (
          <div className="p-4">
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          </div>
        ) : !q.data?.items.length ? (
          <EmptyState title="No vehicles match" icon={<Car className="h-6 w-6" />}>
            Try a different search or readiness filter.
          </EmptyState>
        ) : (
          <>
            <div className="scroll-thin overflow-x-auto">
              <table className="table-base min-w-[1000px]">
                <thead>
                  <tr>
                    <th>Vehicle</th>
                    <th>Depot</th>
                    <th className="w-[210px]">SoC · required</th>
                    <th>Readiness</th>
                    <th>Next departure</th>
                    <th className="text-right">Energy needed</th>
                    <th>Driver</th>
                    <th>Priority</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((v) => (
                    <tr key={v.id} className="cursor-pointer" onClick={() => navigate(`/vehicles/${v.id}`)}>
                      <td>
                        <Link to={`/vehicles/${v.id}`} className="num font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                          {v.registration}
                        </Link>
                        <div className="text-2xs text-ink-3">
                          {v.vehicle_type} · {v.battery_capacity_kwh} kWh
                        </div>
                      </td>
                      <td className="font-mono text-xs">{v.current_station_id ? stationName(v.current_station_id) : <span className="text-ink-3">away</span>}</td>
                      <td>
                        <SocBar soc={v.current_soc} required={v.required_soc} />
                      </td>
                      <td>
                        <ReadinessBadge value={v.readiness} />
                      </td>
                      <td className="num whitespace-nowrap">
                        {v.next_trip ? (
                          <>
                            {dayTime(v.next_trip.departure_at)}
                            <div className="text-2xs text-ink-3">{relative(v.next_trip.departure_at)}</div>
                          </>
                        ) : (
                          <span className="text-ink-3">No trip</span>
                        )}
                      </td>
                      <td className="num text-right">{v.energy_to_requirement_kwh > 0 ? kwh(v.energy_to_requirement_kwh) : "—"}</td>
                      <td className="text-ink-2">{v.assigned_driver ?? <span className="text-ink-3">—</span>}</td>
                      <td className="text-xs capitalize text-ink-2">{v.priority_category}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Panel>
      <VehicleForm open={formOpen} onClose={() => setFormOpen(false)} onSaved={(v) => navigate(`/vehicles/${v.id}`)} />
    </div>
  );
}
