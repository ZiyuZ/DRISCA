import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeFogRegion, Telemetry, Weather } from "../types/api";
import { Modal } from "./common";
import { NumberInput } from "./number-input";
import { WeatherEditor } from "./weather-editor";
import { Button } from "./ui/button";

type Props = {
  weather: Weather;
  presets: Record<string, Weather>;
  regions: RuntimeFogRegion[];
  telemetry: Telemetry | null;
  running: boolean;
  onClose: () => void;
};
type FogUpdate = { radius_m?: number; density?: number; transition_seconds: number };

const percent = (value: number) => Math.round(value * 10000) / 100;
const round = (value: number) => Math.round(value * 100) / 100;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function LiveWeather({ weather, presets, regions, telemetry, running, onClose }: Props) {
  const [draft, setDraft] = useState(weather);
  const [transition, setTransition] = useState(0);
  const [busy, setBusy] = useState(false);
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
  const close = () => {
    clearTimeout(timer.current);
    void apply();
    onClose();
  };
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
  return <Modal title="实时天气" open onClose={close}>
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
      <FogRegionEditor regions={regions} telemetry={telemetry} running={running} busy={busy}
        onCreate={(body) => void submit(() => api("/api/weather/regions", "POST", body), "局部球雾已创建")}
        onUpdate={(regionId, body) => void submit(() => api(`/api/weather/regions/${regionId}`, "PATCH", body), "局部球雾已更新")}
        onDelete={(regionId, seconds) => void submit(() => api(`/api/weather/regions/${regionId}?transition_seconds=${seconds}`, "DELETE"), "局部球雾删除已提交")} />
    </div>
  </Modal>;
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
      <div className="fog-regions-head">
        <div>
          <h3>局部球雾</h3>
          <p>独立于全局天气。运行中经驾驶端命令应用，空闲时直接应用到当前世界。</p>
        </div>
      </div>
      {regions.length === 0
        ? <p className="weather-note">当前没有局部球雾。</p>
        : regions.map(region => (
          <FogRegionRow key={region.region_id} region={region} busy={busy}
            onUpdate={body => onUpdate(region.region_id, body)}
            onDelete={seconds => onDelete(region.region_id, seconds)} />
        ))}
      <div className="fog-region">
        <div className="fog-region-head">
          <span>新增区域</span>
          {running && telemetry
            ? <Button variant="ghost" disabled={busy} onClick={fillFront}>主车前方 25m</Button>
            : <span className="weather-note">运行中且有遥测时可填入主车前方</span>}
        </div>
        <div className="fog-region-grid">
          {(["X", "Y", "Z"] as const).map((axis, index) => (
            <label className="dr-field" key={axis}>
              <span>中心 {axis} · m</span>
              <NumberInput className="input mono" step="0.1" value={center[index]}
                onValueChange={value => setCenter(old => {
                  const next = [...old] as [number, number, number];
                  next[index] = value;
                  return next;
                })} />
            </label>
          ))}
          <label className="dr-field">
            <span>半径 · m</span>
            <NumberInput className="input mono" min="0.1" step="any" value={radius} onValueChange={setRadius} />
          </label>
          <label className="dr-field">
            <span>雾强度 · %</span>
            <NumberInput className="input mono" min="0" max="100" step="1" value={density} onValueChange={setDensity} />
          </label>
          <label className="dr-field">
            <span>渐变 · s</span>
            <NumberInput className="input mono" min="0" step="0.5" value={transition} onValueChange={setTransition} />
          </label>
        </div>
        <Button className="justify-self-start" disabled={busy}
          onClick={() => onCreate({ center_m: center, radius_m: radius, density: density / 100, transition_seconds: transition })}>
          创建并应用
        </Button>
        <p className="small">创建后立即生效，无需再点“应用更新”。</p>
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
        <span>区域 {region.region_id}</span>
        <span className="text-sm text-muted-foreground">
          {region.deleting ? "渐隐中" : `中心 (${region.center_m.map(value => value.toFixed(1)).join(", ")})`}
        </span>
      </div>
      <div className="fog-region-grid">
        <label className="dr-field">
          <span>半径 · m</span>
          <NumberInput className="input mono" disabled={disabled} min="0.1" step="any" value={radius} onValueChange={setRadius} />
        </label>
        <label className="dr-field">
          <span>雾强度 · %</span>
          <NumberInput className="input mono" disabled={disabled} min="0" max="100" step="1" value={density} onValueChange={setDensity} />
        </label>
        <label className="dr-field">
          <span>渐变 · s</span>
          <NumberInput className="input mono" disabled={disabled} min="0" step="0.5" value={transition} onValueChange={setTransition} />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={disabled || !dirty}
          onClick={() => onUpdate({ radius_m: radius, density: density / 100, transition_seconds: transition })}>
          应用更新
        </Button>
        <span className="small" role="status">
          {region.deleting ? "渐隐中" : dirty ? "参数已修改，待应用" : "未修改"}
        </span>
        <Button variant="outline" disabled={disabled} aria-label={`删除区域 ${region.region_id}`}
          onClick={() => onDelete(transition)}>
          渐隐删除
        </Button>
      </div>
    </div>
  );
}
