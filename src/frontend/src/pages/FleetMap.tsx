import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, Tooltip } from "react-leaflet";
import { api } from "@/api/client";
import type { Charger, Page, Vehicle } from "@/api/types";
import { ReadinessBadge } from "@/components/status";
import { ErrorState, LoadingBlock, PageHeader, Panel, SocBar, Toggle } from "@/components/ui";
import { useSession } from "@/lib/session";
import { num, pct } from "@/lib/format";

interface Provider {
  id: number;
  name: string;
  kind: string;
  latitude: number;
  longitude: number;
  is_directory_sample: boolean;
}

const READINESS_COLOR: Record<string, string> = {
  ready: "#0CA30C",
  charging: "#1F4D3A",
  needs_charge: "#FAB219",
  at_risk: "#D03B3B",
  on_trip: "#2A78D6",
  maintenance: "#86837B",
  out_of_service: "#86837B",
};

function depotIcon(code: string, free: number, total: number) {
  return L.divIcon({
    className: "",
    html: `<div style="transform:translate(-50%,-50%);display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:6px;background:#1F4D3A;color:#F4F2ED;font:500 12px 'IBM Plex Mono',monospace;box-shadow:0 2px 8px rgba(0,0,0,.25);white-space:nowrap">${code}<span style="color:#C9E86A">${free}/${total}</span></div>`,
    iconSize: [0, 0],
  });
}

export default function FleetMap() {
  const { stations } = useSession();
  const [showVehicles, setShowVehicles] = useState(true);
  const [showProviders, setShowProviders] = useState(true);
  const vehicles = useQuery({ queryKey: ["vehicles", "map"], queryFn: () => api.get<Page<Vehicle>>("/vehicles", { page_size: 200 }) });
  const chargers = useQuery({ queryKey: ["chargers"], queryFn: () => api.get<Charger[]>("/chargers") });
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Provider[]>("/service-providers") });

  const center = useMemo<[number, number]>(() => {
    if (!stations.length) return [12.97, 77.59];
    return [stations.reduce((a, s) => a + s.latitude, 0) / stations.length, stations.reduce((a, s) => a + s.longitude, 0) / stations.length];
  }, [stations]);

  const spread = (v: Vehicle, i: number): [number, number] => {
    const lat = v.latitude ?? 0;
    const lon = v.longitude ?? 0;
    if (v.availability === "on_trip") return [lat, lon];
    const angle = (i * 137.5 * Math.PI) / 180;
    const r = 0.008 + (i % 6) * 0.0035;
    return [lat + r * Math.sin(angle), lon + r * Math.cos(angle)];
  };

  if (vehicles.isLoading || chargers.isLoading) return <LoadingBlock rows={8} />;
  if (vehicles.error) return <ErrorState error={vehicles.error} onRetry={() => vehicles.refetch()} />;
  const list = vehicles.data?.items ?? [];
  const away = list.filter((v) => v.availability === "on_trip");

  return (
    <div>
      <PageHeader title="Fleet map" description="Depots with free chargers, vehicles by readiness and contingency providers. Vehicles parked at a depot are fanned out around it for legibility." />
      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <div className="panel self-start overflow-hidden">
          <div className="h-[calc(100vh-220px)] min-h-[420px]">
            <MapContainer center={center} zoom={11} scrollWheelZoom className="h-full w-full" attributionControl>
              <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {stations.map((s) => {
                const cs = (chargers.data ?? []).filter((c) => c.station_id === s.id && c.is_active);
                return (
                  <Marker key={s.id} position={[s.latitude, s.longitude]} icon={depotIcon(s.code, cs.filter((c) => c.status === "available").length, cs.length)}>
                    <Popup>
                      <strong>{s.name}</strong>
                      <br />
                      {cs.length} chargers · load limit {s.max_load_kw ? `${num(s.max_load_kw)} kW` : "none"}
                      {s.solar_capacity_kw > 0 && (
                        <>
                          <br />
                          Solar {num(s.solar_capacity_kw)} kW
                        </>
                      )}
                      {s.battery_capacity_kwh > 0 && (
                        <>
                          <br />
                          Storage {num(s.battery_capacity_kwh)} kWh
                        </>
                      )}
                    </Popup>
                  </Marker>
                );
              })}
              {showVehicles &&
                list.map((v, i) =>
                  v.latitude !== null && v.longitude !== null ? (
                    <CircleMarker key={v.id} center={spread(v, i)} radius={v.readiness === "at_risk" ? 7 : 5} pathOptions={{ color: "#FCFCFB", weight: 1.5, fillColor: READINESS_COLOR[v.readiness] ?? "#86837B", fillOpacity: 0.95 }}>
                      <Tooltip direction="top" offset={[0, -4]}>
                        {v.registration} · {pct(v.current_soc)}
                      </Tooltip>
                      <Popup>
                        <strong>{v.registration}</strong> · {v.vehicle_type}
                        <br />
                        SoC {pct(v.current_soc)} / required {pct(v.required_soc)}
                        <br />
                        <a href={`/vehicles/${v.id}`}>Open vehicle</a>
                      </Popup>
                    </CircleMarker>
                  ) : null,
                )}
              {showProviders &&
                (providers.data ?? []).map((p) => (
                  <CircleMarker key={`p${p.id}`} center={[p.latitude, p.longitude]} radius={5} pathOptions={{ color: "#4A3AA7", weight: 2, fillColor: "#FCFCFB", fillOpacity: 1 }}>
                    <Tooltip>{p.name}</Tooltip>
                  </CircleMarker>
                ))}
            </MapContainer>
          </div>
        </div>
        <div className="space-y-4">
          <Panel eyebrow="Layers" title="Map layers">
            <div className="space-y-3">
              <Toggle checked={showVehicles} onChange={setShowVehicles} label="Vehicles" description="Coloured by readiness" />
              <Toggle checked={showProviders} onChange={setShowProviders} label="Contingency providers" description="Public chargers, mobile charging, towing" />
            </div>
            <ul className="mt-4 grid grid-cols-2 gap-1.5 text-xs text-ink-2">
              {Object.entries(READINESS_COLOR)
                .filter(([k]) => k !== "out_of_service")
                .map(([k, c]) => (
                  <li key={k} className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} aria-hidden />
                    {k.replace("_", " ")}
                  </li>
                ))}
            </ul>
          </Panel>
          <Panel eyebrow="On the road" title={`${away.length} vehicles on trips`} bodyClassName="p-0">
            <ul className="scroll-thin max-h-[420px] divide-y divide-line overflow-y-auto">
              {away.map((v) => (
                <li key={v.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between">
                    <Link to={`/vehicles/${v.id}`} className="num text-sm font-medium hover:underline">
                      {v.registration}
                    </Link>
                    <ReadinessBadge value={v.readiness} />
                  </div>
                  <div className="mt-1">
                    <SocBar soc={v.current_soc} size="sm" />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
