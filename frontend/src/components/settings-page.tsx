import { zhCN, format } from "../i18n";
import { NumberInput } from "./number-input";
import { RotateCcw } from "lucide-react";
import { useRef } from "react";
import type { Bootstrap, ControlConfig, MachineConfig } from "../types/api";
import { IconAction } from "./icon-action";
import { PageTabs } from "./page-tabs";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";

type Props = {
  page: "machine" | "control";
  children?: React.ReactNode;
  cameraInstallation?: React.ReactNode;
  toolbar?: React.ReactNode;
  disabled: boolean;
  tab: string;
  setTab: (v: string) => void;
  machine: MachineConfig;
  control: ControlConfig;
  boot: Bootstrap;
  labels: Record<string, string>;
  updateMachine: (path: string[], value: unknown) => void;
  setControl: (value: ControlConfig) => void;
  onConnect: () => void;
};
export function SettingsPage({
  page,
  children,
  cameraInstallation,
  toolbar,
  disabled,
  tab,
  setTab,
  machine,
  control,
  boot,
  labels,
  updateMachine,
  setControl,
  onConnect,
}: Props) {
  const initialControl = useRef(structuredClone(control));
  const field = (
    label: string,
    value: string | number,
    path: string[],
    type = "text",
    hint?: string,
  ) => (
    <label className="dr-field">
      <span>{label}</span>
      {type === "number" ? <NumberInput
        className="input mono"
        value={Number(value)}
        onValueChange={value => updateMachine(path, value)}
      /> : <Input
        className="input mono"
        type={type}
        value={value}
        onChange={(e) =>
          updateMachine(
            path,
            e.target.value,
          )
        }
      />}
      {hint && <small className="field-hint">{hint}</small>}
    </label>
  );
  const wheel = (key: string, value: string | number | boolean) =>
    setControl({ ...control, wheel: { ...control.wheel, [key]: value } });
  return (
    <PageTabs value={tab} onValueChange={setTab} actions={toolbar}
      items={page === "machine"
        ? [["connection", zhCN.settings.connectionTab], ["display", zhCN.settings.displayTab], ["camera", zhCN.settings.camerasTab], ["storage", zhCN.settings.storageTab]]
        : [["keyboard", zhCN.settings.keyboardTab], ["wheel", zhCN.settings.wheelTab]]}>
      <div className="tab-scroll">
        {page === "machine" ? (
          <div className="stack">
            {tab === "camera" && cameraInstallation}
            {tab === "connection" && (
              <fieldset disabled={disabled} className="settings-fields grid2 equal">
                <Card className="dr-card gap-0">
                  <div className="card-head"><h2>{zhCN.settings.runtime}</h2></div>
                  <div className="form">
                    <label className="dr-field"><span>{zhCN.settings.executableMode}</span>
                      <SharedSelect value={machine.carla_runtime.kind}
                        options={[["editor", zhCN.carla.editor], ["packaged", zhCN.carla.shipping]]}
                        onValueChange={value => updateMachine(["carla_runtime", "kind"], value)} />
                    </label>
                    {machine.carla_runtime.kind === "editor" ? <>
                      {field(zhCN.settings.editorPath, machine.carla_runtime.editor_executable, ["carla_runtime", "editor_executable"])}
                      {field(zhCN.settings.projectPath, machine.carla_runtime.project, ["carla_runtime", "project"])}
                    </> : field(zhCN.settings.executablePath, machine.carla_runtime.packaged_executable, ["carla_runtime", "packaged_executable"])}
                    <label className="dr-field"><span>{zhCN.settings.quality}</span>
                      <SharedSelect value={machine.carla_runtime.quality}
                        options={[["Low", zhCN.settings.qualityLow], ["Medium", zhCN.settings.qualityMedium], ["High", zhCN.settings.qualityHigh], ["Epic", zhCN.settings.qualityEpic]]}
                        onValueChange={value => updateMachine(["carla_runtime", "quality"], value)} />
                    </label>
                    {field(zhCN.settings.launchWait, machine.carla_runtime.startup_timeout, ["carla_runtime", "startup_timeout"], "number")}
                    <div className="field-divider" />
                    {field(
                      zhCN.settings.launchAddress,
                      machine.carla.host,
                      ["carla", "host"],
                      "text",
                      zhCN.settings.launchAddressHint,
                    )}
                    {field(
                      zhCN.settings.rpcPort,
                      machine.carla.port,
                      ["carla", "port"],
                      "number",
                      zhCN.settings.rpcPortHint,
                    )}
                  </div>
                </Card>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>{zhCN.settings.connection}</h2>
                  </div>
                  <div className="form">
                    {field(
                      zhCN.settings.address,
                      machine.driving_view.host,
                      ["driving_view", "host"],
                    )}
                    {field(
                      zhCN.settings.connectionPort,
                      machine.driving_view.port,
                      ["driving_view", "port"],
                      "number",
                    )}
                    {field(
                      zhCN.settings.requestTimeout,
                      machine.driving_view.timeout,
                      ["driving_view", "timeout"],
                      "number",
                      zhCN.settings.requestTimeoutHint,
                    )}
                    <Button variant="outline" onClick={onConnect}>
                      {zhCN.settings.checkConnection}</Button>
                  </div>
                </Card>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>{zhCN.settings.managementAccess}</h2>
                  </div>
                  <div className="form">
                    {field(zhCN.settings.accessAddress, machine.service.launcher_host, [
                      "service",
                      "launcher_host",
                    ])}
                    {field(
                      zhCN.settings.accessPort,
                      machine.service.launcher_port,
                      ["service", "launcher_port"],
                      "number",
                      zhCN.settings.accessHint,
                    )}
                    <label className="check">
                      <Checkbox
                        checked={machine.service.enable_tts}
                        onCheckedChange={(v) =>
                          updateMachine(["service", "enable_tts"], v === true)
                        }
                      />
                      {zhCN.settings.speech}</label>
                    <label className="check">
                      <Checkbox
                        checked={machine.service.debug}
                        onCheckedChange={(v) =>
                          updateMachine(["service", "debug"], v === true)
                        }
                      />
                      {zhCN.settings.debug}</label>
                  </div>
                </Card>
              </fieldset>
            )}
            {tab === "storage" && (
              <fieldset disabled={disabled} className="settings-fields"><Card className="dr-card gap-0">
                <div className="card-head">
                  <h2>{zhCN.settings.storageTab}</h2>
                </div>
                <div className="form">
                  {field(zhCN.settings.database, machine.db_path, ["db_path"])}
                  {field(zhCN.settings.recordings, machine.recorder_dir, ["recorder_dir"])}
                  {field(zhCN.settings.exports, machine.export_dir, ["export_dir"])}
                </div>
              </Card></fieldset>
            )}
            {tab === "display" && (
              <>
                <fieldset disabled={disabled} className="settings-fields"><Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>{zhCN.settings.displayWindow}</h2>
                  </div>
                  <div className="three">
                    {field(zhCN.settings.windowX, machine.display.position[0], ["display", "position", "0"], "number")}
                    {field(zhCN.settings.windowY, machine.display.position[1], ["display", "position", "1"], "number")}
                    {field(
                      zhCN.settings.targetFps,
                      machine.display.target_fps,
                      ["display", "target_fps"],
                      "number",
                    )}
                  </div>
                  <div className="row settings-checks">
                    <label className="check">
                      <Checkbox
                        checked={machine.display.fullscreen}
                        onCheckedChange={(v) =>
                          updateMachine(["display", "fullscreen"], v === true)
                        }
                      />
                      {zhCN.settings.fullscreen}</label>
                    <label className="check">
                      <Checkbox
                        checked={machine.display.borderless}
                        onCheckedChange={(v) =>
                          updateMachine(["display", "borderless"], v === true)
                        }
                      />
                      {zhCN.settings.frameless}</label>
                  </div>
                </Card></fieldset>
                {children}
              </>
            )}
          </div>
        ) : (
          <fieldset disabled={disabled} className="settings-fields stack">
            {tab === "wheel" && (
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <h2>{zhCN.settings.wheelTab}</h2>
                  <Switch
                    checked={control.wheel.enable_wheel === true}
                    onCheckedChange={(v) => wheel("enable_wheel", v)}
                    aria-label={zhCN.settings.enableWheel}
                  />
                </div>
                <div className="row spread wrap">
                  <div>
                    <h3>
                      {control.wheel.enable_wheel
                        ? format(zhCN.settings.wheelDevice, { deviceIndex: control.wheel.device_index })
                        : zhCN.settings.keyboardDriving}
                    </h3>
                  </div>
                  <label className="check">
                    <Checkbox
                      checked={control.wheel.show_button_key === true}
                      onCheckedChange={(v) =>
                        wheel("show_button_key", v === true)
                      }
                    />
                    {zhCN.settings.buttonNumberLog}</label>
                </div>
                <div className="row settings-checks">
                  <label className="dr-field">
                    <span>{zhCN.settings.deviceIndex}</span>
                    <NumberInput
                      className="input mono"
                      
                      value={Number(control.wheel.device_index)}
                      onValueChange={(value) =>
                        wheel("device_index", value)
                      }
                    />
                  </label>
                  <label className="check">
                    <Checkbox
                      checked={control.wheel.autopilot_wheel_sync === true}
                      onCheckedChange={(v) =>
                        wheel("autopilot_wheel_sync", v === true)
                      }
                    />
                    {zhCN.settings.autopilotWheel}</label>
                </div>
              </Card>
            )}
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>{zhCN.settings.bindings}</h2>
                <IconAction
                  label={zhCN.settings.undoBindings}
                  onClick={() => setControl(structuredClone(initialControl.current))}
                >
                  <RotateCcw />
                </IconAction>
              </div>
              <div className="binding-grid header small">
                <span>{zhCN.settings.drivingAction}</span>
                <span>{tab === "keyboard" ? zhCN.settings.keyboardTab : zhCN.settings.wheelTab}</span>
              </div>
              {Object.keys(control.keyboard).map((key) => (
                <div className="binding-grid" key={key}>
                  <span>{labels[key] || key}</span>
                  {tab === "keyboard" ? (
                    <SharedSelect
                      className="select"
                      value={control.keyboard[key]}
                      options={Object.entries(boot.keyboard_labels)}
                      onValueChange={(value) =>
                        setControl({
                          ...control,
                          keyboard: { ...control.keyboard, [key]: value },
                        })
                      }
                    />
                  ) : (
                    <SharedSelect
                      className="select"
                      value={String(control.wheel[key] ?? "unbound")}
                      disabled={
                        !control.wheel.enable_wheel || !(key in control.wheel)
                      }
                      options={Object.entries(boot.wheel_labels)}
                      onValueChange={(value) => wheel(key, value)}
                    />
                  )}
                </div>
              ))}
            </Card>
          </fieldset>
        )}
      </div>
    </PageTabs>
  );
}
