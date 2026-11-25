import { useEffect, useRef, useState } from "react";
import { useRememberedTab } from "../hooks/use-remembered-tab";
import { SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState, Weather } from "../types/api";
import { ActionTooltip } from "./action-tooltip";
import { EventActionPanel } from "./event-action-panel";
import { LiveFogRegionManager, LiveWeatherControls } from "./live-weather";
import { PageTabs } from "./page-tabs";
import { FogRegionsEditor, WeatherEditor } from "./weather-editor";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";

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
  presetName,
  saveStatus,
  state,
  update,
  commands,
  online,
  onOpenPresets,
}: Props) {
  const [tab, setTab] = useRememberedTab("weather", "global");
  const [fogDialogOpen, setFogDialogOpen] = useState(false);
  const previewTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const live = state.phase === "running";
  const weather = preset?.world.weather;
  const fogCount = live ? state.fog_regions.length : (preset?.world.fog_regions.length ?? 0);
  const canPreview = online
    && state.carla_connected
    && !state.carla_connecting
    && !state.world_loading
    && state.phase === "idle"
    && weather !== undefined;
  useEffect(() => () => clearTimeout(previewTimer.current), [canPreview, presetName]);
  const defaultWeather = state.catalog.weather_presets.Default ?? state.catalog.weather_presets.ClearNoon;
  const eventDisabledReason = !online
    ? "管理端连接已断开"
    : !live
      ? "仅在实验运行期间可即时触发天气事件"
      : undefined;
  const preview = async (value: Weather) => {
    try {
      await api("/api/weather", "POST", { weather: value, transition_seconds: 0 });
    } catch (error) {
      toast.error(errorText(error));
    }
  };
  const changeWeather = (value: Weather) => {
    update(["world", "weather"], value);
    clearTimeout(previewTimer.current);
    if (canPreview) previewTimer.current = setTimeout(() => void preview(value), 300);
  };
  const restoreDefault = () => {
    if (!defaultWeather) return;
    clearTimeout(previewTimer.current);
    const value = structuredClone(defaultWeather);
    update(["world", "weather"], value);
    if (canPreview) void preview(value);
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
              <DialogContent className="fog-dialog flex flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
                <DialogHeader className="shrink-0 border-b px-6 py-5 text-left">
                  <DialogTitle>管理已添加的团雾</DialogTitle>
                  <DialogDescription>
                    {live
                      ? "运行期场景团雾：调整半径、雾强度或渐隐删除当前实验中的团雾，操作记录到日志与实验事件。"
                      : "空闲期预设团雾：维护实验启动时自动部署的初始团雾，修改自动保存到当前预设。"}
                  </DialogDescription>
                </DialogHeader>
                <div className="fog-dialog-body">
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
                </div>
                <DialogFooter className="shrink-0 border-t px-6 py-3">
                  <Button variant="outline" onClick={() => setFogDialogOpen(false)}>完成</Button>
                </DialogFooter>
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
                    <p className="small">{canPreview ? "修改自动保存到预设，并在 300ms 后预览到场景。" : "修改自动保存到当前预设；空闲且连接模拟器时自动预览。"}</p>
                  </div>
                  <ActionTooltip reason={!defaultWeather ? "等待模拟器提供默认天气目录" : null}>
                    <Button variant="outline" disabled={!defaultWeather} onClick={restoreDefault}>
                      复原默认
                    </Button>
                  </ActionTooltip>
                </div>
                <WeatherEditor
                  weather={weather}
                  weatherPresets={state.catalog.weather_presets}
                  onChange={changeWeather}
                />
              </Card>
            )}
          </section>
        )}
      </div>
    </PageTabs>
  );
}
