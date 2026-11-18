"""传感器采集与碰撞、压线事件。"""

import queue
import time
from collections.abc import Callable
from typing import cast

import carla

from drisca.core.config import CameraConfig, CameraRigConfig, DisplayLayoutConfig
from drisca.core.protocol import (
    CollisionEvent,
    CollisionPayload,
    LaneInvasionEvent,
    LaneInvasionPayload,
    WorkerEvent,
)


def camera_transform(config: CameraConfig, box: carla.BoundingBox) -> carla.Transform:
    location = carla.Location(x=config.x * box.extent.x, y=config.y * box.extent.y, z=config.z * box.extent.z)
    location = carla.Transform(carla.Location(), box.rotation).transform(location)
    return carla.Transform(
        carla.Location(
            x=location.x + box.location.x, y=location.y + box.location.y, z=location.z + box.location.z
        ),
        carla.Rotation(pitch=config.pitch, yaw=config.yaw, roll=config.roll),
    )


class SensorSuite:
    def __init__(self, world: carla.World, vehicle: carla.Vehicle, send_event: Callable[[WorkerEvent], None]):
        self.world = world
        self.vehicle = vehicle
        self.send_event = send_event
        self.error: Exception | None = None
        self.collision_intensity = 0.0
        self.invaded_lane_marking = ''
        self.sensors: list[carla.Sensor] = []
        self.continuous: dict[str, queue.Queue[carla.SensorData]] = {}
        try:
            for name, blueprint in (('imu', 'sensor.other.imu'), ('gnss', 'sensor.other.gnss')):
                channel: queue.Queue[carla.SensorData] = queue.Queue(maxsize=256)
                self.continuous[name] = channel
                sensor = self._spawn(blueprint)
                sensor.listen(self._guard(channel.put_nowait))
            self._spawn('sensor.other.collision').listen(self._guard(self._collision))
            self._spawn('sensor.other.lane_invasion').listen(self._guard(self._lane_invasion))
        except Exception:
            self.close()
            raise

    def _guard(self, callback: Callable[[carla.SensorData], None]) -> Callable[[carla.SensorData], None]:
        def guarded(data: carla.SensorData) -> None:
            try:
                callback(data)
            except Exception as exc:
                self.error = exc

        return guarded

    def check(self) -> None:
        if self.error is not None:
            raise RuntimeError('传感器回调失败') from self.error

    def _spawn(self, blueprint_id: str) -> carla.Sensor:
        blueprint = self.world.get_blueprint_library().find(blueprint_id)
        sensor = cast(
            carla.Sensor,
            self.world.spawn_actor(
                blueprint, carla.Transform(carla.Location(), carla.Rotation()), attach_to=self.vehicle
            ),
        )
        self.sensors.append(sensor)
        return sensor

    def _collision(self, data: carla.SensorData) -> None:
        event = cast(carla.CollisionEvent, data)
        impulse = event.normal_impulse
        self.collision_intensity = impulse.length()
        self.send_event(
            CollisionEvent(
                source='sensor',
                frame_no=event.frame,
                timestamp=time.time(),
                payload=CollisionPayload(
                    actor_id=event.other_actor.id,
                    actor_type=event.other_actor.type_id,
                    impulse_x=impulse.x,
                    impulse_y=impulse.y,
                    impulse_z=impulse.z,
                ),
            )
        )

    def _lane_invasion(self, data: carla.SensorData) -> None:
        event = cast(carla.LaneInvasionEvent, data)
        self.invaded_lane_marking = ', '.join(str(mark.type) for mark in event.crossed_lane_markings)
        self.send_event(
            LaneInvasionEvent(
                source='sensor',
                frame_no=event.frame,
                timestamp=time.time(),
                payload=LaneInvasionPayload(
                    markings=tuple(str(mark.type) for mark in event.crossed_lane_markings)
                ),
            )
        )

    def close(self) -> None:
        for sensor in self.sensors:
            sensor.stop()
            sensor.destroy()


class CameraRig:
    def __init__(
        self,
        world: carla.World,
        vehicle: carla.Vehicle,
        config: CameraRigConfig,
        resolution: tuple[int, int],
        layout: DisplayLayoutConfig,
    ) -> None:
        self.world = world
        self.vehicle = vehicle
        self.resolution = resolution
        self.layout = layout
        self.mounts = {
            name: getattr(config, name) for name in ('front', 'rear_top', 'rear_left', 'rear_right')
        }
        self.sensors: dict[str, carla.Sensor] = {}
        self.frames: dict[str, queue.Queue[carla.Image]] = {}
        self.pending: dict[str, dict[int, carla.Image]] = {}
        self.error: Exception | None = None
        try:
            for name in ('front', 'rear_top', 'rear_left', 'rear_right'):
                self.update(name, getattr(config, name))
        except Exception:
            self.close()
            raise

    def update(self, name: str, config: CameraConfig) -> None:
        blueprint = self.world.get_blueprint_library().find('sensor.camera.rgb')
        width, height = self.resolution if name == 'front' else getattr(self.layout, name).image_size
        self.mounts[name] = config
        blueprint.set_attribute('image_size_x', str(width))
        blueprint.set_attribute('image_size_y', str(height))
        blueprint.set_attribute('fov', str(config.fov))
        channel: queue.Queue[carla.Image] = queue.Queue(maxsize=256)
        sensor = cast(
            carla.Sensor,
            self.world.spawn_actor(
                blueprint,
                camera_transform(config, self.vehicle.bounding_box),
                attach_to=self.vehicle,
                attachment_type=carla.AttachmentType.Rigid,
            ),
        )

        def receive(data: carla.SensorData) -> None:
            try:
                channel.put_nowait(cast(carla.Image, data))
            except Exception as exc:
                self.error = exc

        try:
            sensor.listen(receive)
        except Exception:
            sensor.destroy()
            raise
        old_sensor = self.sensors.get(name)
        if old_sensor is not None:
            old_sensor.stop()
            old_sensor.destroy()
        self.sensors[name] = sensor
        self.frames[name] = channel
        self.pending = {camera: {} for camera in self.frames}

    def update_layout(self, layout: DisplayLayoutConfig) -> None:
        previous = self.layout
        self.layout = layout
        for name in ('rear_top', 'rear_left', 'rear_right'):
            if getattr(previous, name).image_size != getattr(layout, name).image_size:
                self.update(name, self.mounts[name])

    def read_aligned(self) -> dict[str, carla.Image] | None:
        """在世界继续推进时收集各相机同一帧的图像。"""
        if self.error is not None:
            raise RuntimeError('相机回调失败') from self.error
        for name, channel in self.frames.items():
            while True:
                try:
                    image = channel.get_nowait()
                except queue.Empty:
                    break
                self.pending[name][image.frame] = image
                if len(self.pending[name]) > 256:
                    raise RuntimeError(f'相机帧未能对齐：{name}')
        if any(not frames for frames in self.pending.values()):
            return None
        common = set.intersection(*(set(frames) for frames in self.pending.values()))
        if not common:
            return None
        frame = max(common)
        images = {name: frames[frame] for name, frames in self.pending.items()}
        for frames in self.pending.values():
            for old_frame in tuple(frames):
                if old_frame <= frame:
                    del frames[old_frame]
        return images

    def close(self) -> None:
        for sensor in self.sensors.values():
            sensor.stop()
            sensor.destroy()
