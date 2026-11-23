# 进程间通信协议

本文保留上下行消息的字段定义。配置类型见[配置模型](./08-ConfigurationModels.md)，入库字段见[运行状态与实验数据](./02-DataStructures.md)，离散操作与传感器事件的完整类型见[实验事件](./09-ExperimentEvents.md)。

`simulator` 与 `launcher` 之间通过本地 WebSocket 传输 Pydantic JSON 消息，利用 `discriminator` 实现多态反序列化。

其中 `TelemetrySnapshotEvent`（遥测快照）包含 `simulator` 的实时运行状态，由 `launcher` 用于以下两处：

1. 平板 HUD：`launcher` 从快照中取出子集（车速、限速、挡位、转向、驾驶模式），通过 SSE 推送给平板。
2. `launcher` 数据面板与调试面板：以 20~30 Hz 显示遥测指标与控制条，并在方案配置页支持拾取快照里的主车当前坐标作为 `spawn_point`。

```python
from enum import StrEnum
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


class ControlMode(StrEnum):
    MANUAL = 'manual'
    AUTOPILOT = 'autopilot'


# 上行消息：子进程 -> launcher (WorkerEvent)

class WorkerReadyEvent(BaseModel, frozen=True):
    """主车与传感器在 CARLA 中生成完毕后立刻上报，用于回填 session 表"""
    type: Literal['ready'] = 'ready'
    role: WorkerRole = WorkerRole.SIMULATOR
    ego_actor_id: int
    ego_type_id: str
    vehicle_box: dict[str, dict[str, float]]  # 包围盒 location、extent 与 rotation，供相机示意使用


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
    input_throttle: float = 0.0
    input_steer: float = 0.0
    input_brake: float = 0.0
    speed_mps: float = 0.0
    speed_limit_mps: float = 0.0
    gear: int = 0               # -1: R, 0: N, >=1: D 挡位
    steer: float = 0.0          # [-1.0, 1.0]
    throttle: float = 0.0       # [0.0, 1.0]
    brake: float = 0.0          # [0.0, 1.0]
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
    WorkerReadyEvent
    | WorkerStatusEvent
    | LogEvent
    | ExperimentEvent
    | TelemetrySnapshotEvent,
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
```

> 命令与事件的区别：`XxxCommand` 表示要求子进程执行某个操作，由 `launcher` 发出。`ExperimentEvent`（`XxxEvent`）表示某个操作已经在子进程中执行生效，由实际执行它的进程在应用之后上报并记录。例如 Launcher 发出天气命令，原生应用后产生 set_weather 事件，由 worker 回填来源 command_id 并上报。事件表记录实际生效的操作，界面依据事件和最新遥测更新。

## 命令错误

命令沿用 `command_id`。成功应用的状态变化通过现有实验事件上报，事件携带来源命令编号。执行失败时记录一条 ERROR 日志，在已有 `LogEvent` 中附上 `command_id` 和错误说明。

命令按失败后是否影响实验继续进行处理，分类在执行处确定。

| 操作 | 失败处理 |
| --- | --- |
| 相机微调、后视镜显示等调试操作 | 记录错误，继续实验 |
| 接管、控制权切换等决定实验过程的操作 | 记录错误并停止实验 |
| 停止命令 | 按停机超时流程回收进程 |

天气切换默认按普通操作处理；某次实验要求该操作必须成功时，在该实验的执行处明确失败后停止。

## 接管与事件

`control_mode` 表示手动或自动驾驶，`takeover_requested` 表示当前采样期间的主动接管动作。操作者可发出接管请求。被试执行接管动作时，直接关闭自动驾驶并进入人工驾驶，同时结束接管提示。键盘与方向盘的 `takeover` 绑定执行这一动作。

碰撞与压线回调每发生一次生成一条事件，同一世界帧可有多条。事件携带发生时的世界帧号和时间戳。操作者打点使用实际时间戳并关联最新遥测帧。管理端收到事件后更新面板，开启保存时写入 event 表。

相机命令中的 `CameraConfig.x/y/z` 使用车辆包围盒比例，由 Unreal 根据主车原生包围盒转换为实际安装位置。管理端指令库中的按钮定义与下行命令分别由 launcher 编排和 core 协议表达。

## 原生接口与新增事件

worker 到 Launcher 保持本地 JSON WebSocket；Launcher/worker 到 Unreal 使用独立原生连接，契约见[原生 WebSocket 接口](./11-NativeAPI.md)。当前启用自动驾驶的命令明确拒绝并保留人工实验，控制连接或研究数据错误按实验失败处理。

ExperimentEventBase.source 增加 model，区分研究模型与操作者操作。原生事件带 native 对象：event_id、world_id、simulation_time_us、request_id、operation_index；Launcher 将其写入已有 payload_json 的 native 键。command_id 仍用于 Launcher 命令关联。遥测增加 control_source，保留业务层 control_mode。

driver_request 记录驾驶人的自动化切换请求；control_mode_changed 记录实际来源变化；toggle_takeover 载荷包含 enabled、actor_id 与 revision。信号操作新增 traffic_light_state_changed、traffic_controller_timing_changed、traffic_light_group_frozen、traffic_light_group_reset、traffic_light_all_frozen，保留实际作用域与前后值。模型定义以 core/protocol.py 为准，事件含义见[实验事件](./09-ExperimentEvents.md)。
