import { zhCN, format } from "../i18n";
import {
  Eraser, Gauge,
  Lock, Pencil, Play,
  Plus,
  SlidersHorizontal,
  Square
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
      toast.success(zhCN.console.detailCopied);
    } catch (error) {
      toast.error(format(zhCN.console.copyFailed, { error: error instanceof Error ? error.message : String(error) }));
    }
  };
  const t = state.telemetry;
  const entries = logTab === "logs" ? logs : events;
  const spawnReady = !preset || spawnBound(preset);
  const startBlocked = !state.carla_connected || !spawnReady;
  return (
    <fieldset className="home-layout settings-fields" disabled={!serviceOnline}>
      <div className="control-top-row">
        <Card className="dr-card driving-card gap-0">
          <header className="driving-card-heading">
            <h2>{zhCN.console.drivingStatus}</h2>
            <div className="row">
              <span className="dr-badge">
                {t
                  ? t.takeover_requested
                    ? zhCN.console.takeoverRequested
                    : t.control_mode === "autopilot"
                      ? zhCN.console.autopilot
                      : zhCN.console.manual
                  : state.phase === "starting"
                    ? zhCN.status.starting
                    : state.phase === "stopping"
                      ? zhCN.status.stopping
                      : zhCN.console.idle}
              </span>
            </div>
          </header>
          <label className="dr-field driving-subject">
            <span>{zhCN.console.subjectId}</span>
            <Input
              className="input"
              placeholder={zhCN.console.subjectId}
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
                {zhCN.console.speedLimit}{" "}
                <span className="mono">
                  {t ? (t.speed_limit_mps * 3.6).toFixed(0) : "—"}
                </span>{" "}
                km/h
              </span>
            </div>
            <div className="three live-meters">
              {(
                [
                  ["throttle", zhCN.console.throttle, ""],
                  ["brake", zhCN.console.brake, "brake"],
                  ["steer", zhCN.console.steer, "steer"],
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
                ? format(zhCN.console.frameStats, { simulatorFps: t.simulator_fps.toFixed(0), frameNo: t.frame_no.toLocaleString() })
                : null}
            </div>
            <Hint
              enabled={!running && startBlocked}
              text={
                !state.carla_connected
                  ? zhCN.carla.connectFirst
                  : !spawnReady
                    ? zhCN.console.chooseSpawn
                    : running
                      ? zhCN.console.stopExperiment
                      : zhCN.console.startExperiment
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
                      ? zhCN.console.startingProgress
                      : zhCN.console.stoppingProgress
                    : running
                      ? zhCN.console.stopExperiment
                      : zhCN.console.startExperiment}
                </Button>
              </span>
            </Hint>
          </footer>
        </Card>
        <Card className="dr-card markers-card gap-0">
          <div className="card-head">
            <h2>{zhCN.console.markers}</h2>
            <Button variant="ghost" size="sm" disabled={!preset} onClick={onEditMarkers}>
              <Pencil />{zhCN.console.manageMarkers}</Button>
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
                <span>{zhCN.console.availableWhenRunning}</span>
              </div>
            )}
          </div>
        </Card>
      </div>
      <Card className="dr-card runtime-card command-card gap-0">
        <div className="card-head">
          <h2>{zhCN.console.instructionDialog}</h2>
          {!running && (
              <Button
                variant="ghost"
                size="sm"
                disabled={!preset || !commands.length}
                onClick={() => onEditInstruction()}
                aria-label={zhCN.console.addInstruction}
              >
                <Plus />{zhCN.console.addInstruction}</Button>
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
              {zhCN.console.addShortcut}</Button>
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
              <TabsTrigger value="logs">{zhCN.console.logs}</TabsTrigger>
              <TabsTrigger value="events">{zhCN.console.events}</TabsTrigger>
            </TabsList>
          </Tabs>
          <IconAction label={zhCN.console.clearLogs} onClick={onClear}>
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
                  {detail && <Button variant="ghost" size="sm" className="h-6 shrink-0 px-2 text-xs" onClick={() => setLogDetail(detail)}>{zhCN.common.details}</Button>}
                </span>
              </div>
            );
          })}
          {!entries.length && <div className="empty">{zhCN.console.noLogs}</div>}
        </div>
      </Card>
      {logDetail !== null && (
        <Modal title={zhCN.console.logDetails} open onClose={() => setLogDetail(null)} footer={
          <>
            <Button variant="outline" onClick={() => setLogDetail(null)}>{zhCN.common.close}</Button>
            <Button onClick={() => void copyDetail()}>{zhCN.console.copyDetails}</Button>
          </>
        }>
          <pre tabIndex={0} aria-label={zhCN.console.fullTraceback} className="log-detail"><code>{logDetail}</code></pre>
        </Modal>
      )}
    </fieldset>
  );
}
