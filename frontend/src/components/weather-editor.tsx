import { NumberInput } from "./number-input";
import { ChevronDown } from "lucide-react";
import type { FogRegion, Weather } from "../types/api";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "./ui/collapsible";
import { Slider } from "./ui/slider";
import { useId } from "react";

type Props = {
  weather: Weather;
  weatherPresets: Record<string, Weather>;
  onChange: (weather: Weather) => void;
};
const presets = [
  ["Default", "默认"],
  ["ClearNoon", "晴朗正午"],
  ["CloudyNoon", "阴天正午"],
  ["WetNoon", "湿润正午"],
  ["WetCloudyNoon", "湿润阴天"],
  ["MidRainyNoon", "中雨正午"],
  ["HardRainNoon", "大雨正午"],
  ["SoftRainNoon", "小雨正午"],
  ["ClearSunset", "晴朗傍晚"],
  ["CloudySunset", "阴天傍晚"],
  ["WetSunset", "湿润傍晚"],
  ["WetCloudySunset", "湿润阴天傍晚"],
  ["MidRainSunset", "中雨傍晚"],
  ["HardRainSunset", "大雨傍晚"],
  ["SoftRainSunset", "小雨傍晚"],
  ["ClearNight", "晴朗夜间"],
  ["CloudyNight", "阴天夜间"],
  ["WetNight", "湿润夜间"],
  ["WetCloudyNight", "湿润阴天夜间"],
  ["MidRainyNight", "中雨夜间"],
  ["HardRainNight", "大雨夜间"],
  ["SoftRainNight", "小雨夜间"],
  ["DustStorm", "沙尘暴"],
  ["Custom", "自定义"],
] as const;
export const weatherName = (value: string) =>
  presets.find(([key]) => key === value)?.[1] ?? value;

type Row = {
  path: string[];
  label: string;
  min: number;
  max: number;
  step: number;
  percent?: boolean;
};
const primary: Row[] = [
  { path: ["cloudiness"], label: "云量 · %", min: 0, max: 100, step: 1, percent: true },
  { path: ["precipitation", "rain"], label: "降雨 · %", min: 0, max: 100, step: 1, percent: true },
  { path: ["surface", "wetness"], label: "路面湿润 · %", min: 0, max: 100, step: 1, percent: true },
  { path: ["sun", "elevation_deg"], label: "太阳高度 · °", min: -90, max: 90, step: 1 },
  { path: ["fog", "density"], label: "雾密度参数", min: 0, max: 10, step: 0.001 },
  { path: ["wind"], label: "风 · %", min: 0, max: 100, step: 1, percent: true },
];
const extra: Row[] = [
  { path: ["surface", "puddles"], label: "路面积水 · %", min: 0, max: 100, step: 1, percent: true },
  { path: ["dust"], label: "沙尘 · %", min: 0, max: 100, step: 1, percent: true },
  { path: ["sun", "azimuth_deg"], label: "太阳方位角 · °", min: 0, max: 359, step: 1 },
  { path: ["fog", "distance_m"], label: "雾起始距离 · m", min: 0, max: 1000000, step: 100 },
  { path: ["fog", "height_falloff"], label: "雾高度衰减参数", min: 0, max: 10000, step: 0.1 },
  { path: ["scattering", "light"], label: "光散射参数", min: 0, max: 1000, step: 0.1 },
  { path: ["scattering", "mie"], label: "米氏散射参数", min: 0, max: 1000, step: 0.001 },
  { path: ["scattering", "rayleigh"], label: "瑞利散射参数", min: 0, max: 1000, step: 0.001 },
];
const numberAt = (source: Weather, path: string[]): number => {
  let target: unknown = source;
  for (const key of path) target = (target as Record<string, unknown>)[key];
  return Number(target);
};
const withNumber = (source: Weather, path: string[], value: number): Weather => {
  const result = structuredClone(source);
  let target = result as unknown as Record<string, unknown>;
  for (const key of path.slice(0, -1)) target = target[key] as Record<string, unknown>;
  target[path[path.length - 1]] = value;
  return result;
};
const daylight = [["day", "白天", 75], ["dusk", "黄昏", 0], ["night", "夜晚", -30]] as const;
const daylightValue = (weather: Weather) => weather.sun.elevation_deg > 6 ? "day" : weather.sun.elevation_deg < -6 ? "night" : "dusk";
const weatherOptions = (presets: Record<string, Weather>) => Object.keys(presets)
  .filter(name => name.endsWith("Noon") || name === "DustStorm")
  .map(name => [name, weatherName(name).replace(/正午$/, "")] as const);
const matchingWeather = (weather: Weather, presets: Record<string, Weather>) => weatherOptions(presets)
  .find(([name]) => [...primary, ...extra].filter(({ path }) => path[0] !== "sun").every(({ path }) =>
    numberAt(weather, path) === numberAt(presets[name], path)
  ))?.[0];

export function weatherDescription(weather: Weather, presets: Record<string, Weather>) {
  const light = daylight.find(([value]) => value === daylightValue(weather))![1];
  const name = matchingWeather(weather, presets) ?? weather.preset_name;
  return `${light} · ${weatherName(name).replace(/正午|傍晚|夜间/g, "")}`;
}

export function WeatherEditor({ weather, weatherPresets, onChange }: Props) {
  const id = useId();
  const weatherValue = matchingWeather(weather, weatherPresets) ?? "Custom";
  const row = ({ path, label, min, max, step, percent }: Row) => {
    const raw = numberAt(weather, path);
    const value = percent ? Math.round(raw * 10000) / 100 : raw;
    const change = (next: number) =>
      onChange({ ...withNumber(weather, path, percent ? next / 100 : next), preset_name: "Custom" });
    return (
      <div className="weather-field" key={path.join(".")}>
        <label htmlFor={`${id}-${path.join("-")}`}>{label}</label>
        <div className="weather-range">
          <Slider
            className="prototype-slider"
            aria-label={label}
            min={min}
            max={max}
            step={step}
            value={[Math.min(max, Math.max(min, value))]}
            onValueChange={([v]) => change(v)}
          />
          <NumberInput id={`${id}-${path.join("-")}`} min={min} max={max} value={value} onValueChange={change} />
        </div>
      </div>
    );
  };
  return (
    <div className="weather-editor">
      <div className="weather-field">
        <span id={`${id}-daylight`}>日照</span>
        <SharedSelect
          aria-labelledby={`${id}-daylight`}
          value={daylightValue(weather)}
          options={daylight.map(([value, label]) => [value, label] as const)}
          onValueChange={value => {
            const selected = daylight.find(([name]) => name === value);
            if (selected) onChange({ ...weather, sun: { ...weather.sun, elevation_deg: selected[2] }, preset_name: "Custom" });
          }}
        />
      </div>
      <div className="weather-field">
        <span id={`${id}-weather`}>天气类型</span>
        <SharedSelect
          aria-labelledby={`${id}-weather`}
          value={weatherValue}
          options={[...weatherOptions(weatherPresets), ...(weatherValue === "Custom" ? [["Custom", "自定义"] as const] : [])]}
          onValueChange={value => {
            if (value !== "Custom") onChange({ ...weatherPresets[value], sun: weather.sun, preset_name: "Custom" });
          }}
        />
      </div>
      {primary.map(row)}
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="px-0">
            更多天气参数
            <ChevronDown className="size-4" />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="weather-extra">
          {extra.map(row)}
        </CollapsibleContent>
      </Collapsible>
      <p className="weather-note">
        日照与天气独立组合；太阳高度可继续微调。雾密度范围 0–100，直接控制高度雾；起始距离与密度均未标定为能见距离。雪效待实现。
      </p>
    </div>
  );
}

export function FogRegionsEditor({ regions, onChange }: { regions: FogRegion[]; onChange: (regions: FogRegion[]) => void }) {
  const update = (index: number, changes: Partial<FogRegion>) =>
    onChange(regions.map((region, current) => current === index ? { ...region, ...changes } : region));
  const center = (index: number, axis: number, value: number) => {
    const region = regions[index];
    const next = [...region.center_m] as [number, number, number];
    next[axis] = value;
    update(index, { center_m: next });
  };
  return (
    <section className="fog-regions">
      <div className="fog-regions-head">
        <div>
          <h3>初始团雾列表</h3>
          <p>固定世界坐标的团雾区域，实验启动前自动创建，实验结束随会话清理。</p>
        </div>
        <Button
          variant="outline"
          onClick={() => onChange([...regions, { center_m: [0, 0, 0], radius_m: 50, density: 0.5, transition_seconds: 0 }])}
        >
          添加团雾
        </Button>
      </div>
      {regions.length === 0 && <p className="weather-note">未配置初始团雾。</p>}
      {regions.map((region, index) => (
        <div className="fog-region" key={index}>
          <div className="fog-region-head">
            <span>区域 {index + 1}</span>
            <Button variant="ghost" aria-label={`移除区域 ${index + 1}`} onClick={() => onChange(regions.filter((_, current) => current !== index))}>
              移除
            </Button>
          </div>
          <div className="fog-region-grid">
            {(["X", "Y", "Z"] as const).map((axis, position) => (
              <label className="dr-field" key={axis}>
                <span>中心 {axis} · m</span>
                <NumberInput
                  className="input mono"
                  step="0.1"
                  value={region.center_m[position]}
                  onValueChange={value => center(index, position, value)}
                />
              </label>
            ))}
            <label className="dr-field">
              <span>半径 · m</span>
              <NumberInput
                className="input mono"
                min="0.1"
                step="any"
                value={region.radius_m}
                onValueChange={value => update(index, { radius_m: value })}
              />
            </label>
            <label className="dr-field">
              <span>雾强度 · %</span>
              <NumberInput
                className="input mono"
                min="0"
                max="100"
                step="1"
                value={region.density * 100}
                onValueChange={value => update(index, { density: value / 100 })}
              />
            </label>
          </div>
        </div>
      ))}
    </section>
  );
}
