"""模拟器生命周期和逐帧循环。"""

import queue
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Literal, TypedDict, cast

import carla
import pygame
from loguru import logger

from drisca.core.client import CarlaSession
from drisca.core.config import RunConfig
from drisca.core.protocol import (
    ChangeGearEvent,
    ChangeGearPayload,
    ControlMode,
    EnabledPayload,
    SetAutopilotCommand,
    SetTakeoverCommand,
    SetWeatherCommand,
    SetWeatherEvent,
    SetWeatherPayload,
    StopCommand,
    ToggleAutopilotEvent,
    ToggleHandbrakeEvent,
    ToggleLightEvent,
    ToggleLightPayload,
    ToggleManualGearEvent,
    ToggleReverseEvent,
    ToggleTakeoverEvent,
    UpdateCameraCommand,
    UpdateCameraEvent,
    UpdateCameraPayload,
    UpdateLayoutCommand,
    UpdateLayoutEvent,
    WorkerReadyEvent,
    WorkerRole,
    WorkerState,
    WorkerStatusEvent,
)
from drisca.simulator.input import InputAction, InputController
from drisca.simulator.renderer import ViewportRenderer
from drisca.simulator.sensors import CameraRig, SensorSuite
from drisca.simulator.state import DrivingState
from drisca.simulator.vehicle import EgoVehicle
from drisca.simulator.ws_client import WorkerWSClient
from drisca.storage.writer import BatchDataWriter


class EventContext(TypedDict):
    source: Literal['keyboard', 'wheel', 'launcher', 'sensor', 'system']
    frame_no: int | None
    timestamp: float
    command_id: str | None


class SimulatorApp:
    def __init__(self, run_config: RunConfig) -> None:
        self.config = run_config
        self.running = True
        self.takeover_requested = False
        self.control = carla.VehicleControl()
        self.lights = carla.VehicleLightState.NONE
        self.frame_no: int | None = None

    def run(self) -> None:
        cfg = self.config
        with ExitStack() as stack:
            channel = WorkerWSClient(cfg.launcher_ws_url)
            channel.start()
            stack.callback(channel.close)
            renderer = ViewportRenderer(cfg.machine.display)
            stack.callback(renderer.close)
            inputs = InputController(cfg.control)
            stack.callback(inputs.close)
            session = CarlaSession(cfg.machine.carla)
            session.connect()
            session.set_sync_mode(cfg.preset.world.sync_mode, cfg.preset.world.simulation_fps)
            vehicle = EgoVehicle(session.world, cfg.preset.ego, cfg.machine.carla.tm_port)
            stack.callback(vehicle.close)
            sensors = SensorSuite(session.world, vehicle.actor, channel.send_event)
            stack.callback(sensors.close)
            cameras = CameraRig(
                session.world,
                vehicle.actor,
                cfg.preset.cameras,
                renderer.actual_resolution,
                cfg.machine.display.layout,
            )
            stack.callback(cameras.close)
            if cfg.run.save_data and cfg.run.enable_carla_recorder:
                recorder_dir = Path(cfg.machine.recorder_dir).resolve()
                recorder_dir.mkdir(parents=True, exist_ok=True)
                session.client.start_recorder(str(recorder_dir / f'{cfg.session_id}.rec'))
                stack.callback(session.client.stop_recorder)
            writer = None
            if cfg.run.save_data:
                assert cfg.db_path is not None
                writer = BatchDataWriter(Path(cfg.db_path))
                writer.start()
                stack.callback(writer.close)
            box = vehicle.actor.bounding_box
            channel.send_event(
                WorkerReadyEvent(
                    ego_actor_id=vehicle.actor.id,
                    ego_type_id=vehicle.actor.type_id,
                    vehicle_box={
                        'location': {'x': box.location.x, 'y': box.location.y, 'z': box.location.z},
                        'extent': {'x': box.extent.x, 'y': box.extent.y, 'z': box.extent.z},
                        'rotation': {
                            'pitch': box.rotation.pitch,
                            'yaw': box.rotation.yaw,
                            'roll': box.rotation.roll,
                        },
                    },
                )
            )
            channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.RUNNING))
            clock = pygame.time.Clock()
            sequence = 0
            last_telemetry = 0.0
            last_camera_frame = time.monotonic()
            render_interval = 1 / cfg.machine.display.target_fps
            next_render = time.monotonic()
            road_map = session.map
            timings = dict(input=0.0, world=0.0, sensors=0.0, render=0.0, sample=0.0)
            measured_frames = 0
            while self.running:
                frame_started = time.perf_counter()
                sensors.check()
                loop_fps = cfg.preset.world.simulation_fps if cfg.preset.world.sync_mode else 0
                delta = clock.tick(loop_fps) / 1000.0
                for command in channel.poll_commands():
                    try:
                        self._command(command, session, vehicle, cameras, renderer, channel)
                        if isinstance(command, (UpdateCameraCommand, UpdateLayoutCommand)):
                            last_camera_frame = time.monotonic()
                    except Exception:
                        logger.bind(command_id=command.command_id).exception('命令执行失败')
                        if not isinstance(
                            command, (UpdateCameraCommand, UpdateLayoutCommand, SetWeatherCommand)
                        ):
                            raise
                input_control, actions = inputs.read(delta)
                for action in actions:
                    self._action(action, vehicle, channel)
                if not self.running:
                    break
                self.control.throttle = input_control.throttle
                self.control.steer = input_control.steer
                self.control.brake = input_control.brake
                vehicle.apply_control(self.control)
                before_tick = time.perf_counter()
                if cfg.preset.world.sync_mode:
                    frame_no = session.world.tick()
                    snapshot = session.world.get_snapshot()
                else:
                    snapshot = session.world.wait_for_tick(cfg.machine.carla.timeout)
                    frame_no = snapshot.frame
                after_tick = time.perf_counter()
                self.frame_no = frame_no
                imu = cast(carla.IMUMeasurement, self._frame(sensors.continuous['imu'], frame_no))
                gnss = cast(carla.GnssMeasurement, self._frame(sensors.continuous['gnss'], frame_no))
                after_sensors = time.perf_counter()
                images = cameras.read_aligned()
                if images is not None:
                    last_camera_frame = time.monotonic()
                    if last_camera_frame >= next_render:
                        renderer.render_frame(images)
                        next_render += render_interval
                        if next_render < last_camera_frame:
                            next_render = last_camera_frame + render_interval
                elif time.monotonic() - last_camera_frame > cfg.machine.carla.timeout:
                    raise RuntimeError('相机图像接收或帧对齐超时')
                after_render = time.perf_counter()
                transform = vehicle.actor.get_transform()
                waypoint = road_map.get_waypoint(transform.location)
                if waypoint is None:
                    raise RuntimeError('主车位置没有对应道路')
                speed_limit = (
                    vehicle.actor.get_speed_limit() / 3.6
                    if cfg.preset.ego.dynamic_speed_limit
                    else cfg.preset.ego.default_speed_limit
                )
                state = DrivingState(
                    frame_no=frame_no,
                    timestamp=time.time(),
                    server_fps=1 / snapshot.timestamp.delta_seconds,
                    simulator_fps=clock.get_fps(),
                    velocity=vehicle.actor.get_velocity(),
                    transform=transform,
                    input_control=input_control,
                    control=vehicle.actor.get_control(),
                    control_mode=ControlMode.AUTOPILOT if vehicle.autopilot else ControlMode.MANUAL,
                    takeover_requested=self.takeover_requested,
                    accelerometer=imu.accelerometer,
                    gyroscope=imu.gyroscope,
                    compass=imu.compass,
                    longitude=gnss.longitude,
                    latitude=gnss.latitude,
                    altitude=gnss.altitude,
                    waypoint=waypoint,
                    speed_limit=speed_limit,
                    collision_intensity=sensors.collision_intensity,
                    invaded_lane_marking=sensors.invaded_lane_marking,
                )
                if writer is not None:
                    writer.enqueue(state.to_frame_row(cfg.session_id))
                if time.monotonic() - last_telemetry >= 1 / 25:
                    channel.publish_telemetry(state.to_telemetry_snapshot(sequence))
                    sequence += 1
                    last_telemetry = time.monotonic()
                timings['input'] += before_tick - frame_started
                timings['world'] += after_tick - before_tick
                timings['sensors'] += after_sensors - after_tick
                timings['render'] += after_render - after_sensors
                timings['sample'] += time.perf_counter() - after_render
                measured_frames += 1
            if measured_frames:
                average = {name: elapsed * 1000 / measured_frames for name, elapsed in timings.items()}
                logger.info(
                    '平均每帧耗时：输入与限速 {:.1f}ms，世界推进 {:.1f}ms，'
                    '传感器等待 {:.1f}ms，画面合成 {:.1f}ms，状态采样与入队 {:.1f}ms',
                    average['input'],
                    average['world'],
                    average['sensors'],
                    average['render'],
                    average['sample'],
                )
            channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.STOPPING))

    def _frame(self, channel: queue.Queue, frame_no: int) -> carla.SensorData:
        try:
            if not self.config.preset.world.sync_mode:
                data = channel.get(timeout=self.config.machine.carla.timeout)
                while True:
                    try:
                        data = channel.get_nowait()
                    except queue.Empty:
                        return data
            while True:
                data = channel.get(timeout=self.config.machine.carla.timeout)
                if data.frame == frame_no:
                    return data
                if data.frame > frame_no:
                    raise RuntimeError(f'传感器帧缺失：{frame_no}')
        except queue.Empty as exc:
            raise RuntimeError(f'等待传感器帧 {frame_no} 超时') from exc

    def _command(self, command, session, vehicle, cameras, renderer, channel) -> None:
        common: EventContext = {
            'source': 'launcher',
            'frame_no': self.frame_no,
            'timestamp': time.time(),
            'command_id': command.command_id,
        }
        if isinstance(command, StopCommand):
            self.running = False
        elif isinstance(command, SetAutopilotCommand):
            self._set_autopilot(command.enabled, vehicle, channel, common)
        elif isinstance(command, SetTakeoverCommand):
            self.takeover_requested = command.enabled
            channel.send_event(ToggleTakeoverEvent(**common, payload=EnabledPayload(enabled=command.enabled)))
        elif isinstance(command, SetWeatherCommand):
            session.apply_weather(command.weather)
            channel.send_event(SetWeatherEvent(**common, payload=SetWeatherPayload(weather=command.weather)))
        elif isinstance(command, UpdateCameraCommand):
            cameras.update(command.camera_name, command.mount)
            channel.send_event(
                UpdateCameraEvent(
                    **common,
                    payload=UpdateCameraPayload(camera_name=command.camera_name, mount=command.mount),
                )
            )
        elif isinstance(command, UpdateLayoutCommand):
            cameras.update_layout(command.layout)
            renderer.update_layout(command.layout)
            channel.send_event(UpdateLayoutEvent(**common, payload=command.layout))

    def _set_autopilot(
        self, enabled: bool, vehicle: EgoVehicle, channel: WorkerWSClient, common: EventContext
    ) -> None:
        if vehicle.autopilot != enabled:
            if not enabled:
                actual = vehicle.actor.get_control()
                self.control.gear = actual.gear
                self.control.reverse = actual.reverse
                self.control.hand_brake = actual.hand_brake
                self.control.manual_gear_shift = actual.manual_gear_shift
            vehicle.set_autopilot(enabled)
            channel.send_event(ToggleAutopilotEvent(**common, payload=EnabledPayload(enabled=enabled)))
        if not enabled and self.takeover_requested:
            self.takeover_requested = False
            channel.send_event(ToggleTakeoverEvent(**common, payload=EnabledPayload(enabled=False)))

    def _action(self, action: InputAction, vehicle: EgoVehicle, channel: WorkerWSClient) -> None:
        common: EventContext = {
            'source': action.source,
            'frame_no': self.frame_no,
            'timestamp': time.time(),
            'command_id': None,
        }
        name = action.name
        if vehicle.autopilot and name in (
            'toggle_reverse',
            'toggle_handbrake',
            'toggle_manual_transmission',
            'gear_up',
            'gear_down',
        ):
            return
        if name == 'quit':
            self.running = False
        elif name == 'toggle_autopilot':
            self._set_autopilot(not vehicle.autopilot, vehicle, channel, common)
        elif name == 'takeover':
            self._set_autopilot(False, vehicle, channel, common)
        elif name == 'toggle_reverse':
            self.control.reverse = not self.control.reverse
            self.control.gear = -1 if self.control.reverse else 1
            vehicle.actor.apply_control(self.control)
            channel.send_event(
                ToggleReverseEvent(**common, payload=EnabledPayload(enabled=self.control.reverse))
            )
        elif name == 'toggle_handbrake':
            self.control.hand_brake = not self.control.hand_brake
            vehicle.actor.apply_control(self.control)
            channel.send_event(
                ToggleHandbrakeEvent(**common, payload=EnabledPayload(enabled=self.control.hand_brake))
            )
        elif name == 'toggle_manual_transmission':
            self.control.manual_gear_shift = not self.control.manual_gear_shift
            if self.control.manual_gear_shift:
                actual = vehicle.actor.get_control()
                self.control.gear = actual.gear
                self.control.reverse = actual.reverse
            vehicle.actor.apply_control(self.control)
            channel.send_event(
                ToggleManualGearEvent(
                    **common, payload=EnabledPayload(enabled=self.control.manual_gear_shift)
                )
            )
        elif name in ('gear_up', 'gear_down'):
            if not self.control.manual_gear_shift:
                return
            gear = max(-1, self.control.gear + (1 if name == 'gear_up' else -1))
            if gear != self.control.gear:
                self.control.gear = gear
                self.control.reverse = gear < 0
                vehicle.actor.apply_control(self.control)
                channel.send_event(ChangeGearEvent(**common, payload=ChangeGearPayload(gear=gear)))
        elif name.startswith('toggle_light_'):
            lights = {
                'toggle_light_double_blinker': carla.VehicleLightState.LeftBlinker
                | carla.VehicleLightState.RightBlinker,
                'toggle_light_low_beam': carla.VehicleLightState.LowBeam,
                'toggle_light_high_beam': carla.VehicleLightState.HighBeam,
                'toggle_light_left_blinker': carla.VehicleLightState.LeftBlinker,
                'toggle_light_right_blinker': carla.VehicleLightState.RightBlinker,
                'toggle_light_interior': carla.VehicleLightState.Interior,
            }
            flag = lights[name]
            enabled = not (self.lights & flag == flag)
            self.lights = self.lights | flag if enabled else self.lights & ~flag
            vehicle.actor.set_light_state(carla.VehicleLightState(self.lights))
            channel.send_event(
                ToggleLightEvent(
                    **common,
                    payload=ToggleLightPayload(light=name.removeprefix('toggle_light_'), enabled=enabled),
                )
            )
