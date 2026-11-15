# 核心数据结构与协议契约

> 文档定位：本文面向项目开发者，定义 DRISCA 的四类核心数据结构：配置模型（`core.config`）、进程间通信协议（`core.protocol`）、模拟器运行时状态（`simulator.state`）以及数据库表与行模型（`storage.models`）。各模块的函数与类接口设计见 [模块职责与 API 规范](./03-ModuleAPI.md)，桌面界面布局与交互设计见 [桌面管理端设计](./04-LauncherDesign.md)。

## 设计准则与类型约定

1. Python 3.12 类型特性：
   - 枚举统一使用标准库 `enum.StrEnum` 与 `enum.IntEnum`（可直接用于 JSON 序列化与 SQLite 参数绑定）。
   - 跨进程配置与 WebSocket 消息统一使用 `pydantic.BaseModel(frozen=True)`。
   - 高频创建的数据库行结构统一使用 `@dataclass(slots=True, frozen=True)`，避免每帧构造时的校验开销与字典分配。
2. 物理量单位统一：
   - 内部计算与数据库持久化中的所有速度量统一采用国际单位制 `m/s`（米/秒），角度统一指明弧度（`rad`）或角度（`deg`）。
   - CARLA API 单位转换注意：CARLA 的 `vehicle.get_speed_limit()` 返回值单位为 `km/h`，在开启 `dynamic_speed_limit` 时必须除以 `3.6` 转换为 `m/s` 后再存入运行时状态与数据库。
   - `km/h` 仅在面向人的展示边界（如平板 HUD、桌面端数据面板与预设输入）由前端或视图层按 `× 3.6` 转换。
3. C++ 计算对象与持久化标量的边界分离：
   - 在 `simulator` 内部，运行时状态直接持有 CARLA 的 C++ 对象（`carla.Vector3D`、`carla.Transform`、`carla.Location`、`carla.Waypoint`），直接调用 C++ 绑定的 `.length()`、`.cross()`、`.distance_2d()` 完成几何计算。
   - 在进入 `storage` 写入队列时，通过显式的纯函数投影为只含基础标量（`int / float / str / bool`）的 `DataRow`。

## 配置模型（`core/config.py`）

配置按职责划分为机器配置（`MachineConfig`）、控制配置（`ControlConfig`）、实验预设（`PresetConfig`）与单次实验设置（`RunSettings`），并在启动实验时由 `launcher` 合成为不可变的 `RunConfig`。

### 2.1 基础几何与相机配置结构

车载四路相机（主视图 `front` + 三路后视镜 `rear_top` / `rear_left` / `rear_right`）的安装位置因车型而异。预设页提供静态编辑；实验运行期可通过实验控制台的调试面板发送 `UpdateCameraCommand` 实时微调相机，并选择覆盖当前预设或另存为新预设：

```python
from enum import StrEnum
from pydantic import BaseModel


class STransform(BaseModel, frozen=True):
    """纯数据三维位姿（替代导入期依赖 carla.Transform），在 core 层提供 to_carla/from_carla 转换"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0


class CameraAttachment(StrEnum):
    RIGID = 'Rigid'
    SPRING_ARM_GHOST = 'SpringArmGhost'


class CameraMountConfig(BaseModel, frozen=True):
    """单路相机的安装与画面配置"""
    transform: STransform
    screen_position: tuple[float, float] = (0.5, 0.5)  # 画面中心在窗口中的归一化坐标 (0~1)
    image_size: tuple[int, int] | None = None          # None 表示自动跟随模拟器主窗口分辨率（用于 front）
    fov: float = 100.0
    attachment: CameraAttachment = CameraAttachment.RIGID


class CameraRigConfig(BaseModel, frozen=True):
    """主车四路相机组合配置（固定使用 sensor.camera.rgb）"""
    show_rearview: bool = True
    front: CameraMountConfig = CameraMountConfig(
        transform=STransform(x=0.5, y=-0.35, z=1.35, pitch=5.8),
        screen_position=(0.5, 0.5),
        image_size=None,  # 运行时自动取窗口实际分辨率，无需改写配置对象
        fov=120.0,
    )
    rear_top: CameraMountConfig = CameraMountConfig(
        transform=STransform(x=0.34, y=0.0, z=1.27, pitch=5.8, yaw=180.0),
        screen_position=(0.5, 0.1),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_left: CameraMountConfig = CameraMountConfig(
        transform=STransform(x=0.4, y=-0.93, z=1.03, pitch=5.8, yaw=180.0),
        screen_position=(0.12, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_right: CameraMountConfig = CameraMountConfig(
        transform=STransform(x=0.4, y=0.93, z=1.03, pitch=5.8, yaw=180.0),
        screen_position=(0.88, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )
```

### 2.2 机器配置（`MachineConfig` ↔ `config/machine.toml`）

存放与运行主机网络、显示器及本地服务绑定的环境参数，每台实验机器配置一次：

```python
class CarlaConnectionConfig(BaseModel, frozen=True):
    host: str = '127.0.0.1'
    port: int = 2000
    tm_port: int = 8000
    timeout: float = 5.0


class DisplayConfig(BaseModel, frozen=True):
    resolution: tuple[int, int] = (1600, 900)  # 宽度建议为 64 的倍数以避免 CARLA 相机画面撕裂
    fullscreen: bool = False
    borderless: bool = False
    fps: int = 60


class ServiceConfig(BaseModel, frozen=True):
    launcher_host: str = '0.0.0.0'  # 监听局域网以便平板连接
    launcher_port: int = 7777
    db_name_prefix: str = 'experiment'
    enable_tts: bool = True         # 由 launcher 托管的语音播报开关
    debug: bool = False


class MachineConfig(BaseModel, frozen=True):
    carla: CarlaConnectionConfig = CarlaConnectionConfig()
    display: DisplayConfig = DisplayConfig()
    service: ServiceConfig = ServiceConfig()
```

### 2.3 控制配置（`ControlConfig` ↔ `config/control.toml`）

将键盘与方向盘的参数（开关、灵敏度系数、轴号、按钮映射）统一收归 `config/control.toml`。不同实验机器若使用相同型号的方向盘外设，可直接复用同一份 `control.toml`。

`simulator` 负责面向被试的驾驶控制输入；运行期调试由操作者通过 `launcher` 界面完成。

```python
# 罗技 G29 / G920 / G923 DirectInput 物理按钮编号与名称对照表（供 launcher 界面与按键说明展示）
G29_BUTTON_NAMES: dict[int, str] = {
    0: 'X 键 (Cross)',
    1: '方块键 (Square)',
    2: '圆圈键 (Circle)',
    3: '三角键 (Triangle)',
    4: '右换挡拨片 (R1)',
    5: '左换挡拨片 (L1)',
    6: 'R2 键',
    7: 'L2 键',
    8: 'Share 键',
    9: 'Options 键',
    10: 'R3 键',
    11: 'L3 键',
    19: '加号键 (+)',
    20: '减号键 (-)',
    21: '红旋钮右旋',
    22: '红旋钮左旋',
    23: '红旋钮确认键 (Enter)',
    24: 'PS / Logo 键',
}


class KeyboardControlConfig(BaseModel, frozen=True):
    """键盘按键绑定（使用 pygame.key.name 名称，元组内任一按键均可触发）"""
    quit: tuple[str, ...] = ('escape',)
    toggle_autopilot: tuple[str, ...] = ('p', 'keypad 1')
    toggle_takeover: tuple[str, ...] = ('backslash', 'keypad 2')
    toggle_reverse: tuple[str, ...] = ('q',)
    toggle_manual_transmission: tuple[str, ...] = ('m',)
    gear_up: tuple[str, ...] = ('period',)
    gear_down: tuple[str, ...] = ('comma',)
    toggle_handbrake: tuple[str, ...] = ('space',)
    toggle_light_double_blinker: tuple[str, ...] = ('semicolon',)
    toggle_light_low_beam: tuple[str, ...] = ('k',)
    toggle_light_high_beam: tuple[str, ...] = ('l',)
    toggle_light_left_blinker: tuple[str, ...] = ('z',)
    toggle_light_right_blinker: tuple[str, ...] = ('x',)
    toggle_light_interior: tuple[str, ...] = ('i',)
    drive_forward: tuple[str, ...] = ('up', 'w')
    drive_backward: tuple[str, ...] = ('down', 's')
    drive_left: tuple[str, ...] = ('left', 'a')
    drive_right: tuple[str, ...] = ('right', 'd')


class WheelControlConfig(BaseModel, frozen=True):
    """方向盘硬件开关、响应灵敏度、轴号与按钮绑定（按钮为 None 表示未绑定）"""
    enable_wheel: bool = True
    show_button_key: bool = False
    autopilot_wheel_sync: bool = False
    acceleration_factor: float = 1.2
    deceleration_factor: float = 0.003
    angle_scale_factor: float = 0.1
    angle_max_rotate_factor: float = 1.4
    # 轴序号
    steering_axis: int = 0
    throttle_axis: int = 1
    brake_axis: int = 2
    # 动作按钮序号（int | None；在 TOML 文件中显式写出，未绑定项可在界面中置空）
    toggle_autopilot: int | None = 23
    toggle_takeover: int | None = 0
    toggle_reverse: int | None = 5
    toggle_handbrake: int | None = 4
    toggle_light_left_blinker: int | None = 7
    toggle_light_right_blinker: int | None = 6
    toggle_light_double_blinker: int | None = 3


class ControlConfig(BaseModel, frozen=True):
    keyboard: KeyboardControlConfig = KeyboardControlConfig()
    wheel: WheelControlConfig = WheelControlConfig()
```

### 2.4 实验预设、单次实验设置与合成运行配置（`PresetConfig`、`RunSettings`、`RunConfig`）

`PresetConfig` 对应 `presets/*.toml`：

```python
class WeatherConfig(BaseModel, frozen=True):
    preset_name: str = 'Default'  # 如 'ClearNoon', 'WetNoon', 'HardRainNoon'；为 'Custom' 时使用下方参数
    cloudiness: float = 30.0
    wetness: float = 80.0
    precipitation: float = 80.0
    precipitation_deposits: float = 80.0
    wind_intensity: float = 20.0
    dust_storm: float = 0.0
    sun_azimuth_angle: float = 0.0
    sun_altitude_angle: float = 45.0
    fog_density: float = 0.0
    fog_distance: float = 0.0
    fog_falloff: float = 0.0
    scattering_intensity: float = 0.0
    mie_scattering_scale: float = 0.0
    rayleigh_scattering_scale: float = 0.0331


class WorldConfig(BaseModel, frozen=True):
    map_name: str = 'Town10HD_Opt'
    load_map: bool = False
    sync_mode: bool = False
    clear_existing_actors: bool = True
    random_seed: int | None = None  # 可选，默认不设置；影响出生点与蓝图的随机选取
    weather: WeatherConfig = WeatherConfig()


class EgoVehicleConfig(BaseModel, frozen=True):
    role_name: str = 'hero'
    blueprint: str | None = 'vehicle.audi.a2'  # None 表示从可用车辆蓝图中随机选取
    generation: int = 0                        # 0 表示不限世代，可选 1, 2, 3
    spawn_point: STransform | None = None      # None 表示随机选取出生点；运行期可在调试面板中拾取当前主车位置并写回预设
    default_speed_limit: float = 33.33         # 默认限速 (m/s，对应 120 km/h)
    dynamic_speed_limit: bool = False          # 开启时读取 actor.get_speed_limit() / 3.6 转为 m/s
    init_autopilot: bool = False               # 启动后是否默认进入 CARLA 自动驾驶


class RecordConfig(BaseModel, frozen=True):
    save_data: bool = True
    enable_carla_recorder: bool = False


class PresetConfig(BaseModel, frozen=True):
    world: WorldConfig = WorldConfig()
    ego: EgoVehicleConfig = EgoVehicleConfig()
    cameras: CameraRigConfig = CameraRigConfig()
    record: RecordConfig = RecordConfig()


class RunSettings(BaseModel, frozen=True):
    """实验设置：每次实验启动时在 launcher 实验控制台中填写，不保存为预设。
    与预设合并得到本次实验的设置，最终随 RunConfig 一起写入会话。"""
    subject_id: str = ''  # 被试编号
    note: str = ''        # 本次实验备注


class RunConfig(BaseModel, frozen=True):
    """实验启动时由 launcher 合成并写入 cache/run/<session_id>.json 的不可变配置。
    由机器配置、控制配置、预设与实验设置四部分组成，运行期间的临时改动不回写。"""
    session_id: str
    db_path: str                        # 由 launcher 决定的 SQLite 数据库文件绝对路径
    launcher_ws_url: str | None = None  # 例如 'ws://127.0.0.1:7777/ws/worker/simulator'；独立调试时为 None
    machine: MachineConfig
    control: ControlConfig
    preset: PresetConfig
    run: RunSettings
```

## 进程间通信协议（`core/protocol.py`）

`simulator` 与 `launcher` 之间通过本地 WebSocket 传输 Pydantic JSON 消息，利用 `discriminator` 实现多态反序列化。

其中 `TelemetrySnapshotEvent`（遥测快照）包含 `simulator` 的实时运行状态，由 `launcher` 分三路使用：

1. 平板 HUD：`launcher` 从快照中取出子集（车速、限速、挡位、转向、驾驶模式），通过 SSE 推送给平板。
2. `launcher` 数据面板与调试面板：以 20~30 Hz 显示遥测指标与控制条，并支持在调试面板中拾取快照里的主车当前坐标作为 `spawn_point`。
3. `launcher` 事件与语音播报引擎：检测超速、驾驶模式切换或特定场景条件，触发语音播报，或向 `simulator` 下发接管命令。

```python
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field


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


class DriveMode(IntEnum):
    NOT_RUNNING = -1
    MANUAL = 0
    AUTOPILOT = 1
    TAKEOVER = 2


# ==========================================
# 上行消息：子进程 -> launcher (WorkerEvent)
# ==========================================

class WorkerReadyEvent(BaseModel, frozen=True):
    """主车与传感器在 CARLA 中生成完毕后立刻上报，用于回填 session 表"""
    type: Literal['ready'] = 'ready'
    role: WorkerRole = WorkerRole.SIMULATOR
    ego_actor_id: int
    ego_type_id: str


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


class EventKind(StrEnum):
    OPERATOR_ACTION = 'operator_action'  # 离散操作：自动驾驶、接管、倒挡、档位、手刹、车灯、后视镜显隐、镜头调整、天气等
    WORKER_STATUS = 'worker_status'      # 子进程就绪与状态变化（由 launcher 记录）
    RUN_LIFECYCLE = 'run_lifecycle'      # 实验开始、结束请求、子进程退出（由 launcher 记录）
    CUSTOM_EVENT = 'custom_event'        # 实验规则引擎或自定义事件打点记录


class AutopilotPayload(BaseModel, frozen=True):
    enabled: bool


class TakeoverPayload(BaseModel, frozen=True):
    enabled: bool


class RearviewPayload(BaseModel, frozen=True):
    enabled: bool


class UpdateCameraPayload(BaseModel, frozen=True):
    camera_name: Literal['front', 'rear_top', 'rear_left', 'rear_right']
    mount: CameraMountConfig   # 调整后的安装位姿与视野


class SetWeatherPayload(BaseModel, frozen=True):
    weather: WeatherConfig


class ExperimentEventBase(BaseModel, frozen=True):
    """实验事件公共基类，描述已经发生的操作或状态变化，最终写入 event 表。
    由实际执行该操作的进程上报，launcher 统一写入事件表，同一个操作只记录一次。"""
    type: Literal['experiment_event'] = 'experiment_event'
    kind: EventKind
    source: Literal['wheel', 'keyboard', 'launcher', 'system']
    frame_no: int | None = None
    elapsed_seconds: float | None = None
    timestamp: float


class ToggleAutopilotEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_autopilot'] = 'toggle_autopilot'
    payload: AutopilotPayload


class ToggleTakeoverEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_takeover'] = 'toggle_takeover'
    payload: TakeoverPayload


class ToggleReverseEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_reverse'] = 'toggle_reverse'
    payload: AutopilotPayload  # {'enabled': bool}


class ToggleManualGearEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_manual_gear'] = 'toggle_manual_gear'
    payload: AutopilotPayload  # {'enabled': bool}


class ChangeGearPayload(BaseModel, frozen=True):
    gear: int


class ChangeGearEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['change_gear'] = 'change_gear'
    payload: ChangeGearPayload


class ToggleHandbrakeEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_handbrake'] = 'toggle_handbrake'
    payload: AutopilotPayload  # {'enabled': bool}


class ToggleLightPayload(BaseModel, frozen=True):
    light: str
    enabled: bool


class ToggleLightEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_light'] = 'toggle_light'
    payload: ToggleLightPayload


class SetRearviewEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['set_rearview'] = 'set_rearview'
    payload: RearviewPayload


class UpdateCameraEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['update_camera'] = 'update_camera'
    payload: UpdateCameraPayload


class SetWeatherEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['set_weather'] = 'set_weather'
    payload: SetWeatherPayload


class CustomExperimentEvent(ExperimentEventBase, frozen=True):
    """自定义剧本打点或其他扩展事件"""
    name: Literal['custom'] = 'custom'
    payload: dict[str, Any] = Field(default_factory=dict)


# 解析时外层 WorkerEvent 先按 type='experiment_event' 分发，内层 ExperimentEvent 再按 discriminator='name' 还原为具体子类。
# launcher 自身产生的生命周期事件（session_start / session_end）与子进程状态事件直接构造 EventRow 写入数据库，不经过子进程上行通道。
ExperimentEvent = Annotated[
    ToggleAutopilotEvent
    | ToggleTakeoverEvent
    | ToggleReverseEvent
    | ToggleManualGearEvent
    | ChangeGearEvent
    | ToggleHandbrakeEvent
    | ToggleLightEvent
    | SetRearviewEvent
    | UpdateCameraEvent
    | SetWeatherEvent
    | CustomExperimentEvent,
    Field(discriminator='name'),
]


class TelemetrySnapshotEvent(BaseModel, frozen=True):
    """遥测快照（20~30Hz）：simulator 的实时运行状态，供 launcher 数据面板、平板 HUD（取子集）与事件引擎使用"""
    type: Literal['telemetry'] = 'telemetry'
    seq: int
    updated_at: float
    frame_no: int = 0
    elapsed_seconds: float = 0.0
    server_fps: float = 0.0
    simulator_fps: float = 0.0
    # 核心 HUD 与控制状态
    mode: DriveMode = DriveMode.NOT_RUNNING
    speed_mps: float = 0.0
    speed_limit_mps: float = 0.0
    gear: int = 0               # -1: R, 0: N, >=1: D 挡位
    steer: float = 0.0          # [-1.0, 1.0]
    throttle: float = 0.0       # [0.0, 1.0]
    brake: float = 0.0          # [0.0, 1.0]
    reverse: bool = False
    hand_brake: bool = False
    manual_gear_shift: bool = False
    autopilot: bool = False
    takeover: bool = False
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
    WorkerReadyEvent
    | WorkerStatusEvent
    | LogEvent
    | ExperimentEvent
    | TelemetrySnapshotEvent,
    Field(discriminator='type'),
]


# ==========================================
# 下行命令：launcher -> 子进程 (LauncherCommand)
# ==========================================

class StopCommand(BaseModel, frozen=True):
    """通知子进程退出主循环、Flush 数据库并销毁 Actor"""
    type: Literal['stop'] = 'stop'


class SetAutopilotCommand(BaseModel, frozen=True):
    """由 launcher 远程切换主车自动驾驶状态"""
    type: Literal['set_autopilot'] = 'set_autopilot'
    enabled: bool


class SetTakeoverCommand(BaseModel, frozen=True):
    """由 launcher 事件引擎或操作者远程触发/解除接管请求"""
    type: Literal['set_takeover'] = 'set_takeover'
    enabled: bool


class SetWeatherCommand(BaseModel, frozen=True):
    """由 launcher 运行期动态切换天气"""
    type: Literal['set_weather'] = 'set_weather'
    weather: WeatherConfig


class UpdateCameraCommand(BaseModel, frozen=True):
    """由 launcher 实时调整任一车载相机的安装位姿与视野"""
    type: Literal['update_camera'] = 'update_camera'
    camera_name: Literal['front', 'rear_top', 'rear_left', 'rear_right'] = 'front'
    mount: CameraMountConfig


class SetRearviewCommand(BaseModel, frozen=True):
    """由 launcher 远程显隐三路后视镜画面"""
    type: Literal['set_rearview'] = 'set_rearview'
    enabled: bool


LauncherCommand = Annotated[
    StopCommand
    | SetAutopilotCommand
    | SetTakeoverCommand
    | SetWeatherCommand
    | UpdateCameraCommand
    | SetRearviewCommand,
    Field(discriminator='type'),
]
```

> 命令与事件的区别：`XxxCommand` 表示要求子进程执行某个操作，由 `launcher` 发出。`ExperimentEvent`（`XxxEvent`）表示某个操作已经在子进程中执行生效，由实际执行它的进程在应用之后上报，只记录，不下发。例如 `launcher` 发出 `SetAutopilotCommand`，`simulator` 切换成功后上报 `ToggleAutopilotEvent(source='launcher')`。命令本身不写入事件表，事件表只记录实际发生过的事。

## 模拟器运行时状态（`simulator/state.py`）

为了兼顾 CARLA C++ 向量计算的性能与静态类型检查（`ty`），将模拟器内部状态与数据库持久化行解耦：

1. 直接持有 CARLA C++ 对象完成几何运算：
   `RuntimeFrameData` 在 `simulator` 进程内部直接保存 `carla.Vector3D`、`carla.Transform`、`carla.Waypoint | None` 等 C++ 绑定对象。计算车速标量（`velocity.length()`）、计算车道横向偏移（`road_direction.cross(location_vector)` 与 `location.distance_2d(...)`）、计算碰撞冲量强度（`collision_impulse.length()`）均直接调用 C++ 方法。
2. 移除全局车辆轮询：
   `simulator` 只采集与控制主车（Ego Vehicle）自身的状态，不再每帧调用 `world.get_actors().filter('vehicle.*')` 统计全图或附近背景车数量（多车状态维护归属后续的 `launcher` / `traffic` 模块）。
3. 相机画面直接保存 `carla.Image` / `pygame.Surface`：
   不再预先分配 `(W, H, 3)` 的 `np.ndarray` 零矩阵，传感器回调直接缓存最新到达的传感器帧对象，渲染时通过 `pygame.image.frombuffer(image.raw_data, (w, h), 'BGRA')` 映射上屏。
4. 显式投影方法：
   `RuntimeFrameData` 提供两个无反射的显式转换方法：
   - `to_data_row(session_id: str) -> DataRow`：将当前帧的 C++ 对象属性提取为扁平标量结构，送入 `storage` 写入队列。
   - `to_telemetry_snapshot(seq: int) -> TelemetrySnapshotEvent`：构造最新的遥测快照放入 WebSocket 发送单槽。

## 数据库表与行模型（`storage/models.py`，`SCHEMA_VERSION = 5`）

`storage` 层不导入 `carla`，只定义扁平行数据类与对应的 SQLite 表结构：

### 5.1 会话元数据表（`session`）

```python
from dataclasses import dataclass
from enum import StrEnum


class SessionStatus(StrEnum):
    RUNNING = 'running'
    COMMITTED = 'committed'
    ABORTED = 'aborted'


@dataclass(slots=True, frozen=True)
class SessionRow:
    session_id: str                 # PRIMARY KEY，格式如 '20261113_143022_a1b2'
    status: SessionStatus           # 'running' | 'committed' | 'aborted'
    started_at: float               # 实验启动时间戳 time.time()
    finished_at: float | None       # 结束时间戳，运行中为 None
    app_version: str                # 应用版本号
    schema_version: int             # 数据库 Schema 版本号 (5)
    map_name: str                   # 地图名称
    ego_actor_id: int | None        # 主车在 CARLA 中的 actor.id，就绪后回填
    ego_role_name: str              # 主车 role_name（默认 'hero'）
    ego_type_id: str | None         # 实际生成的车辆蓝图 ID，就绪后回填
    subject_id: str                 # 被试编号，可为空字符串
    run_config_json: str            # 完整 RunConfig 的 JSON 文本快照
    note: str                       # 实验备注
```

### 5.2 主车与传感器帧数据表（`data`）

建立联合索引 `idx_data_session_frame ON data (session_id, frame_no)`，所有速度单位统一为 `m/s`：

```python
@dataclass(slots=True, frozen=True)
class DataRow:
    session_id: str
    # 帧与时间信息
    frame_no: int
    timestamp: float
    elapsed_seconds: float
    server_fps: float
    simulator_fps: float
    # 运动与位姿 (速度单位: m/s, 位置单位: m, 旋转单位: deg)
    velocity_x: float
    velocity_y: float
    velocity_z: float
    speed: float
    location_x: float
    location_y: float
    location_z: float
    rotation_pitch: float
    rotation_yaw: float
    rotation_roll: float
    # 车辆控制与驾驶模式
    throttle: float
    steer: float
    brake: float
    reverse: bool
    hand_brake: bool
    manual_gear_shift: bool
    gear: int
    autopilot: bool
    takeover: bool
    # 传感器数据 (IMU / GNSS / 碰撞 / 压线)
    accelerometer_x: float
    accelerometer_y: float
    accelerometer_z: float
    gyroscope_x: float
    gyroscope_y: float
    gyroscope_z: float
    compass: float
    gnss_longitude: float
    gnss_latitude: float
    gnss_altitude: float
    collision_frame: int
    collision_actor: str      # 无碰撞为 ''，发生碰撞为 '{id}-{type_id}'
    collision_impulse_x: float
    collision_impulse_y: float
    collision_impulse_z: float
    invaded_lane_marking: str # 以 ';' 连接的压线类型字符串
    # 道路拓扑
    road_id: int
    lane_id: int
    lane_width: float
    lane_type: str
    road_direction_x: float
    road_direction_y: float
    road_direction_z: float
    lane_offset: float
    speed_limit: float        # 统一为 m/s（动态限速需将 CARLA 返回值除以 3.6）
```

### 5.3 事件表（`event`）

记录实验全生命周期中的事件（被试离散驾驶操作、操作者远程控制生效、自定义实验事件、子进程状态与启停生命周期）。

将所有事件共有的时间对齐维度（`frame_no`、`elapsed_seconds`、`timestamp`）与分类维度（`kind`、`name`、`source`）拆为独立表列，同时用 `payload_json` 存储结构化 JSON 数据：

```python
@dataclass(slots=True, frozen=True)
class EventRow:
    session_id: str
    frame_no: int | None            # 世界帧号（与 data.frame_no 对齐；launcher 自身启停事件为 None）
    elapsed_seconds: float | None   # 实验内经过秒数（与 data.elapsed_seconds 对齐）
    timestamp: float                # 墙上时间 time.time()
    kind: str                       # EventKind 取值 ('operator_action' | 'worker_status' | 'run_lifecycle' | 'custom_event')
    name: str                       # 具体事件名称，如 'toggle_takeover', 'set_weather', 'session_start'
    source: str                     # 触发来源：'wheel' | 'keyboard' | 'launcher' | 'system'
    payload_json: str               # 结构化事件负载的 JSON 文本
```

建立联合索引 `idx_event_session_frame ON event (session_id, frame_no)` 与 `idx_event_session_time ON event (session_id, timestamp)`。

> 关于背景交通流表（`traffic`，计划中）：
> 当前阶段不实现交通流，`src/drisca/traffic/` 只保留占位包。交通流表的结构待交通流模块设计定稿后，按 `(session_id, frame_no, vehicle_id)` 加入 `TrafficRow`，速度单位同样统一为 `m/s`。
