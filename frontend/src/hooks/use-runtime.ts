import { zhCN } from "../i18n";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { Bootstrap, RuntimeState } from "../types/api";

export function useRuntime() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [state, setState] = useState<RuntimeState | null>(null);
  const [logs, setLogs] = useState<Record<string, unknown>[]>([]);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let stream: EventSource | undefined;
    void api<Bootstrap>("/api/bootstrap").then(data => {
      if (!active) return;
      setBoot(data); setState(data.state); setLogs(data.logs); setEvents(data.events);
      stream = new EventSource("/api/events");
      stream.onopen = () => setOnline(true);
      stream.onerror = () => setOnline(false);
      stream.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "state") setState(message.data);
        if (message.type === "telemetry") {
          setState(current => current ? { ...current, telemetry: message.data } : current);
        }
        if (message.type === "log") {
          setLogs(items => [...items.slice(-499), message.data]);
          const level = String(message.data.level ?? "").toUpperCase();
          if (level === "ERROR" || level === "CRITICAL") {
            toast.error(String(message.data.message ?? zhCN.status.backendError));
          }
        }
        if (message.type === "experiment_event") setEvents(items => [...items.slice(-499), message.data]);
      };
    }).catch(error => { if (active) setError(String(error)); });
    return () => { active = false; stream?.close(); };
  }, []);
  return { boot, setBoot, state, logs, events, setLogs, setEvents, online, error };
}
