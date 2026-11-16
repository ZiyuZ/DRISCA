"""运行状态与持久化、遥测投影。"""

from dataclasses import dataclass

import carla

from drisca.core.protocol import ControlMode, TelemetrySnapshotEvent
from drisca.storage.models import FrameRow


@dataclass(slots=True)
class DrivingState:
    frame_no: int
    timestamp: float
    server_fps: float
    simulator_fps: float
    velocity: carla.Vector3D
    transform: carla.Transform
    input_control: carla.VehicleControl
    control: carla.VehicleControl
    control_mode: ControlMode
    takeover_requested: bool
    accelerometer: carla.Vector3D
    gyroscope: carla.Vector3D
    compass: float
    longitude: float
    latitude: float
    altitude: float
    waypoint: carla.Waypoint
    speed_limit: float
    collision_intensity: float = 0.0
    invaded_lane_marking: str = ''

    @property
    def lane_offset(self) -> float:
        direction = self.waypoint.transform.get_forward_vector()
        center = self.waypoint.transform.location
        location = self.transform.location
        return direction.x * (location.y - center.y) - direction.y * (location.x - center.x)

    def to_frame_row(self, session_id: str) -> FrameRow:
        location, rotation = self.transform.location, self.transform.rotation
        direction = self.waypoint.transform.get_forward_vector()
        return FrameRow(
            session_id=session_id,
            frame_no=self.frame_no,
            timestamp=self.timestamp,
            server_fps=self.server_fps,
            simulator_fps=self.simulator_fps,
            velocity_x=self.velocity.x,
            velocity_y=self.velocity.y,
            velocity_z=self.velocity.z,
            speed=self.velocity.length(),
            location_x=location.x,
            location_y=location.y,
            location_z=location.z,
            rotation_pitch=rotation.pitch,
            rotation_yaw=rotation.yaw,
            rotation_roll=rotation.roll,
            input_throttle=self.input_control.throttle,
            input_steer=self.input_control.steer,
            input_brake=self.input_control.brake,
            throttle=self.control.throttle,
            steer=self.control.steer,
            brake=self.control.brake,
            reverse=self.control.reverse,
            hand_brake=self.control.hand_brake,
            manual_gear_shift=self.control.manual_gear_shift,
            gear=self.control.gear,
            control_mode=self.control_mode,
            takeover_requested=self.takeover_requested,
            accelerometer_x=self.accelerometer.x,
            accelerometer_y=self.accelerometer.y,
            accelerometer_z=self.accelerometer.z,
            gyroscope_x=self.gyroscope.x,
            gyroscope_y=self.gyroscope.y,
            gyroscope_z=self.gyroscope.z,
            compass=self.compass,
            gnss_longitude=self.longitude,
            gnss_latitude=self.latitude,
            gnss_altitude=self.altitude,
            road_id=self.waypoint.road_id,
            lane_id=self.waypoint.lane_id,
            lane_width=self.waypoint.lane_width,
            lane_type=str(self.waypoint.lane_type),
            road_direction_x=direction.x,
            road_direction_y=direction.y,
            road_direction_z=direction.z,
            lane_offset=self.lane_offset,
            speed_limit=self.speed_limit,
        )

    def to_telemetry_snapshot(self, seq: int) -> TelemetrySnapshotEvent:
        location, rotation = self.transform.location, self.transform.rotation
        return TelemetrySnapshotEvent(
            seq=seq,
            timestamp=self.timestamp,
            frame_no=self.frame_no,
            server_fps=self.server_fps,
            simulator_fps=self.simulator_fps,
            control_mode=self.control_mode,
            input_throttle=self.input_control.throttle,
            input_steer=self.input_control.steer,
            input_brake=self.input_control.brake,
            speed_mps=self.velocity.length(),
            speed_limit_mps=self.speed_limit,
            gear=self.control.gear,
            steer=self.control.steer,
            throttle=self.control.throttle,
            brake=self.control.brake,
            reverse=self.control.reverse,
            hand_brake=self.control.hand_brake,
            manual_gear_shift=self.control.manual_gear_shift,
            takeover_requested=self.takeover_requested,
            location_x=location.x,
            location_y=location.y,
            location_z=location.z,
            rotation_pitch=rotation.pitch,
            rotation_yaw=rotation.yaw,
            rotation_roll=rotation.roll,
            compass=self.compass,
            road_id=self.waypoint.road_id,
            lane_id=self.waypoint.lane_id,
            lane_offset=self.lane_offset,
            collision_intensity=self.collision_intensity,
            invaded_lane_marking=self.invaded_lane_marking,
        )
