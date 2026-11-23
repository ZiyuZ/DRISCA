"""运行状态与持久化、遥测投影。"""

from dataclasses import dataclass

import numpy as np

from drisca.core.protocol import ControlMode, TelemetrySnapshotEvent
from drisca.core.snapshot import (
    CONTROL_SOURCE_EXTERNAL_PYTHON,
    CONTROL_SOURCE_MANUAL_HUMAN,
    INPUT_FLAG_TAKEOVER,
    RESEARCH_FLOAT_FIELDS,
    RESEARCH_VALID_READY,
    RESEARCH_VALID_ROAD,
    RESEARCH_VALID_VIEW_ACTIVE,
    VEHICLE_FLAG_HAND_BRAKE,
    VEHICLE_FLAG_MANUAL_GEAR_SHIFT,
    VEHICLE_FLAG_REVERSE,
    VEHICLE_FLOAT_FIELDS,
    Snapshot,
    control_source,
    control_source_name,
    lane_type_name,
    require_finite,
)
from drisca.storage.models import FrameRow

Vec3 = tuple[float, float, float]


def _vec3(record: np.void, name: str) -> Vec3:
    values = record[name]
    return (float(values[0]), float(values[1]), float(values[2]))


@dataclass(slots=True)
class DrivingState:
    frame_no: int
    timestamp: float
    server_fps: float
    simulator_fps: float
    velocity: Vec3
    location: Vec3
    rotation: Vec3
    input_throttle: float
    input_steer: float
    input_brake: float
    throttle: float
    steer: float
    brake: float
    reverse: bool
    hand_brake: bool
    manual_gear_shift: bool
    gear: int
    control_mode: ControlMode
    control_source: str
    takeover_requested: bool
    accelerometer: Vec3
    gyroscope: Vec3
    compass: float
    longitude: float
    latitude: float
    altitude: float
    road_id: int
    lane_id: int
    lane_width: float
    lane_type: str
    road_direction: Vec3
    lane_offset: float
    speed_limit: float
    collision_intensity: float = 0.0
    invaded_lane_marking: str = ''

    @property
    def speed(self) -> float:
        x, y, z = self.velocity
        return (x * x + y * y + z * z) ** 0.5

    def to_frame_row(self, session_id: str) -> FrameRow:
        return FrameRow(
            session_id=session_id,
            frame_no=self.frame_no,
            timestamp=self.timestamp,
            server_fps=self.server_fps,
            simulator_fps=self.simulator_fps,
            velocity_x=self.velocity[0],
            velocity_y=self.velocity[1],
            velocity_z=self.velocity[2],
            speed=self.speed,
            location_x=self.location[0],
            location_y=self.location[1],
            location_z=self.location[2],
            rotation_pitch=self.rotation[0],
            rotation_yaw=self.rotation[1],
            rotation_roll=self.rotation[2],
            input_throttle=self.input_throttle,
            input_steer=self.input_steer,
            input_brake=self.input_brake,
            throttle=self.throttle,
            steer=self.steer,
            brake=self.brake,
            reverse=self.reverse,
            hand_brake=self.hand_brake,
            manual_gear_shift=self.manual_gear_shift,
            gear=self.gear,
            control_mode=self.control_mode,
            takeover_requested=self.takeover_requested,
            accelerometer_x=self.accelerometer[0],
            accelerometer_y=self.accelerometer[1],
            accelerometer_z=self.accelerometer[2],
            gyroscope_x=self.gyroscope[0],
            gyroscope_y=self.gyroscope[1],
            gyroscope_z=self.gyroscope[2],
            compass=self.compass,
            gnss_longitude=self.longitude,
            gnss_latitude=self.latitude,
            gnss_altitude=self.altitude,
            road_id=self.road_id,
            lane_id=self.lane_id,
            lane_width=self.lane_width,
            lane_type=self.lane_type,
            road_direction_x=self.road_direction[0],
            road_direction_y=self.road_direction[1],
            road_direction_z=self.road_direction[2],
            lane_offset=self.lane_offset,
            speed_limit=self.speed_limit,
        )

    def to_telemetry_snapshot(self, seq: int) -> TelemetrySnapshotEvent:
        return TelemetrySnapshotEvent(
            seq=seq,
            timestamp=self.timestamp,
            frame_no=self.frame_no,
            server_fps=self.server_fps,
            simulator_fps=self.simulator_fps,
            control_mode=self.control_mode,
            control_source=self.control_source,
            input_throttle=self.input_throttle,
            input_steer=self.input_steer,
            input_brake=self.input_brake,
            speed_mps=self.speed,
            speed_limit_mps=self.speed_limit,
            gear=self.gear,
            steer=self.steer,
            throttle=self.throttle,
            brake=self.brake,
            reverse=self.reverse,
            hand_brake=self.hand_brake,
            manual_gear_shift=self.manual_gear_shift,
            takeover_requested=self.takeover_requested,
            location_x=self.location[0],
            location_y=self.location[1],
            location_z=self.location[2],
            rotation_pitch=self.rotation[0],
            rotation_yaw=self.rotation[1],
            rotation_roll=self.rotation[2],
            compass=self.compass,
            road_id=self.road_id,
            lane_id=self.lane_id,
            lane_offset=self.lane_offset,
            collision_intensity=self.collision_intensity,
            invaded_lane_marking=self.invaded_lane_marking,
        )


def research_ready(snapshot: Snapshot) -> bool:
    record = snapshot.research_record
    return record is not None and bool(int(record['validity_flags']) & RESEARCH_VALID_READY)


def project_snapshot(
    snapshot: Snapshot,
    *,
    ego_actor_id: int,
    dynamic_speed_limit: bool,
    default_speed_limit_mps: float,
    simulator_fps: float,
    invaded_lane_marking: str,
) -> DrivingState:
    """把一帧完整快照投影为主车运行状态，契约不一致时直接报错。"""
    index = snapshot.vehicle_index(ego_actor_id)
    if index is None:
        raise ValueError(f'快照中没有主车 {ego_actor_id}')
    vehicle = snapshot.vehicles[index]
    research = snapshot.research_record
    if research is None:
        raise ValueError('快照缺少主车研究记录')
    if int(research['actor_id']) != ego_actor_id:
        raise ValueError(f'研究记录主车 {int(research["actor_id"])} 与实验主车 {ego_actor_id} 不一致')
    require_finite(vehicle, VEHICLE_FLOAT_FIELDS, '主车记录')
    require_finite(research, RESEARCH_FLOAT_FIELDS, '主车研究记录')

    validity = int(research['validity_flags'])
    if not validity & RESEARCH_VALID_READY:
        raise ValueError('主车研究采集未就绪')
    if not validity & RESEARCH_VALID_VIEW_ACTIVE:
        raise ValueError('主车驾驶视图不在活动状态')
    if not validity & RESEARCH_VALID_ROAD:
        raise ValueError('主车位置没有对应道路')

    flags = int(vehicle['flags'])
    source = control_source(flags)
    if source not in (CONTROL_SOURCE_MANUAL_HUMAN, CONTROL_SOURCE_EXTERNAL_PYTHON):
        raise ValueError(f'主车控制来源非法：{control_source_name(source)}')
    control_mode = ControlMode.MANUAL if source == CONTROL_SOURCE_MANUAL_HUMAN else ControlMode.AUTOPILOT

    input_flags = int(research['input_flags'])
    speed_limit = float(vehicle['speed_limit_mps']) if dynamic_speed_limit else default_speed_limit_mps
    return DrivingState(
        frame_no=snapshot.frame_no,
        timestamp=snapshot.wall_time_us / 1e6,
        server_fps=1 / snapshot.delta_seconds if snapshot.delta_seconds > 0 else 0.0,
        simulator_fps=simulator_fps,
        velocity=_vec3(vehicle, 'velocity'),
        location=_vec3(vehicle, 'location'),
        rotation=_vec3(vehicle, 'rotation'),
        input_throttle=float(research['input_throttle']),
        input_steer=float(research['input_steer']),
        input_brake=float(research['input_brake']),
        throttle=float(vehicle['throttle']),
        steer=float(vehicle['steer']),
        brake=float(vehicle['brake']),
        reverse=bool(flags & VEHICLE_FLAG_REVERSE),
        hand_brake=bool(flags & VEHICLE_FLAG_HAND_BRAKE),
        manual_gear_shift=bool(flags & VEHICLE_FLAG_MANUAL_GEAR_SHIFT),
        gear=int(vehicle['gear']),
        control_mode=control_mode,
        control_source=control_source_name(source),
        takeover_requested=bool(input_flags & INPUT_FLAG_TAKEOVER),
        accelerometer=_vec3(research, 'accelerometer'),
        gyroscope=_vec3(research, 'gyroscope'),
        compass=float(research['compass']),
        longitude=float(research['longitude']),
        latitude=float(research['latitude']),
        altitude=float(research['altitude']),
        road_id=int(vehicle['road_id']),
        lane_id=int(vehicle['lane_id']),
        lane_width=float(research['lane_width']),
        lane_type=lane_type_name(int(research['lane_type'])),
        road_direction=_vec3(research, 'road_direction'),
        lane_offset=float(research['lane_offset']),
        speed_limit=speed_limit,
        collision_intensity=float(research['collision_intensity']),
        invaded_lane_marking=invaded_lane_marking,
    )
