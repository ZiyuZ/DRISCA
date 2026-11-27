"""全局天气配置与原生环境载荷之间的转换。"""

from drisca.core.config import GlobalWeather, WeatherConfig
from drisca.core.types import JsonObject


def to_payload(config: GlobalWeather) -> JsonObject:
    """展开为 environment.apply/update 的 weather 对象。"""
    return config.model_dump(mode='json', exclude={'preset_name'})


def from_payload(payload: JsonObject) -> WeatherConfig:
    """解析目录中的完整天气条目，条目同时带有同名 preset_name。"""
    return WeatherConfig.model_validate(payload)


def from_native(payload: JsonObject) -> GlobalWeather:
    """解析原生 current/target 中的 weather 对象，不含预设名。"""
    return GlobalWeather.model_validate(payload)


def to_config(weather: GlobalWeather, preset_name: str = 'Custom') -> WeatherConfig:
    """把原生天气值包装为带预设名的配置对象。"""
    return WeatherConfig.model_validate({**weather.model_dump(mode='json'), 'preset_name': preset_name})


def resolve_weather(config: WeatherConfig, presets: dict[str, WeatherConfig]) -> WeatherConfig:
    """把命名预设展开为完整数值，Custom 原样返回。"""
    if config.preset_name == 'Custom':
        return config
    preset = presets.get(config.preset_name)
    if preset is None:
        raise ValueError(f'未知天气预设：{config.preset_name}')
    return preset
