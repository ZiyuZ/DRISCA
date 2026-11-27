"""可注册实验指令与事件库（按 category 分为 weather / traffic / ego / custom）。"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, Unpack

from pydantic import BaseModel, ConfigDict, Field

from drisca.core.client import NativeApiClient
from drisca.core.protocol import LauncherCommand
from drisca.core.traffic_models import (
    AdjacentCutInParams,
    AheadSignalChangeParams,
    DualLaneSlowdownParams,
    LeadBreakdownParams,
    LeadHardBrakeParams,
    RearOvertakeParams,
    RedLightRunnerParams,
    SetTrafficCountParams,
    TrafficAction,
    TrafficActionParams,
)
from drisca.core.types import JsonObject, JsonValue, as_float, as_int
from drisca.launcher.state import LauncherState, LauncherStatePatch


class CommandRuntime(Protocol):
    """实验指令处理器依赖的 Runtime 最小接口协议。"""

    api: NativeApiClient | None
    state: LauncherState

    def send(self, command: LauncherCommand) -> None: ...
    def speak(self, text: str, command_id: str) -> None: ...
    def update(self, **changes: Unpack[LauncherStatePatch]) -> None: ...
    def log(
        self,
        message: str,
        level: str = 'INFO',
        role: str = 'launcher',
        *,
        detail: str | None = None,
    ) -> None: ...
    def read_fog_regions(self) -> list[JsonObject]: ...


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
    fields: tuple[JsonObject, ...]
    handler: Callable[[CommandRuntime, BaseModel, str], None]

    def to_bootstrap(self) -> JsonObject:
        field_list: list[JsonValue] = list(self.fields)
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
            'category': str(self.category),
            'fields': field_list,
        }


REGISTRY: dict[str, CommandSpec] = {}
MODELS: dict[str, type[BaseModel]] = {}
COMMANDS: list[JsonObject] = []


def register_command[P: BaseModel](
    *,
    command_id: str,
    label: str,
    description: str,
    category: CommandCategory,
    params_model: type[P],
    fields: list[JsonObject],
) -> Callable[[Callable[[CommandRuntime, P, str], None]], Callable[[CommandRuntime, P, str], None]]:
    """注册一条可由前端动态渲染与触发的实验事件/指令。"""

    def decorator(
        func: Callable[[CommandRuntime, P, str], None],
    ) -> Callable[[CommandRuntime, P, str], None]:
        def runner(rt: CommandRuntime, raw_params: BaseModel, command_id: str) -> None:
            validated = (
                raw_params
                if isinstance(raw_params, params_model)
                else params_model.model_validate(raw_params.model_dump())
            )
            func(rt, validated, command_id)

        spec = CommandSpec(
            id=command_id,
            label=label,
            description=description,
            category=category,
            params_model=params_model,
            fields=tuple(fields),
            handler=runner,
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
def _run_autopilot(rt: CommandRuntime, params: AutopilotParams, command_id: str) -> None:
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
def _run_takeover(rt: CommandRuntime, params: TakeoverParams, command_id: str) -> None:
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
def _run_speech(rt: CommandRuntime, params: SpeechParams, command_id: str) -> None:
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
def _run_local_fog_burst(rt: CommandRuntime, params: LocalFogBurstParams, command_id: str) -> None:
    from uuid import uuid4

    from drisca.core.protocol import CreateFogRegionCommand, DeleteFogRegionCommand

    if params.placement == 'fixed':
        center = (params.x, params.y, params.z)
    else:
        telemetry = rt.state.get('telemetry')
        if isinstance(telemetry, dict):
            x = as_float(telemetry.get('location_x'))
            y = as_float(telemetry.get('location_y'))
            z = as_float(telemetry.get('location_z'))
            yaw = math.radians(as_float(telemetry.get('rotation_yaw')))
        else:
            catalog = rt.state.get('catalog')
            spawns = catalog.get('spawn_points') if isinstance(catalog, dict) else None
            if not isinstance(spawns, list) or not spawns or not isinstance(spawns[0], dict):
                raise RuntimeError('当前无主车遥测且无可用出生点，无法按主车前方定位')
            sp = spawns[0]
            x = as_float(sp.get('x'))
            y = as_float(sp.get('y'))
            z = as_float(sp.get('z'))
            yaw = math.radians(as_float(sp.get('yaw')))
        center = (
            x + math.cos(yaw) * params.distance_m,
            y + math.sin(yaw) * params.distance_m,
            z + 2.0,
        )

    if rt.state['phase'] == 'running':
        expected_session = rt.state.get('session_id')
        raw_regions = rt.state.get('fog_regions')
        before_ids = {
            as_int(r.get('region_id'))
            for r in (raw_regions if isinstance(raw_regions, list) else [])
            if isinstance(r, dict)
        }
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

        def _region_ids() -> list[int]:
            regions = rt.state.get('fog_regions')
            if not isinstance(regions, list):
                return []
            return [as_int(r.get('region_id')) for r in regions if isinstance(r, dict)]

        def schedule_cleanup() -> None:
            # 等待新区域创建事件回传以获取 region_id，并校验会话一致性
            region_id: int | None = None
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and rt.state.get('session_id') == expected_session:
                added = [rid for rid in _region_ids() if rid not in before_ids]
                if added:
                    region_id = added[-1]
                    break
                time.sleep(0.1)
            if region_id is None:
                return
            time.sleep(params.fade_in_s + params.hold_s)
            if rt.state['phase'] != 'running' or rt.state.get('session_id') != expected_session:
                return
            if region_id in _region_ids():
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
def _run_rain_squall(rt: CommandRuntime, params: RainSquallParams, command_id: str) -> None:
    from uuid import uuid4

    from drisca.core.config import PrecipitationConfig, SurfaceConfig, WeatherConfig
    from drisca.core.protocol import SetWeatherCommand
    from drisca.core.weather import to_config, to_payload

    raw_weather = rt.state.get('weather')
    if raw_weather is None:
        preset = rt.state.get('active_preset')
        world = preset.get('world') if isinstance(preset, dict) else None
        raw_weather = world.get('weather') if isinstance(world, dict) else None
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


def _send_traffic_action(
    rt: CommandRuntime,
    action: TrafficAction,
    params: TrafficActionParams,
    command_id: str,
) -> None:
    from drisca.core.protocol import TrafficActionCommand

    if rt.state['phase'] != 'running':
        raise RuntimeError('交通事件仅支持在实验运行期间触发')
    rt.send(
        TrafficActionCommand(
            command_id=command_id,
            action=action,
            params=params,
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
def _run_rear_overtake(rt: CommandRuntime, params: RearOvertakeParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.REAR_OVERTAKE, params, command_id)


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
def _run_adjacent_cut_in(rt: CommandRuntime, params: AdjacentCutInParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.ADJACENT_CUT_IN, params, command_id)


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
def _run_lead_hard_brake(rt: CommandRuntime, params: LeadHardBrakeParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.LEAD_HARD_BRAKE, params, command_id)


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
def _run_lead_breakdown(rt: CommandRuntime, params: LeadBreakdownParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.LEAD_BREAKDOWN, params, command_id)


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
def _run_ahead_signal_change(rt: CommandRuntime, params: AheadSignalChangeParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.AHEAD_SIGNAL_CHANGE, params, command_id)


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
def _run_dual_lane_slowdown(rt: CommandRuntime, params: DualLaneSlowdownParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.DUAL_LANE_SLOWDOWN, params, command_id)


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
def _run_red_light_runner(rt: CommandRuntime, params: RedLightRunnerParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.RED_LIGHT_RUNNER, params, command_id)


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
def _run_set_traffic_count(rt: CommandRuntime, params: SetTrafficCountParams, command_id: str) -> None:
    _send_traffic_action(rt, TrafficAction.SET_TRAFFIC_COUNT, params, command_id)
