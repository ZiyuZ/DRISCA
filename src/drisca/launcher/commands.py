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
    hold_s: float = Field(default=0.0, ge=0, le=600)
    fade_out_s: float = Field(default=2.0, ge=0, le=60)


class RainSquallParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    rain_intensity: float = Field(default=0.9, ge=0.1, le=1.0)
    cloudiness: float = Field(default=0.9, ge=0.0, le=1.0)
    wetness: float = Field(default=0.85, ge=0.0, le=1.0)
    puddles: float = Field(default=0.7, ge=0.0, le=1.0)
    fade_in_s: float = Field(default=3.0, ge=0.0, le=60.0)
    hold_s: float = Field(default=15.0, ge=1.0, le=600.0)
    fade_out_s: float = Field(default=5.0, ge=0.0, le=60.0)


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
    command_id='local_fog_burst',
    label='团雾',
    description='按固定世界坐标或主车前方距离部署团雾，持续时长为 0 时持久存在',
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
        {'key': 'radius_m', 'label': '团雾半径 · m', 'type': 'number', 'required': True, 'default': 25},
        {'key': 'density', 'label': '雾密度 (0–1)', 'type': 'number', 'required': True, 'default': 0.8},
        {'key': 'fade_in_s', 'label': '渐入时长 · s', 'type': 'number', 'required': True, 'default': 1.5},
        {
            'key': 'hold_s',
            'label': '持续时长 · s (0 为持久存在)',
            'type': 'number',
            'required': True,
            'default': 0,
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
        raise RuntimeError('CARLA 尚未连接，无法触发局部团雾')


@register_command(
    command_id='rain_squall',
    label='短时强降雨',
    description='平滑增大降雨、云量与路面湿滑积水，持续指定时长后自动恢复触发前天气',
    category=CommandCategory.WEATHER,
    params_model=RainSquallParams,
    fields=[
        {
            'key': 'rain_intensity',
            'label': '降雨强度 (0.1–1)',
            'type': 'number',
            'required': True,
            'default': 0.9,
        },
        {
            'key': 'cloudiness',
            'label': '云量 (0–1)',
            'type': 'number',
            'required': True,
            'default': 0.9,
        },
        {
            'key': 'wetness',
            'label': '路面湿滑 (0–1)',
            'type': 'number',
            'required': True,
            'default': 0.85,
        },
        {
            'key': 'puddles',
            'label': '路面积水 (0–1)',
            'type': 'number',
            'required': True,
            'default': 0.7,
        },
        {'key': 'fade_in_s', 'label': '增强渐变 · s', 'type': 'number', 'required': True, 'default': 3},
        {'key': 'hold_s', 'label': '持续时长 · s', 'type': 'number', 'required': True, 'default': 15},
        {'key': 'fade_out_s', 'label': '恢复渐变 · s', 'type': 'number', 'required': True, 'default': 5},
    ],
)
def _run_rain_squall(rt: Any, params: RainSquallParams, command_id: str) -> None:
    from uuid import uuid4

    from drisca.core.config import PrecipitationConfig, SurfaceConfig, WeatherConfig
    from drisca.core.protocol import SetWeatherCommand
    from drisca.core.weather import to_config, to_payload

    raw_weather = rt.state.get('weather')
    if raw_weather is None:
        preset = rt.state.get('active_preset')
        raw_weather = preset['world']['weather'] if preset else None
    if raw_weather is None:
        raise RuntimeError('当前无可用全局天气基准，无法触发短时强降雨')

    baseline = WeatherConfig.model_validate(raw_weather)
    squall = baseline.model_copy(
        update={
            'preset_name': 'Custom',
            'cloudiness': max(baseline.cloudiness, params.cloudiness),
            'wind': max(baseline.wind, 0.45),
            'precipitation': PrecipitationConfig(
                rain=params.rain_intensity, snow=baseline.precipitation.snow
            ),
            'surface': SurfaceConfig(
                wetness=max(baseline.surface.wetness, params.wetness),
                puddles=max(baseline.surface.puddles, params.puddles),
            ),
        }
    )

    if rt.state['phase'] == 'running':
        expected_session = rt.state.get('session_id')
        rt.send(
            SetWeatherCommand(
                command_id=command_id,
                weather=squall,
                transition_seconds=params.fade_in_s,
            )
        )

        def restore_running() -> None:
            time.sleep(params.fade_in_s + params.hold_s)
            if rt.state['phase'] != 'running' or rt.state.get('session_id') != expected_session:
                return
            rt.send(
                SetWeatherCommand(
                    command_id=uuid4().hex,
                    weather=baseline,
                    transition_seconds=params.fade_out_s,
                )
            )

        threading.Thread(target=restore_running, daemon=True).start()
    elif rt.api is not None:
        applied = rt.api.environment_apply(to_payload(squall), transition_seconds=params.fade_in_s)
        rt.update(weather=to_config(applied.target.weather, 'Custom').model_dump(mode='json'))

        def restore_idle() -> None:
            time.sleep(params.fade_in_s + params.hold_s)
            if rt.api is not None and rt.state['phase'] == 'idle':
                try:
                    restored = rt.api.environment_apply(
                        to_payload(baseline), transition_seconds=params.fade_out_s
                    )
                    rt.update(
                        weather=to_config(restored.target.weather, baseline.preset_name).model_dump(
                            mode='json'
                        )
                    )
                except Exception as exc:
                    rt.log(f'短时强降雨自动恢复失败：{exc}', 'ERROR')

        threading.Thread(target=restore_idle, daemon=True).start()
    else:
        raise RuntimeError('CARLA 尚未连接，无法触发短时强降雨')


class LeadHardBrakeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=60.0, gt=0, le=300)
    duration_s: float = Field(default=2.5, gt=0, le=30)
    brake_intensity: float = Field(default=0.95, ge=0.1, le=1.0)


class AdjacentCutInParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: Literal['reuse_adjacent', 'spawn_cut_in'] = 'reuse_adjacent'
    side: Literal['any', 'left', 'right'] = 'any'
    min_front_m: float = Field(default=3.5, ge=-20, le=100)
    max_front_m: float = Field(default=28.0, gt=0, le=200)
    spawn_distance_m: float = Field(default=45.0, ge=10, le=200)
    trigger_distance_m: float = Field(default=14.0, ge=4, le=80)


class RearOvertakeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: Literal['reuse_rear', 'spawn_rear'] = 'reuse_rear'
    side: Literal['any', 'left', 'right'] = 'any'
    rear_distance_m: float = Field(default=22.0, ge=6, le=120)
    extra_speed_mps: float = Field(default=8.0, ge=2.0, le=30.0)
    clear_front_m: float = Field(default=18.0, ge=8, le=60)
    return_to_lane: bool = True


class LeadBreakdownParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: Literal['reuse_lead', 'spawn_far'] = 'reuse_lead'
    distance_m: float = Field(default=130.0, ge=15, le=350)
    speed_factor: float = Field(default=0.0, ge=0.0, le=1.2)


class AheadSignalChangeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    target_state: Literal['yellow', 'red', 'green'] = 'yellow'
    max_distance_m: float = Field(default=120.0, ge=10, le=300)


class DualLaneSlowdownParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=100.0, ge=15, le=250)
    speed_factor: float = Field(default=0.45, ge=0.1, le=0.9)
    duration_s: float = Field(default=10.0, ge=2.0, le=60.0)


class RedLightRunnerParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=120.0, ge=15, le=250)
    duration_s: float = Field(default=8.0, ge=2.0, le=30.0)


class SetTrafficCountParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    target_count: int = Field(default=10, ge=0, le=100)


_TrafficActionName = Literal[
    'lead_hard_brake',
    'adjacent_cut_in',
    'rear_overtake',
    'lead_breakdown',
    'ahead_signal_change',
    'dual_lane_slowdown',
    'red_light_runner',
    'set_traffic_count',
]


def _send_traffic_action(
    rt: Any,
    action: _TrafficActionName,
    params: BaseModel,
    command_id: str,
) -> None:
    from drisca.core.protocol import TrafficActionCommand

    if rt.state['phase'] != 'running':
        raise RuntimeError('交通事件仅支持在实验运行期间触发')
    rt.send(
        TrafficActionCommand(
            command_id=command_id,
            action=action,
            params=params.model_dump(mode='json'),
        )
    )


@register_command(
    command_id='rear_overtake',
    label='后车超车',
    description='不受道路限速限制，让主车后方车辆变道加速超越主车并在拉出安全前距后切回主车车道',
    category=CommandCategory.TRAFFIC,
    params_model=RearOvertakeParams,
    fields=[
        {
            'key': 'mode',
            'label': '触发方式',
            'type': 'select',
            'required': True,
            'default': 'reuse_rear',
            'options': [
                {'value': 'reuse_rear', 'label': '复用后方已有车'},
                {'value': 'spawn_rear', 'label': '后方邻道临时生成超车车（带初速度）'},
            ],
        },
        {
            'key': 'side',
            'label': '超车方向',
            'type': 'select',
            'required': True,
            'default': 'any',
            'options': [
                {'value': 'any', 'label': '左右任意'},
                {'value': 'left', 'label': '左侧超车'},
                {'value': 'right', 'label': '右侧超车'},
            ],
        },
        {
            'key': 'rear_distance_m',
            'label': '后方搜索或生成距离 · m',
            'type': 'number',
            'required': True,
            'default': 22,
        },
        {
            'key': 'extra_speed_mps',
            'label': '超车相对主车增速 · m/s（无视限速）',
            'type': 'number',
            'required': True,
            'default': 8,
        },
        {
            'key': 'clear_front_m',
            'label': '超越后安全切回前距 · m',
            'type': 'number',
            'required': True,
            'default': 18,
        },
        {
            'key': 'return_to_lane',
            'label': '超越后切回主车车道',
            'type': 'boolean',
            'required': False,
            'default': True,
        },
    ],
)
def _run_rear_overtake(rt: Any, params: RearOvertakeParams, command_id: str) -> None:
    _send_traffic_action(rt, 'rear_overtake', params, command_id)


@register_command(
    command_id='adjacent_cut_in',
    label='邻车切入 / 加塞',
    description='让相邻同向车道的背景车立即切入，或在前方邻道生成车辆待主车靠近时起步加塞',
    category=CommandCategory.TRAFFIC,
    params_model=AdjacentCutInParams,
    fields=[
        {
            'key': 'mode',
            'label': '触发方式',
            'type': 'select',
            'required': True,
            'default': 'reuse_adjacent',
            'options': [
                {'value': 'reuse_adjacent', 'label': '复用相邻车道已有车（立即切入）'},
                {'value': 'spawn_cut_in', 'label': '前方邻道生成（主车靠近后加塞切入）'},
            ],
        },
        {
            'key': 'side',
            'label': '切入方向',
            'type': 'select',
            'required': True,
            'default': 'any',
            'options': [
                {'value': 'any', 'label': '左右任意'},
                {'value': 'left', 'label': '左侧车道'},
                {'value': 'right', 'label': '右侧车道'},
            ],
        },
        {
            'key': 'min_front_m',
            'label': '最小前方距离 · m',
            'type': 'number',
            'required': True,
            'default': 3.5,
        },
        {
            'key': 'max_front_m',
            'label': '最大前方距离 · m',
            'type': 'number',
            'required': True,
            'default': 28,
        },
        {
            'key': 'spawn_distance_m',
            'label': '生成距离（生成模式）· m',
            'type': 'number',
            'required': True,
            'default': 45,
        },
        {
            'key': 'trigger_distance_m',
            'label': '加塞触发距离（近距切入）· m',
            'type': 'number',
            'required': True,
            'default': 14,
        },
    ],
)
def _run_adjacent_cut_in(rt: Any, params: AdjacentCutInParams, command_id: str) -> None:
    _send_traffic_action(rt, 'adjacent_cut_in', params, command_id)


@register_command(
    command_id='lead_hard_brake',
    label='前车急刹',
    description='使主车正前方最近的背景车执行持续数秒的紧急制动',
    category=CommandCategory.TRAFFIC,
    params_model=LeadHardBrakeParams,
    fields=[
        {
            'key': 'max_distance_m',
            'label': '最大搜索距离 · m',
            'type': 'number',
            'required': True,
            'default': 60,
        },
        {
            'key': 'duration_s',
            'label': '急刹持续时长 · s',
            'type': 'number',
            'required': True,
            'default': 2.5,
        },
        {
            'key': 'brake_intensity',
            'label': '制动强度 (0.1–1)',
            'type': 'number',
            'required': True,
            'default': 0.95,
        },
    ],
)
def _run_lead_hard_brake(rt: Any, params: LeadHardBrakeParams, command_id: str) -> None:
    _send_traffic_action(rt, 'lead_hard_brake', params, command_id)


@register_command(
    command_id='lead_breakdown',
    label='前车故障停驶 / 障碍车',
    description='支持复用已有前车停驶开双闪，或在前方同车道远距离生成低速/静止故障车',
    category=CommandCategory.TRAFFIC,
    params_model=LeadBreakdownParams,
    fields=[
        {
            'key': 'mode',
            'label': '触发方式',
            'type': 'select',
            'required': True,
            'default': 'reuse_lead',
            'options': [
                {'value': 'reuse_lead', 'label': '复用已有前车（停驶并开双闪）'},
                {'value': 'spawn_far', 'label': '远距离生成低速 / 静止障碍车'},
            ],
        },
        {
            'key': 'distance_m',
            'label': '搜索或生成距离 · m',
            'type': 'number',
            'required': True,
            'default': 130,
        },
        {
            'key': 'speed_factor',
            'label': '目标速度系数 (0 为静止开双闪)',
            'type': 'number',
            'required': True,
            'default': 0,
        },
    ],
)
def _run_lead_breakdown(rt: Any, params: LeadBreakdownParams, command_id: str) -> None:
    _send_traffic_action(rt, 'lead_breakdown', params, command_id)


@register_command(
    command_id='ahead_signal_change',
    label='前方信号灯突变',
    description='自动匹配主车当前行驶路径前方的最近信号灯并动态切换灯色（两难区实验）',
    category=CommandCategory.TRAFFIC,
    params_model=AheadSignalChangeParams,
    fields=[
        {
            'key': 'target_state',
            'label': '目标灯色',
            'type': 'select',
            'required': True,
            'default': 'yellow',
            'options': [
                {'value': 'yellow', 'label': '黄灯'},
                {'value': 'red', 'label': '红灯'},
                {'value': 'green', 'label': '绿灯'},
            ],
        },
        {
            'key': 'max_distance_m',
            'label': '前方搜索距离 · m',
            'type': 'number',
            'required': True,
            'default': 120,
        },
    ],
)
def _run_ahead_signal_change(rt: Any, params: AheadSignalChangeParams, command_id: str) -> None:
    _send_traffic_action(rt, 'ahead_signal_change', params, command_id)


@register_command(
    command_id='dual_lane_slowdown',
    label='双车道并排压速',
    description='同步压低主车同车道与相邻车道前车的目标速度，形成移动路障',
    category=CommandCategory.TRAFFIC,
    params_model=DualLaneSlowdownParams,
    fields=[
        {
            'key': 'max_distance_m',
            'label': '最大搜索距离 · m',
            'type': 'number',
            'required': True,
            'default': 100,
        },
        {
            'key': 'speed_factor',
            'label': '压速系数 (0.1–0.9)',
            'type': 'number',
            'required': True,
            'default': 0.45,
        },
        {
            'key': 'duration_s',
            'label': '持续时长 · s',
            'type': 'number',
            'required': True,
            'default': 10,
        },
    ],
)
def _run_dual_lane_slowdown(rt: Any, params: DualLaneSlowdownParams, command_id: str) -> None:
    _send_traffic_action(rt, 'dual_lane_slowdown', params, command_id)


@register_command(
    command_id='red_light_runner',
    label='他车闯红灯 / 路口抢行',
    description='使前方指定范围内的背景车暂时忽略交通信号灯并加速通过路口',
    category=CommandCategory.TRAFFIC,
    params_model=RedLightRunnerParams,
    fields=[
        {
            'key': 'max_distance_m',
            'label': '最大搜索距离 · m',
            'type': 'number',
            'required': True,
            'default': 120,
        },
        {
            'key': 'duration_s',
            'label': '忽略信号时长 · s',
            'type': 'number',
            'required': True,
            'default': 8,
        },
    ],
)
def _run_red_light_runner(rt: Any, params: RedLightRunnerParams, command_id: str) -> None:
    _send_traffic_action(rt, 'red_light_runner', params, command_id)


@register_command(
    command_id='set_traffic_count',
    label='动态调整周边车流数量',
    description='设置主车周边目标背景车数量：偏多时销毁最远车辆，偏少时在远处活动半径内逐步补充',
    category=CommandCategory.TRAFFIC,
    params_model=SetTrafficCountParams,
    fields=[
        {
            'key': 'target_count',
            'label': '目标背景车数量 (0–100)',
            'type': 'number',
            'required': True,
            'default': 10,
        },
    ],
)
def _run_set_traffic_count(rt: Any, params: SetTrafficCountParams, command_id: str) -> None:
    _send_traffic_action(rt, 'set_traffic_count', params, command_id)
