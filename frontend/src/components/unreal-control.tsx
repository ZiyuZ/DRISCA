import type { MachineConfig, RuntimeState } from "../types/api";
import { Modal } from "./common";
import { Hint } from "./hint";
import { Button } from "./ui/button";

const phases = {
  stopped: "未启动",
  starting: "正在启动",
  running: "运行中",
  stopping: "正在关闭",
  error: "启动或运行异常",
};

export function UnrealControl({
  machine,
  state,
  online,
  onStart,
  onStop,
  onConnectExisting,
  onConfigure,
  onClose,
}: {
  machine: MachineConfig;
  state: RuntimeState;
  online: boolean;
  onStart: () => void;
  onStop: () => void;
  onConnectExisting: () => void;
  onConfigure: () => void;
  onClose: () => void;
}) {
  const phase = state.unreal.phase;
  const busy = phase === "starting" || phase === "stopping";
  const running = phase === "running";
  const kind = (busy || running ? state.unreal.kind : null) ?? machine.carla_runtime.kind;
  const linked = state.carla_connected ? "已连接" : state.carla_connecting ? "连接中" : "未连接";
  const executable = kind === "editor"
    ? machine.carla_runtime.editor_executable
    : machine.carla_runtime.packaged_executable;
  return (
    <Modal
      title="模拟器"
      open
      onClose={onClose}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onConfigure}>运行配置</Button>
          <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" disabled={!online || busy || state.phase !== "idle" || state.carla_connecting} onClick={onConnectExisting}>
            连接已运行实例
          </Button>
          <Button
            variant={running ? "destructive" : "default"}
            disabled={
              !online ||
              busy ||
              state.phase !== "idle" ||
              state.carla_connecting ||
              (!running && state.carla_connected)
            }
            onClick={running ? onStop : onStart}
          >
            {busy ? phases[phase] : running ? "停止模拟器" : "启动模拟器"}
          </Button>
          </div>
        </div>
      }
    >
      <div className="grid min-w-0 gap-4">
        <section className="overflow-hidden rounded-lg border bg-muted/30">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <strong className="text-sm">{kind === "editor" ? "UE 编辑器版" : "CARLA 打包版"}</strong>
            <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${phase === "error" ? "border-destructive/30 text-destructive" : "bg-background"}`}>
              {phases[phase]}
            </span>
          </div>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-2 px-4 py-3 text-sm">
            <dt className="text-muted-foreground">进程 PID</dt>
            <dd className="font-mono">{state.unreal.pid ?? "—"}</dd>
            <dt className="text-muted-foreground">模拟器接口</dt>
            <dd className="min-w-0 break-all"><span className="font-medium">{linked}</span><span className="ml-2 font-mono text-xs text-muted-foreground">{machine.driving_view.host}:{machine.driving_view.port}</span></dd>
          </dl>
        </section>
        <div className="flex min-w-0 items-center gap-3 text-xs text-muted-foreground">
          <span className="shrink-0">可执行文件</span>
          <Hint text={executable || "尚未配置可执行文件"}>
            <span className="min-w-0 truncate font-mono">{executable || "尚未配置"}</span>
          </Hint>
        </div>
        {state.error && (
          <p role="alert" className="text-sm text-destructive">
            {state.error}
          </p>
        )}
      </div>
    </Modal>
  );
}
