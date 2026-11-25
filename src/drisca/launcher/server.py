"""管理端 HTTP 与实时通信接口。"""

import asyncio
import json
import math
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from drisca.core.config import (
    KEYBOARD_KEY_LABELS,
    WHEEL_BUTTON_LABELS,
    CameraConfig,
    ControlConfig,
    DisplayLayoutConfig,
    MachineConfig,
    PresetConfig,
    TrafficConfig,
    list_presets,
    load_preset,
    save_control_config,
    save_machine_config,
    save_preset,
)
from drisca.core.paths import PRESETS_DIR
from drisca.core.protocol import (
    CreateFogRegionCommand,
    DeleteFogRegionCommand,
    SetWeatherCommand,
    UpdateCameraCommand,
    UpdateFogRegionCommand,
    UpdateLayoutCommand,
    parse_worker_event,
)
from drisca.core.weather import resolve_weather, to_config, to_payload
from drisca.launcher.commands import COMMANDS, MODELS
from drisca.launcher.routes_data import build_data_router
from drisca.launcher.runtime import Runtime
from drisca.launcher.schemas import (
    CarlaStartRequest,
    FogRegionCreateRequest,
    FogRegionUpdateRequest,
    MapRequest,
    MarkerRequest,
    PreviewFollowRequest,
    StartRequest,
    TrafficLightFreezeRequest,
    TrafficLightStateRequest,
    ViewModeRequest,
    WeatherApplyRequest,
)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(asyncio.get_running_loop())
        app.state.runtime.update(carla_connecting=True)
        app.state.runtime.background(app.state.runtime.connect, silent=True)
        yield
        runtime = app.state.runtime
        await runtime.shutdown()
        runtime.job.Close()

    app = FastAPI(lifespan=lifespan)

    @app.middleware('http')
    async def world_loading(request: Request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and rt().state['world_loading']:
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

    def environment_api():
        api = rt().api
        if api is None or rt().state['carla_connecting']:
            raise HTTPException(409, 'CARLA 尚未连接')
        return api

    def safe_name(name: str) -> str:
        if not name or name in ('.', '..') or Path(name).name != name or '/' in name or '\\' in name:
            raise HTTPException(400, '名称无效')
        return name

    @app.get('/api/bootstrap')
    def bootstrap():
        try:
            host = socket.gethostbyname(socket.gethostname())
        except OSError:
            host = '127.0.0.1'
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

    @app.post('/api/instructions/{instruction_id}/execute')
    def execute(instruction_id: str):
        ensure_running()
        cfg = rt().run_config
        assert cfg is not None
        instruction = next((item for item in cfg.preset.instructions if item.id == instruction_id), None)
        if instruction is None:
            raise HTTPException(404, '指令不存在')
        rt().background(rt().execute, instruction)
        return {'ok': True}

    @app.post('/api/commands/{command_id}/trigger')
    def trigger_command(command_id: str, params: dict[str, object]):
        if command_id not in MODELS:
            raise HTTPException(404, f'未注册的事件或指令：{command_id}')
        try:
            MODELS[command_id].model_validate(params)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if rt().state['carla_connecting'] or not rt().state['carla_connected']:
            raise HTTPException(409, 'CARLA 尚未连接')
        rt().background(rt().trigger_command, command_id, params)
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
    def weather(request: WeatherApplyRequest):
        config = request.weather
        if config.preset_name != 'Custom':
            config = resolve_weather(config, rt().weather_presets)
        if rt().state['phase'] == 'running':
            rt().send(
                SetWeatherCommand(
                    command_id=uuid4().hex,
                    weather=config,
                    transition_seconds=request.transition_seconds,
                )
            )
        else:
            ensure_idle()
            api = environment_api()
            applied = api.environment_apply(to_payload(config), request.transition_seconds)
            rt().update(weather=to_config(applied.target.weather, config.preset_name).model_dump(mode='json'))
        return {'ok': True}

    @app.post('/api/weather/regions')
    def create_fog_region(request: FogRegionCreateRequest):
        if rt().state['phase'] == 'running':
            rt().send(
                CreateFogRegionCommand(
                    command_id=uuid4().hex,
                    center_m=request.center_m,
                    radius_m=request.radius_m,
                    density=request.density,
                    transition_seconds=request.transition_seconds,
                )
            )
            rt().log(
                f'已创建团雾：中心={request.center_m}，半径={request.radius_m:g}m，密度={request.density:g}',
                'INFO',
            )
            return {'ok': True}
        ensure_idle()
        environment_api().environment_create(
            center_m=request.center_m,
            radius_m=request.radius_m,
            density=request.density,
            transition_seconds=request.transition_seconds,
        )
        rt().update(fog_regions=rt().read_fog_regions())
        rt().log(
            f'已创建团雾（空闲预览）：中心={request.center_m}，半径={request.radius_m:g}m，密度={request.density:g}',
            'INFO',
        )
        return {'ok': True}

    @app.patch('/api/weather/regions/{region_id}')
    def update_fog_region(region_id: int, request: FogRegionUpdateRequest):
        if region_id < 1:
            raise HTTPException(422, '区域编号无效')
        if rt().state['phase'] == 'running':
            rt().send(
                UpdateFogRegionCommand(
                    command_id=uuid4().hex,
                    region_id=region_id,
                    center_m=request.center_m,
                    radius_m=request.radius_m,
                    density=request.density,
                    transition_seconds=request.transition_seconds,
                )
            )
            rt().log(
                f'已更新团雾 #{region_id}：半径={request.radius_m}，密度={request.density}',
                'INFO',
            )
            return {'ok': True}
        ensure_idle()
        environment_api().environment_update_region(
            region_id,
            center_m=request.center_m,
            radius_m=request.radius_m,
            density=request.density,
            transition_seconds=request.transition_seconds,
        )
        rt().update(fog_regions=rt().read_fog_regions())
        rt().log(
            f'已更新团雾 #{region_id}（空闲预览）：半径={request.radius_m}，密度={request.density}',
            'INFO',
        )
        return {'ok': True}

    @app.delete('/api/weather/regions/{region_id}')
    def delete_fog_region(region_id: int, transition_seconds: float = Query(0.0)):
        if region_id < 1:
            raise HTTPException(422, '区域编号无效')
        if not math.isfinite(transition_seconds) or transition_seconds < 0:
            raise HTTPException(422, '渐变时长必须是非负有限数值')
        if rt().state['phase'] == 'running':
            rt().send(
                DeleteFogRegionCommand(
                    command_id=uuid4().hex,
                    region_id=region_id,
                    transition_seconds=transition_seconds,
                )
            )
            rt().log(f'已删除团雾 #{region_id}（渐隐 {transition_seconds:g}s）', 'INFO')
            return {'ok': True}
        ensure_idle()
        environment_api().environment_delete(region_id, transition_seconds)
        rt().update(fog_regions=rt().read_fog_regions())
        rt().log(f'已删除团雾 #{region_id}（空闲预览，渐隐 {transition_seconds:g}s）', 'INFO')
        return {'ok': True}

    @app.post('/api/traffic/preview/start')
    def start_traffic_preview(traffic: TrafficConfig):
        ensure_idle()
        if rt().state['carla_connecting'] or not rt().state['carla_connected']:
            raise HTTPException(409, 'CARLA 尚未连接')
        if traffic.vehicle_count <= 0:
            raise HTTPException(422, '预览背景车数量必须大于 0')
        rt().start_traffic_preview(traffic)
        return {'ok': True}

    @app.post('/api/traffic/preview/stop')
    def stop_traffic_preview():
        rt().stop_traffic_preview()
        return {'ok': True}

    @app.post('/api/traffic/preview/follow')
    def cycle_traffic_preview_follow(request: PreviewFollowRequest):
        try:
            actor_id = rt().traffic_preview.cycle_follow(request.delta)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'ok': True, 'follow_actor_id': actor_id}

    @app.post('/api/view/mode')
    def set_view_mode(request: ViewModeRequest):
        try:
            rt().set_view_mode(request.mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'ok': True, 'view_mode': request.mode}

    @app.post('/api/traffic-lights/{actor_id}/state')
    def set_traffic_light_state(actor_id: int, request: TrafficLightStateRequest):
        if actor_id < 1:
            raise HTTPException(422, '信号灯编号无效')
        if rt().traffic_preview.running:
            rt().traffic_preview.queue_operation(
                {
                    'method': 'traffic_light.set_state',
                    'params': {'actor_id': actor_id, 'state': request.state},
                }
            )
            rt().log(f'已切换信号灯 #{actor_id} -> {request.state}', 'INFO')
            return {'ok': True}
        ensure_idle()
        environment_api().set_traffic_light_state(actor_id, request.state)
        rt().log(f'已切换信号灯 #{actor_id} -> {request.state}', 'INFO')
        return {'ok': True}

    @app.post('/api/traffic-lights/groups/{group_id}/freeze')
    def freeze_traffic_light_group(group_id: int, request: TrafficLightFreezeRequest):
        if group_id < 0:
            raise HTTPException(422, '灯组编号无效')
        if rt().traffic_preview.running:
            rt().traffic_preview.queue_operation(
                {
                    'method': 'traffic_light_group.freeze',
                    'params': {'group_id': group_id, 'frozen': request.frozen},
                }
            )
            rt().log(f'已{"冻结" if request.frozen else "解冻"}信号灯组 #{group_id}', 'INFO')
            return {'ok': True}
        ensure_idle()
        environment_api().freeze_traffic_light_group(group_id, request.frozen)
        rt().log(f'已{"冻结" if request.frozen else "解冻"}信号灯组 #{group_id}', 'INFO')
        return {'ok': True}

    app.include_router(build_data_router(rt, ensure_idle, safe_name))

    @app.get('/api/events')
    async def events():
        async def stream():
            queue: asyncio.Queue = asyncio.Queue(maxsize=256)
            rt().subscribers.add(queue)
            rt().client_connected('console', 1)
            try:
                yield (
                    'data: '
                    + json.dumps({'type': 'state', 'data': rt().snapshot_state()}, ensure_ascii=False)
                    + '\n\n'
                )
                while not rt().closing:
                    item = await queue.get()
                    if item is None:
                        break
                    yield 'data: ' + json.dumps(item, ensure_ascii=False) + '\n\n'
            finally:
                rt().subscribers.discard(queue)
                rt().client_connected('console', -1)

        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.get('/stream')
    async def hud_stream():
        async def stream():
            rt().client_connected('hud', 1)
            try:
                while not rt().closing:
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
            try:
                await sender
            except asyncio.CancelledError:
                pass
            rt().worker = None
            rt().worker_closed.set()

    static = Path(__file__).parent / 'static'
    if static.is_dir():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

        @app.get('/{path:path}')
        def frontend(path: str):
            return FileResponse(static / 'index.html')

    return app
