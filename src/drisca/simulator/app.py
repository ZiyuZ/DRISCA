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
    CreateFogRegionCommand,
    DeleteFogRegionCommand,
    LauncherCommand,
    SetAutopilotCommand,
    SetTakeoverCommand,
    SetViewModeCommand,
    SetWeatherCommand,
    StopCommand,
    TrafficActionCommand,
    UpdateCameraCommand,
    UpdateFogRegionCommand,
    UpdateLayoutCommand,
    WorkerReadyEvent,
    WorkerRole,
    WorkerState,
    WorkerStatusEvent,
)
from drisca.core.snapshot import Snapshot
from drisca.core.weather import to_payload
from drisca.simulator.events import map_event
from drisca.simulator.state import DrivingState, project_snapshot, research_ready
from drisca.simulator.ws_client import WorkerWSClient
from drisca.storage.writer import BatchDataWriter
from drisca.traffic import AutopilotController, RoadGraph, SignalTracker, TrafficManager, TrafficScene

SAMPLE_INTERVAL = 1 / 20
TELEMETRY_INTERVAL = 1 / 25


class SimulatorApp:
    def __init__(self, run_config: RunConfig) -> None:
        self.config = run_config
        self.running = True
        self.ego_actor_id = 0
        self.control_revision = 0
        self.control_mode = ''
        self.invaded_lane_marking = ''
        self.pending_environment: dict[tuple[int, int], str] = {}
        self.prepared_regions: set[int] = set()
        self.autopilot: AutopilotController | None = None
        self.traffic_manager: TrafficManager | None = None
        self.last_snapshot: Snapshot | None = None
        self.last_scene: TrafficScene | None = None
        self.last_driving: DrivingState | None = None
        self.last_traffic_lights: tuple[dict[str, Any], ...] = ()
        self.last_selected_actor_id: int | None = None
        self._pending_mode_toggle = False
        self._pending_init_autopilot = run_config.preset.ego.init_autopilot

    def run(self) -> None:
        cfg = self.config
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
        self._init_autopilot(api)
        self._create_fog_regions(api)
        view = api.start_view(
            session_id=cfg.session_id,
            ego_actor_id=ego_actor_id,
            cameras=cfg.preset.cameras.model_dump(mode='json'),
            layout=cfg.machine.display.layout.model_dump(mode='json'),
            keyboard=keyboard_mapping(cfg.control.keyboard),
            mode='manual',
            suppress_screen_messages=not cfg.machine.service.debug,
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
                fog_regions=api.environment_list(),
            )
        )
        channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.RUNNING))
        self._loop(api, channel, writer)
        final = api.stop_experiment(cfg.session_id)
        self._forward_raw(channel, final.get('events') or (), None, {})
        channel.send_event(WorkerStatusEvent(role=WorkerRole.SIMULATOR, state=WorkerState.STOPPING))

    def _init_autopilot(self, api: NativeApiClient) -> None:
        """从原生接口加载道路图与信号灯映射，构造主车自动驾驶与背景交通流管理器。"""
        raw_graph = api.road_graph_all(sampling_step=2.0)
        raw_signals = api.road_signals()
        graph = RoadGraph.from_native(raw_graph)
        signals = SignalTracker.from_native(raw_signals, graph)
        ego = self.config.preset.ego
        self.autopilot = AutopilotController(
            graph,
            signals,
            default_speed_limit_mps=ego.default_speed_limit,
            dynamic_speed_limit=ego.dynamic_speed_limit,
        )
        self.traffic_manager = TrafficManager(graph, signals, self.config.preset.traffic)
        sp = ego.spawn_point
        self.traffic_manager.spawn_background(
            api,
            ego_location=(sp.x, sp.y, sp.z),
            default_speed_limit_mps=ego.default_speed_limit,
        )
        logger.info(
            f'自研交通模块已初始化：车道数 {int(raw_graph.get("lane_count", 0))}，'
            f'背景车 {self.traffic_manager.vehicle_count} 辆'
        )

    def _create_fog_regions(self, api: NativeApiClient) -> None:
        """在 start_view 之前创建预设球雾，使区域随会话转入控制连接。"""
        for region in self.config.preset.world.fog_regions:
            result = api.environment_create(
                center_m=region.center_m,
                radius_m=region.radius_m,
                density=region.density,
                transition_seconds=region.transition_seconds,
            )
            self.prepared_regions.add(result.region_id)
            logger.info(f'局部球雾已创建：region_id {result.region_id}，半径 {region.radius_m:g} m')

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
            operations, command_ids = self._operations(channel.poll_commands(), api, channel)
            if not self.running and not operations:
                break
            mode_changed_in_batch = any(op.get('method') == 'vehicle.set_mode' for op in operations)
            if mode_changed_in_batch:
                # 收到显式模式切换命令时清空旧的待切换意图，避免下一帧意外反转模式
                self._pending_init_autopilot = False
                self._pending_mode_toggle = False
            if self.running and not mode_changed_in_batch:
                if self._pending_init_autopilot:
                    self._pending_init_autopilot = False
                    init_op = self._external_operation()
                    if init_op is not None:
                        operations.append(init_op)
                        mode_changed_in_batch = True
                elif self._pending_mode_toggle:
                    self._pending_mode_toggle = False
                    toggle_op = (
                        self._manual_operation()
                        if self.control_mode == 'external'
                        else self._external_operation()
                    )
                    if toggle_op is not None:
                        operations.append(toggle_op)
                        mode_changed_in_batch = True
            dt = (
                max(1e-3, 1.0 / self.last_driving.server_fps)
                if self.last_driving is not None and self.last_driving.server_fps > 0
                else SAMPLE_INTERVAL
            )
            if (
                self.running
                and not mode_changed_in_batch
                and self.control_mode == 'external'
                and self.autopilot is not None
                and self.last_driving is not None
            ):
                control = self.autopilot.step(
                    x=self.last_driving.location[0],
                    y=self.last_driving.location[1],
                    yaw_deg=self.last_driving.rotation[1],
                    speed_mps=self.last_driving.speed,
                    dt=dt,
                    road_id=self.last_driving.road_id,
                    lane_id=self.last_driving.lane_id,
                    road_speed_limit_mps=self.last_driving.speed_limit,
                    traffic_lights=self.last_traffic_lights,
                    scene=self.last_scene,
                    self_actor_id=self.ego_actor_id,
                )
                operations.append(control.to_operation(self.ego_actor_id, self.control_revision))
            if (
                self.running
                and self.traffic_manager is not None
                and self.last_snapshot is not None
                and self.last_scene is not None
            ):
                ego_xy = (
                    (self.last_driving.location[0], self.last_driving.location[1])
                    if self.last_driving is not None
                    else None
                )
                operations.extend(
                    self.traffic_manager.step_operations(
                        self.last_snapshot,
                        self.last_scene,
                        self.last_traffic_lights,
                        dt,
                        ego_xy=ego_xy,
                        selected_actor_id=self.last_selected_actor_id,
                    )
                )
            deadline = time.monotonic() + SAMPLE_INTERVAL
            started = time.monotonic()
            result = api.exchange(operations, session_id=cfg.session_id)
            exchange_ms.append((time.monotonic() - started) * 1000)
            self.last_traffic_lights = result.traffic_lights
            self.last_selected_actor_id = result.selected_actor_id
            self.last_snapshot = result.snapshot
            self.last_scene = TrafficScene.from_vehicles(result.snapshot.vehicles)
            self._apply_control_state(result.control_state)
            if self.running and self.traffic_manager is not None:
                ego_xy = (
                    (self.last_driving.location[0], self.last_driving.location[1])
                    if self.last_driving is not None
                    else None
                )
                self.traffic_manager.respawn_lost(
                    api,
                    ego_xy=ego_xy,
                    scene=self.last_scene,
                    default_speed_limit_mps=cfg.preset.ego.default_speed_limit,
                )
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
                self.invaded_lane_marking = ''
                self.last_driving = driving
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

    def _operations(
        self,
        commands: list[LauncherCommand],
        api: NativeApiClient,
        channel: WorkerWSClient,
    ) -> tuple[list[dict[str, Any]], dict[int, str]]:
        operations: list[dict[str, Any]] = []
        command_ids: dict[int, str] = {}
        for command in commands:
            if isinstance(command, StopCommand):
                self.running = False
                break
            if isinstance(command, TrafficActionCommand):
                self._run_traffic_action(command, api, channel)
                continue
            operation = self._operation(command)
            if operation is None:
                continue
            command_ids[len(operations)] = command.command_id
            operations.append(operation)
        return operations, command_ids

    def _run_traffic_action(
        self,
        command: TrafficActionCommand,
        api: NativeApiClient,
        channel: WorkerWSClient,
    ) -> None:
        if self.traffic_manager is None or self.last_driving is None:
            logger.error('交通流或主车状态尚未就绪，无法执行交通事件')
            return
        try:
            detail = self.traffic_manager.trigger_action(
                api,
                action=command.action,
                params=command.params,
                ego_actor_id=self.ego_actor_id,
                ego_x=self.last_driving.location[0],
                ego_y=self.last_driving.location[1],
                ego_yaw_deg=self.last_driving.rotation[1],
                ego_road_id=self.last_driving.road_id,
                ego_lane_id=self.last_driving.lane_id,
                scene=self.last_scene,
                traffic_lights=self.last_traffic_lights,
                default_speed_limit_mps=self.config.preset.ego.default_speed_limit,
                debug=self.config.machine.service.debug,
            )
            from drisca.core.protocol import CustomExperimentEvent, EventKind

            channel.send_event(
                CustomExperimentEvent(
                    kind=EventKind.OPERATOR_ACTION,
                    source='launcher',
                    frame_no=self.last_driving.frame_no,
                    timestamp=time.time(),
                    command_id=command.command_id,
                    payload={'label': f'traffic:{detail["action"]}', **detail},
                )
            )
        except Exception as exc:
            logger.error(f'交通事件 {command.action} 执行失败：{exc}')

    def _operation(self, command: LauncherCommand) -> dict[str, Any] | None:
        if isinstance(command, SetWeatherCommand):
            return {
                'method': 'environment.apply',
                'params': {
                    'weather': to_payload(command.weather),
                    'transition_seconds': command.transition_seconds,
                },
            }
        if isinstance(command, CreateFogRegionCommand):
            return {
                'method': 'environment.create',
                'params': {
                    'center_m': list(command.center_m),
                    'radius_m': command.radius_m,
                    'weather': {'fog': {'density': command.density}},
                    'transition_seconds': command.transition_seconds,
                },
            }
        if isinstance(command, UpdateFogRegionCommand):
            params: dict[str, Any] = {
                'region_id': command.region_id,
                'transition_seconds': command.transition_seconds,
            }
            if command.center_m is not None:
                params['center_m'] = list(command.center_m)
            if command.radius_m is not None:
                params['radius_m'] = command.radius_m
            if command.density is not None:
                params['weather'] = {'fog': {'density': command.density}}
            return {'method': 'environment.update', 'params': params}
        if isinstance(command, DeleteFogRegionCommand):
            return {
                'method': 'environment.delete',
                'params': {
                    'region_id': command.region_id,
                    'transition_seconds': command.transition_seconds,
                },
            }
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
        if isinstance(command, SetViewModeCommand):
            return {
                'method': 'driving_view.update',
                'params': {'view_mode': command.view_mode},
            }
        if isinstance(command, SetTakeoverCommand):
            if not command.enabled:
                logger.info('接管请求已取消，驾驶人保持当前控制模式')
                return None
            return self._manual_operation()
        if isinstance(command, SetAutopilotCommand):
            if command.enabled:
                return self._external_operation()
            return self._manual_operation()
        raise ValueError(f'未知的驾驶端命令：{command}')

    def _external_operation(self) -> dict[str, Any] | None:
        if self.control_mode == 'external':
            logger.info('主车已处于自动驾驶，无需切换控制模式')
            return None
        return {
            'method': 'vehicle.set_mode',
            'params': {
                'actor_id': self.ego_actor_id,
                'mode': 'external',
                'controller': 'python',
                'expected_control_revision': self.control_revision,
            },
        }

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
        if self.traffic_manager is not None:
            self.traffic_manager.apply_control_state(control_state)
        for item in control_state or ():
            if int(item.get('actor_id', 0)) != self.ego_actor_id:
                continue
            new_mode = str(item.get('mode', ''))
            if new_mode != self.control_mode and self.autopilot is not None:
                self.autopilot.reset()
            self.control_revision = int(item.get('revision', 0))
            self.control_mode = new_mode

    def _forward_events(
        self,
        channel: WorkerWSClient,
        result: ExchangeResult,
        command_ids: dict[int, str],
    ) -> None:
        self._forward_raw(channel, result.events, result.request_id, command_ids)
        for outcome in result.outcomes:
            if outcome.superseded:
                logger.info(f'控制请求被跳过：{outcome.error.get("message", "")}')

    def _forward_raw(
        self,
        channel: WorkerWSClient,
        events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        request_id: int | None,
        command_ids: dict[int, str],
    ) -> None:
        for raw in events:
            session_id = str(raw.get('session_id') or '')
            name = str(raw['name'])
            payload = raw.get('payload') or {}
            if not session_id:
                # 空 session 的外部管理旧事件过滤；本次 worker 在 start_view 前创建
                # 的准备区域事件保留，按 create 返回的 region_id 精确识别。
                region_id = payload.get('region_id')
                prepared = (
                    name.startswith('environment_')
                    and region_id is not None
                    and int(region_id) in self.prepared_regions
                )
                if not prepared:
                    continue
            elif session_id != self.config.session_id:
                raise RuntimeError(f'收到会话 {session_id} 的事件，当前会话 {self.config.session_id}')
            event_request = raw.get('request_id')
            index = raw.get('operation_index')
            key = (
                (int(event_request), int(index)) if event_request is not None and index is not None else None
            )
            source = str(raw['source'])
            command_id = None
            if name.startswith('environment_'):
                # request_id 按连接递增，不能跨连接视为唯一。只有当前控制 worker 的
                # 原生来源 model 事件才与本 worker 的指令关联；管理连接发起的同类
                # 事件照常记录，但不匹配本 worker 的 command 与未完成操作表。
                if source == 'model' and key is not None:
                    if request_id is not None and key[0] == request_id:
                        command_id = command_ids.get(key[1])
                    if command_id is None:
                        command_id = self.pending_environment.get(key)
                    if name in ('environment_completed', 'environment_replaced'):
                        self.pending_environment.pop(key, None)
                    if name == 'environment_applied' and command_id is not None:
                        if float(payload.get('transition_seconds') or 0) > 0:
                            self.pending_environment[key] = command_id
            elif key is not None and request_id is not None and key[0] == request_id:
                command_id = command_ids.get(key[1])
            if command_id is not None and source == 'model':
                source = 'launcher'
            self._emit(channel, raw, command_id=command_id, source=source)

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
            self._pending_mode_toggle = True
            logger.info('收到驾驶人自动驾驶切换请求，下一交换帧执行模式切换')
        if event.name == 'lane_invasion':
            markings = (raw.get('payload') or {}).get('markings') or ()
            self.invaded_lane_marking = ', '.join(str(item) for item in markings)
        channel.send_event(event)
