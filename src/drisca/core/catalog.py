"""原生 scene.catalog 的强类型不可变模型，将裸 JSON 字典隔离在协议边界。"""

from pydantic import BaseModel

from .config import SpawnPoint, WeatherConfig
from .types import JsonObject, as_float
from .weather import from_payload


class NativeCatalog(BaseModel, frozen=True):
    """解析后的当前世界目录，供 launcher 与 traffic 强类型共用。"""

    current_map: str
    maps: tuple[str, ...]
    vehicle_blueprints: tuple[str, ...]
    spawn_points: tuple[SpawnPoint, ...]
    weather_presets: dict[str, WeatherConfig]

    @classmethod
    def from_native(cls, raw: JsonObject) -> NativeCatalog:
        points: list[SpawnPoint] = []
        raw_points = raw.get('spawn_points')
        if isinstance(raw_points, list):
            for point in raw_points:
                if not isinstance(point, dict):
                    continue
                loc = point.get('location')
                rot = point.get('rotation')
                if not isinstance(loc, list) or not isinstance(rot, list) or len(loc) < 3 or len(rot) < 3:
                    continue
                points.append(
                    SpawnPoint(
                        x=as_float(loc[0]),
                        y=as_float(loc[1]),
                        z=as_float(loc[2]),
                        pitch=as_float(rot[0]),
                        yaw=as_float(rot[1]),
                        roll=as_float(rot[2]),
                    )
                )
        raw_bps = raw.get('vehicle_blueprints')
        blueprints = tuple(
            sorted(
                str(item['id']) if isinstance(item, dict) else str(item)
                for item in (raw_bps if isinstance(raw_bps, list) else ())
            )
        )
        raw_presets = raw.get('weather_presets')
        presets = {
            str(item['preset_name']): from_payload(item)
            for item in (raw_presets if isinstance(raw_presets, list) else ())
            if isinstance(item, dict)
        }
        raw_maps = raw.get('maps')
        return cls(
            current_map=str(raw.get('current_map') or ''),
            maps=tuple(sorted(str(name) for name in (raw_maps if isinstance(raw_maps, list) else ()))),
            vehicle_blueprints=blueprints,
            spawn_points=tuple(points),
            weather_presets=presets,
        )
