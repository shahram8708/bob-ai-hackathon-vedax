import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, setUnauthorizedHandler } from "@/api/client";
import type { OperationalConfig, Station, User } from "@/api/types";
import { setFleetLocale } from "@/lib/format";

interface SessionValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  can: (...perms: string[]) => boolean;
  config: OperationalConfig | null;
  stations: Station[];
  station: number | null;
  setStation: (id: number | null) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [station, setStationState] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem("chargeopt.station");
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    api
      .get<{ user: User | null }>("/auth/session")
      .then((r) => setUser(r.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      qc.clear();
    });
  }, [qc]);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<{ config: OperationalConfig }>("/config"),
    enabled: !!user,
    staleTime: 60_000,
  });
  const stationsQuery = useQuery({
    queryKey: ["stations"],
    queryFn: () => api.get<Station[]>("/stations"),
    enabled: !!user,
    staleTime: 5 * 60_000,
  });

  const config = configQuery.data?.config ?? null;
  if (config) setFleetLocale(config.timezone, config.currency);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ user: User }>("/auth/login", { email, password });
      qc.clear();
      setUser(res.user);
      return res.user;
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    setUser(null);
    qc.clear();
  }, [qc]);

  const setStation = useCallback((id: number | null) => {
    setStationState(id);
    try {
      if (id) localStorage.setItem("chargeopt.station", String(id));
      else localStorage.removeItem("chargeopt.station");
    } catch {
      /* storage unavailable */
    }
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      user,
      loading,
      login,
      logout,
      can: (...perms) => !!user && perms.some((p) => user.permissions.includes(p)),
      config,
      stations: stationsQuery.data ?? [],
      station,
      setStation,
    }),
    [user, loading, login, logout, config, stationsQuery.data, station, setStation],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
