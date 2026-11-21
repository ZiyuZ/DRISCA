"""模拟器生命周期、观察循环与命令处理。"""

import time
from contextlib import ExitStack
from pathlib import Path
from typing import Literal, TypedDict, cast

import carla
from loguru import logger

from drisca.core.client import CarlaSession
from drisca.core.config import RunConfig
from drisca.core.driving_view import DrivingViewClient, DrivingViewState, keyboard_mapping
from drisca.core.protocol import (
    ControlMode,
    EnabledPayload,
    SetAutopilotCommand,
    SetTakeoverCommand,
    SetWeatherCommand,
    SetWeatherEvent,
    SetWeatherPayload,
    StopCommand,
    ToggleAutopilotEvent,
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
from drisca.simulator.sensors import SensorSuite
from drisca.simulator.state import DrivingState
from drisca.simulator.vehicle import EgoVehicle
from drisca.simulator.ws_client import WorkerWSClient
from drisca.storage.writer import BatchDataWriter


class EventContext(TypedDict):
    source: Literal['keyboard', 'wheel', 'launcher', 'sensor', 'system']
    frame_no: int | None
    timestamp: float
    command_id: str | None


def box_payload(box: carla.BoundingBox) -> dict:
    return {
        'location': {'x': box.location.x, 'y': box.location.y, 'z': box.location.z},
        'extent': {'x': box.extent.x, 'y': box.extent.y, 'z': box.extent.z},
        'rotation': {
            'pitch': box.rotation.pitch,
            'yaw': box.rotation.yaw,
            'roll': box.rotation.roll,
        },
    }


class SimulatorApp:
    def __init__(self, run_config: RunConfig) -> None:
        self.config = run_config
        self.running = True
        self.frame_no: int | None = None
        self.cameras = run_config.preset.cameras.model_dump(mode='json')
        self.layout = run_config.machine.display.layout.model_dump(mode='json')

    def run(self) -> None:
        cfg = self.config
        with ExitStack() as stack:
            channel = WorkerWSClient(cfg.launcher_ws_url)
            channel.start()
            stack.callback(channel.close)
            session = CarlaSession(cfg.machine.carla)
            session.connect()
            session.set_async_mode(cfg.preset.world.simulation_fps)
            vehicle = EgoVehicle(session.world, cfg.preset.ego, cfg.machine.carla.tm_port)
            stack.callback(vehicle.close)
            sensors = SensorSuite(session.world, vehicle.actor, channel.send_event)
            stack.callback(sensors.close)
            view = DrivingViewClient(cfg.machine.driving_view)
            stack.callback(view.close)
            mode = 'autopilot' if cfg.preset.ego.init_autopilot else 'manual'
            view.start(
                vehicle.actor.id,
                box_payload(vehicle.actor.bounding_box),
                self.cameras,
                self.layout,
                keyboard_mapping(cfg.control.keyboard),
                mode,
            )
            stack.callback(view.stop)
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
            channel.send_event(
                WorkerReadyEvent(
                    ego_actor_id=vehicle.actor.id,
                    ego_type_id=vehicle.actor.type_id,
                    vehicle_box=box_payload(vehicle.actor.bounding_box),
                )
            )
            channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.RUNNING))
            clock_started = time.monotonic()
            loop_frames = 0
            sequence = 0
            last_telemetry = 0.0
            last_state_frame = -1
            last_imu: carla.IMUMeasurement | None = None
            last_gnss: carla.GnssMeasurement | None = None
            road_map = session.map
            while self.running:
                for command in channel.poll_commands():
                    try:
                        self._command(command, session, vehicle, view, channel)
                    except Exception:
                        logger.bind(command_id=command.command_id).exception('命令执行失败')
                        if not isinstance(
                            command, (UpdateCameraCommand, UpdateLayoutCommand, SetWeatherCommand)
                        ):
                            raise
                state = view.get_state()
                if not state.active:
                    raise RuntimeError('驾驶视图已停止')
                self.frame_no = state.frame_no
                self._apply_driver_requests(state, vehicle, view, channel)
                if state.active and state.frame_no != last_state_frame:
                    last_state_frame = state.frame_no
                    imu = cast(carla.IMUMeasurement | None, sensors.read_latest('imu'))
                    if imu is not None:
                        last_imu = imu
                    gnss = cast(carla.GnssMeasurement | None, sensors.read_latest('gnss'))
                    if gnss is not None:
                        last_gnss = gnss
                    loop_frames += 1
                    elapsed = time.monotonic() - clock_started
                    simulator_fps = loop_frames / elapsed if elapsed > 0 else 0.0
                    driving = self._driving_state(
                        state, last_imu, last_gnss, vehicle, road_map, simulator_fps
                    )
                    if writer is not None:
                        writer.enqueue(driving.to_frame_row(cfg.session_id))
                    if time.monotonic() - last_telemetry >= 1 / 25:
                        channel.publish_telemetry(driving.to_telemetry_snapshot(sequence))
                        sequence += 1
                        last_telemetry = time.monotonic()
                time.sleep(1 / 20)
            channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.STOPPING))

    def _driving_state(
        self,
        state: DrivingViewState,
        imu: carla.IMUMeasurement | None,
        gnss: carla.GnssMeasurement | None,
        vehicle: EgoVehicle,
        road_map: carla.Map,
        simulator_fps: float,
    ) -> DrivingState:
        location = carla.Location(*state.location)
        rotation = carla.Rotation(*state.rotation)
        transform = carla.Transform(location, rotation)
        waypoint = road_map.get_waypoint(location)
        if waypoint is None:
            raise RuntimeError('主车位置没有对应道路')
        speed_limit = (
            vehicle.actor.get_speed_limit() / 3.6
            if self.config.preset.ego.dynamic_speed_limit
            else self.config.preset.ego.default_speed_limit
        )
        input_control = carla.VehicleControl(
            throttle=state.input.throttle,
            steer=state.input.steer,
            brake=state.input.brake,
            reverse=state.input.reverse,
            hand_brake=state.input.hand_brake,
            manual_gear_shift=state.input.manual_gear_shift,
            gear=state.input.gear,
        )
        control = carla.VehicleControl(
            throttle=state.control.throttle,
            steer=state.control.steer,
            brake=state.control.brake,
            reverse=state.control.reverse,
            hand_brake=state.control.hand_brake,
            manual_gear_shift=state.control.manual_gear_shift,
            gear=state.control.gear,
        )
        return DrivingState(
            frame_no=state.frame_no,
            timestamp=state.wall_time,
            server_fps=1 / state.delta if state.delta > 0 else 0.0,
            simulator_fps=simulator_fps,
            velocity=carla.Vector3D(*state.velocity),
            transform=transform,
            input_control=input_control,
            control=control,
            control_mode=ControlMode.AUTOPILOT if state.mode == 'autopilot' else ControlMode.MANUAL,
            takeover_requested=state.input.takeover_requested,
            accelerometer=imu.accelerometer if imu is not None else carla.Vector3D(),
            gyroscope=imu.gyroscope if imu is not None else carla.Vector3D(),
            compass=imu.compass if imu is not None else 0.0,
            longitude=gnss.longitude if gnss is not None else 0.0,
            latitude=gnss.latitude if gnss is not None else 0.0,
            altitude=gnss.altitude if gnss is not None else 0.0,
            waypoint=waypoint,
            speed_limit=speed_limit,
        )

    def _apply_driver_requests(
        self,
        state: DrivingViewState,
        vehicle: EgoVehicle,
        view: DrivingViewClient,
        channel: WorkerWSClient,
    ) -> None:
        common: EventContext = {
            'source': 'keyboard',
            'frame_no': state.frame_no,
            'timestamp': time.time(),
            'command_id': None,
        }
        if state.input.toggle_autopilot_requested:
            mode = 'manual' if state.mode == 'autopilot' else 'autopilot'
            self._set_mode(vehicle, view, mode)
            channel.send_event(
                ToggleAutopilotEvent(**common, payload=EnabledPayload(enabled=mode == 'autopilot'))
            )
        if state.input.takeover_requested and state.mode == 'autopilot':
            self._set_mode(vehicle, view, 'manual')
            channel.send_event(ToggleTakeoverEvent(**common, payload=EnabledPayload(enabled=True)))

    def _set_mode(self, vehicle: EgoVehicle, view: DrivingViewClient, mode: str) -> None:
        """驾驶模式的唯一入口：视图模式和车辆控制来源一起切换。"""
        view.set_mode('autopilot' if mode == 'autopilot' else 'manual')
        vehicle.set_autopilot(mode == 'autopilot')

    def _command(
        self,
        command,
        session: CarlaSession,
        vehicle: EgoVehicle,
        view: DrivingViewClient,
        channel,
    ) -> None:
        common: EventContext = {
            'source': 'launcher',
            'frame_no': self.frame_no,
            'timestamp': time.time(),
            'command_id': command.command_id,
        }
        if isinstance(command, StopCommand):
            self.running = False
        elif isinstance(command, SetAutopilotCommand):
            self._set_mode(vehicle, view, 'autopilot' if command.enabled else 'manual')
            channel.send_event(
                ToggleAutopilotEvent(**common, payload=EnabledPayload(enabled=command.enabled))
            )
        elif isinstance(command, SetTakeoverCommand):
            if command.enabled:
                self._set_mode(vehicle, view, 'manual')
            channel.send_event(ToggleTakeoverEvent(**common, payload=EnabledPayload(enabled=command.enabled)))
        elif isinstance(command, SetWeatherCommand):
            session.apply_weather(command.weather)
            channel.send_event(SetWeatherEvent(**common, payload=SetWeatherPayload(weather=command.weather)))
        elif isinstance(command, UpdateCameraCommand):
            self.cameras[command.camera_name] = command.mount.model_dump(mode='json')
            view.update(cameras=self.cameras, layout=self.layout)
            channel.send_event(
                UpdateCameraEvent(
                    **common,
                    payload=UpdateCameraPayload(camera_name=command.camera_name, mount=command.mount),
                )
            )
        elif isinstance(command, UpdateLayoutCommand):
            self.layout = command.layout.model_dump(mode='json')
            view.update(cameras=self.cameras, layout=self.layout)
            channel.send_event(UpdateLayoutEvent(**common, payload=command.layout))
