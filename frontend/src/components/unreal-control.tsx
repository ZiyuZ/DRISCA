import type { MachineConfig, RuntimeState } from "../types/api";
import { Modal } from "./common";
import { Button } from "./ui/button";

const phases = { stopped: "未启动", starting: "正在启动", running: "运行中", stopping: "正在关闭", error: "启动或运行异常" };

export function UnrealControl({ machine, state, online, onStart, onStop, onConfigure, onClose }: {
  machine: MachineConfig;
  state: RuntimeState;
  online: boolean;
  onStart: () => void;
  onStop: () => void;
  onConfigure: () => void;
  onClose: () => void;
}) {
  const phase = state.unreal.phase;
  const busy = phase === "starting" || phase === "stopping";
  const running = phase === "running";
  const kind = (busy || running ? state.unreal.kind : null) ?? machine.carla_runtime.kind;
  return <Modal title="Unreal 运行程序" open onClose={onClose} footer={
    <Button variant={running ? "destructive" : "default"}
      disabled={!online || busy || state.phase !== "idle" || state.carla_connecting || (!running && state.carla_connected)}
      onClick={running ? onStop : onStart}>
      {busy ? phases[phase] : running ? "关闭 Unreal" : "启动 Unreal"}
    </Button>
  }>
    <div className="grid min-w-0 gap-4">
      <div className="flex items-center justify-between gap-3">
        <span>{phases[phase]}{state.unreal.pid ? ` · PID ${state.unreal.pid}` : ""}</span>
        <Button variant="ghost" onClick={onConfigure}>运行配置</Button>
      </div>
      <span className="text-sm text-muted-foreground">{kind === "editor" ? "UE 编辑器版" : "CARLA 打包版"}</span>
      <p className="break-all text-sm">{kind === "editor" ? machine.carla_runtime.editor_executable : machine.carla_runtime.packaged_executable}</p>
      {state.error && <p role="alert" className="text-sm text-destructive">{state.error}</p>}
    </div>
  </Modal>;
}
