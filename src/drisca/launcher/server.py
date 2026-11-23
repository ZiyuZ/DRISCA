"""管理端 HTTP 与实时通信接口。"""

import asyncio
import json
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drisca.core.config import (
    KEYBOARD_KEY_LABELS,
    WHEEL_BUTTON_LABELS,
    CameraConfig,
    ControlConfig,
    DisplayLayoutConfig,
    MachineConfig,
    PresetConfig,
    RunSettings,
    WeatherConfig,
    list_presets,
    load_preset,
    save_control_config,
    save_machine_config,
    save_preset,
)
from drisca.core.paths import PRESETS_DIR, PROJECT_ROOT
from drisca.core.protocol import (
    SetWeatherCommand,
    UpdateCameraCommand,
    UpdateLayoutCommand,
    parse_worker_event,
)
from drisca.core.tools import query_recorder_info, replay_recorder
from drisca.core.weather import resolve_weather, to_config, to_payload
from drisca.launcher.commands import COMMANDS, MODELS
from drisca.launcher.runtime import Runtime


class StartRequest(BaseModel, frozen=True):
    preset_name: str
    run: RunSettings


class NoteRequest(BaseModel, frozen=True):
    note: str


class MarkerRequest(BaseModel, frozen=True):
    label: str


class EnabledRequest(BaseModel, frozen=True):
    enabled: bool


class MapRequest(BaseModel, frozen=True):
    map_name: str


class CarlaStartRequest(BaseModel, frozen=True):
    kind: Literal['editor', 'packaged'] | None = None


class SessionSelectionRequest(BaseModel, frozen=True):
    session_ids: list[str]


class RecordingRequest(BaseModel, frozen=True):
    name: str


class ReplayRequest(RecordingRequest):
    start_time: float
    duration: float
    time_factor: float
    follow_actor_id: int


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(asyncio.get_running_loop())
        app.state.runtime.update(carla_connecting=True)
        app.state.runtime.background(app.state.runtime.connect)
        yield
        runtime = app.state.runtime
        await runtime.shutdown()
        runtime.job.Close()

    app = FastAPI(lifespan=lifespan)

    @app.middleware('http')
    async def world_loading(request: Request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE') and rt().state['world_loading']:
            return JSONResponse(status_code=409, content={'detail': '正在加载世界，请稍候'})
        return await call_next(request)

    @app.exception_handler(Exception)
    async def report_error(request: Request, exc: Exception):
        app.state.runtime.log(str(exc), 'ERROR')
        return JSONResponse(status_code=500, content={'detail': str(exc)})

    def rt() -> Runtime:
        return app.state.runtime

    def ensure_idle() -> None:
        if rt().state['world_loading']:
            raise HTTPException(409, '正在加载世界，请稍候')
        if rt().state['phase'] != 'idle':
            raise HTTPException(409, '实验正在运行')

    def ensure_running() -> None:
        if rt().state['phase'] != 'running':
            raise HTTPException(409, '实验尚未运行')

    def safe_name(name: str) -> str:
        if not name or name in ('.', '..') or Path(name).name != name or '/' in name or '\\' in name:
            raise HTTPException(400, '名称无效')
        return name

    def recorder(name: str) -> Path:
        path = (PROJECT_ROOT / rt().machine.recorder_dir / safe_name(name)).resolve()
        if not path.is_file():
            raise HTTPException(404, '录像不存在')
        return path

    @app.get('/api/bootstrap')
    def bootstrap():
        host = socket.gethostbyname(socket.gethostname())
        port = rt().launcher_port
        base = f'http://{host}:{port}'
        return {
            'machine': rt().machine,
            'control': rt().control,
            'presets': [{'name': name, 'config': load_preset(name)} for name in list_presets()],
            'commands': COMMANDS,
            'keyboard_labels': KEYBOARD_KEY_LABELS,
            'wheel_labels': WHEEL_BUTTON_LABELS,
            'state': rt().state,
            'logs': list(rt().logs),
            'events': list(rt().events),
            'urls': {'console': base, 'hud': base + '/hud'},
        }

    @app.get('/api/status')
    def status():
        return rt().state

    @app.get('/api/logs')
    def logs():
        return list(rt().logs)

    @app.post('/api/carla/start')
    async def start_carla(request: CarlaStartRequest):
        ensure_idle()
        if rt().state['unreal']['phase'] in ('starting', 'running', 'stopping'):
            raise HTTPException(409, 'Unreal 已启动或正在处理进程操作')
        if rt().state['carla_connecting'] or rt().state['carla_connected']:
            raise HTTPException(409, '请先关闭已连接的 CARLA，再启动本机程序')
        kind = request.kind or rt().machine.carla_runtime.kind
        rt().carla_closed.clear()
        rt().update(
            unreal={'phase': 'starting', 'pid': None, 'kind': kind},
            carla_connecting=True,
            error=None,
        )
        rt().background(rt().start_carla, kind)
        return {'ok': True, 'unreal': rt().state['unreal']}

    @app.post('/api/carla/stop')
    async def stop_carla():
        ensure_idle()
        if rt().carla_process is None or rt().state['unreal']['phase'] not in ('starting', 'running'):
            raise HTTPException(409, 'Launcher 当前没有可关闭的 Unreal 进程')
        rt().update(unreal={**rt().state['unreal'], 'phase': 'stopping'})
        rt().background(rt().stop_carla)
        return {'ok': True}

    @app.put('/api/config/machine')
    def machine(config: MachineConfig):
        ensure_idle()
        if rt().state['carla_connecting']:
            raise HTTPException(409, '正在连接 CARLA')
        connection_changed = (
            rt().machine.carla != config.carla or rt().machine.driving_view != config.driving_view
        )
        if rt().carla_process is not None and connection_changed:
            raise HTTPException(409, '请先关闭 Unreal，再修改 CARLA 与原生接口连接参数')
        save_machine_config(config)
        rt().machine = config
        if connection_changed:
            rt().close_api()
            rt().update(
                carla_connected=False,
                carla_detail='',
                catalog={
                    'maps': [],
                    'vehicles': [],
                    'map_name': None,
                    'spawn_points': [],
                    'weather_presets': {},
                },
            )
        return config

    @app.put('/api/config/control')
    def control(config: ControlConfig):
        ensure_idle()
        save_control_config(config)
        rt().control = config
        return config

    @app.put('/api/presets/{name}')
    def preset(name: str, config: PresetConfig):
        safe_name(name)
        for instruction in config.instructions:
            try:
                MODELS[instruction.command].model_validate(instruction.params)
            except (KeyError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
        save_preset(name, config)
        return {'name': name, 'config': config}

    @app.delete('/api/presets/{name}')
    def delete_preset(name: str):
        path = PRESETS_DIR / f'{safe_name(name)}.toml'
        if not path.is_file():
            raise HTTPException(404, '预设不存在')
        path.unlink()
        return {'ok': True}

    @app.post('/api/connect')
    def connect():
        ensure_idle()
        if rt().state['carla_connecting']:
            raise HTTPException(409, '正在连接 CARLA')
        rt().update(carla_connecting=True, carla_connected=False)
        rt().background(rt().connect)
        return {'ok': True}

    @app.post('/api/experiment/start')
    def start(request: StartRequest):
        ensure_idle()
        if rt().state['carla_connecting'] or not rt().state['carla_connected']:
            raise HTTPException(409, 'CARLA 尚未连接')
        config = load_preset(safe_name(request.preset_name))
        if config.ego.init_autopilot:
            raise HTTPException(409, '自动驾驶尚未实现，请在预设中关闭启动即自动驾驶')
        problem = rt().spawn_point_problem(config)
        if problem is not None:
            raise HTTPException(409, problem)
        rt().update(
            phase='starting', worker_state='starting', error=None, active_preset_name=request.preset_name
        )
        rt().background(rt().start, config, request.run)
        return {'ok': True}

    @app.post('/api/world/map')
    async def load_map(request: MapRequest):
        ensure_idle()
        if rt().state['carla_connecting'] or not rt().state['carla_connected']:
            raise HTTPException(409, 'CARLA 尚未连接')
        if request.map_name not in rt().state['catalog']['maps']:
            raise HTTPException(422, '请选择服务器提供的地图')
        rt().update(world_loading=True, error=None)
        rt().background(rt().load_world, request.map_name)
        return {'ok': True}

    @app.post('/api/experiment/stop')
    def stop():
        if rt().state['phase'] not in ('starting', 'running'):
            raise HTTPException(409, '实验未启动或正在结束')
        rt().update(phase='stopping', worker_state='stopping')
        rt().background(rt().stop)
        return {'ok': True}

    @app.put('/api/sessions/{session_id}/note')
    def session_note(session_id: str, request: NoteRequest):
        db = rt().db()
        try:
            if not any(row.session_id == session_id for row in db.list_sessions()):
                raise HTTPException(404, '会话不存在')
            db.update_session_note(session_id, request.note)
        finally:
            db.close()
        return {'ok': True}

    @app.post('/api/instructions/{instruction_id}/execute')
    def execute(instruction_id: str):
        ensure_running()
        cfg = rt().run_config
        assert cfg is not None
        instruction = next((item for item in cfg.preset.instructions if item.id == instruction_id), None)
        if instruction is None:
            raise HTTPException(404, '指令不存在')
        if instruction.command == 'autopilot':
            raise HTTPException(409, '自动驾驶尚未实现，无法执行该指令')
        rt().background(rt().execute, instruction)
        return {'ok': True}

    @app.post('/api/markers')
    def marker(request: MarkerRequest):
        ensure_running()
        telemetry = rt().state['telemetry']
        rt().event(
            {
                'kind': 'custom_event',
                'name': 'custom',
                'source': 'launcher',
                'frame_no': telemetry['frame_no'] if telemetry else None,
                'timestamp': time.time(),
                'command_id': None,
                'payload': {'label': request.label},
            }
        )
        return {'ok': True}

    @app.post('/api/cameras/{name}')
    def camera(name: Literal['front', 'rear_top', 'rear_left', 'rear_right'], config: CameraConfig):
        ensure_running()
        rt().send(UpdateCameraCommand(command_id=uuid4().hex, camera_name=name, mount=config))
        return {'ok': True}

    @app.post('/api/display-layout')
    def display_layout(layout: DisplayLayoutConfig):
        ensure_running()
        rt().send(UpdateLayoutCommand(command_id=uuid4().hex, layout=layout))
        return {'ok': True}

    @app.post('/api/weather')
    def weather(config: WeatherConfig):
        if config.preset_name != 'Custom':
            config = resolve_weather(config, rt().weather_presets)
        if rt().state['phase'] == 'running':
            rt().send(SetWeatherCommand(command_id=uuid4().hex, weather=config))
        else:
            ensure_idle()
            api = rt().api
            if api is None or rt().state['carla_connecting']:
                raise HTTPException(409, 'CARLA 尚未连接')
            applied = api.environment_apply(to_payload(config))
            rt().update(
                weather=to_config(applied.current.weather, config.preset_name).model_dump(mode='json')
            )
        return {'ok': True}

    @app.get('/api/sessions')
    def sessions(start_date: str = '', end_date: str = '', status: str = '', search: str = ''):
        db = rt().db()
        try:
            rows = db.list_sessions()
            items = []
            for row in rows:
                date = datetime.fromtimestamp(row.started_at).strftime('%Y-%m-%d')
                if (start_date and date < start_date) or (end_date and date > end_date):
                    continue
                if status and status != row.status:
                    continue
                if search.lower() not in (row.session_id + row.subject_id).lower():
                    continue
                items.append({**asdict(row), 'frame_count': db.count_session_frames(row.session_id)})
            return {'total': len(rows), 'items': items}
        finally:
            db.close()

    @app.get('/api/sessions/{session_id}')
    def session(session_id: str):
        db = rt().db()
        try:
            row = next((item for item in db.list_sessions() if item.session_id == session_id), None)
            if row is None:
                raise HTTPException(404, '会话不存在')
            return {
                'session': asdict(row),
                'events': [asdict(e) for e in db.list_session_events(session_id)],
                'frame_count': db.count_session_frames(session_id),
                'run_config': json.loads(row.run_config_json),
            }
        finally:
            db.close()

    @app.post('/api/sessions/delete')
    def delete_sessions(request: SessionSelectionRequest):
        if not request.session_ids:
            raise HTTPException(422, '请选择会话')
        if rt().state['session_id'] in request.session_ids:
            raise HTTPException(409, '请先结束选中的实验')
        if rt().state['export']['running']:
            raise HTTPException(409, '请等待当前导出完成')
        db = rt().db()
        try:
            db.delete_sessions(request.session_ids)
        finally:
            db.close()
        return {'ok': True}

    @app.post('/api/export')
    def export(request: SessionSelectionRequest):
        if not request.session_ids:
            raise HTTPException(422, '请选择会话')
        if rt().state['export']['running']:
            raise HTTPException(409, '正在导出')
        rt().update(export={'running': True, 'progress': 0, 'path': None, 'error': None})

        def work():
            path = (
                PROJECT_ROOT / rt().machine.export_dir / f'{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}'
            ).resolve()
            try:
                db = rt().db()
                try:
                    existing = {row.session_id for row in db.list_sessions()}
                    if not set(request.session_ids) <= existing:
                        raise ValueError('选中的会话不存在')
                    db.export_sessions(
                        path,
                        request.session_ids,
                        lambda progress: rt().update(
                            export={
                                'running': True,
                                'progress': progress,
                                'path': str(path),
                                'error': None,
                            }
                        ),
                    )
                finally:
                    db.close()
                rt().update(export={'running': False, 'progress': 100, 'path': str(path), 'error': None})
            except Exception as exc:
                rt().update(export={'running': False, 'progress': 0, 'path': None, 'error': str(exc)})
                raise

        rt().background(work)
        return {'ok': True}

    @app.get('/api/recordings')
    def recordings(search: str = '', page: int = 1, page_size: int = 20):
        if page < 1 or page_size < 1:
            raise HTTPException(422, '分页参数无效')
        directory = PROJECT_ROOT / rt().machine.recorder_dir
        paths = sorted(
            (p for p in directory.glob('*.rec') if search.lower() in p.name.lower()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return {
            'total': len(paths),
            'items': [
                {'name': p.name, 'size_bytes': p.stat().st_size, 'modified_at': p.stat().st_mtime}
                for p in paths[(page - 1) * page_size : page * page_size]
            ],
        }

    @app.post('/api/recordings/info')
    def recording_info(request: RecordingRequest):
        api = rt().api
        if api is None:
            raise HTTPException(409, 'CARLA 尚未连接')
        return {'text': query_recorder_info(api, recorder(request.name))}

    @app.post('/api/recordings/replay')
    def replay(request: ReplayRequest):
        ensure_idle()
        api = rt().api
        if api is None:
            raise HTTPException(409, 'CARLA 尚未连接')
        replay_recorder(
            api,
            recorder(request.name),
            request.start_time,
            request.duration,
            request.time_factor,
            request.follow_actor_id,
            ignore_hero=False,
        )
        return {'ok': True}

    @app.get('/api/events')
    async def events():
        async def stream():
            queue: asyncio.Queue = asyncio.Queue()
            rt().subscribers.add(queue)
            rt().client_connected('console', 1)
            try:
                yield (
                    'data: ' + json.dumps({'type': 'state', 'data': rt().state}, ensure_ascii=False) + '\n\n'
                )
                while True:
                    yield 'data: ' + json.dumps(await queue.get(), ensure_ascii=False) + '\n\n'
            finally:
                rt().subscribers.discard(queue)
                rt().client_connected('console', -1)

        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.get('/stream')
    async def hud_stream():
        async def stream():
            rt().client_connected('hud', 1)
            try:
                while True:
                    snapshot = rt().state['telemetry'] or {}
                    data = {
                        'running': rt().state['phase'] == 'running',
                        **{
                            key: snapshot.get(key, value)
                            for key, value in {
                                'speed_mps': 0,
                                'speed_limit_mps': 0,
                                'gear': 0,
                                'steer': 0,
                                'control_mode': 'manual',
                                'takeover_requested': False,
                            }.items()
                        },
                    }
                    yield 'data: ' + json.dumps(data) + '\n\n'
                    await asyncio.sleep(0.04)
            finally:
                rt().client_connected('hud', -1)

        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.websocket('/ws/worker/simulator')
    async def worker(socket: WebSocket):
        if rt().worker is not None or rt().state['phase'] not in ('starting', 'stopping'):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        rt().worker = queue
        rt().worker_closed.clear()
        if rt().stop_requested.is_set():
            from drisca.core.protocol import StopCommand, dump_launcher_command

            queue.put_nowait(dump_launcher_command(StopCommand(command_id=uuid4().hex)))

        async def send():
            while True:
                await socket.send_text(await queue.get())

        sender = asyncio.create_task(send())
        try:
            while True:
                event = parse_worker_event(await socket.receive_text())
                await asyncio.to_thread(rt().receive, event)
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            rt().worker = None
            rt().worker_closed.set()

    static = Path(__file__).parent / 'static'
    if static.is_dir():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

        @app.get('/{path:path}')
        def frontend(path: str):
            return FileResponse(static / 'index.html')

    return app
