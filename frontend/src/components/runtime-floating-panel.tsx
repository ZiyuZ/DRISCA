import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, SlidersHorizontal, Square } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeState, ViewMode } from "../types/api";
import { FloatingActionCard } from "./floating-action-card";
import { Button } from "./ui/button";

const views: readonly { mode: ViewMode; label: string }[] = [
  { mode: "free", label: "自由" },
  { mode: "cockpit", label: "车内" },
  { mode: "chase", label: "第三人称" },
];

export function RuntimeFloatingPanel({ state, disabled }: { state: RuntimeState; disabled: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  const [pending, setPending] = useState(false);
  const activity = state.phase === "running" ? "experiment"
    : state.traffic_preview.running ? "preview" : state.replay.running ? "replay" : null;
  if (!activity) return null;
  const label = activity === "experiment" ? "实验中" : activity === "preview" ? "车流预览" : "回放中";
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
      aria-label={`展开运行控制：${label}`} aria-expanded={false} onClick={() => setCollapsed(false)}>
      {dot}<span>{label}</span><SlidersHorizontal className="size-3.5" />
    </Button>
  );
  return (
    <FloatingActionCard title="运行控制" icon={dot}
      badge={activity === "preview" ? `车流预览 · ${state.traffic_preview.vehicle_count} 辆` : activity === "replay" ? "录像回放" : "实验中"}
      description={activity === "replay" ? state.replay.name : undefined}
      headerAction={<Button variant="ghost" size="icon-xs" aria-label="收起运行控制" aria-expanded={true} onClick={() => setCollapsed(true)}><ChevronDown /></Button>}>
        <div className={`grid gap-1 rounded-md border bg-muted/30 p-1 ${activity === "experiment" ? "grid-cols-2" : "grid-cols-3"}`} role="group" aria-label="运行视角">
          {views.filter(view => activity !== "experiment" || view.mode !== "free").map(view => (
            <Button key={view.mode} size="sm" variant={state.view_mode === view.mode ? "secondary" : "ghost"}
              aria-pressed={state.view_mode === view.mode} disabled={disabled || pending}
              onClick={() => {
                if (state.view_mode !== view.mode) void submit("/api/view/mode", { mode: view.mode }, `已切换为${view.label}视角`);
              }}>{view.label}</Button>
          ))}
        </div>
        {activity === "preview" && state.view_mode !== "free" && (
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">观察车辆</span>
            <div className="flex items-center rounded-md border" role="group" aria-label="切换观察车辆">
              <Button size="icon-xs" variant="ghost" aria-label="上一辆" disabled={disabled || pending}
                onClick={() => void submit("/api/traffic/preview/follow", { delta: -1 }, "已切换观察车辆")}><ChevronLeft /></Button>
              <span className="min-w-12 px-1 text-center font-mono text-xs" role="status">{state.traffic_preview.follow_actor_id == null ? "—" : `#${state.traffic_preview.follow_actor_id}`}</span>
              <Button size="icon-xs" variant="ghost" aria-label="下一辆" disabled={disabled || pending}
                onClick={() => void submit("/api/traffic/preview/follow", { delta: 1 }, "已切换观察车辆")}><ChevronRight /></Button>
            </div>
          </div>
        )}
      {activity === "replay" && (
        <div className="flex items-center justify-between gap-2 border-t pt-3">
          <span className="text-xs text-muted-foreground">观察车辆</span>
          <div className="flex items-center gap-1 rounded-md border p-1" role="group" aria-label="选择回放观察车辆">
          <Button size="sm" variant="ghost" disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "hero" }, "回放已跟随主车")}>主车</Button>
          <Button size="icon-sm" variant="ghost" aria-label="观察上一辆回放车辆" disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "prev" }, "回放已切换到上一辆车")}><ChevronLeft /></Button>
          <Button size="icon-sm" variant="ghost" aria-label="观察下一辆回放车辆" disabled={disabled || pending}
            onClick={() => void submit("/api/recordings/follow", { target: "next" }, "回放已切换到下一辆车")}><ChevronRight /></Button>
          </div>
        </div>
      )}
      <div className="flex justify-end border-t pt-3">
        <Button variant="destructive" size="sm" disabled={disabled || pending}
          onClick={() => void submit(
            activity === "experiment" ? "/api/experiment/stop" : activity === "preview" ? "/api/traffic/preview/stop" : "/api/recordings/stop",
            undefined,
            activity === "experiment" ? "实验已结束" : activity === "preview" ? "车流预览已停止" : "录像回放已停止",
          )}>
          <Square className="size-3" />{activity === "experiment" ? "结束实验" : activity === "preview" ? "停止预览" : "停止回放"}
        </Button>
      </div>
    </FloatingActionCard>
  );
}
