# 运行状态与实验数据

本文说明逐帧采集的运行状态和 SQLite 数据记录。配置定义见[配置模型](./08-ConfigurationModels.md)，消息定义见[进程通信](./07-Protocol.md)，函数接口见[模块职责与 API 规范](./03-ModuleAPI.md)。

## 类型、单位与边界

配置与跨进程消息采用冻结的 Pydantic 模型，数据库行采用 `@dataclass(slots=True, frozen=True)`。Python 状态使用普通数值、三元组与 NumPy 结构化数组，原生对象保留在 Unreal。

内部与落盘速度统一为 m/s，展示层乘以 3.6。原生接口在读取 CARLA 限速时将 km/h 转为 m/s。运动量在线使用 float32，时间使用 int64 微秒，帧号与身份使用整数。GNSS 经纬度同样使用 float32，几何分析使用米制世界坐标。

## 采样与时间

Unreal 在物理更新结束后形成完整世界快照。worker 以约 20 Hz exchange 取得新帧，按 frame_no 去重，每个采到的世界帧最多保存一行。数据 timestamp 来自原生 wall_time_us / 1e6；帧与事件保留实际采样时间和帧号。会话时间由 Launcher 记录，界面按本地时区显示。

位姿、速度和实际控制来自同一次运动采样；IMU/GNSS 的最新样本分别保留原始采样帧和仿真时间。Python 运行快照保留这些元信息，当前 FrameRow 列保持既有结构。人工输入与车辆实际控制分别保存。

## 模拟器运行时状态（`simulator/state.py`）

`project_snapshot()` 查找主车车辆记录与研究记录，校验 actor_id、控制来源、研究有效位及有限数值，构造数值化 `DrivingState`。车辆记录提供运动与实际控制，研究记录提供人工输入、传感器和道路细节。车速在 Python 根据速度三元组计算，车道偏移由原生道路计算提供。

控制来源位 0 为 manual/human，2 为 external/python；主车遇到其他来源按契约错误处理。control_mode 保留业务层 manual/autopilot 枚举，external 对应模型驾驶；具体原生来源另由遥测 control_source 展示。当前自研交通算法尚未实现。

`takeover_requested` 来自研究记录 input_flags bit3，表示采样期间的主动接管动作。碰撞强度沿用最近一次碰撞冲量模长，压线字符串由最新 lane_invasion 事件恢复。离散事件完整保存到 event 表。

`to_frame_row(session_id)` 将状态投影为存储标量，`to_telemetry_snapshot(seq)` 构造界面快照。两条路径保持独立，Unreal 画面与后视镜始终在原生侧渲染。

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
    name: str                       # 具体事件名称，如 'toggle_takeover', 'environment_applied', 'session_start'
    source: str                     # 触发来源：'wheel' | 'keyboard' | 'launcher' | 'model' | 'sensor' | 'system'
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
