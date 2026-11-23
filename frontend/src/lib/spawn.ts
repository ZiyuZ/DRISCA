import type { PresetConfig, SpawnPoint } from "../types/api";

/** 地图名按最后一段比较，兼容目录中的完整包路径。 */
export const mapKey = (name: string) => name.split("/").pop() ?? name;

/** 出生点是否绑定到预设的目标地图。 */
export const spawnBound = (preset: PresetConfig) =>
  Boolean(preset.ego.spawn_map) &&
  mapKey(preset.ego.spawn_map) === mapKey(preset.world.map_name);

/** 当前加载的世界是否就是预设的目标地图。 */
export const catalogMatchesPreset = (preset: PresetConfig, catalogMap: string | null) =>
  Boolean(catalogMap) && mapKey(catalogMap!) === mapKey(preset.world.map_name);

const near = (left: number, right: number, tolerance: number) =>
  Math.abs(left - right) <= tolerance;

/** 坐标与地图预设点一致时返回其序号。 */
export const matchSpawnIndex = (points: SpawnPoint[], point: SpawnPoint): number | null => {
  const index = points.findIndex(
    (item) =>
      near(item.x, point.x, 0.05) &&
      near(item.y, point.y, 0.05) &&
      near(item.z, point.z, 0.05) &&
      near(item.pitch, point.pitch, 0.1) &&
      near(item.yaw, point.yaw, 0.1) &&
      near(item.roll, point.roll, 0.1),
  );
  return index >= 0 ? index : null;
};

export const spawnLabel = (point: SpawnPoint) =>
  `(${point.x.toFixed(1)}, ${point.y.toFixed(1)}, ${point.z.toFixed(1)}) · ${point.yaw.toFixed(1)}°`;
