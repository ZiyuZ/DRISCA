import { useState } from "react";
import { useRememberedTab } from "../hooks/use-remembered-tab";
import { Shuffle, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandDefinition, PresetConfig, RuntimeState, TrafficStyleCounts, ViewMode } from "../types/api";
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
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

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
  ["config", "交通流配置"],
  ["events", "交通事件"],
] as const;
const VIEW_LABELS: Record<ViewMode, string> = {
  free: "自由视角",
  cockpit: "车内视角",
  chase: "第三人称",
};

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
    ? "管理端连接已断开"
    : !state.carla_connected
      ? "请先启动并连接 CARLA 模拟器"
      : state.phase !== "idle"
        ? "实验运行中无法开启空闲期车流预览"
        : totalVehicles <= 0
          ? "请先设置至少 1 辆背景车"
          : null;
  const stopPreviewDisabledReason = !online
    ? "管理端连接已断开"
    : !preview.running
      ? "当前未开启车流预览"
      : null;
  const eventDisabledReason = !online
    ? "管理端连接已断开"
    : state.phase !== "running"
      ? "仅在实验运行期间可即时触发交通事件"
      : undefined;
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
  const changeView = async (mode: ViewMode) => {
    if (mode === state.view_mode) return;
    setViewPending(true);
    try {
      await api("/api/view/mode", "POST", { mode });
      toast.success(`已切换为${VIEW_LABELS[mode]}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setViewPending(false);
    }
  };
  const changeFollow = async (delta: -1 | 1) => {
    setFollowPending(true);
    try {
      await api("/api/traffic/preview/follow", "POST", { delta });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setFollowPending(false);
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
              title="交通事件"
              description={state.phase === "running"
                ? "即时触发已注册的交通事件，结果记录到当前实验。"
                : "实验运行时可即时触发已注册的交通事件。"}
            />
          ) : !preset || !traffic || !counts ? (
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
                  <div className="grid min-w-0 gap-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <h2>背景交通流</h2>
                      <label className="check">
                        <Switch aria-label="启用背景交通流" checked={traffic.enabled}
                          onCheckedChange={value => update(["traffic", "enabled"], value)} />
                        {traffic.enabled ? "已启用" : "未启用"}
                      </label>
                      <label className="check" title="开启后，在非封闭地图上车辆离开边界或侧翻销毁时会自动在空闲出生点补充同风格车辆">
                        <Switch aria-label="越界自动补充" checked={traffic.auto_respawn} disabled={!enabled}
                          onCheckedChange={value => update(["traffic", "auto_respawn"], value)} />
                        越界自动补充
                      </label>
                      <span className={`dr-badge${preview.running ? " live" : ""}`}>
                        {preview.running ? `预览中 · ${preview.vehicle_count} 辆车` : "未开启预览"}
                      </span>
                    </div>
                    <p className="small">
                      总开关决定正式实验是否生成背景车；空闲期可按下方车辆构成与模型直接预览，不保存实验数据，开跑实验或切换地图时自动停止。
                    </p>
                    {preview.error && <p className="text-sm text-destructive" role="alert">{preview.error}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionTooltip reason={previewDisabled ? previewDisabledReason : null}>
                      <Button disabled={previewDisabled} onClick={() => void startPreview()}>
                        预览当前交通流
                      </Button>
                    </ActionTooltip>
                    <ActionTooltip reason={!online || !preview.running ? stopPreviewDisabledReason : null}>
                      <Button variant="outline" disabled={!online || !preview.running} onClick={() => void stopPreview()}>
                        停止预览
                      </Button>
                    </ActionTooltip>
                  </div>
                </div>
                {preview.running && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/60 pt-3">
                    <span className="small">预览视角</span>
                    <Tabs value={state.view_mode} onValueChange={value => void changeView(value as ViewMode)}>
                      <TabsList>
                        {(Object.keys(VIEW_LABELS) as ViewMode[]).map(mode => (
                          <TabsTrigger key={mode} value={mode} disabled={viewPending}>
                            {VIEW_LABELS[mode]}
                          </TabsTrigger>
                        ))}
                      </TabsList>
                    </Tabs>
                    {state.view_mode !== "free" && (
                      <div className="flex items-center gap-1 rounded-md border p-0.5" role="group" aria-label="切换观察车辆">
                        <Button size="sm" variant="ghost" disabled={!online || followPending || viewPending} onClick={() => void changeFollow(-1)}>上一辆</Button>
                        <span className="min-w-20 px-2 text-center font-mono text-xs" role="status">车辆 {preview.follow_actor_id == null ? "—" : `#${preview.follow_actor_id}`}</span>
                        <Button size="sm" variant="ghost" disabled={!online || followPending || viewPending} onClick={() => void changeFollow(1)}>下一辆</Button>
                      </div>
                    )}
                  </div>
                )}
              </Card>
              <Card className="dr-card gap-0">
                <div className="card-head">
                  <div>
                    <h2>车辆数量与驾驶风格</h2>
                    <p className="small">分别指定各类驾驶风格的车辆数，总车辆数自动汇总（上限 100 辆）。</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="dr-badge">总计 {totalVehicles} 辆</span>
                    <ActionTooltip reason={!enabled ? "请先启用背景交通流" : "按当前总数随机打散到四种风格"}>
                      <Button variant="outline" size="sm" disabled={!enabled} onClick={randomizeStyles}>
                        <Shuffle className="mr-1.5 size-3.5" />
                        随机分配
                      </Button>
                    </ActionTooltip>
                    <ActionTooltip reason={!enabled ? "请先启用背景交通流" : `同风格个体差异分布（当前 ±${diversityPct}%）`}>
                      <Button variant="ghost" size="sm" aria-label="个体差异分布设置" disabled={!enabled}
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
                  <div className="grid gap-3 sm:grid-cols-2">
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
              <Dialog open={diversityOpen} onOpenChange={setDiversityOpen}>
                <DialogContent className="sm:max-w-lg">
                  <DialogHeader>
                    <DialogTitle>同风格个体差异分布</DialogTitle>
                    <DialogDescription>
                      在同一驾驶风格均值附近，以截断高斯分布为每辆车独立抽样速度倍率、车头时距、加速度、换道冷却与感知延迟；受预设随机种子控制，可完整复现。
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-2">
                    <div className="weather-field">
                      <span>参数离散度 · %（0% 为完全一致，默认 12%）</span>
                      <div className="weather-range">
                        <Slider
                          className="prototype-slider"
                          aria-label="参数离散度"
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
                      实际抽样范围会被截断在 ±2σ 内并夹紧到物理安全上下界，避免出现过小安全距离或异常加减速。
                    </p>
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
