import { zhCN, format } from "../i18n";
import { useState } from "react";
import { useRememberedTab } from "../hooks/use-remembered-tab";
import { Shuffle, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState, TrafficStyleCounts } from "../types/api";
import { carFollowingModels, laneChangeModels, totalTrafficVehicles, trafficStyles } from "../lib/traffic";
import { ActionTooltip } from "./action-tooltip";
import { EventActionPanel } from "./event-action-panel";
import { NumberInput } from "./number-input";
import { PageTabs } from "./page-tabs";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Slider } from "./ui/slider";
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
const TRAFFIC_TABS = [
  ["config", zhCN.traffic.configTab],
  ["events", zhCN.traffic.eventsTab],
] as const;
export function TrafficPage({
  preset,
  saveStatus,
  state,
  update,
  commands,
  online,
  onOpenPresets,
}: Props) {
  const [tab, setTab] = useRememberedTab("traffic", "config");
  const [diversityOpen, setDiversityOpen] = useState(false);
  const [viewPending, setViewPending] = useState(false);
  const [followPending, setFollowPending] = useState(false);
  const traffic = preset?.traffic;
  const counts = traffic?.style_counts;
  const totalVehicles = totalTrafficVehicles(counts);
  const diversityPct = Math.round((traffic?.diversity ?? 0.12) * 100);
  const following = carFollowingModels.find(item => item.value === traffic?.car_following_model);
  const laneChange = laneChangeModels.find(item => item.value === traffic?.lane_change_model);
  const enabled = traffic?.enabled === true;
  const laneChangeEnabled = enabled && traffic?.enable_lane_change === true;
  const preview = state.traffic_preview;
  const previewDisabled = !online || !state.carla_connected || state.phase !== "idle" || totalVehicles <= 0;
  const previewDisabledReason = !online
    ? zhCN.status.serviceDisconnected
    : !state.carla_connected
      ? zhCN.traffic.connectFirst
      : state.phase !== "idle"
        ? zhCN.traffic.previewWhileRunning
        : totalVehicles <= 0
          ? zhCN.traffic.vehiclesRequired
          : null;
  const stopPreviewDisabledReason = !online
    ? zhCN.status.serviceDisconnected
    : !preview.running
      ? zhCN.traffic.noPreview
      : null;
  const eventDisabledReason = !online
    ? zhCN.status.serviceDisconnected
    : state.phase !== "running"
      ? zhCN.traffic.eventRunningOnly
      : undefined;
  const startPreview = async () => {
    if (!traffic) return;
    try {
      await api("/api/traffic/preview/start", "POST", traffic);
      toast.success(zhCN.traffic.previewStarted);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };
  const stopPreview = async () => {
    try {
      await api("/api/traffic/preview/stop", "POST");
      toast.success(zhCN.traffic.previewStopped);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };
  const updateStyleCount = (key: keyof TrafficStyleCounts, raw: number) => {
    if (!counts) return;
    const otherTotal = totalVehicles - counts[key];
    const clamped = Math.max(0, Math.min(100 - otherTotal, Math.round(raw)));
    update(["traffic", "style_counts", key], clamped);
  };
  const randomizeStyles = () => {
    const target = totalVehicles > 0 ? totalVehicles : 20;
    const keys: (keyof TrafficStyleCounts)[] = ["balanced", "aggressive", "conservative", "sluggish"];
    const weights = keys.map(() => Math.random() + 0.15);
    const weightSum = weights.reduce((acc, item) => acc + item, 0);
    const next: TrafficStyleCounts = { balanced: 0, aggressive: 0, conservative: 0, sluggish: 0 };
    let assigned = 0;
    for (let i = 0; i < keys.length - 1; i++) {
      const value = Math.round((weights[i] / weightSum) * target);
      const bounded = Math.min(value, target - assigned);
      next[keys[i]] = bounded;
      assigned += bounded;
    }
    next[keys[keys.length - 1]] = Math.max(0, target - assigned);
    update(["traffic", "style_counts"], next);
  };
  return (
    <PageTabs
      value={tab}
      onValueChange={setTab}
      items={TRAFFIC_TABS}
      actions={<span className="save-status" role="status">{preset ? saveStatus : ""}</span>}
    >
      <div className="tab-scroll">
        <div className="stack config-page">
          {tab === "events" ? (
            <EventActionPanel
              commands={commands}
              category="traffic"
              disabled={!online || state.phase !== "running"}
              disabledReason={eventDisabledReason}
              title={zhCN.traffic.eventsTab}
              description={state.phase === "running"
                ? zhCN.traffic.eventHint
                : zhCN.traffic.eventIdleHint}
            />
          ) : !preset || !traffic || !counts ? (
            <Card className="dr-card gap-0">
              <div className="card-head">
                <h2>{zhCN.traffic.title}</h2>
              </div>
              <div className="spawn-missing">
                <span>{zhCN.traffic.noPreset}</span>
                <Button variant="outline" onClick={onOpenPresets}>{zhCN.traffic.openPresets}</Button>
              </div>
            </Card>
          ) : (
            <>
              {state.phase !== "idle" && (
                <p className="small" role="status">
                  {zhCN.traffic.nextExperimentHint}</p>
              )}
              <Card className="dr-card gap-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="grid min-w-0 gap-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <h2>{zhCN.traffic.title}</h2>
                      <label className="check">
                        <Switch aria-label={zhCN.traffic.enable} checked={traffic.enabled}
                          onCheckedChange={value => update(["traffic", "enabled"], value)} />
                        {traffic.enabled ? zhCN.traffic.enabled : zhCN.traffic.disabled}
                      </label>
                      <label className="check" title={zhCN.traffic.autoRespawnHint}>
                        <Switch aria-label={zhCN.traffic.autoRespawn} checked={traffic.auto_respawn} disabled={!enabled}
                          onCheckedChange={value => update(["traffic", "auto_respawn"], value)} />
                        {zhCN.traffic.autoRespawn}</label>
                      <span className={`dr-badge${preview.running ? " live" : ""}`}>
                        {preview.running ? format(zhCN.traffic.previewCount, { vehicleCount: preview.vehicle_count }) : zhCN.traffic.notPreviewing}
                      </span>
                    </div>
                    <p className="small">
                      {zhCN.traffic.previewHint}</p>
                    {preview.error && <p className="text-sm text-destructive" role="alert">{preview.error}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionTooltip reason={previewDisabled ? previewDisabledReason : null}>
                      <Button disabled={previewDisabled} onClick={() => void startPreview()}>
                        {zhCN.traffic.startPreview}</Button>
                    </ActionTooltip>
                    <ActionTooltip reason={!online || !preview.running ? stopPreviewDisabledReason : null}>
                      <Button variant="outline" disabled={!online || !preview.running} onClick={() => void stopPreview()}>
                        {zhCN.traffic.stopPreview}</Button>
                    </ActionTooltip>
                  </div>
                </div>
              </Card>
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <div>
                    <h2>{zhCN.traffic.countsTitle}</h2>
                    <p className="small">{zhCN.traffic.countsHint}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="dr-badge">{format(zhCN.traffic.total, { count: totalVehicles })}</span>
                    <ActionTooltip reason={!enabled ? zhCN.traffic.enableFirst : zhCN.traffic.randomizeHint}>
                      <Button variant="outline" size="sm" disabled={!enabled} onClick={randomizeStyles}>
                        <Shuffle className="mr-1.5 size-3.5" />
                        {zhCN.traffic.randomize}</Button>
                    </ActionTooltip>
                    <ActionTooltip reason={!enabled ? zhCN.traffic.enableFirst : format(zhCN.traffic.diversityHint, { diversityPct: diversityPct })}>
                      <Button variant="ghost" size="sm" aria-label={zhCN.traffic.diversitySettings} disabled={!enabled}
                        onClick={() => setDiversityOpen(true)}>
                        <SlidersHorizontal className="size-4" />
                      </Button>
                    </ActionTooltip>
                  </div>
                </div>
                <div className="form">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {trafficStyles.map(item => (
                      <label className="dr-field" key={item.value} title={item.description}>
                        <span>{item.label}</span>
                        <NumberInput
                          className="input mono"
                          min="0"
                          max="100"
                          step="1"
                          disabled={!enabled}
                          value={counts[item.value]}
                          onValueChange={value => updateStyleCount(item.value, value)}
                        />
                        <span className="small">{item.description}</span>
                      </label>
                    ))}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="dr-field">
                      <span>{zhCN.traffic.seed}</span>
                      <NumberInput className="input mono" step="1" disabled={!enabled}
                        value={traffic.seed}
                        onValueChange={value => update(["traffic", "seed"], Math.trunc(value))} />
                    </label>
                    <label className="dr-field">
                      <span>{zhCN.traffic.speedFactor}</span>
                      <NumberInput className="input mono" min="0.3" max="1.5" step="0.05" disabled={!enabled}
                        value={traffic.speed_factor}
                        onValueChange={value => update(["traffic", "speed_factor"], value)} />
                    </label>
                    <label className="dr-field">
                      <span>{zhCN.traffic.activeRadius}</span>
                      <NumberInput className="input mono" min="80" max="2000" step="any" disabled={!enabled}
                        value={traffic.active_radius_m}
                        onValueChange={value => update(["traffic", "active_radius_m"], value)} />
                    </label>
                  </div>
                </div>
              </Card>
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <h2>{zhCN.traffic.models}</h2>
                </div>
                <div className="form">
                  <label className="dr-field">
                    <span>{zhCN.traffic.followingModel}</span>
                    <SharedSelect
                      value={traffic.car_following_model}
                      disabled={!enabled}
                      options={carFollowingModels.map(item => [item.value, item.label] as const)}
                      onValueChange={value => update(["traffic", "car_following_model"], value)} />
                  </label>
                  <p className="small">{following?.description}</p>
                  <label className="check">
                    <Switch aria-label={zhCN.traffic.laneChange} checked={traffic.enable_lane_change} disabled={!enabled}
                      onCheckedChange={value => update(["traffic", "enable_lane_change"], value)} />
                    {zhCN.traffic.laneChange}</label>
                  <label className="dr-field">
                    <span>{zhCN.traffic.laneChangeModel}</span>
                    <SharedSelect
                      value={traffic.lane_change_model}
                      disabled={!laneChangeEnabled}
                      options={laneChangeModels.map(item => [item.value, item.label] as const)}
                      onValueChange={value => update(["traffic", "lane_change_model"], value)} />
                  </label>
                  <p className="small">
                    {laneChangeEnabled ? laneChange?.description : zhCN.traffic.laneChangeHint}
                  </p>
                </div>
              </Card>
              <Dialog open={diversityOpen} onOpenChange={setDiversityOpen}>
                <DialogContent className="sm:max-w-lg">
                  <DialogHeader>
                    <DialogTitle>{zhCN.traffic.diversityTitle}</DialogTitle>
                    <DialogDescription>
                      {zhCN.traffic.diversityDescription}</DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-2">
                    <div className="weather-field">
                      <span>{zhCN.traffic.diversityRange}</span>
                      <div className="weather-range">
                        <Slider
                          className="prototype-slider"
                          aria-label={zhCN.traffic.diversitySlider}
                          min={0}
                          max={35}
                          step={1}
                          value={[diversityPct]}
                          onValueChange={([v]) => update(["traffic", "diversity"], Math.round(v) / 100)}
                        />
                        <NumberInput
                          className="input mono"
                          min="0"
                          max="35"
                          step="1"
                          value={diversityPct}
                          onValueChange={v => update(["traffic", "diversity"], Math.max(0, Math.min(35, Math.round(v))) / 100)}
                        />
                      </div>
                    </div>
                    <p className="small">
                      {zhCN.traffic.diversitySafetyHint}</p>
                  </div>
                </DialogContent>
              </Dialog>
            </>
          )}
        </div>
      </div>
    </PageTabs>
  );
}
