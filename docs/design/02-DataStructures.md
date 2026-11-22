# 运行状态与实验数据

本文说明逐帧采集的运行状态和 SQLite 数据记录。配置定义见[配置模型](./08-ConfigurationModels.md)，消息定义见[进程通信](./07-Protocol.md)，函数接口见[模块职责与 API 规范](./03-ModuleAPI.md)。

## 设计准则与类型约定

1. Python 3.14 类型特性：
   - 枚举统一使用标准库 `enum.StrEnum` 与 `enum.IntEnum`（可直接用于 JSON 序列化与 SQLite 参数绑定）。
   - 跨进程配置与 WebSocket 消息统一使用 `pydantic.BaseModel(frozen=True)`。
   - 高频创建的数据库行结构统一使用 `@dataclass(slots=True, frozen=True)`，避免每帧构造时的校验开销与字典分配。
2. 物理量单位统一：
   - 内部计算与数据库持久化中的所有速度量统一采用国际单位制 `m/s`（米/秒），角度统一指明弧度（`rad`）或角度（`deg`）。
   - CARLA API 单位转换注意：CARLA 的 `vehicle.get_speed_limit()` 返回值单位为 `km/h`，在开启 `dynamic_speed_limit` 时必须除以 `3.6` 转换为 `m/s` 后再存入运行时状态与数据库。
   - `km/h` 仅在面向人的展示边界（如平板 HUD、桌面端数据面板与预设输入）由前端或视图层按 `× 3.6` 转换。
3. C++ 计算对象与持久化标量的边界分离：
   - 在 `simulator` 内部，运行时状态直接持有 CARLA 的 C++ 对象（`carla.Vector3D`、`carla.Transform`、`carla.Location`、`carla.Waypoint`），直接调用 C++ 绑定的 `.length()`、`.cross()`、`.distance_2d()` 完成几何计算。
   - 在进入 `storage` 写入队列时，通过显式的纯函数投影为只含基础标量（`int / float / str / bool`）的 `FrameRow`。

## 采样与时间

每个世界帧采样一次。`frame_no` 使用 CARLA 世界帧号，`timestamp` 使用采样或事件发生时的 `time.time()` 时间戳。帧与事件通过帧号关联，也可按时间戳查询。会话开始和结束使用相同的时间戳形式，界面按本地时区显示。

驾驶人输入和车辆实际控制分别保存，自动驾驶期间继续记录输入。碰撞、压线和其他离散事件共用 event 表，按名称与类别筛选。

## 模拟器运行时状态（`simulator/state.py`）

为了兼顾 CARLA C++ 向量计算的性能与静态类型检查（`ty`），将模拟器内部状态与数据库持久化行解耦：

1. 直接持有 CARLA C++ 对象完成几何运算：
   `DrivingState` 在 `simulator` 进程内部直接保存 `carla.Vector3D`、`carla.Transform`、`carla.Waypoint | None` 等 C++ 绑定对象。计算车速标量（`velocity.length()`）、计算车道横向偏移（`road_direction.cross(location_vector)` 与 `location.distance_2d(...)`）、计算碰撞冲量强度（`collision_impulse.length()`）均直接调用 C++ 方法。
2. 移除全局车辆轮询：
   `simulator` 采集与控制主车（Ego Vehicle）自身的状态。多车状态维护归属后续的 `traffic` 模块。
3. 原生画面与研究数据分别处理：
   Unreal 直接渲染主视图与三路后视镜，PostPhysics 汇总最新驾驶状态。Python 按世界帧号读取新状态，结合道路与 IMU/GNSS 数据生成记录；相机图像留在原生渲染链路。
4. 显式投影方法：
   `DrivingState` 提供两个无反射的显式转换方法：
   - `to_frame_row(session_id: str) -> FrameRow`：将当前帧的 C++ 对象属性提取为扁平标量结构，送入 `storage` 写入队列。
   - `to_telemetry_snapshot(seq: int) -> TelemetrySnapshotEvent`：构造最新的遥测快照放入 WebSocket 发送单槽。

## 数据库表与行模型（`storage/models.py`）

`storage` 层不导入 `carla`，只定义扁平行数据类与对应的 SQLite 表结构：

### 1. 会话元数据表（`session`）

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
    schema_version: int             # 数据库 Schema 版本号，由 storage 维护
    map_name: str                   # 地图名称
    ego_actor_id: int | None        # 主车在 CARLA 中的 actor.id，就绪后回填
    ego_role_name: str              # 主车 role_name（默认 'hero'）
    ego_type_id: str | None         # 实际生成的车辆蓝图 ID，就绪后回填
    subject_id: str                 # 被试编号，可为空字符串
    run_config_json: str            # 完整 RunConfig 的 JSON 文本快照
    note: str                       # 实验备注
```

### 2. 主车与传感器帧数据表（`data`）

以 `(session_id, frame_no)` 为联合主键，并建立联合索引 `idx_data_session_frame ON data (session_id, frame_no)`，所有速度单位统一为 `m/s`：

```python
@dataclass(slots=True, frozen=True)
class FrameRow:
    session_id: str
    # 帧与时间信息
    frame_no: int
    timestamp: float
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
    # 驾驶人输入，自动驾驶期间照常记录
    input_throttle: float
    input_steer: float
    input_brake: float
    # 车辆实际控制与控制权
    throttle: float
    steer: float
    brake: float
    reverse: bool
    hand_brake: bool
    manual_gear_shift: bool
    gear: int
    control_mode: str  # manual / autopilot
    takeover_requested: bool
    # 连续传感器数据 (IMU / GNSS)
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

### 3. 事件表（`event`）

记录实验全生命周期中的事件（被试离散驾驶操作、操作者远程控制生效、自定义实验事件、子进程状态与启停生命周期）。

将所有事件共有的时间对齐维度（`frame_no`、`timestamp`）与分类维度（`kind`、`name`、`source`）拆为独立表列，同时用 `payload_json` 存储结构化 JSON 数据：

```python
@dataclass(slots=True, frozen=True)
class EventRow:
    session_id: str
    command_id: str | None          # 远程操作关联的命令编号
    frame_no: int | None            # 世界帧号（与 data.frame_no 对齐；launcher 自身启停事件为 None）
    timestamp: float               # 事件发生时的 time.time() 时间戳
    kind: str                       # EventKind 取值 ('operator_action' | 'worker_status' | 'run_lifecycle' | 'sensor' | 'custom_event')
    name: str                       # 具体事件名称，如 'toggle_takeover', 'set_weather', 'session_start'
    source: str                     # 触发来源：'wheel' | 'keyboard' | 'launcher' | 'sensor' | 'system'
    payload_json: str               # 结构化事件负载的 JSON 文本
```

建立联合索引 `idx_event_session_frame ON event (session_id, frame_no)` 与 `idx_event_session_time ON event (session_id, timestamp)`。

> 关于背景交通流表（`traffic`，计划中）：
> 当前阶段 `src/drisca/traffic/` 保留占位包。交通流表的结构待交通流模块设计定稿后，按 `(session_id, frame_no, vehicle_id)` 加入 `TrafficRow`，速度单位同样统一为 `m/s`。

## 事件详情与导出

`collision` 保存对方 actor ID、蓝图类型和冲量三分量，`lane_invasion` 保存本次车道线类型数组。具体负载模型见[实验事件](./09-ExperimentEvents.md)。事件按时间戳与 SQLite 行顺序排列，按会话和世界帧查询。

保存数据开关控制整次运行的实验数据写入。开启时保存会话、帧数据、事件和启动配置，并按录像开关决定是否启用 CARLA Recorder。关闭时，数据库与 Recorder 保持关闭，数据面板、事件时间线和日志照常工作。运行配置传递文件在调试结束后删除。

## 批量导出

实验数据页默认显示最近 30 天的会话，表格内部滚动，支持勾选和选择当前筛选的全部会话。一次导出生成所选会话的 `sessions.csv`、`data.csv` 和 `events.csv`，各表通过 `session_id` 关联。`sessions.csv` 包含原有启动配置字段，CSV 沿用表字段名称和内部单位。文件保存到实验主机配置的导出目录，页面显示进度与完成路径。
