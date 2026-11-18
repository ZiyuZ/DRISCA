"""CARLA 天气参数转换。"""

import carla

from .config import WeatherConfig


def to_carla_weather(config: WeatherConfig) -> carla.WeatherParameters:
    if config.preset_name != 'Custom':
        return getattr(carla.WeatherParameters, config.preset_name)
    return carla.WeatherParameters(**config.model_dump(exclude={'preset_name'}))


def from_carla_weather(weather: carla.WeatherParameters, preset_name: str = 'Custom') -> WeatherConfig:
    return WeatherConfig(
        preset_name=preset_name,
        **{name: getattr(weather, name) for name in WeatherConfig.model_fields if name != 'preset_name'},
    )


def list_weather_presets() -> dict[str, WeatherConfig]:
    return {
        name: from_carla_weather(value, name)
        for name in dir(carla.WeatherParameters)
        if isinstance(value := getattr(carla.WeatherParameters, name), carla.WeatherParameters)
    }
