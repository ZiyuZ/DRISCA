import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Field, Modal } from "./components/common";
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
import { Toaster } from "./components/ui/sonner";
import { SpawnPointDialog } from "./components/spawn-point-dialog";
import { TrafficPage } from "./components/traffic-page";
import { WeatherPage } from "./components/weather-page";
import { useConfig } from "./hooks/use-config";
import { useRuntime } from "./hooks/use-runtime";
import { useScrollbars } from "./hooks/use-scrollbars";
import { api } from "./lib/api";
import { mapKey } from "./lib/spawn";
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
    [noteSession, setNoteSession] = useState<string | null>(null),
    [configTab, setConfigTab] = useState("scene"),
    [machineTab, setMachineTab] = useState("connection"),
    [controlTab, setControlTab] = useState("keyboard");
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
    busy = state?.phase === "starting" || state?.phase === "stopping",
    t = state?.telemetry;
  const activePreset = state?.active_preset ?? preset;
  const displayedRun = state?.phase === "idle" ? run : (state?.active_run ?? run);
  const [spawnDialog, setSpawnDialog] = useState(false);
  const changePresetMap = (mapName: string) => {
    update(["world", "map_name"], mapName);
    if (mapKey(mapName) !== mapKey(preset?.ego.spawn_map ?? "")) setSpawnDialog(true);
  };
  const confirmSpawn = (point: SpawnPoint) => {
    update(["ego", "spawn_point"], point);
    update(["ego", "spawn_map"], preset?.world.map_name ?? "");
    setSpawnDialog(false);
  };
  if (!boot || !machine || !control || !state)
    return (
      <div className="loading">
        {loadError ? `管理服务初始化失败：${loadError}` : "正在连接管理服务…"}
        <Toaster richColors />
      </div>
    );
  return (
    <TooltipProvider>
      <div className="app">
        <Toaster richColors position="top-center" />
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
            <ExperimentHome
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
              onEditMarkers={() => {
                setPage("方案配置");
                setConfigTab("actions");
              }}
              onEditInstruction={() => {
                setPage("方案配置");
                setConfigTab("actions");
              }}
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
            />
          )}
          {page === "方案配置" && !preset && (
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
          {page === "方案配置" && preset && (
            <PageTabs
                value={configTab}
                onValueChange={setConfigTab}
                items={[["scene", "场景与车辆"], ["camera", "相机安装"], ["actions", "指令与标记"]]}
                actions={<span className="save-status" role="status">{presetSave.status}</span>}
              >
              <div className="tab-scroll">
                {configTab === "scene" && (
                  <ExperimentConfig
                    preset={preset}
                    state={state}
                    update={update}
                    onOpenWeather={() => setPage("天气")}
                    onMapChange={changePresetMap}
                    onPickSpawn={() => setSpawnDialog(true)}
                    onOpenTraffic={() => setPage("交通流")}
                  />
                )}
                {configTab === "camera" && (
                  <CameraInstallation key={presetName}
                    cameras={preset.cameras}
                    applied={state.cameras}
                    extent={state.vehicle_box?.extent}
                    running={running && online}
                    onChange={(name, value) => update(["cameras", name], value)}
                    onApply={(name, value) => call(() => api("/api/cameras/" + name, "POST", value), "相机调整已提交")}
                  />
                )}
                {configTab === "actions" && (
                  <ExperimentActions
                    instructions={preset.instructions}
                    markers={preset.markers}
                    commands={boot.commands}
                    onInstructions={items => update(["instructions"], items)}
                    onMarkers={items => update(["markers"], items)}
                  />
                )}
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
                toolbar={<span className="save-status" role="status">{page === "主机配置" ? machineSave.status : controlSave.status}</span>}
                disabled={!online || state.phase !== "idle" || state.carla_connecting}
                page={page === "主机配置" ? "machine" : "control"}
                tab={page === "主机配置" ? machineTab : controlTab}
                setTab={page === "主机配置" ? setMachineTab : setControlTab}
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
          title="本次备注"
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
          <Field label="本次备注" value={stopNote} onChange={setStopNote} />
        </Modal>
        <Modal
          title="连接地址"
          open={modal === "urls"}
          onClose={() => setModal("")}
        >
          <p className="client-count">已连接：控制台 {state.clients.console} · HUD {state.clients.hud} · 共 {state.clients.console + state.clients.hud} 个客户端</p>
          <div className="qr-grid">
            {Object.entries(boot.urls).map(([k, v]) => (
              <div key={k}>
                <h3>{k === "console" ? "操作者控制台" : "被试 HUD"}</h3>
                <QR url={String(v)} />
                <p>{String(v)}</p>
              </div>
            ))}
          </div>
        </Modal>

        {spawnDialog && preset && (
          <SpawnPointDialog
            preset={preset}
            catalogMap={state.catalog.map_name}
            spawnPoints={state.catalog.spawn_points}
            connected={online && state.carla_connected}
            worldLoading={state.world_loading}
            phaseIdle={state.phase === "idle"}
            onLoadMap={() =>
              call(() => api("/api/world/map", "POST", { map_name: preset.world.map_name }))
            }
            onConfirm={confirmSpawn}
            onClose={() => setSpawnDialog(false)}
          />
        )}

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
