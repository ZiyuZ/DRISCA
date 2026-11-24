import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState } from "../types/api";
import { EventActionPanel } from "./event-action-panel";
import { LiveWeatherControls } from "./live-weather";
import { WeatherEditor } from "./weather-editor";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

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
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function WeatherPage({
  preset,
  presetName,
  saveStatus,
  state,
  update,
  commands,
  online,
  onOpenPresets,
}: Props) {
  const live = state.phase === "running";
  const weather = preset?.world.weather;
  const canPreview = online
    && state.carla_connected
    && !state.carla_connecting
    && !state.world_loading
    && state.phase === "idle"
    && weather !== undefined;
  const previewHint = !online
    ? "管理端连接已断开"
    : !state.carla_connected
      ? "连接模拟器后可预览"
      : state.phase !== "idle"
        ? "实验进行中不能预览预设天气"
        : state.world_loading
          ? "正在加载世界"
          : "将当前预设的全局天气应用到场景";
  const preview = async () => {
    if (!weather) return;
    try {
      await api("/api/weather", "POST", { weather, transition_seconds: 0 });
      toast.success("已将预设天气预览到场景");
    } catch (error) {
      toast.error(errorText(error));
    }
  };
  const writeBack = () => {
    if (!state.weather) return;
    update(["world", "weather"], { ...state.weather, preset_name: "Custom" });
    toast.success("已写回当前预设");
  };
  return (
    <div className="tabbed-page tabs weather-page">
      <div className="page-tabs-row">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-sm text-muted-foreground">当前预设</span>
          <strong className="truncate text-sm">{presetName || "未选择"}</strong>
        </div>
        <span className="save-status" role="status">{preset ? saveStatus : ""}</span>
      </div>
      <div className="tab-scroll">
        {!preset || !weather ? (
          <div className="stack config-page">
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>天气与局部球雾</h2>
              </div>
              <div className="spawn-missing">
                <span>尚未选择预设，天气参数保存在实验预设中。</span>
                <Button variant="outline" onClick={onOpenPresets}>打开方案管理</Button>
              </div>
            </Card>
          </div>
        ) : (
          <section className="stack config-page">
            {live ? (
              <>
                <div className="spawn-status" role="status">
                  <strong>实时调控模式</strong>
                  <span>运行期调整实时生效，不会自动覆盖预设文件。</span>
                </div>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <div>
                      <h2>全局天气与局部球雾</h2>
                      <p className="small">调整经驾驶端实时应用；写回当前预设仅包含全局天气。</p>
                    </div>
                    <Button variant="outline" disabled={!state.weather} onClick={writeBack}>
                      写回当前预设
                    </Button>
                  </div>
                  {state.weather
                    ? (
                      <LiveWeatherControls
                        weather={state.weather}
                        presets={state.catalog.weather_presets}
                        regions={state.fog_regions}
                        telemetry={state.telemetry}
                        running
                      />
                    )
                    : <p className="small">等待驾驶端上报当前天气。</p>}
                </Card>
              </>
            ) : (
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <div>
                    <h2>全局天气与初始球雾</h2>
                    <p className="small">修改自动保存到当前预设；连接模拟器后可预览到场景。</p>
                  </div>
                  <Button variant="outline" disabled={!canPreview} title={previewHint} onClick={() => void preview()}>
                    预览到场景
                  </Button>
                </div>
                <WeatherEditor
                  weather={weather}
                  weatherPresets={state.catalog.weather_presets}
                  onChange={value => update(["world", "weather"], value)}
                  regions={preset.world.fog_regions}
                  onRegionsChange={value => update(["world", "fog_regions"], value)}
                />
              </Card>
            )}
            <EventActionPanel
              commands={commands}
              category="weather"
              disabled={!online || !live}
              title="天气事件"
              description={live
                ? "即时触发已注册的天气事件，结果记录到当前实验。"
                : "实验运行时可即时触发已注册的天气事件。"}
            />
          </section>
        )}
      </div>
    </div>
  );
}
