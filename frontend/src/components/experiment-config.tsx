import { NumberInput } from "./number-input";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import type { PresetConfig, RuntimeState, SpawnPoint } from "../types/api";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Slider } from "./ui/slider";
import { SearchSelect } from "./common";
import { SpawnPointEditor } from "./spawn-point-dialog";

type Props = {
  preset: PresetConfig;
  state: RuntimeState;
  tab: string;
  update: (path: string[], value: unknown) => void;
  onMapChange: (mapName: string) => void;
  onLoadMap: () => Promise<void>;
  onConfirmSpawn: (point: SpawnPoint) => void;
};

export function ExperimentConfig({ preset, state, tab, update, onMapChange, onLoadMap, onConfirmSpawn }: Props) {
  return (
    <section className="stack config-page">
      {state.phase !== "idle" && <p className="small">当前修改保存到预设，对下一次实验生效。</p>}
      {tab === "scene" ? <>
        <Card className="dr-card gap-0">
          <div className="card-head"><h2>场景地图</h2></div>
          <div className="grid gap-4">
            <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
              <label className="dr-field"><span>预设地图</span>
                <SearchSelect label="地图" value={preset.world.map_name} options={state.catalog.maps} onChange={onMapChange} />
              </label>
              <Button disabled={!state.carla_connected || state.carla_connecting || state.world_loading || state.phase !== "idle"} onClick={() => void onLoadMap()}>
                {state.world_loading ? "正在加载…" : "立即加载地图"}
              </Button>
            </div>
            <p className="small">当前场景：{state.catalog.map_name ?? "尚未连接模拟器"}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="dr-field"><span>同步推进频率 · Hz</span><NumberInput min={1} value={preset.world.simulation_fps} onValueChange={value => update(["world", "simulation_fps"], value)} /></label>
              <div className="grid content-center gap-3">
                <label className="check"><Checkbox checked={preset.world.sync_mode} onCheckedChange={value => update(["world", "sync_mode"], value === true)} />使用同步模式</label>
                <label className="check"><Checkbox checked={preset.world.load_map} onCheckedChange={value => update(["world", "load_map"], value === true)} />启动时重新加载地图</label>
              </div>
            </div>
          </div>
        </Card>

      </> : <><Card className="dr-card gap-0">
        <div className="card-head"><h2>主车与道路限速</h2></div>
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
        <Card className="dr-card gap-0">
          <div className="card-head"><h2>主车出生点</h2></div>
          <SpawnPointEditor key={preset.world.map_name}
            preset={preset} catalogMap={state.catalog.map_name} spawnPoints={state.catalog.spawn_points}
            connected={state.carla_connected} telemetry={state.telemetry} onConfirm={onConfirmSpawn} />
        </Card>
      </>}
    </section>
  );
}
