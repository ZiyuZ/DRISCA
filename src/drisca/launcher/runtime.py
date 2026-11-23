"""实验编排与实时状态。"""

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from importlib.metadata import version
from typing import Any, Literal
from uuid import uuid4

import win32api  # ty: ignore[import-not-found]
import win32con
import win32job  # ty: ignore[import-not-found]

from drisca.core.client import NativeApiClient, NativeApiError
from drisca.core.config import (
    PresetConfig,
    RunSettings,
    WeatherConfig,
    WorldConfig,
    compose_run_config,
    load_control_config,
    load_machine_config,
    write_run_config,
)
from drisca.core.paths import resolve_db_path
from drisca.core.protocol import (
    LogEvent,
    SetTakeoverCommand,
    SetWeatherCommand,
    StopCommand,
    TelemetrySnapshotEvent,
    WorkerReadyEvent,
    WorkerStatusEvent,
    dump_launcher_command,
)
from drisca.core.weather import from_payload, to_payload
from drisca.launcher.commands import MODELS
from drisca.launcher.unreal import launch_arguments
from drisca.storage.db import StorageDB
from drisca.storage.models import SCHEMA_VERSION, EventRow, SessionRow, SessionStatus


class Runtime:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.machine = load_machine_config()
        self.launcher_host = self.machine.service.launcher_host
        self.launcher_port = self.machine.service.launcher_port
        self.control = load_control_config()
        self.api: NativeApiClient | None = None
        self.weather_presets: dict[str, WeatherConfig] = {}
        self.run_config = None
        self.process: subprocess.Popen | None = None
        self.carla_process: subprocess.Popen | None = None
        self.carla_closed = threading.Event()
        self.carla_closed.set()
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
            'unreal': {'phase': 'stopped', 'pid': None, 'kind': None},
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
            'catalog': {
                'maps': [],
                'vehicles': [],
                'map_name': None,
                'spawn_points': [],
                'weather_presets': {},
            },
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

    def assign_process(self, process: subprocess.Popen) -> None:
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, process.pid)
        try:
            win32job.AssignProcessToJobObject(self.job, handle)
        finally:
            handle.Close()

    def start_carla(self, kind: Literal['editor', 'packaged']) -> None:
        process = None
        expected_stop = False
        try:
            args, directory = launch_arguments(self.machine, kind)
            if self.state['unreal']['phase'] == 'stopping':
                expected_stop = True
                return
            ports = (self.machine.carla.port, self.machine.carla.port + 1, self.machine.driving_view.port)
            if len(set(ports)) != len(ports):
                raise ValueError('CARLA RPC、流传输与驾驶接口端口应各不相同')
            for port in ports:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
            process = subprocess.Popen(
                args,
                cwd=directory,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.carla_process = process
            self.assign_process(process)
            self.update(unreal={'phase': 'starting', 'pid': process.pid, 'kind': kind})
            deadline = time.monotonic() + self.machine.carla_runtime.startup_timeout
            while True:
                if self.state['unreal']['phase'] == 'stopping':
                    expected_stop = True
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        f'Unreal 启动期间退出：{process.returncode}，请查看 .cache/logs/carla-unreal.log'
                    )
                ready = True
                for port in (self.machine.carla.port, self.machine.driving_view.port):
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                            pass
                    except OSError:
                        ready = False
                        break
                if ready:
                    # 原生接口先于世界就绪开始监听，地图名称为空时按截止时间重试。
                    try:
                        self.connect(starting_unreal=True)
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise
                    else:
                        self.update(
                            unreal={'phase': 'running', 'pid': process.pid, 'kind': kind},
                            carla_connecting=False,
                        )
                        self.log(f'CARLA Unreal 已就绪：PID {process.pid}')
                        break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Unreal 启动超时，请查看 .cache/logs/carla-unreal.log')
                time.sleep(0.25)
            code = process.wait()
            expected_stop = expected_stop or self.state['unreal']['phase'] == 'stopping'
            if not expected_stop:
                raise RuntimeError(f'CARLA Unreal 已退出：{code}')
        except Exception:
            if process is not None and process.poll() is None:
                self._terminate_carla(process)
            self.update(unreal={'phase': 'error', 'pid': None, 'kind': kind})
            raise
        finally:
            self.carla_process = None
            self.close_api()
            changes: dict[str, Any] = {
                'carla_connected': False,
                'carla_connecting': False,
                'catalog': {
                    'maps': [],
                    'vehicles': [],
                    'map_name': None,
                    'spawn_points': [],
                    'weather_presets': {},
                },
            }
            if expected_stop:
                changes['unreal'] = {'phase': 'stopped', 'pid': None, 'kind': kind}
            self.update(**changes)
            self.carla_closed.set()

    def _terminate_carla(self, process: subprocess.Popen) -> None:
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process.wait()

    def stop_carla(self) -> None:
        process = self.carla_process
        self.close_api()
        self.update(carla_connected=False, carla_detail='')
        if process is not None and process.poll() is None:
            self._terminate_carla(process)
        if not self.carla_closed.wait(timeout=10):
            raise TimeoutError('Unreal 进程监视尚未结束')

    def _require_api(self) -> NativeApiClient:
        if self.api is None:
            raise RuntimeError('原生接口尚未连接')
        return self.api

    def close_api(self) -> None:
        api, self.api = self.api, None
        if api is not None:
            api.close()

    def connect(self, *, starting_unreal: bool = False) -> None:
        try:
            self.close_api()
            api = NativeApiClient(
                self.machine.driving_view,
                client='drisca-launcher',
                long_timeout=self.machine.carla_runtime.startup_timeout,
            )
            info = api.connect()
            if not info.map_name:
                api.close()
                raise RuntimeError('原生接口已连接，但世界尚未就绪')
            self.api = api
            self.refresh_world()
            self.update(
                carla_connected=True,
                carla_detail=f'{self.machine.driving_view.host}:{self.machine.driving_view.port}',
                error=None,
            )
        except Exception:
            self.close_api()
            if not starting_unreal:
                self.update(carla_connected=False, carla_detail='连接失败')
            raise
        finally:
            if not starting_unreal:
                self.update(carla_connecting=False)

    def refresh_world(self) -> None:
        api = self._require_api()
        catalog = api.catalog()
        points = []
        for point in catalog['spawn_points']:
            location, rotation = point['location'], point['rotation']
            points.append(
                {
                    'x': location[0],
                    'y': location[1],
                    'z': location[2],
                    'pitch': rotation[0],
                    'yaw': rotation[1],
                    'roll': rotation[2],
                }
            )
        self.weather_presets = {
            str(item['preset_name']): from_payload(item) for item in catalog['weather_presets']
        }
        self.update(
            catalog={
                'maps': sorted(str(name) for name in catalog['maps']),
                'vehicles': sorted(str(item['id']) for item in catalog['vehicle_blueprints']),
                'map_name': str(catalog['current_map']),
                'spawn_points': points,
                'weather_presets': {
                    name: config.model_dump(mode='json') for name, config in self.weather_presets.items()
                },
            },
            weather=from_payload(api.get_weather()).model_dump(mode='json'),
        )

    def load_world(self, map_name: str) -> None:
        api = self._require_api()
        try:
            result = api.load_map(map_name)
            self.log(f'地图已加载：{result.get("world_id")} {map_name}')
            self.refresh_world()
        except NativeApiError as exc:
            if exc.code == 'world_changed':
                self.close_api()
                self.update(carla_connected=False, carla_detail='世界标识已变化，请重新连接')
            raise
        finally:
            self.update(world_loading=False)

    def prepare_world(self, world_cfg: WorldConfig) -> None:
        api = self._require_api()
        current = str(self.state['catalog']['map_name'] or '')
        if world_cfg.load_map or current.rsplit('/', 1)[-1] != world_cfg.map_name.rsplit('/', 1)[-1]:
            api.load_map(world_cfg.map_name)
            self.refresh_world()
        applied = from_payload(api.set_weather(to_payload(world_cfg.weather)))
        self.update(weather=applied.model_dump(mode='json'))
        api.clear_actors()

    async def shutdown(self) -> None:
        if self.state['phase'] != 'idle':
            await asyncio.to_thread(self.stop)
            while self.state['phase'] != 'idle':
                await asyncio.sleep(0.05)
        if self.state['unreal']['phase'] in ('starting', 'running', 'stopping'):
            self.update(unreal={**self.state['unreal'], 'phase': 'stopping'})
            await asyncio.to_thread(self.stop_carla)

    def client_connected(self, role: str, delta: int) -> None:
        clients = dict(self.state['clients'])
        clients[role] += delta
        self.update(clients=clients)

    def event(self, item: dict) -> None:
        self.events.append(item)
        self.emit('experiment_event', item)
        cfg = self.run_config
        if cfg is not None and cfg.run.save_data:
            payload = dict(item.get('payload') or {})
            if item.get('native') is not None:
                payload['native'] = item['native']
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
                            json.dumps(payload, ensure_ascii=False),
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
        if self.api is None:
            raise RuntimeError('原生接口尚未连接')
        try:
            if preset.ego.init_autopilot:
                raise RuntimeError('自动驾驶尚未实现，请在预设中关闭启动即自动驾驶')
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
            cfg = compose_run_config(machine, self.control, preset, run, self.weather_presets)
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
                weather=cfg.preset.world.weather.model_dump(mode='json'),
            )
            self.lifecycle('session_start')
            self.update(world_loading=True)
            try:
                self.prepare_world(preset.world)
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
            self.assign_process(self.process)
            self.background(self.read_output, self.process)
            if self.stop_requested.is_set():
                self.background(self.stop)
            code = self.process.wait()
            drained = True
            if self.worker is not None:
                drained = self.worker_closed.wait(timeout=15)
            if code != 0:
                raise RuntimeError(f'驾驶端异常退出，退出码：{code}')
            if not drained:
                raise TimeoutError('驾驶端消息收尾超时')
            if not self.stop_requested.is_set():
                raise RuntimeError('驾驶端在实验停止请求前退出')
            if not self.state['carla_connected']:
                raise RuntimeError('实验期间 CARLA 连接已结束')
            self.finish(True)
        except Exception as exc:
            self.update(error=str(exc))
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
            if (
                self.api is not None
                and self.state['carla_connected']
                and (self.carla_process is None or self.carla_process.poll() is None)
            ):
                try:
                    self.api.clear_actors()
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
                weather = from_payload(item['payload']['weather'])
                self.update(weather=weather.model_dump(mode='json'))
            self.event(item)

    def execute(self, instruction) -> None:
        params: Any = MODELS[instruction.command].model_validate(instruction.params)
        command_id = uuid4().hex
        if instruction.command == 'autopilot':
            raise RuntimeError('自动驾驶尚未实现，无法提交该指令')
        if instruction.command == 'takeover':
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
