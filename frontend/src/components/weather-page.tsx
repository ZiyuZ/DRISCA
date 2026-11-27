import { zhCN } from "../i18n";
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
  ["global", zhCN.weather.globalTab],
  ["events", zhCN.weather.eventsTab],
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
    ? zhCN.status.serviceDisconnected
    : !live
      ? zhCN.weather.eventRunningOnly
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
    toast.success(zhCN.weather.writeBackSuccess);
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
              title={zhCN.weather.eventsTab}
              description={live
                ? zhCN.weather.eventHint
                : zhCN.weather.eventIdleHint}
              cardHeaderAction={command => command.id === "local_fog_burst" ? (
                <ActionTooltip reason={!live && !preset ? zhCN.weather.choosePreset : (live ? zhCN.weather.manageLiveRegions : zhCN.weather.managePresetRegions)}>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="shrink-0 gap-1.5"
                    aria-label={zhCN.weather.manageRegions}
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
                  <DialogTitle>{zhCN.weather.regionsDialog}</DialogTitle>
                  <DialogDescription>
                    {live
                      ? zhCN.weather.liveRegionsHint
                      : zhCN.weather.presetRegionsHint}
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
                  <Button variant="outline" onClick={() => setFogDialogOpen(false)}>{zhCN.common.done}</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </section>
        ) : !preset || !weather ? (
          <div className="stack config-page">
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>{zhCN.weather.globalTab}</h2>
              </div>
              <div className="spawn-missing">
                <span>{zhCN.weather.noPreset}</span>
                <Button variant="outline" onClick={onOpenPresets}>{zhCN.weather.openPresets}</Button>
              </div>
            </Card>
          </div>
        ) : (
          <section className="stack config-page">
            {live ? (
              <>
                <div className="spawn-status" role="status">
                  <strong>{zhCN.weather.liveMode}</strong>
                  <span>{zhCN.weather.liveModeHint}</span>
                </div>
                <Card className="dr-card gap-0">
                  <div className="card-head">
                    <div>
                      <h2>{zhCN.weather.globalTab}</h2>
                      <p className="small">{zhCN.weather.liveHint}</p>
                    </div>
                    <ActionTooltip reason={!state.weather ? zhCN.weather.waiting : null}>
                      <Button variant="outline" disabled={!state.weather} onClick={writeBack}>
                        {zhCN.weather.writeBack}</Button>
                    </ActionTooltip>
                  </div>
                  {state.weather
                    ? (
                      <LiveWeatherControls
                        weather={state.weather}
                        presets={state.catalog.weather_presets}
                      />
                    )
                    : <p className="small">{zhCN.weather.waitingSentence}</p>}
                </Card>
              </>
            ) : (
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <div>
                    <h2>{zhCN.weather.globalTab}</h2>
                    <p className="small">{canPreview ? zhCN.weather.autosavePreviewHint : zhCN.weather.autosaveHint}</p>
                  </div>
                  <ActionTooltip reason={!defaultWeather ? zhCN.weather.waitingDefault : null}>
                    <Button variant="outline" disabled={!defaultWeather} onClick={restoreDefault}>
                      {zhCN.weather.resetDefault}</Button>
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
