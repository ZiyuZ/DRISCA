"""可注册实验指令与事件库（按 category 分为 weather / traffic / ego / custom）。"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CommandCategory(StrEnum):
    WEATHER = 'weather'
    TRAFFIC = 'traffic'
    EGO = 'ego'
    CUSTOM = 'custom'


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """已注册实验动作/事件的元数据与处理器。"""

    id: str
    label: str
    description: str
    category: CommandCategory
    params_model: type[BaseModel]
    fields: tuple[dict[str, Any], ...]
    handler: Callable[[Any, Any, str], None]

    def to_bootstrap(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'category': str(self.category),
            'fields': list(self.fields),
        }


REGISTRY: dict[str, CommandSpec] = {}
MODELS: dict[str, type[BaseModel]] = {}
COMMANDS: list[dict[str, Any]] = []


def register_command(
    *,
    command_id: str,
    label: str,
    description: str,
    category: CommandCategory,
    params_model: type[BaseModel],
    fields: list[dict[str, Any]],
) -> Callable[[Callable[[Any, Any, str], None]], Callable[[Any, Any, str], None]]:
    """注册一条可由前端动态渲染与触发的实验事件/指令。"""

    def decorator(func: Callable[[Any, Any, str], None]) -> Callable[[Any, Any, str], None]:
        spec = CommandSpec(
            id=command_id,
            label=label,
            description=description,
            category=category,
            params_model=params_model,
            fields=tuple(fields),
            handler=func,
        )
        REGISTRY[command_id] = spec
        MODELS[command_id] = params_model
        COMMANDS.append(spec.to_bootstrap())
        return func

    return decorator


class AutopilotParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool


class TakeoverParams(AutopilotParams):
    speech: str


class WeatherPresetParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    preset: str


class SpeechParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    text: str


class LocalFogBurstParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    placement: Literal['fixed', 'ahead'] = 'fixed'
    x: float = 0.0
    y: float = 0.0
    z: float = 2.0
    distance_m: float = Field(default=25.0, ge=0, le=500)
    radius_m: float = Field(default=25.0, gt=0, le=1000)
    density: float = Field(default=0.8, ge=0, le=1)
    fade_in_s: float = Field(default=1.5, ge=0, le=60)
    hold_s: float = Field(default=10.0, ge=0, le=600)
    fade_out_s: float = Field(default=2.0, ge=0, le=60)


@register_command(
    command_id='autopilot',
    label='自动驾驶',
    description='切换主车自研自动驾驶开关',
    category=CommandCategory.EGO,
    params_model=AutopilotParams,
    fields=[{'key': 'enabled', 'label': '启用', 'type': 'boolean', 'required': True, 'default': True}],
)
def _run_autopilot(rt: Any, params: AutopilotParams, command_id: str) -> None:
    from drisca.core.protocol import SetAutopilotCommand

    rt.send(SetAutopilotCommand(command_id=command_id, enabled=params.enabled))


@register_command(
    command_id='takeover',
    label='接管请求',
    description='发送接管请求并播放语音',
    category=CommandCategory.EGO,
    params_model=TakeoverParams,
    fields=[
        {'key': 'enabled', 'label': '启用', 'type': 'boolean', 'required': True, 'default': True},
        {'key': 'speech', 'label': '语音内容', 'type': 'text', 'required': True, 'default': ''},
    ],
)
def _run_takeover(rt: Any, params: TakeoverParams, command_id: str) -> None:
    from drisca.core.protocol import SetTakeoverCommand

    rt.send(SetTakeoverCommand(command_id=command_id, enabled=params.enabled))
    rt.speak(params.speech, command_id)


@register_command(
    command_id='speech',
    label='语音播放',
    description='向驾驶人播放指定提示语音',
    category=CommandCategory.EGO,
    params_model=SpeechParams,
    fields=[{'key': 'text', 'label': '语音内容', 'type': 'text', 'required': True, 'default': ''}],
)
def _run_speech(rt: Any, params: SpeechParams, command_id: str) -> None:
    rt.speak(params.text, command_id)


@register_command(
    command_id='weather',
    label='天气切换',
    description='切换当前世界全局天气预设',
    category=CommandCategory.WEATHER,
    params_model=WeatherPresetParams,
    fields=[
        {'key': 'preset', 'label': '天气预设', 'type': 'text', 'required': True, 'default': 'ClearNoon'},
    ],
)
def _run_weather(rt: Any, params: WeatherPresetParams, command_id: str) -> None:
    from drisca.core.config import WeatherConfig
    from drisca.core.protocol import SetWeatherCommand
    from drisca.core.weather import resolve_weather, to_config, to_payload

    weather = resolve_weather(WeatherConfig(preset_name=params.preset), rt.weather_presets)
    if rt.state['phase'] == 'running':
        rt.send(SetWeatherCommand(command_id=command_id, weather=weather))
    elif rt.api is not None:
        applied = rt.api.environment_apply(to_payload(weather))
        rt.update(weather=to_config(applied.target.weather, weather.preset_name).model_dump(mode='json'))


@register_command(
    command_id='local_fog_burst',
    label='突发团雾',
    description='按固定世界坐标或主车正前方距离生成局部球雾，可选在持续时间结束后自动渐隐消散',
    category=CommandCategory.WEATHER,
    params_model=LocalFogBurstParams,
    fields=[
        {
            'key': 'placement',
            'label': '定位方式',
            'type': 'select',
            'required': True,
            'default': 'fixed',
            'options': [
                {'value': 'fixed', 'label': '固定坐标'},
                {'value': 'ahead', 'label': '主车前方（调试）'},
            ],
        },
        {'key': 'x', 'label': '固定 X · m', 'type': 'number', 'required': True, 'default': 0},
        {'key': 'y', 'label': '固定 Y · m', 'type': 'number', 'required': True, 'default': 0},
        {'key': 'z', 'label': '固定 Z · m', 'type': 'number', 'required': True, 'default': 2},
        {'key': 'distance_m', 'label': '主车前方距离 · m', 'type': 'number', 'required': True, 'default': 25},
        {'key': 'radius_m', 'label': '球雾半径 · m', 'type': 'number', 'required': True, 'default': 25},
        {'key': 'density', 'label': '雾密度 (0–1)', 'type': 'number', 'required': True, 'default': 0.8},
        {'key': 'fade_in_s', 'label': '渐入时长 · s', 'type': 'number', 'required': True, 'default': 1.5},
        {
            'key': 'hold_s',
            'label': '持续时长 · s (0 为不自动消散)',
            'type': 'number',
            'required': True,
            'default': 10,
        },
        {'key': 'fade_out_s', 'label': '渐出时长 · s', 'type': 'number', 'required': True, 'default': 2},
    ],
)
def _run_local_fog_burst(rt: Any, params: LocalFogBurstParams, command_id: str) -> None:
    from uuid import uuid4

    from drisca.core.protocol import CreateFogRegionCommand, DeleteFogRegionCommand

    if params.placement == 'fixed':
        center = (params.x, params.y, params.z)
    else:
        telemetry = rt.state.get('telemetry')
        if telemetry is not None:
            x = float(telemetry['location_x'])
            y = float(telemetry['location_y'])
            z = float(telemetry['location_z'])
            yaw = math.radians(float(telemetry['rotation_yaw']))
        else:
            spawns = rt.state.get('catalog', {}).get('spawn_points') or []
            if not spawns:
                raise RuntimeError('当前无主车遥测且无可用出生点，无法按主车前方定位')
            sp = spawns[0]
            x, y, z = float(sp['x']), float(sp['y']), float(sp['z'])
            yaw = math.radians(float(sp['yaw']))
        center = (
            x + math.cos(yaw) * params.distance_m,
            y + math.sin(yaw) * params.distance_m,
            z + 2.0,
        )

    if rt.state['phase'] == 'running':
        expected_session = rt.state.get('session_id')
        before_ids = {int(r['region_id']) for r in (rt.state.get('fog_regions') or [])}
        rt.send(
            CreateFogRegionCommand(
                command_id=command_id,
                center_m=center,
                radius_m=params.radius_m,
                density=params.density,
                transition_seconds=params.fade_in_s,
            )
        )
        if params.hold_s <= 0:
            return

        def schedule_cleanup() -> None:
            # 等待新区域创建事件回传以获取 region_id，并校验会话一致性
            region_id: int | None = None
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and rt.state.get('session_id') == expected_session:
                current = [int(r['region_id']) for r in (rt.state.get('fog_regions') or [])]
                added = [rid for rid in current if rid not in before_ids]
                if added:
                    region_id = added[-1]
                    break
                time.sleep(0.1)
            if region_id is None:
                return
            time.sleep(params.fade_in_s + params.hold_s)
            if rt.state['phase'] != 'running' or rt.state.get('session_id') != expected_session:
                return
            if any(int(r['region_id']) == region_id for r in (rt.state.get('fog_regions') or [])):
                rt.send(
                    DeleteFogRegionCommand(
                        command_id=uuid4().hex,
                        region_id=region_id,
                        transition_seconds=params.fade_out_s,
                    )
                )

        threading.Thread(target=schedule_cleanup, daemon=True).start()
    elif rt.api is not None:
        created = rt.api.environment_create(
            center_m=center,
            radius_m=params.radius_m,
            density=params.density,
            transition_seconds=params.fade_in_s,
        )
        rt.update(fog_regions=rt.read_fog_regions())
        if params.hold_s <= 0:
            return
        region_id = created.region_id

        def cleanup_idle() -> None:
            time.sleep(params.fade_in_s + params.hold_s)
            if rt.api is not None and rt.state['phase'] == 'idle':
                try:
                    rt.api.environment_delete(region_id, transition_seconds=params.fade_out_s)
                    rt.update(fog_regions=rt.read_fog_regions())
                except Exception as exc:
                    rt.log(f'突发团雾自动清理失败：{exc}', 'ERROR')

        threading.Thread(target=cleanup_idle, daemon=True).start()
    else:
        raise RuntimeError('CARLA 尚未连接，无法触发突发团雾')
