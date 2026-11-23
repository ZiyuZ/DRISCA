"""模拟器生命周期、交换循环与命令处理。"""

import statistics
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from loguru import logger

from drisca.core.client import ExchangeResult, NativeApiClient
from drisca.core.config import RunConfig
from drisca.core.driving_view import keyboard_mapping
from drisca.core.protocol import (
    LauncherCommand,
    SetAutopilotCommand,
    SetTakeoverCommand,
    SetWeatherCommand,
    StopCommand,
    UpdateCameraCommand,
    UpdateLayoutCommand,
    WorkerReadyEvent,
    WorkerRole,
    WorkerState,
    WorkerStatusEvent,
)
from drisca.core.weather import to_payload
from drisca.simulator.events import map_event
from drisca.simulator.state import project_snapshot, research_ready
from drisca.simulator.ws_client import WorkerWSClient
from drisca.storage.writer import BatchDataWriter

SAMPLE_INTERVAL = 1 / 20
TELEMETRY_INTERVAL = 1 / 25
AUTOPILOT_UNAVAILABLE = '自动驾驶尚未实现：原生接口只支持人工驾驶与外部控制'


class SimulatorApp:
    def __init__(self, run_config: RunConfig) -> None:
        self.config = run_config
        self.running = True
        self.ego_actor_id = 0
        self.control_revision = 0
        self.control_mode = ''
        self.invaded_lane_marking = ''

    def run(self) -> None:
        cfg = self.config
        if cfg.preset.ego.init_autopilot:
            raise RuntimeError(f'{AUTOPILOT_UNAVAILABLE}，预设要求启动即自动驾驶')
        with ExitStack() as stack:
            channel = WorkerWSClient(cfg.launcher_ws_url)
            channel.start()
            stack.callback(channel.close)
            try:
                self._execute(channel, stack)
            except Exception as exc:
                # 走既有日志通道把失败原因送到 Launcher，便于事后定位。
                logger.error(f'驾驶端失败：{exc}')
                raise

    def _execute(self, channel: WorkerWSClient, stack: ExitStack) -> None:
        cfg = self.config
        api = NativeApiClient(cfg.machine.driving_view, client='drisca-worker')
        info = api.connect()
        stack.callback(api.close)
        logger.info(f'原生接口已连接：{info.map_name}，world_id {info.world_id}')
        api.set_world(cfg.preset.world.simulation_fps)
        ego_actor_id, describe = self._spawn_ego(api)
        self.ego_actor_id = ego_actor_id
        view = api.start_view(
            session_id=cfg.session_id,
            ego_actor_id=ego_actor_id,
            cameras=cfg.preset.cameras.model_dump(mode='json'),
            layout=cfg.machine.display.layout.model_dump(mode='json'),
            keyboard=keyboard_mapping(cfg.control.keyboard),
            mode='manual',
            dynamic_speed_limit=cfg.preset.ego.dynamic_speed_limit,
            default_speed_limit_mps=cfg.preset.ego.default_speed_limit,
        )
        self._apply_control_state(view.get('control_state'))
        self._wait_ready(api, channel)
        writer = None
        if cfg.run.save_data:
            assert cfg.db_path is not None
            writer = BatchDataWriter(Path(cfg.db_path))
            writer.start()
            stack.callback(writer.close)
        if cfg.run.save_data and cfg.run.enable_carla_recorder:
            directory = Path(cfg.machine.recorder_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            api.recorder_start(str(directory / f'{cfg.session_id}.rec'))
        channel.send_event(
            WorkerReadyEvent(
                ego_actor_id=ego_actor_id,
                ego_type_id=str(describe['blueprint']),
                vehicle_box=describe['bounding_box'],
            )
        )
        channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.RUNNING))
        self._loop(api, channel, writer)
        final = api.stop_experiment(cfg.session_id)
        for raw in final.get('events') or ():
            self._emit(channel, raw, command_id=None, source=str(raw['source']))
        channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.STOPPING))

    def _spawn_ego(self, api: NativeApiClient) -> tuple[int, dict[str, Any]]:
        ego = self.config.preset.ego
        if not ego.blueprint:
            raise RuntimeError('预设未选择主车蓝图')
        point = ego.spawn_point
        result = api.spawn_vehicle(
            blueprint=ego.blueprint,
            transform={
                'location': [point.x, point.y, point.z],
                'rotation': [point.pitch, point.yaw, point.roll],
            },
            role_name=ego.role_name,
            mode='manual',
        )
        return int(result['actor_id']), result['describe']

    def _wait_ready(self, api: NativeApiClient, channel: WorkerWSClient) -> None:
        """等研究采集就绪后再报告运行状态，超过启动超时则报错。"""
        cfg = self.config
        deadline = time.monotonic() + cfg.machine.carla_runtime.startup_timeout
        while True:
            result = api.exchange([], session_id=cfg.session_id)
            self._apply_control_state(result.control_state)
            self._forward_events(channel, result, {})
            if research_ready(result.snapshot):
                record = result.snapshot.research_record
                assert record is not None
                logger.info(
                    '研究采集就绪：frame={} imu_frame={} imu_us={} gnss_frame={} gnss_us={}'.format(
                        result.snapshot.frame_no,
                        int(record['imu_frame_no']),
                        int(record['imu_simulation_time_us']),
                        int(record['gnss_frame_no']),
                        int(record['gnss_simulation_time_us']),
                    )
                )
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f'研究采集未在 {cfg.machine.carla_runtime.startup_timeout:g} 秒内就绪')
            time.sleep(SAMPLE_INTERVAL)

    def _loop(
        self,
        api: NativeApiClient,
        channel: WorkerWSClient,
        writer: BatchDataWriter | None,
    ) -> None:
        cfg = self.config
        clock_started = time.monotonic()
        loop_frames = 0
        sequence = 0
        last_telemetry = 0.0
        last_frame = -1
        first_snapshot: tuple[int, int, int] | None = None
        last_snapshot: tuple[int, int, int] | None = None
        last_research: tuple[int, int, int, int] | None = None
        deltas: list[float] = []
        exchange_ms: list[float] = []
        while True:
            operations, command_ids = self._operations(channel.poll_commands())
            if not self.running and not operations:
                break
            deadline = time.monotonic() + SAMPLE_INTERVAL
            started = time.monotonic()
            result = api.exchange(operations, session_id=cfg.session_id)
            exchange_ms.append((time.monotonic() - started) * 1000)
            self._apply_control_state(result.control_state)
            self._forward_events(channel, result, command_ids)
            if result.frame_no != last_frame:
                last_frame = result.frame_no
                loop_frames += 1
                elapsed = time.monotonic() - clock_started
                driving = project_snapshot(
                    result.snapshot,
                    ego_actor_id=self.ego_actor_id,
                    dynamic_speed_limit=cfg.preset.ego.dynamic_speed_limit,
                    default_speed_limit_mps=cfg.preset.ego.default_speed_limit,
                    simulator_fps=loop_frames / elapsed if elapsed > 0 else 0.0,
                    invaded_lane_marking=self.invaded_lane_marking,
                )
                snapshot = result.snapshot
                stamp = (snapshot.frame_no, snapshot.simulation_time_us, snapshot.wall_time_us)
                if first_snapshot is None:
                    first_snapshot = stamp
                last_snapshot = stamp
                deltas.append(snapshot.delta_seconds)
                record = snapshot.research_record
                if record is not None:
                    last_research = (
                        int(record['imu_frame_no']),
                        int(record['imu_simulation_time_us']),
                        int(record['gnss_frame_no']),
                        int(record['gnss_simulation_time_us']),
                    )
                if writer is not None:
                    writer.enqueue(driving.to_frame_row(cfg.session_id))
                if time.monotonic() - last_telemetry >= TELEMETRY_INTERVAL:
                    channel.publish_telemetry(driving.to_telemetry_snapshot(sequence))
                    sequence += 1
                    last_telemetry = time.monotonic()
            if not self.running:
                break
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        if first_snapshot is not None and last_snapshot is not None:
            self._log_summary(first_snapshot, last_snapshot, loop_frames, deltas, exchange_ms, last_research)

    def _log_summary(
        self,
        first: tuple[int, int, int],
        last: tuple[int, int, int],
        rows: int,
        deltas: list[float],
        exchange_ms: list[float],
        research: tuple[int, int, int, int] | None,
    ) -> None:
        sim_seconds = (last[1] - first[1]) / 1e6
        wall_seconds = (last[2] - first[2]) / 1e6
        frames = last[0] - first[0]
        ratio = sim_seconds / wall_seconds if wall_seconds > 0 else 0.0
        world_fps = frames / sim_seconds if sim_seconds > 0 else 0.0
        sample_fps = rows / wall_seconds if wall_seconds > 0 else 0.0
        server_fps = 1 / statistics.median(deltas) if deltas else 0.0
        logger.info(
            '实验采样汇总：frames {}→{} 行 {}；sim {:.3f}s wall {:.3f}s 比 {:.4f}；'
            'world {:.2f}fps server {:.2f}fps 采样 {:.2f}fps；exchange 中位 {:.1f}ms；'
            '末帧 imu {}/{} gnss {}/{}'.format(
                first[0],
                last[0],
                rows,
                sim_seconds,
                wall_seconds,
                ratio,
                world_fps,
                server_fps,
                sample_fps,
                statistics.median(exchange_ms) if exchange_ms else 0.0,
                research[0] if research else -1,
                research[1] if research else -1,
                research[2] if research else -1,
                research[3] if research else -1,
            )
        )

    def _operations(self, commands: list[LauncherCommand]) -> tuple[list[dict[str, Any]], dict[int, str]]:
        operations: list[dict[str, Any]] = []
        command_ids: dict[int, str] = {}
        for command in commands:
            if isinstance(command, StopCommand):
                self.running = False
                break
            operation = self._operation(command)
            if operation is None:
                continue
            command_ids[len(operations)] = command.command_id
            operations.append(operation)
        return operations, command_ids

    def _operation(self, command: LauncherCommand) -> dict[str, Any] | None:
        if isinstance(command, SetWeatherCommand):
            return {'method': 'scene.set_weather', 'params': to_payload(command.weather)}
        if isinstance(command, UpdateCameraCommand):
            return {
                'method': 'driving_view.update',
                'params': {'cameras': {command.camera_name: command.mount.model_dump(mode='json')}},
            }
        if isinstance(command, UpdateLayoutCommand):
            return {
                'method': 'driving_view.update',
                'params': {'layout': command.layout.model_dump(mode='json')},
            }
        if isinstance(command, SetTakeoverCommand):
            if not command.enabled:
                logger.info('接管请求已取消，驾驶人保持当前控制模式')
                return None
            return self._manual_operation()
        if isinstance(command, SetAutopilotCommand):
            if command.enabled:
                logger.error(f'{AUTOPILOT_UNAVAILABLE}，自动驾驶指令已拒绝，实验继续进行')
                return None
            return self._manual_operation()
        raise ValueError(f'未知的驾驶端命令：{command}')

    def _manual_operation(self) -> dict[str, Any] | None:
        if self.control_mode == 'manual':
            logger.info('主车已处于人工驾驶，无需切换控制模式')
            return None
        return {
            'method': 'vehicle.set_mode',
            'params': {
                'actor_id': self.ego_actor_id,
                'mode': 'manual',
                'controller': 'human',
                'expected_control_revision': self.control_revision,
            },
        }

    def _apply_control_state(
        self, control_state: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None
    ) -> None:
        for item in control_state or ():
            if int(item.get('actor_id', 0)) != self.ego_actor_id:
                continue
            self.control_revision = int(item.get('revision', 0))
            self.control_mode = str(item.get('mode', ''))

    def _forward_events(
        self,
        channel: WorkerWSClient,
        result: ExchangeResult,
        command_ids: dict[int, str],
    ) -> None:
        for raw in result.events:
            request_id = raw.get('request_id')
            index = raw.get('operation_index')
            command_id = None
            if request_id is not None and index is not None and int(request_id) == result.request_id:
                command_id = command_ids.get(int(index))
            source = str(raw['source'])
            if command_id is not None and source == 'model':
                source = 'launcher'
            self._emit(channel, raw, command_id=command_id, source=source)
        for outcome in result.outcomes:
            if outcome.superseded:
                logger.info(f'控制请求被跳过：{outcome.error.get("message", "")}')

    def _emit(
        self,
        channel: WorkerWSClient,
        raw: dict[str, Any],
        *,
        command_id: str | None,
        source: str,
    ) -> None:
        event = map_event(raw, command_id=command_id, source=source)
        if event.name == 'driver_request':
            logger.error(f'{AUTOPILOT_UNAVAILABLE}，驾驶人请求切换自动化，当前模式保持不变')
        if event.name == 'lane_invasion':
            markings = (raw.get('payload') or {}).get('markings') or ()
            self.invaded_lane_marking = ', '.join(str(item) for item in markings)
        channel.send_event(event)
