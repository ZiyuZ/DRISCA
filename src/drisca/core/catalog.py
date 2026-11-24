"""原生 scene.catalog 的强类型不可变模型，将裸 JSON 字典隔离在协议边界。"""

from typing import Any

from pydantic import BaseModel

from .config import SpawnPoint, WeatherConfig
from .weather import from_payload


class NativeCatalog(BaseModel, frozen=True):
    """解析后的当前世界目录，供 launcher 与 traffic 强类型共用。"""

    current_map: str
    maps: tuple[str, ...]
    vehicle_blueprints: tuple[str, ...]
    spawn_points: tuple[SpawnPoint, ...]
    weather_presets: dict[str, WeatherConfig]

    @classmethod
    def from_native(cls, raw: dict[str, Any]) -> NativeCatalog:
        points: list[SpawnPoint] = []
        for point in raw.get('spawn_points') or ():
            loc, rot = point['location'], point['rotation']
            points.append(
                SpawnPoint(
                    x=float(loc[0]),
                    y=float(loc[1]),
                    z=float(loc[2]),
                    pitch=float(rot[0]),
                    yaw=float(rot[1]),
                    roll=float(rot[2]),
                )
            )
        blueprints = tuple(
            sorted(
                str(item['id']) if isinstance(item, dict) else str(item)
                for item in (raw.get('vehicle_blueprints') or ())
            )
        )
        presets = {
            str(item['preset_name']): from_payload(item) for item in (raw.get('weather_presets') or ())
        }
        return cls(
            current_map=str(raw.get('current_map') or ''),
            maps=tuple(sorted(str(name) for name in (raw.get('maps') or ()))),
            vehicle_blueprints=blueprints,
            spawn_points=tuple(points),
            weather_presets=presets,
        )
