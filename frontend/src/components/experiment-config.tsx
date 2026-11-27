import { zhCN, format } from "../i18n";
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
      {state.phase !== "idle" && <p className="small">{zhCN.scene.nextExperimentHint}</p>}
      {tab === "scene" ? <>
        <Card className="dr-card gap-0">
          <div className="card-head"><h2>{zhCN.scene.mapCard}</h2></div>
          <div className="grid gap-4">
            <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
              <label className="dr-field"><span>{zhCN.scene.presetMap}</span>
                <SearchSelect label={zhCN.scene.map} value={preset.world.map_name} options={state.catalog.maps} onChange={onMapChange} />
              </label>
              <Button disabled={!state.carla_connected || state.carla_connecting || state.world_loading || state.phase !== "idle"} onClick={() => void onLoadMap()}>
                {state.world_loading ? zhCN.scene.loading : zhCN.scene.loadMap}
              </Button>
            </div>
            <p className="small">{format(zhCN.scene.currentMap, { mapName: state.catalog.map_name ?? zhCN.scene.disconnected })}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="dr-field"><span>{zhCN.scene.simulationFps}</span><NumberInput min={1} value={preset.world.simulation_fps} onValueChange={value => update(["world", "simulation_fps"], value)} /></label>
              <div className="grid content-center gap-3">
                <label className="check"><Checkbox checked={preset.world.sync_mode} onCheckedChange={value => update(["world", "sync_mode"], value === true)} />{zhCN.scene.syncMode}</label>
                <label className="check"><Checkbox checked={preset.world.load_map} onCheckedChange={value => update(["world", "load_map"], value === true)} />{zhCN.scene.reloadMap}</label>
              </div>
            </div>
          </div>
        </Card>

      </> : <><Card className="dr-card gap-0">
        <div className="card-head"><h2>{zhCN.scene.vehicleCard}</h2></div>
        <div className="grid gap-3 sm:grid-cols-2">
            <label className="dr-field">
              <span>{zhCN.scene.vehicleBlueprint}</span>
              <SearchSelect
                label={zhCN.scene.vehicle}
                disabled={!state.carla_connected}
                value={preset.ego.blueprint}
                options={state.catalog.vehicles}
                onChange={(v: string) => update(["ego", "blueprint"], v)}
              />
            </label>
            <label className="dr-field">
              <span>{zhCN.scene.roleName}</span>
              <Input
                className="input"
                value={preset.ego.role_name}
                onChange={(e) => update(["ego", "role_name"], e.target.value)}
              />
            </label>
            <label className="dr-field sm:col-span-2">
              <span>{zhCN.scene.speedLimit}</span>
              <div className="range-number">
                <Slider
                  aria-label={zhCN.scene.speedLimitSlider}
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
              {zhCN.scene.dynamicSpeedLimit}</label>
            <label className="check">
              <Checkbox
                checked={preset.ego.init_autopilot}
                onCheckedChange={(v) =>
                  update(["ego", "init_autopilot"], v === true)
                }
              />
              {zhCN.scene.initialAutopilot}</label>

        </div>
      </Card>
        <Card className="dr-card gap-0">
          <div className="card-head"><h2>{zhCN.scene.spawnCard}</h2></div>
          <SpawnPointEditor key={preset.world.map_name}
            preset={preset} catalogMap={state.catalog.map_name} spawnPoints={state.catalog.spawn_points}
            connected={state.carla_connected} telemetry={state.telemetry} onConfirm={onConfirmSpawn} />
        </Card>
      </>}
    </section>
  );
}
