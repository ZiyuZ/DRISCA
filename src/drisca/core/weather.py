"""天气配置与原生 API 载荷之间的转换。"""

from drisca.core.config import WeatherConfig


def to_payload(config: WeatherConfig) -> dict[str, object]:
    """命名预设只提交名称，由原生侧取内置完整值；Custom 提交全部数值字段。"""
    if config.preset_name != 'Custom':
        return {'preset_name': config.preset_name}
    return config.model_dump(mode='json')


def from_payload(payload: dict) -> WeatherConfig:
    return WeatherConfig.model_validate(payload)


def resolve_weather(config: WeatherConfig, presets: dict[str, WeatherConfig]) -> WeatherConfig:
    """把命名预设展开为完整数值，Custom 原样返回。"""
    if config.preset_name == 'Custom':
        return config
    preset = presets.get(config.preset_name)
    if preset is None:
        raise ValueError(f'未知天气预设：{config.preset_name}')
    return preset
