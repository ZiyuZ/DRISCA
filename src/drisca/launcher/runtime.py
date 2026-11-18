"""实验编排与实时状态。"""

import asyncio
import json
import subprocess
import sys
import threading
import time
from collections import deque
from importlib.metadata import version
from typing import Any
from uuid import uuid4

import win32api  # ty: ignore[import-not-found]
import win32con
import win32job  # ty: ignore[import-not-found]

from drisca.core.client import CarlaSession
from drisca.core.config import (
    PresetConfig,
    RunSettings,
    WeatherConfig,
    compose_run_config,
    load_control_config,
    load_machine_config,
    write_run_config,
)
from drisca.core.paths import resolve_db_path
from drisca.core.protocol import (
    LogEvent,
    SetAutopilotCommand,
    SetTakeoverCommand,
    SetWeatherCommand,
    StopCommand,
    TelemetrySnapshotEvent,
    WorkerReadyEvent,
    WorkerStatusEvent,
    dump_launcher_command,
)
from drisca.core.weather import from_carla_weather, to_carla_weather
from drisca.launcher.commands import MODELS
from drisca.storage.db import StorageDB
from drisca.storage.models import SCHEMA_VERSION, EventRow, SessionRow, SessionStatus


class Runtime:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.machine = load_machine_config()
        self.launcher_host = self.machine.service.launcher_host
        self.launcher_port = self.machine.service.launcher_port
        self.control = load_control_config()
        self.carla: CarlaSession | None = None
        self.run_config = None
        self.process: subprocess.Popen | None = None
        self.worker: asyncio.Queue[str] | None = None
        self.worker_closed = threading.Event()
        self.stop_requested = threading.Event()
        self.subscribers: set[asyncio.Queue] = set()
        self.logs: deque = deque(maxlen=500)
        self.events: deque = deque(maxlen=500)
        self.state: dict[str, Any] = {
            'phase': 'idle',
            'carla_connected': False,
            'carla_connecting': False,
            'world_loading': False,
            'clients': {'console': 0, 'hud': 0},
            'carla_detail': '',
            'worker_state': 'stopped',
            'session_id': None,
            'active_preset': None,
            'active_preset_name': None,
            'active_run': None,
            'telemetry': None,
            'cameras': None,
            'weather': None,
            'display_layout': None,
            'vehicle_box': None,
            'error': None,
            'catalog': {'maps': [], 'vehicles': [], 'map_name': None, 'spawn_points': []},
            'export': {'running': False, 'progress': 0, 'path': None, 'error': None},
        }
        self.job = win32job.CreateJobObject(None, '')
        info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
        path = resolve_db_path(self.machine.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = StorageDB(path)
        db.abort_stale_running_sessions()
        db.close()

    def emit(self, kind: str, data) -> None:
        message = {'type': kind, 'data': data}

        def send() -> None:
            for queue in tuple(self.subscribers):
                queue.put_nowait(message)

        self.loop.call_soon_threadsafe(send)

    def update(self, **changes) -> None:
        self.state.update(changes)
        self.emit('state', self.state.copy())

    def log(self, message: str, level: str = 'INFO') -> None:
        item = {
            'type': 'log',
            'role': 'simulator',
            'timestamp': time.time(),
            'level': level,
            'message': message,
            'command_id': None,
        }
        self.logs.append(item)
        self.emit('log', item)

    def background(self, function, *args) -> None:
        def run() -> None:
            try:
                function(*args)
            except Exception as exc:
                self.log(str(exc), 'ERROR')
                self.update(error=str(exc))

        threading.Thread(target=run, daemon=True).start()

    def db(self) -> StorageDB:
        path = resolve_db_path(self.machine.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return StorageDB(path)

    def connect(self) -> None:
        try:
            session = CarlaSession(self.machine.carla)
            session.connect()
            check = session.preflight_check()
            if not check.ok:
                raise RuntimeError(check.error)
            self.carla = session
            self.refresh_world()
            self.update(
                carla_connected=True,
                carla_detail=f'{self.machine.carla.host}:{self.machine.carla.port}',
                error=None,
            )
        except Exception:
            self.carla = None
            self.update(carla_connected=False, carla_detail='连接失败')
            raise
        finally:
            self.update(carla_connecting=False)

    def refresh_world(self) -> None:
        assert self.carla is not None
        world = self.carla.world
        current_map = world.get_map()
        points = [
            dict(
                x=p.location.x,
                y=p.location.y,
                z=p.location.z,
                pitch=p.rotation.pitch,
                yaw=p.rotation.yaw,
                roll=p.rotation.roll,
            )
            for p in current_map.get_spawn_points()
        ]
        catalog = {
            'maps': sorted(self.carla.client.get_available_maps()),
            'vehicles': sorted(bp.id for bp in world.get_blueprint_library().filter('vehicle.*')),
            'map_name': current_map.name,
            'spawn_points': points,
        }
        self.update(catalog=catalog, weather=from_carla_weather(world.get_weather()).model_dump(mode='json'))

    def load_world(self, map_name: str) -> None:
        assert self.carla is not None
        try:
            self.carla.client.load_world(map_name)
            self.refresh_world()
            self.log(f'地图已加载：{map_name}')
        except Exception:
            self.carla = None
            self.update(carla_connected=False, carla_detail='地图加载失败')
            raise
        finally:
            self.update(world_loading=False)

    async def shutdown(self) -> None:
        if self.state['phase'] != 'idle':
            await asyncio.to_thread(self.stop)
            while self.state['phase'] != 'idle':
                await asyncio.sleep(0.05)

    def client_connected(self, role: str, delta: int) -> None:
        clients = dict(self.state['clients'])
        clients[role] += delta
        self.update(clients=clients)

    def event(self, item: dict) -> None:
        self.events.append(item)
        self.emit('experiment_event', item)
        cfg = self.run_config
        if cfg is not None and cfg.run.save_data:
            db = self.db()
            try:
                db.append_events(
                    [
                        EventRow(
                            cfg.session_id,
                            item.get('command_id'),
                            item.get('frame_no'),
                            item['timestamp'],
                            item['kind'],
                            item['name'],
                            item['source'],
                            json.dumps(item.get('payload', {}), ensure_ascii=False),
                        )
                    ]
                )
            finally:
                db.close()

    def lifecycle(self, name: str) -> None:
        self.event(
            {
                'kind': 'run_lifecycle',
                'name': name,
                'source': 'launcher',
                'frame_no': None,
                'timestamp': time.time(),
                'command_id': None,
                'payload': {},
            }
        )

    def start(self, preset: PresetConfig, run: RunSettings) -> None:
        assert self.carla is not None
        try:
            for instruction in preset.instructions:
                MODELS[instruction.command].model_validate(instruction.params)
            machine = self.machine.model_copy(
                update={
                    'service': self.machine.service.model_copy(
                        update={
                            'launcher_host': self.launcher_host,
                            'launcher_port': self.launcher_port,
                        }
                    )
                }
            )
            cfg = compose_run_config(machine, self.control, preset, run)
            self.run_config = cfg
            if run.save_data:
                db = self.db()
                try:
                    db.create_session(
                        SessionRow(
                            cfg.session_id,
                            SessionStatus.RUNNING,
                            time.time(),
                            None,
                            version('drisca'),
                            SCHEMA_VERSION,
                            preset.world.map_name,
                            None,
                            preset.ego.role_name,
                            None,
                            run.subject_id,
                            cfg.model_dump_json(),
                            run.note,
                        )
                    )
                finally:
                    db.close()
            self.update(
                session_id=cfg.session_id,
                active_preset=cfg.preset.model_dump(mode='json'),
                active_run=cfg.run.model_dump(mode='json'),
                cameras=cfg.preset.cameras.model_dump(mode='json'),
                display_layout=cfg.machine.display.layout.model_dump(mode='json'),
                weather=from_carla_weather(
                    to_carla_weather(cfg.preset.world.weather), cfg.preset.world.weather.preset_name
                ).model_dump(mode='json'),
            )
            self.lifecycle('session_start')
            self.update(world_loading=True)
            try:
                self.carla.prepare_world(preset.world)
                self.refresh_world()
            finally:
                self.update(world_loading=False)
            if self.stop_requested.is_set():
                self.finish(False)
                return
            path = write_run_config(cfg)
            self.process = subprocess.Popen(
                [sys.executable, '-m', 'drisca.simulator', '--config', str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, self.process.pid)
            try:
                win32job.AssignProcessToJobObject(self.job, handle)
            finally:
                handle.Close()
            self.background(self.read_output, self.process)
            if self.stop_requested.is_set():
                self.background(self.stop)
            code = self.process.wait()
            drained = True
            if self.worker is not None:
                drained = self.worker_closed.wait(timeout=15)
            normal = code == 0 and drained
            if not normal:
                self.log(f'驾驶端异常退出：{code}', 'ERROR')
            self.finish(normal)
        except Exception:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                self.process.wait()
            if self.worker is not None:
                self.worker_closed.wait(timeout=15)
            if self.run_config is not None:
                self.finish(False)
            else:
                self.update(phase='idle', worker_state='error', session_id=None, active_preset_name=None)
            raise

    def read_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.log(line.rstrip())

    def finish(self, normal: bool) -> None:
        cfg = self.run_config
        reset_error: Exception | None = None
        try:
            if self.carla is not None:
                try:
                    self.carla.force_reset_after_experiment()
                except Exception as exc:
                    normal = False
                    reset_error = exc
            if cfg is not None:
                self.lifecycle('session_end' if normal else 'session_aborted')
                if cfg.run.save_data:
                    db = self.db()
                    try:
                        db.finish_session(
                            cfg.session_id,
                            SessionStatus.COMMITTED if normal else SessionStatus.ABORTED,
                            time.time(),
                        )
                    finally:
                        db.close()
        finally:
            self.run_config = None
            self.process = None
            self.stop_requested.clear()
            self.update(
                phase='idle',
                worker_state='stopped' if normal else 'error',
                session_id=None,
                active_preset=None,
                active_preset_name=None,
                active_run=None,
                telemetry=None,
                vehicle_box=None,
            )
        if reset_error is not None:
            raise reset_error

    def stop(self) -> None:
        self.stop_requested.set()
        if self.worker is not None:
            self.send(StopCommand(command_id=uuid4().hex))
        if self.run_config is not None:
            self.lifecycle('stop_requested')
        process = self.process
        if process is not None:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()

    def send(self, command) -> None:
        if self.worker is None:
            raise RuntimeError('驾驶端尚未连接')
        self.loop.call_soon_threadsafe(self.worker.put_nowait, dump_launcher_command(command))

    def receive(self, event) -> None:
        if isinstance(event, TelemetrySnapshotEvent):
            self.update(telemetry=event.model_dump(mode='json'))
        elif isinstance(event, WorkerReadyEvent):
            cfg = self.run_config
            if cfg is not None and cfg.run.save_data:
                db = self.db()
                try:
                    db.update_session_ego(cfg.session_id, event.ego_actor_id, event.ego_type_id)
                finally:
                    db.close()
            self.update(
                phase='stopping' if self.stop_requested.is_set() else 'running',
                worker_state='stopping' if self.stop_requested.is_set() else 'running',
                vehicle_box=event.vehicle_box,
            )
        elif isinstance(event, WorkerStatusEvent):
            self.update(worker_state=event.state.value)
            self.event(
                {
                    'kind': 'worker_status',
                    'name': event.state.value,
                    'source': 'system',
                    'frame_no': None,
                    'timestamp': time.time(),
                    'command_id': None,
                    'payload': {'role': event.role.value, 'detail': event.detail},
                }
            )
        elif isinstance(event, LogEvent):
            item = event.model_dump(mode='json')
            self.logs.append(item)
            self.emit('log', item)
        else:
            item = event.model_dump(mode='json')
            if item['name'] == 'update_camera':
                cameras = dict(self.state['cameras'])
                cameras[item['payload']['camera_name']] = item['payload']['mount']
                self.update(cameras=cameras)
            elif item['name'] == 'update_layout':
                self.update(display_layout=item['payload'])
            elif item['name'] == 'set_weather':
                weather = WeatherConfig.model_validate(item['payload']['weather'])
                self.update(
                    weather=from_carla_weather(to_carla_weather(weather), weather.preset_name).model_dump(
                        mode='json'
                    )
                )
            self.event(item)

    def execute(self, instruction) -> None:
        params: Any = MODELS[instruction.command].model_validate(instruction.params)
        command_id = uuid4().hex
        if instruction.command == 'autopilot':
            self.send(SetAutopilotCommand(command_id=command_id, enabled=params.enabled))
        elif instruction.command == 'takeover':
            self.send(SetTakeoverCommand(command_id=command_id, enabled=params.enabled))
            self.speak(params.speech, command_id)
        elif instruction.command == 'weather':
            self.send(
                SetWeatherCommand(command_id=command_id, weather=WeatherConfig(preset_name=params.preset))
            )
        elif instruction.command == 'speech':
            self.speak(params.text, command_id)

    def speak(self, text: str, command_id: str) -> None:
        if self.machine.service.enable_tts:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                voice = win32com.client.Dispatch('SAPI.SpVoice')
                self._speech_event(text, command_id)
                voice.Speak(text)
            finally:
                pythoncom.CoUninitialize()

    def _speech_event(self, text: str, command_id: str) -> None:
        self.event(
            {
                'kind': 'operator_action',
                'name': 'speech',
                'source': 'launcher',
                'frame_no': None,
                'timestamp': time.time(),
                'command_id': command_id,
                'payload': {'text': text},
            }
        )
