import type { PresetConfig, RuntimeState } from "../types/api";
import { carFollowingModels, laneChangeModels, trafficStyles } from "../lib/traffic";
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
  onOpenPresets: () => void;
};

export function TrafficPage({ preset, presetName, saveStatus, state, update, onOpenPresets }: Props) {
  const traffic = preset?.traffic;
  const style = trafficStyles.find(item => item.value === traffic?.style);
  const following = carFollowingModels.find(item => item.value === traffic?.car_following_model);
  const laneChange = laneChangeModels.find(item => item.value === traffic?.lane_change_model);
  const enabled = traffic?.enabled === true;
  const laneChangeEnabled = enabled && traffic?.enable_lane_change === true;
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
        {!preset || !traffic ? (
          <div className="stack config-page">
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>背景交通流</h2>
              </div>
              <div className="spawn-missing">
                <span>尚未选择预设，交通流参数保存在实验预设中。</span>
                <Button variant="outline" onClick={onOpenPresets}>打开方案管理</Button>
              </div>
            </Card>
          </div>
        ) : (
          <section className="stack config-page">
            {state.phase !== "idle" && (
              <p className="small" role="status">
                实验进行中；本页修改保存到预设，对下一次实验生效。
              </p>
            )}
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
          </section>
        )}
      </div>
    </div>
  );
}
