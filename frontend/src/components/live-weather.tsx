import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeFogRegion, Telemetry, Weather } from "../types/api";
import { NumberInput } from "./number-input";
import { WeatherEditor } from "./weather-editor";
import { Button } from "./ui/button";

type Props = {
  weather: Weather;
  presets: Record<string, Weather>;
};
type FogUpdate = { radius_m?: number; density?: number; transition_seconds: number };

const percent = (value: number) => Math.round(value * 10000) / 100;
const round = (value: number) => Math.round(value * 100) / 100;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function LiveWeatherControls({ weather, presets }: Props) {
  const [draft, setDraft] = useState(weather);
  const [transition, setTransition] = useState(0);
  const pending = useRef<{ weather: Weather; transition_seconds: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const apply = async () => {
    const value = pending.current;
    if (!value) return;
    pending.current = null;
    try { await api("/api/weather", "POST", value); }
    catch (error) { toast.error(errorText(error)); }
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  const change = (value: Weather) => {
    setDraft(value);
    pending.current = { weather: value, transition_seconds: transition };
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void apply(), 300);
  };
  return (
    <div className="grid gap-5">
      <label className="weather-field">
        <span>全局渐变时长 · s</span>
        <div className="weather-range">
          <span className="text-sm text-muted-foreground">下一次天气调整使用该时长</span>
          <NumberInput className="input mono" min="0" step="0.5" value={transition}
            onValueChange={setTransition} />
        </div>
      </label>
      <WeatherEditor weather={draft} weatherPresets={presets} onChange={change} />
    </div>
  );
}

export function LiveFogRegionManager({ regions, telemetry, running }: {
  regions: RuntimeFogRegion[];
  telemetry: Telemetry | null;
  running: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const submit = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try {
      await action();
      toast.success(success);
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <FogRegionEditor
      regions={regions}
      telemetry={telemetry}
      running={running}
      busy={busy}
      onCreate={(body) => void submit(() => api("/api/weather/regions", "POST", body), "团雾已创建")}
      onUpdate={(regionId, body) => void submit(() => api(`/api/weather/regions/${regionId}`, "PATCH", body), "团雾已更新")}
      onDelete={(regionId, seconds) => void submit(() => api(`/api/weather/regions/${regionId}?transition_seconds=${seconds}`, "DELETE"), "团雾删除已提交")}
    />
  );
}

function FogRegionEditor({ regions, telemetry, running, busy, onCreate, onUpdate, onDelete }: {
  regions: RuntimeFogRegion[];
  telemetry: Telemetry | null;
  running: boolean;
  busy: boolean;
  onCreate: (body: { center_m: number[]; radius_m: number; density: number; transition_seconds: number }) => void;
  onUpdate: (regionId: number, body: FogUpdate) => void;
  onDelete: (regionId: number, transitionSeconds: number) => void;
}) {
  const [center, setCenter] = useState<[number, number, number]>([0, 0, 0]);
  const [radius, setRadius] = useState(50);
  const [density, setDensity] = useState(50);
  const [transition, setTransition] = useState(0);
  const fillFront = () => {
    if (!telemetry) return;
    const yaw = telemetry.rotation_yaw * Math.PI / 180;
    setCenter([
      round(telemetry.location_x + 25 * Math.cos(yaw)),
      round(telemetry.location_y + 25 * Math.sin(yaw)),
      round(telemetry.location_z + 2),
    ]);
  };
  return (
    <section className="fog-regions">
      <div className="fog-section-head">
        <div>
          <strong>已添加的团雾</strong>
          <span>{regions.length} 个区域</span>
        </div>
      </div>
      {regions.length === 0
        ? <p className="weather-note fog-empty">当前没有已创建的团雾。可在下方新建立即生效。</p>
        : (
          <div className="fog-region-list">
            {regions.map(region => (
              <FogRegionRow key={region.region_id} region={region} busy={busy}
                onUpdate={body => onUpdate(region.region_id, body)}
                onDelete={seconds => onDelete(region.region_id, seconds)} />
            ))}
          </div>
        )}
      <div className="fog-regions-divider" />
      <div className="fog-section-head"><div><strong>新增团雾</strong><span>立即应用到场景</span></div></div>
      <div className="fog-add">
        <div className="fog-region-head">
          <strong>设置新区域</strong>
          {running && telemetry
            ? <Button variant="ghost" disabled={busy} onClick={fillFront}>主车前方 25m</Button>
            : <span className="weather-note">运行中且有遥测时可填入主车前方</span>}
        </div>
        <div className="fog-region-grid">
          {(["X", "Y", "Z"] as const).map((axis, index) => (
            <label className="field-row" key={axis}>
              <span>中心 {axis} · m</span>
              <NumberInput className="input mono" step="0.1" value={center[index]}
                onValueChange={value => setCenter(old => {
                  const next = [...old] as [number, number, number];
                  next[index] = value;
                  return next;
                })} />
            </label>
          ))}
          <label className="field-row">
            <span>半径 · m</span>
            <NumberInput className="input mono" min="0.1" step="any" value={radius} onValueChange={setRadius} />
          </label>
          <label className="field-row">
            <span>雾强度 · %</span>
            <NumberInput className="input mono" min="0" max="100" step="1" value={density} onValueChange={setDensity} />
          </label>
          <label className="field-row">
            <span>渐变 · s</span>
            <NumberInput className="input mono" min="0" step="0.5" value={transition} onValueChange={setTransition} />
          </label>
        </div>
        <div className="fog-region-actions">
          <Button disabled={busy}
            onClick={() => onCreate({ center_m: center, radius_m: radius, density: density / 100, transition_seconds: transition })}>
            创建并应用
          </Button>
          <span className="small">创建后立即生效，无需再点“应用更新”。</span>
        </div>
      </div>
    </section>
  );
}

function FogRegionRow({ region, busy, onUpdate, onDelete }: {
  region: RuntimeFogRegion;
  busy: boolean;
  onUpdate: (body: FogUpdate) => void;
  onDelete: (transitionSeconds: number) => void;
}) {
  const [radius, setRadius] = useState(region.radius_m);
  const [density, setDensity] = useState(percent(region.density));
  const [transition, setTransition] = useState(0);
  useEffect(() => {
    setRadius(region.radius_m);
    setDensity(percent(region.density));
  }, [region.radius_m, region.density]);
  const disabled = busy || region.deleting;
  const dirty = radius !== region.radius_m || density !== percent(region.density);
  return (
    <div className="fog-region">
      <div className="fog-region-head">
        <strong>团雾 #{region.region_id}</strong>
        <span className="rounded-full border bg-background px-2 py-1 text-xs font-normal text-muted-foreground">{region.deleting ? "渐隐中" : "已创建"}</span>
      </div>
      <p className="px-4 pt-3 text-xs text-muted-foreground">中心坐标 · m <span className="ml-2 font-mono">{region.center_m.map(value => value.toFixed(2)).join(" / ")}</span></p>
      <div className="fog-region-grid">
        <label className="field-row">
          <span>半径 · m</span>
          <NumberInput className="input mono" disabled={disabled} min="0.1" step="any" value={radius} onValueChange={setRadius} />
        </label>
        <label className="field-row">
          <span>雾强度 · %</span>
          <NumberInput className="input mono" disabled={disabled} min="0" max="100" step="1" value={density} onValueChange={setDensity} />
        </label>
        <label className="field-row">
          <span>渐变 · s</span>
          <NumberInput className="input mono" disabled={disabled} min="0" step="0.5" value={transition} onValueChange={setTransition} />
        </label>
      </div>
      <div className="fog-region-actions">
        <Button disabled={disabled || !dirty}
          onClick={() => onUpdate({ radius_m: radius, density: density / 100, transition_seconds: transition })}>
          应用更新
        </Button>
        <span className="small" role="status">
          {region.deleting ? "渐隐中" : dirty ? "参数已修改，待应用" : "未修改"}
        </span>
        <Button variant="destructive" className="ml-auto" disabled={disabled} aria-label={`删除区域 ${region.region_id}`}
          onClick={() => onDelete(transition)}>
          渐隐删除
        </Button>
      </div>
    </div>
  );
}
