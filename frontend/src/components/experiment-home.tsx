import {
  Eraser, Gauge,
  Lock, Pencil, Play,
  Plus,
  SlidersHorizontal,
  Square
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type {
  Bootstrap,
  Instruction,
  PresetConfig,
  RuntimeState,
} from "../types/api";
import { Hint } from "./hint";
import { Modal } from "./common";
import { IconAction } from "./icon-action";
import { spawnBound } from "../lib/spawn";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

type Run = NonNullable<RuntimeState["active_run"]>;
type Entry = Record<string, unknown>;
type Props = {
  state: RuntimeState;
  running: boolean;
  busy: boolean;
  serviceOnline: boolean;
  preset: PresetConfig | null;
  run: Run;
  commands: Bootstrap["commands"];
  logs: Entry[];
  events: Entry[];
  setRun: (run: Run) => void;
  onStartStop: () => void;
  onMarker: (label: string) => void;
  onEditMarkers: () => void;
  onEditInstruction: (item?: Instruction) => void;
  onExecute: (item: Instruction) => void;
  onClear: () => void;
};

export function ExperimentHome({
  state,
  running,
  busy,
  serviceOnline,
  preset,
  run,
  commands,
  logs,
  events,
  setRun,
  onStartStop,
  onMarker,
  onEditMarkers,
  onEditInstruction,
  onExecute,
  onClear,
}: Props) {
  const [logTab, setLogTab] = useState<"logs" | "events">("logs");
  const [viewPending, setViewPending] = useState(false);
  const [logDetail, setLogDetail] = useState<string | null>(null);
  const copyDetail = async () => {
    if (logDetail === null) return;
    try {
      await navigator.clipboard.writeText(logDetail);
      toast.success("日志详情已复制");
    } catch (error) {
      toast.error(`复制失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };
  const t = state.telemetry;
  const entries = logTab === "logs" ? logs : events;
  const spawnReady = !preset || spawnBound(preset);
  const changeView = async (mode: "cockpit" | "chase") => {
    if (mode === state.view_mode) return;
    setViewPending(true);
    try {
      await api("/api/view/mode", "POST", { mode });
      toast.success(`已切换为${mode === "cockpit" ? "车内视角" : "第三人称"}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setViewPending(false);
    }
  };
  const startBlocked = !state.carla_connected || !spawnReady;
  return (
    <fieldset className="home-layout settings-fields" disabled={!serviceOnline}>
      <div className="control-top-row">
        <Card className="dr-card driving-card gap-0">
          <header className="driving-card-heading">
            <h2>驾驶状态</h2>
            <div className="row">
              <span className="dr-badge">
                {t
                  ? t.takeover_requested
                    ? "接管请求中"
                    : t.control_mode === "autopilot"
                      ? "自动驾驶"
                      : "人工驾驶"
                  : state.phase === "starting"
                    ? "正在启动"
                    : state.phase === "stopping"
                      ? "正在结束"
                      : "待启动"}
              </span>
            </div>
          </header>
          <label className="dr-field driving-subject">
            <span>被试编号</span>
            <Input
              className="input"
              placeholder="被试编号"
              value={
                state.phase === "idle"
                  ? run.subject_id
                  : (state.active_run?.subject_id ?? run.subject_id)
              }
              disabled={state.phase !== "idle"}
              onChange={(e) => setRun({ ...run, subject_id: e.target.value })}
            />
          </label>
          <div className="driving-readings">
            <div className="live-speed">
              <span className="speed mono">
                {t ? (t.speed_mps * 3.6).toFixed(1) : "—"}
              </span>
              <span className="unit">km/h</span>
              <span className="gear mono">{t?.gear ?? "—"}</span>
              <span className="small">
                限速{" "}
                <span className="mono">
                  {t ? (t.speed_limit_mps * 3.6).toFixed(0) : "—"}
                </span>{" "}
                km/h
              </span>
            </div>
            <div className="three live-meters">
              {(
                [
                  ["throttle", "油门", ""],
                  ["brake", "刹车", "brake"],
                  ["steer", "转向", "steer"],
                ] as const
              ).map(([key, label, kind]) => (
                <div key={key}>
                  <div className="meter-label">
                    <span>{label}</span>
                    <span className="mono">
                      {t ? t[key].toFixed(2) : "—"}
                    </span>
                  </div>
                  <div className={`meter ${kind}`}>
                    <span
                      style={{ width: `${Math.abs(t?.[key] ?? 0) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <footer className="driving-card-footer">
            <div className="small mono">
              {t
                ? `${t.simulator_fps.toFixed(0)} FPS · ${t.frame_no.toLocaleString()} 帧`
                : null}
            </div>
            {running && (
              <div className="flex items-center gap-1.5" role="group" aria-label="运行视角">
                <Button size="sm" variant={state.view_mode === "cockpit" ? "default" : "outline"}
                  disabled={viewPending} onClick={() => void changeView("cockpit")}>
                  车内视角
                </Button>
                <Button size="sm" variant={state.view_mode === "chase" ? "default" : "outline"}
                  disabled={viewPending} onClick={() => void changeView("chase")}>
                  第三人称
                </Button>
              </div>
            )}
            <Hint
              enabled={!running && startBlocked}
              text={
                !state.carla_connected
                  ? "请先连接 CARLA"
                  : !spawnReady
                    ? "请先选择该地图的出生点"
                    : running
                      ? "结束实验"
                      : "开始实验"
              }
            >
              <span className="start-button-wrap">
                <Button
                  className="main-experiment-button"
                  variant={running ? "destructive" : "default"}
                  disabled={
                    busy || (!running && (!state.carla_connected || !preset?.ego.blueprint || !spawnReady))
                  }
                  onClick={onStartStop}
                >
                  {running ? <Square /> : <Play />}
                  {busy
                    ? state.phase === "starting"
                      ? "正在启动…"
                      : "正在结束…"
                    : running
                      ? "结束实验"
                      : "开始实验"}
                </Button>
              </span>
            </Hint>
          </footer>
        </Card>
        <Card className="dr-card markers-card gap-0">
          <div className="card-head">
            <h2>事件标记</h2>
            <Button variant="ghost" size="sm" disabled={!preset} onClick={onEditMarkers}>
              <Pencil />管理标记
            </Button>
          </div>
          <div className={`gated-area${running ? "" : " is-unavailable"}`}>
            <div className="marker-buttons">
              {preset?.markers.map((label) => (
                <Button
                  key={label}
                  variant="outline"
                  disabled={!running}
                  onClick={() => onMarker(label)}
                >
                  <span className="marker-dot" />
                  {label}
                </Button>
              ))}
            </div>
            {!running && (
              <div className="unavailable-overlay">
                <Lock />
                <span>开始实验后可用</span>
              </div>
            )}
          </div>
        </Card>
      </div>
      <Card className="dr-card runtime-card command-card gap-0">
        <div className="card-head">
          <h2>快捷指令</h2>
          {!running && (
              <Button
                variant="ghost"
                size="sm"
                disabled={!preset || !commands.length}
                onClick={() => onEditInstruction()}
                aria-label="添加指令"
              >
                <Plus />添加指令
              </Button>
          )}
        </div>
        <div className="action-buttons">
          {preset?.instructions.map((item) => (
            <Button
              variant="ghost"
              className="action-button"
              key={item.id}
              onClick={() =>
                running ? onExecute(item) : onEditInstruction(item)
              }
            >
              {item.command === "autopilot" ? <Gauge /> : <Play />}
              <strong>{item.name}</strong>
              <span>{commands.find((c) => c.id === item.command)?.label}</span>
              {!running && <SlidersHorizontal className="edit-command-icon" />}
            </Button>
          ))}
          {!preset?.instructions.length && !running && (
            <Button
              variant="ghost"
              className="empty-command"
              disabled={!preset || !commands.length}
              onClick={() => onEditInstruction()}
            >
              添加快捷指令
            </Button>
          )}
        </div>
      </Card>
      <Card className="dr-card activity-card gap-0">
        <div className="card-head">
          <Tabs
            value={logTab}
            onValueChange={(value) => setLogTab(value as "logs" | "events")}
          >
            <TabsList className="segmented">
              <TabsTrigger value="logs">运行日志</TabsTrigger>
              <TabsTrigger value="events">事件日志</TabsTrigger>
            </TabsList>
          </Tabs>
          <IconAction label="清空日志显示" onClick={onClear}>
            <Eraser />
          </IconAction>
        </div>
        <div className="log-list mono">
          {[...entries].reverse().map((entry, index) => {
            const detail = logTab === "logs" && typeof entry.detail === "string" && entry.detail.trim() ? entry.detail : null;
            const level = logTab === "logs" ? String(entry.level ?? "").toUpperCase() : "EVENT";
            const levelClass = level === "ERROR" || level === "CRITICAL"
              ? "error"
              : level === "WARNING"
                ? "warning"
                : level === "DEBUG"
                  ? "debug"
                  : level === "EVENT"
                    ? "event"
                    : "info";
            return (
              <div className="log-row" key={index}>
                <span className="log-time">
                  {typeof entry.timestamp === "number"
                    ? new Date(entry.timestamp * 1000).toLocaleTimeString(
                      "zh-CN",
                      { hour12: false },
                    )
                    : "—"}
                </span>
                <span className={`log-level ${levelClass}`}>{level}</span>
                <span className={detail ? "log-message-with-detail" : undefined}>
                  <span className={detail ? "min-w-0 truncate" : undefined}>
                  {logTab === "logs"
                    ? (detail ? String(entry.message ?? "").split(/\r?\n/, 1)[0] : String(entry.message ?? ""))
                    : `${entry.name ?? ""} ${entry.source ?? ""} ${JSON.stringify(entry.payload ?? "")}`}
                  </span>
                  {detail && <Button variant="ghost" size="sm" className="h-6 shrink-0 px-2 text-xs" onClick={() => setLogDetail(detail)}>详情</Button>}
                </span>
              </div>
            );
          })}
          {!entries.length && <div className="empty">等待运行记录</div>}
        </div>
      </Card>
      {logDetail !== null && (
        <Modal title="日志详情" open onClose={() => setLogDetail(null)} footer={
          <>
            <Button variant="outline" onClick={() => setLogDetail(null)}>关闭</Button>
            <Button onClick={() => void copyDetail()}>复制详情</Button>
          </>
        }>
          <pre tabIndex={0} aria-label="完整日志堆栈" className="log-detail"><code>{logDetail}</code></pre>
        </Modal>
      )}
    </fieldset>
  );
}
