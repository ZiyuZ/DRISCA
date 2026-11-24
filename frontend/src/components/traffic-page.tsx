import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState } from "../types/api";
import { carFollowingModels, laneChangeModels, trafficStyles } from "../lib/traffic";
import { EventActionPanel } from "./event-action-panel";
import { NumberInput } from "./number-input";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Switch } from "./ui/switch";

type Props = {
  preset: PresetConfig | null;
  presetName: string;
  saveStatus: string;
  state: RuntimeState;
  update: (path: string[], value: unknown) => void;
  commands: CommandDefinition[];
  online: boolean;
  onOpenPresets: () => void;
};

export function TrafficPage({
  preset,
  presetName,
  saveStatus,
  state,
  update,
  commands,
  online,
  onOpenPresets,
}: Props) {
  const traffic = preset?.traffic;
  const style = trafficStyles.find(item => item.value === traffic?.style);
  const following = carFollowingModels.find(item => item.value === traffic?.car_following_model);
  const laneChange = laneChangeModels.find(item => item.value === traffic?.lane_change_model);
  const enabled = traffic?.enabled === true;
  const laneChangeEnabled = enabled && traffic?.enable_lane_change === true;
  const preview = state.traffic_preview;
  const previewDisabled = !online || !state.carla_connected || state.phase !== "idle"
    || (traffic?.vehicle_count ?? 0) <= 0;
  const startPreview = async () => {
    if (!traffic) return;
    try {
      await api("/api/traffic/preview/start", "POST", traffic);
      toast.success("车流预览已启动");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };
  const stopPreview = async () => {
    try {
      await api("/api/traffic/preview/stop", "POST");
      toast.success("车流预览已停止");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };
  return (
    <div className="tabbed-page tabs">
      <div className="page-tabs-row">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-sm text-muted-foreground">当前预设</span>
          <strong className="truncate text-sm">{presetName || "未选择"}</strong>
        </div>
        <span className="save-status" role="status">{preset ? saveStatus : ""}</span>
      </div>
      <div className="tab-scroll">
        <div className="stack config-page">
        {!preset || !traffic ? (
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>背景交通流</h2>
              </div>
              <div className="spawn-missing">
                <span>尚未选择预设，交通流参数保存在实验预设中。</span>
                <Button variant="outline" onClick={onOpenPresets}>打开方案管理</Button>
              </div>
            </Card>
        ) : (
            <>
            {state.phase !== "idle" && (
              <p className="small" role="status">
                实验进行中；本页修改保存到预设，对下一次实验生效。
              </p>
            )}
            <Card className="dr-card gap-0">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="grid min-w-0 gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2>车流预览</h2>
                    <span className={`dr-badge${preview.running ? " live" : ""}`}>
                      {preview.running ? `预览中 · ${preview.vehicle_count} 辆车` : "未开启预览"}
                    </span>
                  </div>
                  <p className="small">
                    空闲期预览直接按上方参数生成并驱动车流，不保存实验数据；开始正式实验或切换地图时自动停止并重置。
                  </p>
                  {preview.error && <p className="text-sm text-destructive" role="alert">{preview.error}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button disabled={previewDisabled} onClick={() => void startPreview()}>
                    预览当前交通流
                  </Button>
                  <Button variant="outline" disabled={!online || !preview.running} onClick={() => void stopPreview()}>
                    停止预览
                  </Button>
                </div>
              </div>
            </Card>
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>基础车流</h2>
              </div>
              <div className="form">
                <label className="check">
                  <Switch aria-label="启用背景交通流" checked={traffic.enabled}
                    onCheckedChange={value => update(["traffic", "enabled"], value)} />
                  启用背景交通流
                </label>
                <div className="three">
                  <label className="dr-field">
                    <span>背景车数量</span>
                    <NumberInput className="input mono" min="0" max="100" step="1" disabled={!enabled}
                      value={traffic.vehicle_count}
                      onValueChange={value => update(["traffic", "vehicle_count"], Math.round(value))} />
                  </label>
                  <label className="dr-field">
                    <span>随机种子</span>
                    <NumberInput className="input mono" step="1" disabled={!enabled}
                      value={traffic.seed}
                      onValueChange={value => update(["traffic", "seed"], Math.trunc(value))} />
                  </label>
                  <label className="dr-field">
                    <span>速度系数</span>
                    <NumberInput className="input mono" min="0.3" max="1.5" step="0.05" disabled={!enabled}
                      value={traffic.speed_factor}
                      onValueChange={value => update(["traffic", "speed_factor"], value)} />
                  </label>
                </div>
              </div>
            </Card>
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>行为模型</h2>
              </div>
              <div className="form">
                <label className="dr-field">
                  <span>驾驶风格</span>
                  <SharedSelect
                    value={traffic.style}
                    disabled={!enabled}
                    options={trafficStyles.map(item => [item.value, item.label] as const)}
                    onValueChange={value => update(["traffic", "style"], value)} />
                </label>
                <p className="small">{style?.description}</p>
                <label className="dr-field">
                  <span>跟驰模型</span>
                  <SharedSelect
                    value={traffic.car_following_model}
                    disabled={!enabled}
                    options={carFollowingModels.map(item => [item.value, item.label] as const)}
                    onValueChange={value => update(["traffic", "car_following_model"], value)} />
                </label>
                <p className="small">{following?.description}</p>
                <label className="check">
                  <Switch aria-label="允许换道" checked={traffic.enable_lane_change} disabled={!enabled}
                    onCheckedChange={value => update(["traffic", "enable_lane_change"], value)} />
                  允许换道
                </label>
                <label className="dr-field">
                  <span>换道模型</span>
                  <SharedSelect
                    value={traffic.lane_change_model}
                    disabled={!laneChangeEnabled}
                    options={laneChangeModels.map(item => [item.value, item.label] as const)}
                    onValueChange={value => update(["traffic", "lane_change_model"], value)} />
                </label>
                <p className="small">
                  {laneChangeEnabled ? laneChange?.description : "启用换道后可选择换道模型。"}
                </p>
              </div>
            </Card>
            </>
        )}
          <EventActionPanel
            commands={commands}
            category="traffic"
            disabled={!online || state.phase !== "running"}
            title="交通事件"
            description={state.phase === "running"
              ? "即时触发已注册的交通事件，结果记录到当前实验。"
              : "实验运行时可即时触发已注册的交通事件。"}
          />
        </div>
      </div>
    </div>
  );
}
