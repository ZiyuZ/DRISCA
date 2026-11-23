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


class GlobalWeatherState(BaseModel, frozen=True):
    weather: GlobalWeather


class EnvironmentRegionState(BaseModel, frozen=True):
    center_m: tuple[float, float, float]
    radius_m: float
    weather: RegionWeatherState  # 当前仅为 fog.density


EnvironmentState = GlobalWeatherState | EnvironmentRegionState


class EnvironmentAppliedPayload(BaseModel, frozen=True):
    region_id: int | None  # 全局为 None，局部为区域编号
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: Literal['apply', 'update', 'create', 'delete']
    previous: EnvironmentState
    transition_seconds: float


class EnvironmentCompletedPayload(BaseModel, frozen=True):
    region_id: int | None
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: Literal['apply', 'update', 'create', 'delete']


class EnvironmentReplacedPayload(BaseModel, frozen=True):
    region_id: int | None
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: Literal['apply', 'update', 'create', 'delete']  # 被替换的旧操作
    new_request_id: int | None = None
    new_operation_index: int | None = None
    new_operation: Literal['apply', 'update', 'create', 'delete'] | None = None
    new_target: EnvironmentState | None = None
    reason: str | None = None  # 实验停止时为 session_ended，此时不带 new_* 字段


class NativeEventRef(BaseModel, frozen=True):
    event_id: int
    world_id: int
    simulation_time_us: int
    request_id: int | None = None
    operation_index: int | None = None


class ExperimentEventBase(BaseModel, frozen=True):
    """实验事件公共基类，描述已经发生的操作或状态变化，开启保存时写入 event 表。
    由实际执行该操作的进程上报，launcher 统一处理事件，同一个操作只记录一次。"""
    type: Literal['experiment_event'] = 'experiment_event'
    kind: EventKind
    source: Literal['wheel', 'keyboard', 'launcher', 'model', 'sensor', 'system']
    frame_no: int | None = None
    timestamp: float
    command_id: str | None = None
    native: NativeEventRef | None = None


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
    | UpdateLayoutEvent
    | UpdateCameraEvent
    | EnvironmentAppliedEvent
    | EnvironmentCompletedEvent
    | EnvironmentReplacedEvent
    | CollisionEvent
    | LaneInvasionEvent
    | CustomExperimentEvent,
    Field(discriminator='name'),
]
```

## 管理端事件

实验开始、结束、子进程状态和操作者打点由管理端生成，开启保存时写入 event 表。`kind` 使用对应的生命周期、进程状态或自定义类别，`name` 保存具体名称。打点负载保存标签和备注。语音播放沿用触发它的实验事件及时间戳，提示内容放入该事件的负载；单独播放语音时使用一条自定义事件。

失败收尾时 `session_aborted` 的负载带有 `error` 字段，取 worker 通过日志通道发送的“驾驶端失败：”错误消息，没有时使用 Launcher 侧的错误文本。该字段记录失败原因，worker 的完整堆栈仍只在实时日志中查看。

管理端事件保存发生时的时间戳，取得最新遥测时将其世界帧一并保存。初始化和收尾阶段的帧号可为空。碰撞与压线事件的详情分别保存对象、冲量和车道线数组，界面据此更新最近一次提示。

具体事件类直接继承 `ExperimentEventBase`。`name` 表示具体事件类型，`kind` 用于跨事件类型筛选，例如一起查看传感器事件或运行状态事件。负载模型通过字段组合使用。

## 原生事件关联与控制请求

原生事件通过 worker 映射后由 Launcher 统一持久化。native 对象保留 event_id、world_id、simulation_time_us、request_id 与 operation_index，写入 event.payload_json 的 native 键。原生 wall_time_us 转为事件 timestamp；frame_no 保留发生帧。actor_id、revision、scope 与前后状态保存在各自载荷内。

| 事件 | 含义与载荷 |
| --- | --- |
| driver_request | 驾驶人请求切换自动化，action 为 toggle_automation；请求与实际应用分别记录 |
| control_mode_changed | 实际控制来源变化，保留 actor_id、previous_mode、mode、controller、revision |
| toggle_takeover | 原生主动接管已生效，保留 enabled、actor_id、revision |
| traffic_light_state_changed | 单灯状态变化，保留实际灯、控制器、组和前后状态 |
| traffic_controller_timing_changed | 控制器配时变化，保留实际作用域和前后时长 |
| traffic_light_group_frozen | 灯组冻结变化，保留组、控制器和冻结前后状态 |
| traffic_light_group_reset | 灯组重置，保留受影响身份与冻结前后状态 |
| traffic_light_all_frozen | 全部灯组冻结，保留受影响组、控制器和各组前后状态 |
| environment_applied | 环境命令开始生效，保留 region_id、current/target、previous、operation、transition_seconds |
| environment_completed | 过渡完成，保留 region_id、current/target 和原 operation |
| environment_replaced | 新命令中断未完成过渡，保留旧 current/target/operation 和新请求关联、操作与目标 |

环境事件的全局 region_id 为 null，局部为数字。全局实体载荷为 `{weather: ...}`，局部实体为 `{center_m, radius_m, weather: {fog: {density}}}`。零时长操作只产生 applied。实验停止时被中断的全局过渡产生 reason=session_ended 的 replaced，不带 new_request_id、new_operation_index、new_operation 与 new_target。完成和替换事件可能跨 exchange 到达，worker 按请求关联维护实验内未完成的环境操作，终态时释放；不建立通用恢复框架。

worker 对空 session_id 的事件只保留本次准备区域的事件，按 worker 创建时返回的 region_id 精确识别；这些事件保留原生 event_id、帧、仿真时间与请求关联，不补写 session_id。其余空 session 的管理端旧事件不写入本次实验。实验开始前的初始天气与区域配置仍保存在 RunConfig。环境事件只有来源为当前控制 worker（model）时才与本 worker 的 command_id 和未完成操作关联；request_id 按连接递增，不能跨连接视为唯一。管理连接发起的环境事件照常记录，但不匹配本 worker 指令。键盘、传感器等既有事件的关联语义不变。

操作者命令通过本次 exchange 的 request_id 与 operation_index 回填 command_id；只有实际命中命令关联时才将 worker 的 model 来源映射为 launcher。键盘和传感器保留原始来源。驾驶人按 `P` 键触发 `driver_request` 后，由 `simulator` 切换 `external/python` 与 `manual/human` 控制模式并记录 `control_mode_changed`。正常自动相位由帧快照记录，操作者信号调整按一次操作记录一次事件。
