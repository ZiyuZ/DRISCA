"""数据库行模型。"""

from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = 1


class SessionStatus(StrEnum):
    RUNNING = 'running'
    COMMITTED = 'committed'
    ABORTED = 'aborted'


@dataclass(slots=True, frozen=True)
class SessionRow:
    session_id: str  # PRIMARY KEY，格式如 '20261113_143022_a1b2'
    status: SessionStatus  # 'running' | 'committed' | 'aborted'
    started_at: float  # 实验启动时间戳 time.time()
    finished_at: float | None  # 结束时间戳，运行中为 None
    app_version: str  # 应用版本号
    schema_version: int  # 数据库 Schema 版本号，由 storage 维护
    map_name: str  # 地图名称
    ego_actor_id: int | None  # 主车在 CARLA 中的 actor.id，就绪后回填
    ego_role_name: str  # 主车 role_name（默认 'hero'）
    ego_type_id: str | None  # 实际生成的车辆蓝图 ID，就绪后回填
    subject_id: str  # 被试编号，可为空字符串
    run_config_json: str  # 完整 RunConfig 的 JSON 文本快照
    note: str  # 实验备注


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
    speed_limit: float  # 统一为 m/s（动态限速需将 CARLA 返回值除以 3.6）


@dataclass(slots=True, frozen=True)
class EventRow:
    session_id: str
    command_id: str | None  # 远程操作关联的命令编号
    frame_no: int | None  # 世界帧号（与 data.frame_no 对齐；launcher 自身启停事件为 None）
    timestamp: float  # 事件发生时的 time.time() 时间戳
    kind: str  # EventKind 分类
    name: str  # 具体事件名称，如 'toggle_takeover', 'set_weather', 'session_start'
    source: str  # 触发来源：'wheel' | 'keyboard' | 'launcher' | 'sensor' | 'system'
    payload_json: str  # 结构化事件负载的 JSON 文本


SCHEMA_SQL = """
CREATE TABLE session (
    session_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    app_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    map_name TEXT NOT NULL,
    ego_actor_id INTEGER,
    ego_role_name TEXT NOT NULL,
    ego_type_id TEXT,
    subject_id TEXT NOT NULL,
    run_config_json TEXT NOT NULL,
    note TEXT NOT NULL,
    PRIMARY KEY (session_id)
);

CREATE TABLE data (
    session_id TEXT NOT NULL,
    frame_no INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    server_fps REAL NOT NULL,
    simulator_fps REAL NOT NULL,
    velocity_x REAL NOT NULL,
    velocity_y REAL NOT NULL,
    velocity_z REAL NOT NULL,
    speed REAL NOT NULL,
    location_x REAL NOT NULL,
    location_y REAL NOT NULL,
    location_z REAL NOT NULL,
    rotation_pitch REAL NOT NULL,
    rotation_yaw REAL NOT NULL,
    rotation_roll REAL NOT NULL,
    input_throttle REAL NOT NULL,
    input_steer REAL NOT NULL,
    input_brake REAL NOT NULL,
    throttle REAL NOT NULL,
    steer REAL NOT NULL,
    brake REAL NOT NULL,
    reverse INTEGER NOT NULL,
    hand_brake INTEGER NOT NULL,
    manual_gear_shift INTEGER NOT NULL,
    gear INTEGER NOT NULL,
    control_mode TEXT NOT NULL,
    takeover_requested INTEGER NOT NULL,
    accelerometer_x REAL NOT NULL,
    accelerometer_y REAL NOT NULL,
    accelerometer_z REAL NOT NULL,
    gyroscope_x REAL NOT NULL,
    gyroscope_y REAL NOT NULL,
    gyroscope_z REAL NOT NULL,
    compass REAL NOT NULL,
    gnss_longitude REAL NOT NULL,
    gnss_latitude REAL NOT NULL,
    gnss_altitude REAL NOT NULL,
    road_id INTEGER NOT NULL,
    lane_id INTEGER NOT NULL,
    lane_width REAL NOT NULL,
    lane_type TEXT NOT NULL,
    road_direction_x REAL NOT NULL,
    road_direction_y REAL NOT NULL,
    road_direction_z REAL NOT NULL,
    lane_offset REAL NOT NULL,
    speed_limit REAL NOT NULL,
    PRIMARY KEY (session_id, frame_no)
);

CREATE TABLE event (
    session_id TEXT NOT NULL,
    command_id TEXT,
    frame_no INTEGER,
    timestamp REAL NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_data_session_frame ON data (session_id, frame_no);

CREATE INDEX idx_event_session_frame ON event (session_id, frame_no);

CREATE INDEX idx_event_session_time ON event (session_id, timestamp);
"""
