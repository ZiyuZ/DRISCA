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
    </label>
  );
  const wheel = (key: string, value: string | number | boolean) =>
    setControl({ ...control, wheel: { ...control.wheel, [key]: value } });
  return (
    <PageTabs value={tab} onValueChange={setTab} actions={toolbar}
      items={page === "machine"
        ? [["connection", "连接与服务"], ["display", "驾驶显示"], ["storage", "数据存储"]]
        : [["keyboard", "键盘"], ["wheel", "方向盘"]]}>
      <div className="tab-scroll">
        {page === "machine" ? (
          <div className="stack">
            {tab === "connection" && (
              <fieldset disabled={disabled} className="settings-fields grid2 equal">
                <Card className="dr-card gap-0">
                  <div className="card-head"><h2>Unreal 运行程序</h2></div>
                  <div className="form">
                    <label className="dr-field"><span>运行版本</span>
                      <SharedSelect value={machine.carla_runtime.kind}
                        options={[["editor", "UE 编辑器版"], ["packaged", "CARLA 打包版"]]}
                        onValueChange={value => updateMachine(["carla_runtime", "kind"], value)} />
                    </label>
                    {machine.carla_runtime.kind === "editor" ? <>
                      {field("UE 编辑器路径", machine.carla_runtime.editor_executable, ["carla_runtime", "editor_executable"])}
                      {field("CARLA 工程路径", machine.carla_runtime.project, ["carla_runtime", "project"])}
                    </> : field("CARLA 程序路径", machine.carla_runtime.packaged_executable, ["carla_runtime", "packaged_executable"])}
                    <label className="dr-field"><span>画质</span>
                      <SharedSelect value={machine.carla_runtime.quality}
                        options={[["Low", "低"], ["Medium", "中"], ["High", "高"], ["Epic", "极高"]]}
                        onValueChange={value => updateMachine(["carla_runtime", "quality"], value)} />
                    </label>
                    {field("启动等待 · 秒", machine.carla_runtime.startup_timeout, ["carla_runtime", "startup_timeout"], "number")}
                    {field("驾驶接口端口", machine.driving_view.port, ["driving_view", "port"], "number")}
                  </div>
                </Card>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>模拟服务连接</h2>
                  </div>
                  <div className="form">
                    {field("服务地址", machine.carla.host, ["carla", "host"])}
                    <div className="grid2 equal" style={{ gap: 12 }}>
                      {field(
                        "RPC 端口",
                        machine.carla.port,
                        ["carla", "port"],
                        "number",
                      )}
                      {field(
                        "交通管理端口",
                        machine.carla.tm_port,
                        ["carla", "tm_port"],
                        "number",
                      )}
                    </div>
                    {field(
                      "连接超时 · 秒",
                      machine.carla.timeout,
                      ["carla", "timeout"],
                      "number",
                    )}
                    <Button variant="outline" onClick={onConnect}>
                      检查连接
                    </Button>
                  </div>
                </Card>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>控制台服务</h2>
                  </div>
                  <div className="form">
                    {field("监听地址", machine.service.launcher_host, [
                      "service",
                      "launcher_host",
                    ])}
                    {field(
                      "控制台端口",
                      machine.service.launcher_port,
                      ["service", "launcher_port"],
                      "number",
                    )}
                    <label className="check">
                      <Checkbox
                        checked={machine.service.enable_tts}
                        onCheckedChange={(v) =>
                          updateMachine(["service", "enable_tts"], v === true)
                        }
                      />
                      启用语音提示
                    </label>
                    <label className="check">
                      <Checkbox
                        checked={machine.service.debug}
                        onCheckedChange={(v) =>
                          updateMachine(["service", "debug"], v === true)
                        }
                      />
                      调试日志
                    </label>
                  </div>
                </Card>
              </fieldset>
            )}
            {tab === "storage" && (
              <fieldset disabled={disabled} className="settings-fields"><Card className="dr-card gap-0">
                <div className="card-head">
                  <h2>数据存储</h2>
                </div>
                <div className="form">
                  {field("数据库", machine.db_path, ["db_path"])}
                  {field("录像目录", machine.recorder_dir, ["recorder_dir"])}
                  {field("导出目录", machine.export_dir, ["export_dir"])}
                </div>
              </Card></fieldset>
            )}
            {tab === "display" && (
              <>
                <fieldset disabled={disabled} className="settings-fields"><Card className="dr-card gap-0">
                  <div className="card-head">
                    <h2>驾驶显示窗口</h2>
                  </div>
                  <div className="three">
                    {field("窗口位置 X", machine.display.position[0], ["display", "position", "0"], "number")}
                    {field("窗口位置 Y", machine.display.position[1], ["display", "position", "1"], "number")}
                    {field(
                      "显示目标帧率",
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
                      全屏显示驾驶画面
                    </label>
                    <label className="check">
                      <Checkbox
                        checked={machine.display.borderless}
                        onCheckedChange={(v) =>
                          updateMachine(["display", "borderless"], v === true)
                        }
                      />
                      无边框
                    </label>
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
                  <h2>方向盘</h2>
                  <Switch
                    checked={control.wheel.enable_wheel === true}
                    onCheckedChange={(v) => wheel("enable_wheel", v)}
                    aria-label="启用方向盘"
                  />
                </div>
                <div className="row spread wrap">
                  <div>
                    <h3>
                      {control.wheel.enable_wheel
                        ? `罗技方向盘 · 设备 ${control.wheel.device_index}`
                        : "键盘驾驶"}
                    </h3>
                  </div>
                  <label className="check">
                    <Checkbox
                      checked={control.wheel.show_button_key === true}
                      onCheckedChange={(v) =>
                        wheel("show_button_key", v === true)
                      }
                    />
                    显示按钮编号日志
                  </label>
                </div>
                <div className="row settings-checks">
                  <label className="dr-field">
                    <span>设备编号</span>
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
                    自动驾驶方向盘随动
                  </label>
                </div>
              </Card>
            )}
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>动作绑定</h2>
                <IconAction
                  label="撤销本页按键调整"
                  onClick={() => setControl(structuredClone(initialControl.current))}
                >
                  <RotateCcw />
                </IconAction>
              </div>
              <div className="binding-grid header small">
                <span>驾驶动作</span>
                <span>{tab === "keyboard" ? "键盘" : "方向盘"}</span>
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
