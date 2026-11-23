import type { MachineConfig, RuntimeState } from "../types/api";
import { Modal } from "./common";
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
  return (
    <Modal
      title="模拟器"
      open
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" disabled={!online} onClick={onConnectExisting}>
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
            {busy ? phases[phase] : running ? "关闭 Unreal" : "启动 Unreal"}
          </Button>
        </>
      }
    >
      <div className="grid min-w-0 gap-4">
        <div className="flex items-center justify-between gap-3">
          <span>
            Unreal {phases[phase]}
            {state.unreal.pid ? ` · PID ${state.unreal.pid}` : ""}
          </span>
          <Button variant="ghost" onClick={onConfigure}>
            运行配置
          </Button>
        </div>
        <span className="text-sm text-muted-foreground">
          {kind === "editor" ? "UE 编辑器版" : "CARLA 打包版"} · 接口{linked}
        </span>
        <p className="break-all text-sm">
          {kind === "editor"
            ? machine.carla_runtime.editor_executable
            : machine.carla_runtime.packaged_executable}
        </p>
        <p className="text-sm text-muted-foreground">
          模拟器地址 {machine.driving_view.host}:{machine.driving_view.port}
        </p>
        {state.error && (
          <p role="alert" className="text-sm text-destructive">
            {state.error}
          </p>
        )}
      </div>
    </Modal>
  );
}
