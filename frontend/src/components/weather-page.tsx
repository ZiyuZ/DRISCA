import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState } from "../types/api";
import { ActionTooltip } from "./action-tooltip";
import { EventActionPanel } from "./event-action-panel";
import { LiveFogRegionManager, LiveWeatherControls } from "./live-weather";
import { PageTabs } from "./page-tabs";
import { FogRegionsEditor, WeatherEditor } from "./weather-editor";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

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
const WEATHER_TABS = [
  ["global", "全局天气"],
  ["events", "天气事件"],
] as const;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function WeatherPage({
  preset,
  saveStatus,
  state,
  update,
  commands,
  online,
  onOpenPresets,
}: Props) {
  const [tab, setTab] = useState("global");
  const [fogDialogOpen, setFogDialogOpen] = useState(false);
  const live = state.phase === "running";
  const weather = preset?.world.weather;
  const fogCount = live ? state.fog_regions.length : (preset?.world.fog_regions.length ?? 0);
  const canPreview = online
    && state.carla_connected
    && !state.carla_connecting
    && !state.world_loading
    && state.phase === "idle"
    && weather !== undefined;
  const previewDisabledReason = !online
    ? "管理端连接已断开"
    : !state.carla_connected
      ? "请先启动并连接 CARLA 模拟器"
      : state.carla_connecting
        ? "正在连接 CARLA 模拟器"
        : state.phase !== "idle"
          ? "实验进行中无法预览预设天气"
          : state.world_loading
            ? "正在加载世界，请稍候"
            : null;
  const eventDisabledReason = !online
    ? "管理端连接已断开"
    : !live
      ? "仅在实验运行期间可即时触发天气事件"
      : undefined;
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
    <PageTabs
      value={tab}
      onValueChange={setTab}
      items={WEATHER_TABS}
      actions={<span className="save-status" role="status">{preset ? saveStatus : ""}</span>}
    >
      <div className="tab-scroll">
        {tab === "events" ? (
          <section className="stack config-page">
            <EventActionPanel
              commands={commands}
              category="weather"
              disabled={!online || !live}
              disabledReason={eventDisabledReason}
              title="天气事件"
              description={live
                ? "即时触发已注册的天气事件，结果记录到当前实验。"
                : "实验运行时可即时触发已注册的天气事件；点击团雾右上角按钮可管理预设团雾。"}
              cardHeaderAction={command => command.id === "local_fog_burst" ? (
                <ActionTooltip reason={!live && !preset ? "请先选择一个实验预设" : (live ? "管理当前已创建的团雾" : "管理预设初始团雾")}>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="shrink-0 gap-1.5"
                    aria-label="管理团雾"
                    disabled={!live && !preset}
                    onClick={() => setFogDialogOpen(true)}
                  >
                    <SlidersHorizontal className="size-4" />
                    {fogCount > 0 && <span className="font-mono text-xs">{fogCount}</span>}
                  </Button>
                </ActionTooltip>
              ) : null}
            />
            <Dialog open={fogDialogOpen} onOpenChange={setFogDialogOpen}>
              <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
                <DialogHeader>
                  <DialogTitle>{live ? "管理已创建的团雾" : "管理预设初始团雾"}</DialogTitle>
                  <DialogDescription>
                    {live
                      ? "调整半径、雾强度或渐隐删除已创建的团雾，所有操作均记录到日志与实验事件。"
                      : "维护实验启动时自动部署的初始团雾，修改自动保存到当前预设。"}
                  </DialogDescription>
                </DialogHeader>
                {live ? (
                  <LiveFogRegionManager
                    regions={state.fog_regions}
                    telemetry={state.telemetry}
                    running
                  />
                ) : preset ? (
                  <FogRegionsEditor
                    regions={preset.world.fog_regions}
                    onChange={value => update(["world", "fog_regions"], value)}
                  />
                ) : null}
              </DialogContent>
            </Dialog>
          </section>
        ) : !preset || !weather ? (
          <div className="stack config-page">
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>全局天气</h2>
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
                      <h2>全局天气</h2>
                      <p className="small">调整经驾驶端实时应用，可按需写回当前预设。</p>
                    </div>
                    <ActionTooltip reason={!state.weather ? "等待驾驶端上报当前天气" : null}>
                      <Button variant="outline" disabled={!state.weather} onClick={writeBack}>
                        写回当前预设
                      </Button>
                    </ActionTooltip>
                  </div>
                  {state.weather
                    ? (
                      <LiveWeatherControls
                        weather={state.weather}
                        presets={state.catalog.weather_presets}
                      />
                    )
                    : <p className="small">等待驾驶端上报当前天气。</p>}
                </Card>
              </>
            ) : (
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <div>
                    <h2>全局天气</h2>
                    <p className="small">修改自动保存到当前预设；连接模拟器后可预览到场景。</p>
                  </div>
                  <ActionTooltip reason={!canPreview ? previewDisabledReason : null}>
                    <Button variant="outline" disabled={!canPreview} onClick={() => void preview()}>
                      预览到场景
                    </Button>
                  </ActionTooltip>
                </div>
                <WeatherEditor
                  weather={weather}
                  weatherPresets={state.catalog.weather_presets}
                  onChange={value => update(["world", "weather"], value)}
                />
              </Card>
            )}
          </section>
        )}
      </div>
    </PageTabs>
  );
}
