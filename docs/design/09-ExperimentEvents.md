# 实验事件

碰撞、压线、驾驶操作、操作者干预和运行状态共用事件表，通过类别和名称筛选。关闭保存时，事件仅供本次运行的界面使用。以下模型定义在 `core/protocol.py`，通过[进程通信](./07-Protocol.md)上报，数据库行见[运行状态与实验数据](./02-DataStructures.md)。

事件在操作实际生效或传感器回调发生时生成，保存世界帧与时间戳。连续控制通过逐帧数据保存；一次离散操作记录一次，同帧发生的多次碰撞分别记录。命令来源通过 `command_id` 关联。

## 类型定义

```python
class EventKind(StrEnum):
    OPERATOR_ACTION = 'operator_action'  # 离散操作：自动驾驶、接管、倒挡、档位、手刹、车灯、后视镜显隐、镜头调整、天气等
    WORKER_STATUS = 'worker_status'      # 子进程就绪与状态变化（由 launcher 记录）
    RUN_LIFECYCLE = 'run_lifecycle'      # 实验开始、结束请求、子进程退出（由 launcher 记录）
    SENSOR = 'sensor'                  # 碰撞、压线
    CUSTOM_EVENT = 'custom_event'        # 操作者自定义打点记录


class EnabledPayload(BaseModel, frozen=True):
    enabled: bool


class UpdateCameraPayload(BaseModel, frozen=True):
    camera_name: Literal['front', 'rear_top', 'rear_left', 'rear_right']
    mount: CameraConfig   # 调整后的安装位姿与视野


class SetWeatherPayload(BaseModel, frozen=True):
    weather: WeatherConfig


class ExperimentEventBase(BaseModel, frozen=True):
    """实验事件公共基类，描述已经发生的操作或状态变化，开启保存时写入 event 表。
    由实际执行该操作的进程上报，launcher 统一处理事件，同一个操作只记录一次。"""
    type: Literal['experiment_event'] = 'experiment_event'
    kind: EventKind
    source: Literal['wheel', 'keyboard', 'launcher', 'sensor', 'system']
    frame_no: int | None = None
    timestamp: float
    command_id: str | None = None


class ToggleAutopilotEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_autopilot'] = 'toggle_autopilot'
    payload: EnabledPayload


class ToggleTakeoverEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['toggle_takeover'] = 'toggle_takeover'
    payload: EnabledPayload


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


class SetRearviewEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['set_rearview'] = 'set_rearview'
    payload: EnabledPayload


class UpdateCameraEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['update_camera'] = 'update_camera'
    payload: UpdateCameraPayload


class SetWeatherEvent(ExperimentEventBase, frozen=True):
    kind: Literal[EventKind.OPERATOR_ACTION] = EventKind.OPERATOR_ACTION
    name: Literal['set_weather'] = 'set_weather'
    payload: SetWeatherPayload


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
    | CollisionEvent
    | LaneInvasionEvent
    | CustomExperimentEvent,
    Field(discriminator='name'),
]
```

## 管理端事件

实验开始、结束、子进程状态和操作者打点由管理端生成，开启保存时写入 event 表。`kind` 使用对应的生命周期、进程状态或自定义类别，`name` 保存具体名称。打点负载保存标签和备注。语音播放沿用触发它的实验事件及时间戳，提示内容放入该事件的负载；单独播放语音时使用一条自定义事件。

管理端事件保存发生时的时间戳，取得最新遥测时将其世界帧一并保存。初始化和收尾阶段的帧号可为空。碰撞与压线事件的详情分别保存对象、冲量和车道线数组，界面据此更新最近一次提示。

具体事件类直接继承 `ExperimentEventBase`。`name` 表示具体事件类型，`kind` 用于跨事件类型筛选，例如一起查看传感器事件或运行状态事件。负载模型通过字段组合使用。
