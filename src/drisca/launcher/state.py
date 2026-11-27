"""管理端显式状态枚举、强类型状态 Schema 与线程安全状态广播存储。"""

import asyncio
import copy
import threading
import time
from collections import deque
from enum import StrEnum
from typing import TypedDict, Unpack

from drisca.core.types import JsonObject, JsonValue


class ExperimentPhase(StrEnum):
    IDLE = 'idle'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'


class UnrealPhase(StrEnum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    FAILED = 'failed'


class SystemStatus(StrEnum):
    """面向侧栏的单一显式互斥系统状态。"""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    PREVIEWING = 'previewing'
    REPLAYING = 'replaying'
    RUNNING = 'running'
    ERROR = 'error'


class UnrealState(TypedDict):
    phase: str
    pid: int | None
    kind: str | None


class TrafficPreviewState(TypedDict):
    running: bool
    vehicle_count: int
    follow_actor_id: int | None
    error: str | None


class ReplayState(TypedDict):
    running: bool
    name: str | None
    error: str | None


class ExportState(TypedDict):
    running: bool
    progress: int | float
    path: str | None
    error: str | None


class CatalogState(TypedDict):
    maps: list[str]
    vehicles: list[str]
    map_name: str | None
    spawn_points: list[JsonObject]
    weather_presets: dict[str, JsonObject]


class LauncherState(TypedDict):
    system_status: str
    phase: str
    carla_connected: bool
    carla_connecting: bool
    world_loading: bool
    unreal: UnrealState
    clients: dict[str, int]
    carla_detail: str
    worker_state: str
    session_id: str | None
    active_preset: JsonObject | None
    active_preset_name: str | None
    active_run: JsonObject | None
    telemetry: JsonObject | None
    cameras: JsonObject | None
    weather: JsonObject | None
    fog_regions: list[JsonObject]
    traffic_preview: TrafficPreviewState
    replay: ReplayState
    selected_signal: JsonObject | None
    view_mode: str
    display_layout: JsonObject | None
    vehicle_box: JsonObject | None
    error: str | None
    catalog: CatalogState
    export: ExportState


class LauncherStatePatch(TypedDict, total=False):
    system_status: str
    phase: str
    carla_connected: bool
    carla_connecting: bool
    world_loading: bool
    unreal: UnrealState
    clients: dict[str, int]
    carla_detail: str
    worker_state: str
    session_id: str | None
    active_preset: JsonObject | None
    active_preset_name: str | None
    active_run: JsonObject | None
    telemetry: JsonObject | None
    cameras: JsonObject | None
    weather: JsonObject | None
    fog_regions: list[JsonObject]
    traffic_preview: TrafficPreviewState
    replay: ReplayState
    selected_signal: JsonObject | None
    view_mode: str
    display_layout: JsonObject | None
    vehicle_box: JsonObject | None
    error: str | None
    catalog: CatalogState
    export: ExportState


class StreamMessage(TypedDict):
    type: str
    data: JsonValue | LauncherState


def compute_system_status(state: LauncherState) -> str:
    """由连接、Unreal 进程、实验、预览与回放阶段统一派生单一显式状态。"""
    phase = state['phase']
    if phase in (ExperimentPhase.RUNNING, ExperimentPhase.STARTING, ExperimentPhase.STOPPING):
        return str(SystemStatus.RUNNING)
    unreal_phase = state['unreal']['phase']
    if unreal_phase in ('error', UnrealPhase.FAILED):
        return str(SystemStatus.ERROR)
    if state['replay']['running']:
        return str(SystemStatus.REPLAYING)
    if state['traffic_preview']['running']:
        return str(SystemStatus.PREVIEWING)
    if state['carla_connected']:
        return str(SystemStatus.CONNECTED)
    if state['carla_connecting'] or unreal_phase in (UnrealPhase.STARTING, UnrealPhase.STOPPING):
        return str(SystemStatus.CONNECTING)
    return str(SystemStatus.DISCONNECTED)


def empty_catalog() -> CatalogState:
    return {
        'maps': [],
        'vehicles': [],
        'map_name': None,
        'spawn_points': [],
        'weather_presets': {},
    }


def initial_state() -> LauncherState:
    return {
        'system_status': str(SystemStatus.DISCONNECTED),
        'phase': str(ExperimentPhase.IDLE),
        'carla_connected': False,
        'carla_connecting': False,
        'world_loading': False,
        'unreal': {'phase': str(UnrealPhase.STOPPED), 'pid': None, 'kind': None},
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
        'fog_regions': [],
        'traffic_preview': {'running': False, 'vehicle_count': 0, 'follow_actor_id': None, 'error': None},
        'replay': {'running': False, 'name': None, 'error': None},
        'selected_signal': None,
        'view_mode': 'free',
        'display_layout': None,
        'vehicle_box': None,
        'error': None,
        'catalog': empty_catalog(),
        'export': {'running': False, 'progress': 0, 'path': None, 'error': None},
    }


class StateStore:
    """集中管理 Runtime 状态字典、线程锁、SSE 订阅队列以及日志/事件环形缓冲。"""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.lock = threading.RLock()
        self.state: LauncherState = initial_state()
        self.subscribers: set[asyncio.Queue[StreamMessage | None]] = set()
        self.logs: deque[JsonObject] = deque(maxlen=500)
        self.events: deque[JsonObject] = deque(maxlen=500)

    def snapshot(self) -> LauncherState:
        with self.lock:
            return copy.deepcopy(self.state)

    def emit(self, kind: str, data: JsonValue | LauncherState) -> None:
        if self.loop.is_closed():
            return
        message: StreamMessage = {'type': kind, 'data': data}

        def send() -> None:
            for queue in tuple(self.subscribers):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

        try:
            self.loop.call_soon_threadsafe(send)
        except RuntimeError:
            pass

    def update(self, **changes: Unpack[LauncherStatePatch]) -> None:
        with self.lock:
            self.state.update(changes)
            self.state['system_status'] = compute_system_status(self.state)
            snap = copy.deepcopy(self.state)
        self.emit('state', snap)

    def update_telemetry(self, payload: JsonObject) -> None:
        with self.lock:
            self.state['telemetry'] = payload
        self.emit('telemetry', payload)

    def adjust_client(self, role: str, delta: int) -> None:
        with self.lock:
            clients = dict(self.state['clients'])
            clients[role] = max(0, clients.get(role, 0) + delta)
            self.state['clients'] = clients
            snap = copy.deepcopy(self.state)
        self.emit('state', snap)

    def append_log(
        self,
        message: str,
        level: str = 'INFO',
        role: str = 'launcher',
        *,
        detail: str | None = None,
    ) -> JsonObject:
        item: JsonObject = {
            'type': 'log',
            'role': role,
            'timestamp': time.time(),
            'level': level,
            'message': message,
            'command_id': None,
        }
        if detail:
            item['detail'] = detail
        self.logs.append(item)
        self.emit('log', item)
        return item
