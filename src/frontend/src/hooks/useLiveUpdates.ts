import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type LiveStatus = "connecting" | "live" | "offline";

const TOPIC_KEYS: Record<string, string[][]> = {
  "schedule.updated": [["schedule"], ["dashboard"], ["vehicles"], ["decisions"], ["comparison"], ["runs"], ["vehicle"], ["me-vehicle"]],
  "session.updated": [["sessions"], ["dashboard"], ["chargers"], ["vehicles"], ["schedule"], ["vehicle"], ["me-vehicle"]],
  "session.progress": [["sessions"], ["dashboard"]],
  "charger.updated": [["chargers"], ["dashboard"], ["schedule"]],
  "fleet.updated": [["vehicles"], ["vehicle"], ["trips"], ["dashboard"], ["schedule"], ["decisions"], ["me-vehicle"]],
  "alert.created": [["alerts"], ["dashboard"]],
  "alert.updated": [["alerts"], ["dashboard"]],
  "tariff.updated": [["tariffs"], ["dashboard"], ["schedule"]],
  "config.updated": [["config"], ["dashboard"], ["simulation"]],
  tick: [["dashboard"], ["simulation"]],
};

export function useLiveUpdates(enabled: boolean) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [lastAlert, setLastAlert] = useState<{ id: number; title: string; severity: string } | null>(null);
  const pending = useRef(new Set<string>());
  const flushTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let retry = 0;
    let closed = false;
    let reconnectTimer: number | null = null;
    let heartbeat: number | null = null;

    const flush = () => {
      flushTimer.current = null;
      const keys = [...pending.current];
      pending.current.clear();
      for (const k of keys) qc.invalidateQueries({ queryKey: JSON.parse(k) });
    };

    const connect = () => {
      setStatus("connecting");
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/api/ws`);
      socket.onopen = () => {
        retry = 0;
        setStatus("live");
        heartbeat = window.setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send("ping"), 25_000);
      };
      socket.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as { topic: string; payload: Record<string, unknown> };
          if (msg.topic === "alert.created") setLastAlert(msg.payload as { id: number; title: string; severity: string });
          for (const key of TOPIC_KEYS[msg.topic] ?? []) pending.current.add(JSON.stringify(key));
          if (pending.current.size && flushTimer.current === null) flushTimer.current = window.setTimeout(flush, 600);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (heartbeat) window.clearInterval(heartbeat);
        if (closed) return;
        setStatus("offline");
        retry = Math.min(retry + 1, 6);
        reconnectTimer = window.setTimeout(connect, 1000 * 2 ** retry);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (heartbeat) window.clearInterval(heartbeat);
      socket?.close();
    };
  }, [enabled, qc]);

  return { status, lastAlert };
}
