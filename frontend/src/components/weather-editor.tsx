import { zhCN, format } from "../i18n";
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
  ["Default", zhCN.weather.presetDefault],
  ["ClearNoon", zhCN.weather.presetClearNoon],
  ["CloudyNoon", zhCN.weather.presetCloudyNoon],
  ["WetNoon", zhCN.weather.presetWetNoon],
  ["WetCloudyNoon", zhCN.weather.presetWetCloudyNoon],
  ["MidRainyNoon", zhCN.weather.presetMidRainyNoon],
  ["HardRainNoon", zhCN.weather.presetHardRainNoon],
  ["SoftRainNoon", zhCN.weather.presetSoftRainNoon],
  ["ClearSunset", zhCN.weather.presetClearSunset],
  ["CloudySunset", zhCN.weather.presetCloudySunset],
  ["WetSunset", zhCN.weather.presetWetSunset],
  ["WetCloudySunset", zhCN.weather.presetWetCloudySunset],
  ["MidRainSunset", zhCN.weather.presetMidRainSunset],
  ["HardRainSunset", zhCN.weather.presetHardRainSunset],
  ["SoftRainSunset", zhCN.weather.presetSoftRainSunset],
  ["ClearNight", zhCN.weather.presetClearNight],
  ["CloudyNight", zhCN.weather.presetCloudyNight],
  ["WetNight", zhCN.weather.presetWetNight],
  ["WetCloudyNight", zhCN.weather.presetWetCloudyNight],
  ["MidRainyNight", zhCN.weather.presetMidRainyNight],
  ["HardRainNight", zhCN.weather.presetHardRainNight],
  ["SoftRainNight", zhCN.weather.presetSoftRainNight],
  ["DustStorm", zhCN.weather.presetDustStorm],
  ["Custom", zhCN.weather.presetCustom],
] as const;
export const weatherName = (value: string) =>
  presets.find(([key]) => key === value)?.[1] ?? value;

const weatherTypeName = (value: string) => {
  const type = value.replace(/(?:Noon|Sunset|Night)$/, "");
  return zhCN.weather.typeNames[type as keyof typeof zhCN.weather.typeNames] ?? weatherName(value);
};

type Row = {
  path: string[];
  label: string;
  min: number;
  max: number;
  step: number;
  percent?: boolean;
};
const primary: Row[] = [
  { path: ["cloudiness"], label: zhCN.weather.cloudiness, min: 0, max: 100, step: 1, percent: true },
  { path: ["precipitation", "rain"], label: zhCN.weather.rain, min: 0, max: 100, step: 1, percent: true },
  { path: ["surface", "wetness"], label: zhCN.weather.wetness, min: 0, max: 100, step: 1, percent: true },
  { path: ["sun", "elevation_deg"], label: zhCN.weather.sunElevation, min: -90, max: 90, step: 1 },
  { path: ["fog", "density"], label: zhCN.weather.fogDensity, min: 0, max: 10, step: 0.001 },
  { path: ["wind"], label: zhCN.weather.wind, min: 0, max: 100, step: 1, percent: true },
];
const extra: Row[] = [
  { path: ["surface", "puddles"], label: zhCN.weather.puddles, min: 0, max: 100, step: 1, percent: true },
  { path: ["dust"], label: zhCN.weather.dust, min: 0, max: 100, step: 1, percent: true },
  { path: ["sun", "azimuth_deg"], label: zhCN.weather.sunAzimuth, min: 0, max: 359, step: 1 },
  { path: ["fog", "distance_m"], label: zhCN.weather.fogDistance, min: 0, max: 1000000, step: 100 },
  { path: ["fog", "height_falloff"], label: zhCN.weather.fogFalloff, min: 0, max: 10000, step: 0.1 },
  { path: ["scattering", "light"], label: zhCN.weather.scatteringLight, min: 0, max: 1000, step: 0.1 },
  { path: ["scattering", "mie"], label: zhCN.weather.scatteringMie, min: 0, max: 1000, step: 0.001 },
  { path: ["scattering", "rayleigh"], label: zhCN.weather.scatteringRayleigh, min: 0, max: 1000, step: 0.001 },
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
const daylight = [["day", zhCN.weather.day, 75], ["dusk", zhCN.weather.dusk, 0], ["night", zhCN.weather.night, -30]] as const;
const daylightValue = (weather: Weather) => weather.sun.elevation_deg > 6 ? "day" : weather.sun.elevation_deg < -6 ? "night" : "dusk";
const weatherOptions = (presets: Record<string, Weather>) => Object.keys(presets)
  .filter(name => name.endsWith("Noon") || name === "DustStorm")
  .map(name => [name, weatherTypeName(name)] as const);
const matchingWeather = (weather: Weather, presets: Record<string, Weather>) => weatherOptions(presets)
  .find(([name]) => [...primary, ...extra].filter(({ path }) => path[0] !== "sun").every(({ path }) =>
    numberAt(weather, path) === numberAt(presets[name], path)
  ))?.[0];

export function weatherDescription(weather: Weather, presets: Record<string, Weather>) {
  const light = daylight.find(([value]) => value === daylightValue(weather))![1];
  const name = matchingWeather(weather, presets) ?? weather.preset_name;
  return format(zhCN.weather.summary, { daylight: light, weather: weatherTypeName(name) });
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
        <span id={`${id}-daylight`}>{zhCN.weather.daylight}</span>
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
        <span id={`${id}-weather`}>{zhCN.weather.type}</span>
        <SharedSelect
          aria-labelledby={`${id}-weather`}
          value={weatherValue}
          options={[...weatherOptions(weatherPresets), ...(weatherValue === "Custom" ? [["Custom", zhCN.weather.presetCustom] as const] : [])]}
          onValueChange={value => {
            if (value !== "Custom") onChange({ ...weatherPresets[value], sun: weather.sun, preset_name: "Custom" });
          }}
        />
      </div>
      {primary.map(row)}
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="px-0">
            {zhCN.weather.more}<ChevronDown className="size-4" />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="weather-extra">
          {extra.map(row)}
        </CollapsibleContent>
      </Collapsible>
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
      <div className="fog-section-head">
        <div>
          <strong>{zhCN.weather.regions}</strong>
          <span>{format(zhCN.weather.regionCount, { count: regions.length })}</span>
        </div>
      </div>
      {regions.length === 0
        ? <p className="weather-note fog-empty">{zhCN.weather.noPresetRegions}</p>
        : (
          <div className="fog-region-list">
            {regions.map((region, index) => (
              <div className="fog-region" key={index}>
                <div className="fog-region-head">
                  <strong>{format(zhCN.weather.regionLabel, { index: index + 1 })}</strong>
                  <Button variant="destructive" size="sm" aria-label={format(zhCN.weather.removeRegion, { index: index + 1 })}
                    onClick={() => onChange(regions.filter((_, current) => current !== index))}>
                    {zhCN.weather.remove}</Button>
                </div>
                <div className="fog-region-grid">
                  {(["X", "Y", "Z"] as const).map((axis, position) => (
                    <label className="field-row" key={axis}>
                      <span>{format(zhCN.weather.center, { axis })}</span>
                      <NumberInput
                        className="input mono"
                        step="0.1"
                        value={Number(region.center_m[position].toFixed(2))}
                        onValueChange={value => center(index, position, value)}
                      />
                    </label>
                  ))}
                  <label className="field-row">
                    <span>{zhCN.weather.radius}</span>
                    <NumberInput
                      className="input mono"
                      min="0.1"
                      step="any"
                      value={region.radius_m}
                      onValueChange={value => update(index, { radius_m: value })}
                    />
                  </label>
                  <label className="field-row">
                    <span>{zhCN.weather.density}</span>
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
          </div>
        )}
      <div className="fog-regions-divider" />
      <div className="fog-section-head"><div><strong>{zhCN.weather.newRegion}</strong><span>{zhCN.weather.saveToPreset}</span></div></div>
      <div className="fog-add">
        <div className="fog-region-head">
          <span>{zhCN.weather.initialRegion}</span>
          <Button
            variant="outline"
            onClick={() => onChange([...regions, { center_m: [0, 0, 0], radius_m: 50, density: 0.5, transition_seconds: 0 }])}
          >
            {zhCN.weather.addRegion}</Button>
        </div>
        <p className="weather-note">{zhCN.weather.initialRegionsHint}</p>
      </div>
    </section>
  );
}
