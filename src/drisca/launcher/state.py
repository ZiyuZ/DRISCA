"""管理端显式状态枚举与线程安全状态广播存储。"""

import asyncio
import copy
import threading
import time
from collections import deque
from enum import StrEnum
from typing import Any


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
    """面向侧栏的单一显式系统状态。"""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RUNNING = 'running'
    ERROR = 'error'


def compute_system_status(state: dict[str, Any]) -> str:
    """由连接、Unreal 进程与实验阶段统一派生单一显式状态。"""
    phase = state.get('phase')
    if phase in (ExperimentPhase.RUNNING, ExperimentPhase.STARTING, ExperimentPhase.STOPPING):
        return str(SystemStatus.RUNNING)
    unreal_phase = (state.get('unreal') or {}).get('phase')
    if unreal_phase in ('error', UnrealPhase.FAILED):
        return str(SystemStatus.ERROR)
    if state.get('carla_connected'):
        return str(SystemStatus.CONNECTED)
    if state.get('carla_connecting') or unreal_phase in (UnrealPhase.STARTING, UnrealPhase.STOPPING):
        return str(SystemStatus.CONNECTING)
    return str(SystemStatus.DISCONNECTED)


def empty_catalog() -> dict[str, Any]:
    return {
        'maps': [],
        'vehicles': [],
        'map_name': None,
        'spawn_points': [],
        'weather_presets': {},
    }


def initial_state() -> dict[str, Any]:
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
        self.state: dict[str, Any] = initial_state()
        self.subscribers: set[asyncio.Queue] = set()
        self.logs: deque[dict[str, Any]] = deque(maxlen=500)
        self.events: deque[dict[str, Any]] = deque(maxlen=500)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.state)

    def emit(self, kind: str, data: Any) -> None:
        if self.loop.is_closed():
            return
        message = {'type': kind, 'data': data}

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

    def update(self, **changes: Any) -> None:
        with self.lock:
            self.state.update(changes)
            self.state['system_status'] = compute_system_status(self.state)
            snap = copy.deepcopy(self.state)
        self.emit('state', snap)

    def update_telemetry(self, payload: dict[str, Any]) -> None:
        with self.lock:
            self.state['telemetry'] = payload
        self.emit('telemetry', payload)

    def adjust_client(self, role: str, delta: int) -> None:
        with self.lock:
            clients = dict(self.state['clients'])
            clients[role] = max(0, clients[role] + delta)
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
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
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
