import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Modal } from "./components/common";
import { Hud } from "./components/hud";
import { PageTabs } from "./components/page-tabs";
import { PresetManager } from "./components/preset-manager";
import { QR } from "./components/qr";
import { Button } from "./components/ui/button";
import { LoaderCircle } from "lucide-react";
import { SceneControl } from "./components/scene-control";
import { UnrealControl } from "./components/unreal-control";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./components/ui/dialog";

import {
  TooltipProvider
} from "./components/ui/tooltip";

import { toast } from "sonner";
import { labels } from "./components/action-labels";
import { AppShell } from "./components/app-shell";
import { CameraInstallation } from "./components/camera-installation";
import { DataManager } from "./components/data-manager";
import { DisplayLayoutEditor } from "./components/display-layout";
import { ExperimentActions } from "./components/experiment-actions";
import { ExperimentConfig } from "./components/experiment-config";
import { ExperimentHome } from "./components/experiment-home";
import { SettingsPage } from "./components/settings-page";
import { SignalControlCard } from "./components/signal-control-card";
import { RuntimeFloatingPanel } from "./components/runtime-floating-panel";
import { Toaster } from "./components/ui/sonner";
import { TrafficPage } from "./components/traffic-page";
import { WeatherPage } from "./components/weather-page";
import { useConfig } from "./hooks/use-config";
import { useRuntime } from "./hooks/use-runtime";
import { useRememberedTab } from "./hooks/use-remembered-tab";
import { useScrollbars } from "./hooks/use-scrollbars";
import { api } from "./lib/api";
import type { SpawnPoint } from "./types/api";
import "./style.css";

const clone = <T,>(value: T): T => structuredClone(value);
function App() {
  useScrollbars();
  const { boot, setBoot, state, logs, events, setLogs, setEvents, online, error: loadError } = useRuntime();
  const initialized = useRef(false);
  const [page, setPage] = useState("控制台"),
    [collapsed, setCollapsed] = useState(false),
    [modal, setModal] = useState(""),
    [desktop, setDesktop] = useState(false);
  const [run, setRun] = useState({
    subject_id: "",
    note: "",
    save_data: true,
    enable_carla_recorder: false,
  }),
    [stopNote, setStopNote] = useState(""),
    [noteSession, setNoteSession] = useState<string | null>(null);
  const [configTab, setConfigTab] = useRememberedTab("scene-vehicle", "scene");
  const [machineTab, setMachineTab] = useRememberedTab("machine", "connection");
  const [controlTab, setControlTab] = useRememberedTab("control", "keyboard");
  const call = async (fn: () => Promise<unknown>, success?: string) => {
    try {
      await fn();
      if (success) toast.success(success);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => {
    if (!boot || initialized.current) return;
    initialized.current = true;
    if (boot.state.active_run) setRun(clone(boot.state.active_run));
  }, [boot]);
  useEffect(() => {
    const ready = () => setDesktop(true);
    if ((window as Window & { pywebview?: { api: unknown; }; }).pywebview?.api) ready();
    window.addEventListener("pywebviewready", ready);
    return () => window.removeEventListener("pywebviewready", ready);
  }, []);
  const { presetName, preset, machine, setMachine, control, setControl,
    presetSave, machineSave, controlSave, choosePreset, createPreset, deletePreset, update, updateMachine } = useConfig(boot, setBoot, state, online);
  const running = state?.phase === "running",
    busy = state?.phase === "starting" || state?.phase === "stopping";
  const activePreset = state?.active_preset ?? preset;
  const displayedRun = state?.phase === "idle" ? run : (state?.active_run ?? run);
  const changePresetMap = (mapName: string) => {
    update(["world", "map_name"], mapName);
  };
  const confirmSpawn = (point: SpawnPoint) => {
    update(["ego", "spawn_point"], point);
    update(["ego", "spawn_map"], preset?.world.map_name ?? "");
    toast.success("出生点已确认");
  };
  if (!boot || !machine || !control || !state)
    return (
      <div className="loading">
        {loadError ? `管理服务初始化失败：${loadError}` : "正在连接管理服务…"}
        <Toaster position="bottom-center" />
      </div>
    );
  return (
    <TooltipProvider>
      <div className="app">
        <Toaster position="bottom-center" />
        <AppShell
          page={page}
          setPage={setPage}
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          desktop={desktop}
          state={state}
          onBeforeClose={async () => { await Promise.all([presetSave.flush(), machineSave.flush(), controlSave.flush()]); }}
          serviceOnline={online}
          onUnreal={() => setModal("unreal")}
          onShare={() => setModal("urls")}
          presetAction={<PresetManager
            open={modal === "presets"}
            onOpenChange={open => setModal(open ? "presets" : "")}
            name={state.phase === "idle" ? presetName : state.active_preset_name ?? presetName}
            presets={boot.presets} disabled={!online || state.phase !== "idle"}
            run={displayedRun} onRunChange={setRun} onSelect={choosePreset} onCreate={createPreset} onDelete={deletePreset}
          />}
        >
          {page === "控制台" && (
            <ExperimentActions
              instructions={preset?.instructions ?? []} markers={preset?.markers ?? []} commands={boot.commands}
              onInstructions={items => update(["instructions"], items)} onMarkers={items => update(["markers"], items)}
            >
              {({ editInstruction, editMarkers }) => <ExperimentHome
              state={state}
              running={running}
              busy={busy}
              serviceOnline={online}
              preset={running ? activePreset : preset}
              run={run}
              commands={boot.commands}
              logs={logs}
              events={events}
              setRun={setRun}
              onStartStop={() => {
                if (running) {
                  setStopNote("");
                  setNoteSession(state.active_run?.save_data ? state.session_id : null);
                  call(async () => {
                    await api("/api/experiment/stop", "POST");
                    if (state.active_run?.save_data) setModal("stop");
                  });
                } else {
                  call(async () => {
                    await Promise.all([presetSave.flush(), machineSave.flush(), controlSave.flush()]);
                    await api("/api/experiment/start", "POST", {
                      preset_name: presetName,
                      run: { ...run, note: "" },
                    });
                  });
                }
              }}
              onMarker={(label) =>
                call(() => api("/api/markers", "POST", { label }))
              }
              onEditMarkers={editMarkers}
              onEditInstruction={editInstruction}
              onExecute={(item) =>
                call(() =>
                  api(
                    "/api/instructions/" +
                    encodeURIComponent(item.id) +
                    "/execute",
                    "POST",
                  ),
                )
              }
              onClear={() => {
                setLogs([]);
                setEvents([]);
              }}
            />}
            </ExperimentActions>
          )}
          {page === "场景" && !preset && (
            <div className="page-scroll">
              <Button
                onClick={() => {
                  setModal("presets");
                }}
              >
                新建方案
              </Button>
            </div>
          )}
          {page === "场景" && preset && (
            <PageTabs
                value={configTab}
                onValueChange={setConfigTab}
                items={[["scene", "场景"], ["vehicle", "车辆"]]}
                actions={<span className="save-status" role="status">{presetSave.status}</span>}
              >
              <div className="tab-scroll">
                <ExperimentConfig key={presetName}
                  preset={preset} state={state} tab={configTab} update={update}
                  onMapChange={changePresetMap}
                  onLoadMap={() => call(() => api("/api/world/map", "POST", { map_name: preset.world.map_name }))}
                  onConfirmSpawn={confirmSpawn}
                />
              </div>
            </PageTabs>
          )}
          {page === "天气" && (
            <WeatherPage
              preset={preset}
              presetName={presetName}
              saveStatus={presetSave.status}
              state={state}
              update={update}
              commands={boot.commands}
              online={online}
              onOpenPresets={() => setModal("presets")}
            />
          )}
          {page === "交通流" && (
            <TrafficPage
              preset={preset}
              presetName={presetName}
              saveStatus={presetSave.status}
              state={state}
              update={update}
              commands={boot.commands}
              online={online}
              onOpenPresets={() => setModal("presets")}
            />
          )}
          {page === "数据管理" && (
            <DataManager state={state} online={online} />
          )}
          {(page === "主机配置" || page === "输入配置") && (
            <>
              <SettingsPage key={page}
                toolbar={<span className="save-status" role="status">{page === "主机配置" ? (machineTab === "camera" ? presetSave.status : machineSave.status) : controlSave.status}</span>}
                disabled={!online || state.phase !== "idle" || state.carla_connecting}
                page={page === "主机配置" ? "machine" : "control"}
                tab={page === "主机配置" ? machineTab : controlTab}
                setTab={page === "主机配置" ? setMachineTab : setControlTab}
                cameraInstallation={preset ? <CameraInstallation key={presetName}
                  cameras={preset.cameras} applied={state.cameras} extent={state.vehicle_box?.extent}
                  running={running && online}
                  onChange={(name, value) => update(["cameras", name], value)}
                  onApply={(name, value) => call(() => api("/api/cameras/" + name, "POST", value), "相机调整已提交")}
                /> : <p className="small">请先选择一个实验预设。</p>}
                machine={machine}
                control={control}
                boot={boot}
                labels={labels}
                updateMachine={updateMachine}
                setControl={setControl}
                onConnect={() => call(async () => { await machineSave.flush(); await api("/api/connect", "POST"); })}
              >
                <DisplayLayoutEditor
                  layout={machine.display.layout}
                  applied={state.display_layout}
                  resolution={machine.display.resolution}
                  running={running && online}
                  onChange={value => updateMachine(["display", "layout"], value)}
                  onResolutionChange={value => updateMachine(["display", "resolution"], value)}
                  onApply={value => call(() => api("/api/display-layout", "POST", value), "布局调整已提交")}
                />
              </SettingsPage>
            </>
          )}
        </AppShell>
        <div className="runtime-floating-stack pointer-events-none fixed right-5 bottom-5 z-40 flex max-w-[calc(100dvw-88px)] flex-col items-end gap-3">
          {state.selected_signal && <SignalControlCard key={state.selected_signal.actor_id}
            signal={state.selected_signal} disabled={!online || !state.carla_connected || state.world_loading} />}
          {(state.phase === "running" || state.traffic_preview.running || state.replay.running) &&
            <RuntimeFloatingPanel state={state} disabled={!online || !state.carla_connected || state.world_loading} />}
        </div>
        {modal === "unreal" && <UnrealControl
          machine={machine} state={state} online={online} onClose={() => setModal("")}
          onStart={() => call(async () => {
            await machineSave.flush();
            await api("/api/carla/start", "POST", {});
          })}
          onStop={() => call(() => api("/api/carla/stop", "POST"))}
          onConnectExisting={() => setModal("connect")}
          onConfigure={() => { setModal(""); setPage("主机配置"); setMachineTab("connection"); }}
        />}
        {modal === "connect" && <SceneControl
          state={state} online={online} host={machine.driving_view.host} port={machine.driving_view.port}
          onClose={() => setModal("")}
          onConnect={async (host, port) => {
            const config = {
              ...machine,
              driving_view: { ...machine.driving_view, host, port },
            };
            setMachine(config);
            await machineSave.flush(config);
            await api("/api/connect", "POST");
          }}
        />}
        <Modal
          title="实验结束备注"
          open={modal === "stop"}
          onClose={() => setModal("")}
          footer={
            <>
              <Button variant="outline" onClick={() => setModal("")}>
                跳过
              </Button>
              <Button
                variant="default"
                disabled={!noteSession || !online}
                onClick={() => call(async () => {
                  await api("/api/sessions/" + encodeURIComponent(noteSession!) + "/note", "PUT", { note: stopNote });
                  setModal("");
                })}
              >
                保存备注
              </Button>
            </>
          }
        >
          <p className="text-sm text-muted-foreground">记录本次实验的观察结果或异常情况，备注随会话保存。</p>
          <label className="grid gap-2 text-sm">
            <span className="font-medium">本次备注</span>
            <textarea autoFocus rows={4} value={stopNote} onChange={event => setStopNote(event.target.value)}
              placeholder="输入实验备注…"
              className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50" />
          </label>
        </Modal>
        <Modal
          title="连接地址"
          open={modal === "urls"}
          onClose={() => setModal("")}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/30 px-4 py-3 text-sm">
            <strong>已连接 {state.clients.console + state.clients.hud} 个客户端</strong>
            <span className="text-xs text-muted-foreground">控制台 {state.clients.console} · HUD {state.clients.hud}</span>
          </div>
          <div className="qr-grid">
            {Object.entries(boot.urls).map(([k, v]) => (
              <div key={k} className="min-w-0 rounded-lg border bg-muted/20 p-4">
                <h3 className="text-sm font-semibold">{k === "console" ? "操作者控制台" : "被试 HUD"}</h3>
                <QR url={String(v)} />
                <p className="break-all font-mono text-xs text-muted-foreground">{String(v)}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => void navigator.clipboard.writeText(String(v))
                  .then(() => toast.success("连接地址已复制"))
                  .catch(error => toast.error(`复制失败：${String(error)}`))}>复制地址</Button>
              </div>
            ))}
          </div>
        </Modal>

        <Dialog open={state.world_loading}>
          <DialogContent showCloseButton={false} overlayClassName="world-loading-overlay"
            className="window-dialog sm:max-w-sm" style={{ zIndex: 201 }}
            onEscapeKeyDown={event => event.preventDefault()}
            onPointerDownOutside={event => event.preventDefault()}>
            <div className="flex items-center gap-3" role="status" aria-live="polite">
              <LoaderCircle className="size-6 shrink-0 animate-spin text-primary" />
              <div className="grid gap-2">
                <DialogTitle>正在加载世界</DialogTitle>
                <DialogDescription>等待 CARLA 完成场景加载…</DialogDescription>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
}
createRoot(document.getElementById("root")!).render(
  location.pathname === "/hud" ? <Hud /> : <App />,
);
