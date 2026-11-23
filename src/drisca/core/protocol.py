from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from .config import CameraConfig, DisplayLayoutConfig, WeatherConfig
from .environment import (
    EnvironmentAppliedPayload,
    EnvironmentCompletedPayload,
    EnvironmentReplacedPayload,
    RegionSnapshot,
)


class WorkerRole(StrEnum):
    SIMULATOR = 'simulator'
    TRAFFIC = 'traffic'


class WorkerState(StrEnum):
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'


class LogLevel(StrEnum):
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'


class ControlMode(StrEnum):
    MANUAL = 'manual'
    AUTOPILOT = 'autopilot'


class EventKind(StrEnum):
    OPERATOR_ACTION = 'operator_action'
    WORKER_STATUS = 'worker_status'  # 子进程就绪与状态变化（由 launcher 记录）
    RUN_LIFECYCLE = 'run_lifecycle'  # 实验开始、结束请求、子进程退出（由 launcher 记录）
    SENSOR = 'sensor'  # 碰撞、压线
    CUSTOM_EVENT = 'custom_event'  # 操作者自定义打点记录


class NativeEventRef(BaseModel, frozen=True):
    """原生事件与快照的关联信息，随事件载荷一起保存。"""

    event_id: int
    world_id: int
    simulation_time_us: int
    request_id: int | None = None
    operation_index: int | None = None


class EnabledPayload(BaseModel, frozen=True):
    enabled: bool


class UpdateCameraPayload(BaseModel, frozen=True):
    camera_name: Literal['front', 'rear_top', 'rear_left', 'rear_right']
    mount: CameraConfig  # 调整后的安装位姿与视野


class ExperimentEventBase(BaseModel, frozen=True):
    """实验事件公共基类，描述已经发生的操作或状态变化，开启保存时写入 event 表。
    由实际执行该操作的进程上报，launcher 统一处理事件，同一个操作只记录一次。"""

    type: Literal['experiment_event'] = 'experiment_event'
    kind: EventKind
    source: Literal['wheel', 'keyboard', 'launcher', 'model', 'sensor', 'system']
    frame_no: int | None = None
    timestamp: float
    command_id: str | None = None
    native: NativeEventRef | None = None  # 原生事件编号与世界关联，随载荷写入


class ToggleAutopilotEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_autopilot'] = 'toggle_autopilot'
    payload: EnabledPayload


class TakeoverPayload(BaseModel, frozen=True):
    enabled: bool
    actor_id: int
    revision: int


class ToggleTakeoverEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_takeover'] = 'toggle_takeover'
    payload: TakeoverPayload


class DriverRequestPayload(BaseModel, frozen=True):
    action: str


class DriverRequestEvent(ExperimentEventBase, frozen=True):
    """驾驶人按下的模式请求，未经执行，由实验端决定是否响应。"""

    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['driver_request'] = 'driver_request'
    payload: DriverRequestPayload


class ControlModeChangedPayload(BaseModel, frozen=True):
    actor_id: int
    previous_mode: Literal['manual', 'external']
    mode: Literal['manual', 'external']
    controller: str
    revision: int


class ControlModeChangedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['control_mode_changed'] = 'control_mode_changed'
    payload: ControlModeChangedPayload


class ToggleReverseEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_reverse'] = 'toggle_reverse'
    payload: EnabledPayload  # {'enabled': bool}


class ToggleManualGearEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_manual_gear'] = 'toggle_manual_gear'
    payload: EnabledPayload  # {'enabled': bool}


class ChangeGearPayload(BaseModel, frozen=True):
    gear: int


class ChangeGearEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['change_gear'] = 'change_gear'
    payload: ChangeGearPayload


class ToggleHandbrakeEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_handbrake'] = 'toggle_handbrake'
    payload: EnabledPayload  # {'enabled': bool}


class ToggleLightPayload(BaseModel, frozen=True):
    light: str
    enabled: bool


class ToggleLightEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_light'] = 'toggle_light'
    payload: ToggleLightPayload


class UpdateLayoutEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['update_layout'] = 'update_layout'
    payload: DisplayLayoutConfig


class UpdateCameraEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['update_camera'] = 'update_camera'
    payload: UpdateCameraPayload


class EnvironmentAppliedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['environment_applied'] = 'environment_applied'
    payload: EnvironmentAppliedPayload


class EnvironmentCompletedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['environment_completed'] = 'environment_completed'
    payload: EnvironmentCompletedPayload


class EnvironmentReplacedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['environment_replaced'] = 'environment_replaced'
    payload: EnvironmentReplacedPayload


class CollisionPayload(BaseModel, frozen=True):
    actor_id: int
    actor_type: str
    impulse_x: float
    impulse_y: float
    impulse_z: float


class CollisionEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.SENSOR] = EventKind.SENSOR
    name: Literal['collision'] = 'collision'
    payload: CollisionPayload


class LaneInvasionPayload(BaseModel, frozen=True):
    markings: tuple[str, ...]


class LaneInvasionEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.SENSOR] = EventKind.SENSOR
    name: Literal['lane_invasion'] = 'lane_invasion'
    payload: LaneInvasionPayload


class TrafficLightStatePayload(BaseModel, frozen=True):
    scope: Literal['light']
    actor_id: int
    signal_id: str
    controller_id: str | None = None
    group_id: int | None = None
    previous_state: str
    state: str


class TrafficLightStateChangedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['traffic_light_state_changed'] = 'traffic_light_state_changed'
    payload: TrafficLightStatePayload


class TrafficTiming(BaseModel, frozen=True):
    green: float
    yellow: float
    red: float


class TrafficControllerTimingPayload(BaseModel, frozen=True):
    scope: Literal['controller']
    controller_id: str
    group_id: int | None = None
    previous: TrafficTiming
    current: TrafficTiming


class TrafficControllerTimingChangedEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['traffic_controller_timing_changed'] = 'traffic_controller_timing_changed'
    payload: TrafficControllerTimingPayload


class TrafficLightGroupFrozenPayload(BaseModel, frozen=True):
    scope: Literal['group']
    group_id: int
    junction_id: int
    controller_ids: tuple[str, ...]
    previous: bool
    frozen: bool


class TrafficLightGroupFrozenEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['traffic_light_group_frozen'] = 'traffic_light_group_frozen'
    payload: TrafficLightGroupFrozenPayload


class TrafficLightGroupResetPayload(BaseModel, frozen=True):
    scope: Literal['group']
    group_id: int
    junction_id: int
    controller_ids: tuple[str, ...]
    previous_frozen: bool
    frozen: bool


class TrafficLightGroupResetEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['traffic_light_group_reset'] = 'traffic_light_group_reset'
    payload: TrafficLightGroupResetPayload


class TrafficLightAllFrozenPayload(BaseModel, frozen=True):
    scope: Literal['all']
    group_ids: tuple[int, ...]
    controller_ids: tuple[str, ...]
    previous: bool
    frozen: bool


class TrafficLightAllFrozenEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['traffic_light_all_frozen'] = 'traffic_light_all_frozen'
    payload: TrafficLightAllFrozenPayload


class CustomExperimentEvent(ExperimentEventBase, frozen=True):
    """自定义剧本打点或其他扩展事件"""

    name: Literal['custom'] = 'custom'
    payload: dict[str, Any] = Field(default_factory=dict)


# 实验事件按名称还原为具体子类。
ExperimentEvent = Annotated[
    ToggleAutopilotEvent
    | ToggleTakeoverEvent
    | DriverRequestEvent
    | ControlModeChangedEvent
    | ToggleReverseEvent
    | ToggleManualGearEvent
    | ChangeGearEvent
    | ToggleHandbrakeEvent
    | ToggleLightEvent
    | UpdateLayoutEvent
    | UpdateCameraEvent
    | EnvironmentAppliedEvent
    | EnvironmentCompletedEvent
    | EnvironmentReplacedEvent
    | CollisionEvent
    | LaneInvasionEvent
    | TrafficLightStateChangedEvent
    | TrafficControllerTimingChangedEvent
    | TrafficLightGroupFrozenEvent
    | TrafficLightGroupResetEvent
    | TrafficLightAllFrozenEvent
    | CustomExperimentEvent,
    Field(discriminator='name'),
]


# 上行消息：子进程 -> launcher (WorkerEvent)


class WorkerReadyEvent(BaseModel, frozen=True):
    """主车与传感器在 CARLA 中生成完毕后立刻上报，用于回填 session 表"""

    type: Literal['ready'] = 'ready'
    role: WorkerRole = WorkerRole.SIMULATOR
    ego_actor_id: int
    ego_type_id: str
    vehicle_box: dict[str, dict[str, float]]
    fog_regions: tuple[RegionSnapshot, ...] = ()  # 就绪时的实际局部球雾快照


class WorkerStatusEvent(BaseModel, frozen=True):
    type: Literal['status'] = 'status'
    role: WorkerRole
    state: WorkerState
    detail: str = ''


class LogEvent(BaseModel, frozen=True):
    """由 loguru sink 写入有界队列后异步上报"""

    type: Literal['log'] = 'log'
    role: WorkerRole
    timestamp: float
    level: LogLevel
    message: str
    command_id: str | None = None  # 命令执行错误关联编号


# ExperimentEvent 的字段与判别联合见实验事件文档。


class TelemetrySnapshotEvent(BaseModel, frozen=True):
    """遥测快照（20~30Hz）：simulator 的实时运行状态，供 launcher 数据面板、平板 HUD（取子集）使用"""

    type: Literal['telemetry'] = 'telemetry'
    seq: int
    timestamp: float
    frame_no: int = 0
    server_fps: float = 0.0
    simulator_fps: float = 0.0
    # 核心 HUD 与控制状态
    control_mode: ControlMode = ControlMode.MANUAL
    control_source: str = ''  # 原生控制来源：manual-human / external-python 等
    input_throttle: float = 0.0
    input_steer: float = 0.0
    input_brake: float = 0.0
    speed_mps: float = 0.0
    speed_limit_mps: float = 0.0
    gear: int = 0  # -1: R, 0: N, >=1: D 挡位
    steer: float = 0.0  # [-1.0, 1.0]
    throttle: float = 0.0  # [0.0, 1.0]
    brake: float = 0.0  # [0.0, 1.0]
    reverse: bool = False
    hand_brake: bool = False
    manual_gear_shift: bool = False
    takeover_requested: bool = False
    # 位姿、道路与传感器遥测（供 launcher 数据面板、出生点拾取与事件判定使用）
    location_x: float = 0.0
    location_y: float = 0.0
    location_z: float = 0.0
    rotation_pitch: float = 0.0
    rotation_yaw: float = 0.0
    rotation_roll: float = 0.0
    compass: float = 0.0
    road_id: int = 0
    lane_id: int = 0
    lane_offset: float = 0.0
    collision_intensity: float = 0.0
    invaded_lane_marking: str = ''


WorkerEvent = Annotated[
    WorkerReadyEvent | WorkerStatusEvent | LogEvent | ExperimentEvent | TelemetrySnapshotEvent,
    Field(discriminator='type'),
]


# 下行命令：launcher -> 子进程 (LauncherCommand)


class StopCommand(BaseModel, frozen=True):
    """通知子进程退出主循环、Flush 数据库并销毁 Actor"""

    command_id: str
    type: Literal['stop'] = 'stop'


class SetAutopilotCommand(BaseModel, frozen=True):
    """由 launcher 远程切换主车自动驾驶状态"""

    command_id: str
    type: Literal['set_autopilot'] = 'set_autopilot'
    enabled: bool


class SetTakeoverCommand(BaseModel, frozen=True):
    """由操作者远程触发或解除接管请求"""

    command_id: str
    type: Literal['set_takeover'] = 'set_takeover'
    enabled: bool


class SetWeatherCommand(BaseModel, frozen=True):
    """由 launcher 运行期动态切换天气"""

    command_id: str
    type: Literal['set_weather'] = 'set_weather'
    weather: WeatherConfig


class UpdateCameraCommand(BaseModel, frozen=True):
    """由 launcher 实时调整任一车载相机的安装位姿与视野"""

    command_id: str
    type: Literal['update_camera'] = 'update_camera'
    camera_name: Literal['front', 'rear_top', 'rear_left', 'rear_right'] = 'front'
    mount: CameraConfig


class UpdateLayoutCommand(BaseModel, frozen=True):
    """由 launcher 更新后视镜画面布局"""

    command_id: str
    type: Literal['update_layout'] = 'update_layout'
    layout: DisplayLayoutConfig


LauncherCommand = Annotated[
    StopCommand
    | SetAutopilotCommand
    | SetTakeoverCommand
    | SetWeatherCommand
    | UpdateCameraCommand
    | UpdateLayoutCommand,
    Field(discriminator='type'),
]


_worker_adapter = TypeAdapter(WorkerEvent)
_command_adapter = TypeAdapter(LauncherCommand)


def dump_worker_event(event: WorkerEvent) -> str:
    return _worker_adapter.dump_json(event).decode('utf-8')


def parse_worker_event(raw_json: str | bytes) -> WorkerEvent:
    return _worker_adapter.validate_json(raw_json)


def dump_launcher_command(cmd: LauncherCommand) -> str:
    return _command_adapter.dump_json(cmd).decode('utf-8')


def parse_launcher_command(raw_json: str | bytes) -> LauncherCommand:
    return _command_adapter.validate_json(raw_json)
