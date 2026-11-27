import { zhCN, format } from "../i18n";
import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, SlidersHorizontal, Square } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeState, ViewMode } from "../types/api";
import { FloatingActionCard } from "./floating-action-card";
import { Button } from "./ui/button";

const views: readonly { mode: ViewMode; label: string }[] = [
  { mode: "free", label: zhCN.floating.free },
  { mode: "cockpit", label: zhCN.floating.cockpit },
  { mode: "chase", label: zhCN.floating.chase },
];

export function RuntimeFloatingPanel({ state, disabled }: { state: RuntimeState; disabled: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  const [pending, setPending] = useState(false);
  const activity = state.phase === "running" ? "experiment"
    : state.traffic_preview.running ? "preview" : state.replay.running ? "replay" : null;
  if (!activity) return null;
  const label = activity === "experiment" ? zhCN.status.running : activity === "preview" ? zhCN.floating.preview : zhCN.floating.replay;
  const dot = <span className="size-2 shrink-0 rounded-full bg-emerald-500" aria-hidden="true" />;
  const submit = async (path: string, body: unknown, success: string) => {
    setPending(true);
    try {
      await api(path, "POST", body);
      toast.success(success);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  };
  if (collapsed) return (
    <Button variant="outline" className="floating-action-card pointer-events-auto h-10 rounded-full bg-card px-4 shadow-lg"
      aria-label={format(zhCN.floating.expand, { label: label })} aria-expanded={false} onClick={() => setCollapsed(false)}>
      {dot}<span>{label}</span><SlidersHorizontal className="size-3.5" />
    </Button>
  );
  return (
    <FloatingActionCard title={zhCN.floating.title} icon={dot}
      badge={activity === "preview" ? format(zhCN.floating.previewCount, { vehicleCount: state.traffic_preview.vehicle_count }) : activity === "replay" ? zhCN.floating.replayTitle : zhCN.status.running}
      description={activity === "replay" ? state.replay.name : undefined}
      headerAction={<Button variant="ghost" size="icon-xs" aria-label={zhCN.floating.collapse} aria-expanded={true} onClick={() => setCollapsed(true)}><ChevronDown /></Button>}>
        <div className={`grid gap-1 rounded-md border bg-muted/30 p-1 ${activity === "experiment" ? "grid-cols-2" : "grid-cols-3"}`} role="group" aria-label={zhCN.floating.viewMode}>
          {views.filter(view => activity !== "experiment" || view.mode !== "free").map(view => (
            <Button key={view.mode} size="sm" variant={state.view_mode === view.mode ? "secondary" : "ghost"}
              aria-pressed={state.view_mode === view.mode} disabled={disabled || pending}
              onClick={() => {
                if (state.view_mode !== view.mode) void submit("/api/view/mode", { mode: view.mode }, format(zhCN.floating.viewChanged, { label: view.label }));
              }}>{view.label}</Button>
          ))}
        </div>
        {activity === "preview" && state.view_mode !== "free" && (
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">{zhCN.floating.followedVehicle}</span>
            <div className="flex items-center rounded-md border" role="group" aria-label={zhCN.floating.changeVehicle}>
              <Button size="icon-xs" variant="ghost" aria-label={zhCN.floating.previousVehicle} disabled={disabled || pending}
                onClick={() => void submit("/api/traffic/preview/follow", { delta: -1 }, zhCN.floating.followedVehicleChanged)}><ChevronLeft /></Button>
              <span className="min-w-12 px-1 text-center font-mono text-xs" role="status">{state.traffic_preview.follow_actor_id == null ? "—" : `#${state.traffic_preview.follow_actor_id}`}</span>
              <Button size="icon-xs" variant="ghost" aria-label={zhCN.floating.nextVehicle} disabled={disabled || pending}
                onClick={() => void submit("/api/traffic/preview/follow", { delta: 1 }, zhCN.floating.followedVehicleChanged)}><ChevronRight /></Button>
            </div>
          </div>
        )}
      {activity === "replay" && (
        <div className="flex items-center justify-between gap-2 border-t pt-3">
          <span className="text-xs text-muted-foreground">{zhCN.floating.followedVehicle}</span>
          <div className="flex items-center gap-1 rounded-md border p-1" role="group" aria-label={zhCN.floating.replayVehicle}>
          <Button size="sm" variant="ghost" disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "hero" }, zhCN.floating.followHeroSuccess)}>{zhCN.floating.hero}</Button>
          <Button size="icon-sm" variant="ghost" aria-label={zhCN.floating.replayPrevious} disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "prev" }, zhCN.floating.replayPreviousSuccess)}><ChevronLeft /></Button>
          <Button size="icon-sm" variant="ghost" aria-label={zhCN.floating.replayNext} disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "next" }, zhCN.floating.replayNextSuccess)}><ChevronRight /></Button>
          </div>
        </div>
      )}
      <div className="flex justify-end border-t pt-3">
        <Button variant="destructive" size="sm" disabled={disabled || pending}
          onClick={() => void submit(
            activity === "experiment" ? "/api/experiment/stop" : activity === "preview" ? "/api/traffic/preview/stop" : "/api/recordings/stop",
            undefined,
            activity === "experiment" ? zhCN.floating.experimentStopped : activity === "preview" ? zhCN.floating.previewStopped : zhCN.floating.replayStopped,
          )}>
          <Square className="size-3" />{activity === "experiment" ? zhCN.floating.stopExperiment : activity === "preview" ? zhCN.floating.stopPreview : zhCN.floating.stopReplay}
        </Button>
      </div>
    </FloatingActionCard>
  );
}
