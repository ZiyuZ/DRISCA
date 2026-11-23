import { NumberInput } from "./number-input";
import { IconAction } from "./icon-action";
import { FilePlus2, Trash2, CopyPlus, LocateFixed } from "lucide-react";
import { Card } from "./ui/card";
import { SharedSelect } from "./shared-select";
import { Input } from "./ui/input";
import { FileText } from "lucide-react";
import type { PresetConfig, RuntimeState } from "../types/api";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Slider } from "./ui/slider";
import { SearchSelect } from "./common";
import { weatherDescription } from "./weather-editor";
import { catalogMatchesPreset, matchSpawnIndex, spawnBound } from "../lib/spawn";

type Props = {
  preset: PresetConfig;
  state: RuntimeState;
  update: (path: string[], value: unknown) => void;
  onWeather: () => void;
  onMapChange: (mapName: string) => void;
  onPickSpawn: () => void;
};

export function ExperimentConfig({ preset, state, update, onWeather, onMapChange, onPickSpawn }: Props) {
  const telemetry = state.telemetry;
  const bound = spawnBound(preset);
  const mapLoaded = catalogMatchesPreset(preset, state.catalog.map_name);
  const points = mapLoaded ? state.catalog.spawn_points : [];
  const spawnIndex = bound && mapLoaded ? matchSpawnIndex(points, preset.ego.spawn_point) : null;
  const missingText =
    mapLoaded && points.length === 0
      ? "该地图没有预设出生点，请手动填写完整坐标。"
      : "尚未选择该地图的出生点。";
  const spawnLabels = {
    x: "X · m",
    y: "Y · m",
    z: "Z · m",
    pitch: "俯仰角 · °",
    yaw: "偏航角 · °",
    roll: "翻滚角 · °",
  } as const;
  return (
    <section className="stack config-page">
      <div className="grid2 equal">
        <Card className="dr-card gap-0">
          <div className="card-head">
            <h2>世界与环境</h2>
          </div>
          <div className="form">
            <label className="dr-field">
              <span>地图</span>
              <SearchSelect
                label="地图"
                value={preset.world.map_name}
                options={state.catalog.maps}
                onChange={onMapChange}
              />
            </label>
            <label className="dr-field">
              <span>初始天气</span>
              <Button
                variant="ghost"
                className="choice-button"
                onClick={onWeather}
              >
                <span>
                  {weatherDescription(preset.world.weather, state.catalog.weather_presets)}
                </span>
                <span className="small">
                  {preset.world.fog_regions.length > 0
                    ? `调整参数 · ${preset.world.fog_regions.length} 处球雾`
                    : "调整参数"}
                </span>
              </Button>
            </label>
            <label className="dr-field">
              <span>同步推进频率 · Hz</span>
              <NumberInput
                className="input"
                
                min="1"
                value={preset.world.simulation_fps}
                onValueChange={(value) =>
                  update(["world", "simulation_fps"], value)
                }
              />
            </label>
            <label className="check">
              <Checkbox
                checked={preset.world.sync_mode}
                onCheckedChange={(v) =>
                  update(["world", "sync_mode"], v === true)
                }
              />
              使用同步模式
            </label>
            <label className="check">
              <Checkbox
                checked={preset.world.load_map}
                onCheckedChange={(v) =>
                  update(["world", "load_map"], v === true)
                }
              />
              启动时重新加载地图
            </label>
          </div>
        </Card>
        <Card className="dr-card gap-0">
          <div className="card-head">
            <h2>主车与道路限速</h2>
          </div>
          <div className="form">
            <label className="dr-field">
              <span>车辆蓝图</span>
              <SearchSelect
                label="车辆"
                disabled={!state.carla_connected}
                value={preset.ego.blueprint}
                options={state.catalog.vehicles}
                onChange={(v: string) => update(["ego", "blueprint"], v)}
              />
            </label>
            <label className="dr-field">
              <span>角色名</span>
              <Input
                className="input"
                value={preset.ego.role_name}
                onChange={(e) => update(["ego", "role_name"], e.target.value)}
              />
            </label>
            <label className="dr-field">
              <span>固定限速 · km/h</span>
              <div className="range-number">
                <Slider
                  aria-label="固定限速"
                  className="prototype-slider"
                  min={0}
                  max={180}
                  value={[
                    Math.max(
                      0,
                      Math.min(180, preset.ego.default_speed_limit * 3.6),
                    ),
                  ]}
                  onValueChange={([value]) =>
                    update(["ego", "default_speed_limit"], value / 3.6)
                  }
                />
                <NumberInput
                  className="input mono"
                  
                  min="0"
                  max="180"
                  value={Math.round(preset.ego.default_speed_limit * 3.6)}
                  onValueChange={(value) =>
                    update(
                      ["ego", "default_speed_limit"],
                      value / 3.6,
                    )
                  }
                />
              </div>
            </label>
            <label className="check">
              <Checkbox
                checked={preset.ego.dynamic_speed_limit}
                onCheckedChange={(v) =>
                  update(["ego", "dynamic_speed_limit"], v === true)
                }
              />
              读取道路限速
            </label>
            <label className="check">
              <Checkbox
                checked={preset.ego.init_autopilot}
                onCheckedChange={(v) =>
                  update(["ego", "init_autopilot"], v === true)
                }
              />
              启动后开启自动驾驶
            </label>
          </div>
        </Card>
      </div>
      <Card className="dr-card gap-0">
        <div className="card-head spawn-header">
          <div>
            <h2>主车出生点</h2>
          </div>
          <div className="spawn-actions">
            {bound && (
              <SharedSelect
                className="select spawn-select"
                value={spawnIndex !== null ? `point:${spawnIndex}` : "custom"}
                disabled={!mapLoaded}
                options={[
                  ...points.map((point, index) => [`point:${index}`, `出生点 ${index + 1}`] as const),
                  ["custom", "自定义坐标"] as const,
                ]}
                onValueChange={(value) => {
                  if (value === "custom") return;
                  const point = points[Number(value.slice("point:".length))];
                  if (point) update(["ego", "spawn_point"], point);
                }}
              />
            )}
            <IconAction
              label="拾取当前车辆位置"
              disabled={!telemetry || !bound}
              onClick={() =>
                telemetry &&
                update(["ego", "spawn_point"], {
                  x: telemetry.location_x,
                  y: telemetry.location_y,
                  z: telemetry.location_z,
                  pitch: telemetry.rotation_pitch,
                  yaw: telemetry.rotation_yaw,
                  roll: telemetry.rotation_roll,
                })
              }
            >
              <LocateFixed />
            </IconAction>
          </div>
        </div>
        {bound ? (
          <div className="three spawn-fields">
            {(Object.keys(spawnLabels) as (keyof typeof spawnLabels)[]).map(
              (key) => (
                <label className="dr-field" key={key}>
                  <span>{spawnLabels[key]}</span>
                  <NumberInput
                    className="input mono"
                    step="0.1"
                    value={preset.ego.spawn_point[key]}
                    onValueChange={(value) =>
                      update(["ego", "spawn_point", key], value)
                    }
                  />
                </label>
              ),
            )}
          </div>
        ) : (
          <div className="spawn-missing" role="status">
            <span>{missingText}</span>
            <Button variant="outline" onClick={onPickSpawn}>
              选择出生点
            </Button>
          </div>
        )}
      </Card>
    </section>
  );
}
