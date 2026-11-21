import { NumberInput } from "./number-input";
import { ChevronDown } from "lucide-react";
import type { Weather } from "../types/api";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "./ui/collapsible";
import { Slider } from "./ui/slider";

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
const primary = [
  ["cloudiness", "云量 · %", 0, 100],
  ["precipitation", "降雨 · %", 0, 100],
  ["wetness", "路面湿度 · %", 0, 100],
  ["sun_altitude_angle", "太阳高度 · °", -90, 90],
  ["fog_density", "雾浓度 · %", 0, 100],
  ["wind_intensity", "风力 · %", 0, 100],
] as const;
const extra = [
  ["precipitation_deposits", "路面积水"],
  ["dust_storm", "沙尘"],
  ["sun_azimuth_angle", "太阳方位角"],
  ["fog_distance", "雾起始距离"],
  ["fog_falloff", "雾衰减"],
  ["scattering_intensity", "散射强度"],
  ["mie_scattering_scale", "米氏散射"],
  ["rayleigh_scattering_scale", "瑞利散射"],
] as const;
export function WeatherEditor({ weather, weatherPresets, onChange }: Props) {
  const change = (key: string, value: number) => {
    onChange({ ...weather, [key]: value, preset_name: "Custom" });
  };
  return (
    <div className="weather-editor">
      <label className="weather-field">
        <span>天气预设</span>
        <SharedSelect
          value={String(weather.preset_name)}
          options={[...Object.keys(weatherPresets).map(name => [name, weatherName(name)] as const), ["Custom", "自定义"]]}
          onValueChange={(value) =>
            onChange(value === "Custom" ? { ...weather, preset_name: value } : weatherPresets[value])
          }
        />
      </label>
      {primary.map(([key, label, min, max]) => {
        const value = Number(weather[key]);
        return (
          <label className="weather-field" key={key}>
            <span>{label}</span>
            <div className="weather-range">
              <Slider
                className="prototype-slider"
                aria-label={label}
                min={min}
                max={max}
                step={1}
                value={[Math.max(min, Math.min(max, value))]}
                onValueChange={([v]) => change(key, v)}
              />
              <NumberInput
                value={value}
                min={min}
                max={max}
                onValueChange={(value) => change(key, value)}
              />
            </div>
          </label>
        );
      })}
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="px-0">
            更多天气参数
            <ChevronDown className="size-4" />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="weather-extra">
          {extra.map(([key, label]) => (
            <label className="weather-field" key={key}>
              <span>{label}</span>
              <NumberInput
                step="0.01"
                value={Number(weather[key])}
                onValueChange={(value) => change(key, value)}
              />
            </label>
          ))}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
