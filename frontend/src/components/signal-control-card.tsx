import { zhCN, format } from "../i18n";
import { useState } from "react";
import { LockKeyhole, LockOpen } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeState } from "../types/api";
import { Button } from "./ui/button";
import { FloatingActionCard } from "./floating-action-card";

type Signal = NonNullable<RuntimeState["selected_signal"]>;
const lights = [
  { state: "red", label: zhCN.floating.red, dot: "bg-red-500", active: "border-red-500 bg-red-500/10 text-red-700 dark:text-red-300" },
  { state: "yellow", label: zhCN.floating.yellow, dot: "bg-amber-500", active: "border-amber-500 bg-amber-500/10 text-amber-800 dark:text-amber-300" },
  { state: "green", label: zhCN.floating.green, dot: "bg-emerald-500", active: "border-emerald-500 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300" },
] as const;

export function SignalControlCard({ signal, disabled }: { signal: Signal; disabled: boolean }) {
  const [pending, setPending] = useState(false);
  const current = lights.find(light => light.state === signal.state);
  const submit = async (url: string, body: unknown, success: string) => {
    setPending(true);
    try {
      await api(url, "POST", body);
      toast.success(success);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  };
  return (
    <FloatingActionCard title={format(zhCN.floating.signalTitle, { actorId: signal.actor_id })} description={signal.signal_id}
      badge={signal.frozen ? zhCN.floating.frozen : undefined}
      icon={<span className={`size-2.5 shrink-0 rounded-full ${current?.dot ?? "bg-slate-400"}`} aria-hidden="true" />}>
        <span className="sr-only" role="status">{zhCN.floating.currentSignal}{current?.label ?? (signal.state === "off" ? zhCN.floating.off : signal.state)}</span>
        <div className="grid grid-cols-3 gap-2" role="group" aria-label={zhCN.floating.signalActions}>
          {lights.map(light => (
            <Button key={light.state} size="sm" variant="outline" aria-pressed={signal.state === light.state}
              className={signal.state === light.state ? light.active : undefined}
              disabled={disabled || pending}
              onClick={() => void submit(`/api/traffic-lights/${signal.actor_id}/state`, { state: light.state }, format(zhCN.floating.signalChanged, { actorId: signal.actor_id, label: light.label }))}>
              {light.label}
            </Button>
          ))}
        </div>
        {signal.group_id !== null && (
          <div className="border-t pt-3">
            <Button variant={signal.frozen ? "secondary" : "outline"} size="sm" className="w-full"
              aria-pressed={signal.frozen} disabled={disabled || pending}
              onClick={() => void submit(`/api/traffic-lights/groups/${signal.group_id}/freeze`, { frozen: !signal.frozen }, signal.frozen ? zhCN.floating.groupUnfrozen : zhCN.floating.groupFrozen)}>
              {signal.frozen ? <LockOpen /> : <LockKeyhole />}
              {signal.frozen ? zhCN.floating.unfreezeGroup : zhCN.floating.freezeGroup}
            </Button>
          </div>
        )}
    </FloatingActionCard>
  );
}
