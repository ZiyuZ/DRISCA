"""DRISCA 原生 WebSocket API 客户端。

每条连接串行发送一个请求并读取完整响应；exchange 的 JSON 结果与其后的二进制快照
在同一次加锁区间内读取，保证响应不会与其它线程的请求错配。
"""

import json
import socket
import threading
from dataclasses import dataclass
from typing import Any, Final

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from drisca.core.catalog import NativeCatalog
from drisca.core.config import DrivingViewConfig
from drisca.core.environment import (
    EnvironmentList,
    EnvironmentSnapshot,
    RegionSnapshot,
)
from drisca.core.snapshot import (
    HEADER_BYTES,
    RESEARCH_RECORD_BYTES,
    VEHICLE_RECORD_BYTES,
    Snapshot,
    decode_snapshot,
)

PROTOCOL_VERSION: Final = 1
API_PATH: Final = '/drisca/v1'
MAX_MESSAGE_BYTES: Final = 8 * 1024 * 1024
MAX_REQUEST_ID: Final = 2**32


class NativeApiError(RuntimeError):
    """服务端报告的业务错误，附带错误码与逐项操作结果。"""

    def __init__(
        self,
        method: str,
        code: str,
        message: str,
        results: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(f'{method} 失败（{code}）：{message}')
        self.method = method
        self.code = code
        self.message = message
        self.results = tuple(results or ())


@dataclass(frozen=True, slots=True)
class ServerInfo:
    protocol_version: int
    server_instance: str
    world_id: int
    map_name: str


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    index: int
    status: str
    applied_frame_no: int | None
    sampled_frame_no: int | None
    result: dict[str, Any]
    error: dict[str, Any]

    @property
    def superseded(self) -> bool:
        return self.status == 'skipped' and self.error.get('code') == 'control_superseded'


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    request_id: int
    world_id: int
    frame_no: int
    outcomes: tuple[OperationOutcome, ...]
    events: tuple[dict[str, Any], ...]
    control_state: tuple[dict[str, Any], ...]
    traffic_lights: tuple[dict[str, Any], ...]
    traffic_controllers: tuple[dict[str, Any], ...]
    snapshot: Snapshot
    selected_actor_id: int | None = None
    selected_signal_actor_id: int | None = None


def _outcomes(raw: list[dict[str, Any]] | None) -> tuple[OperationOutcome, ...]:
    items = []
    for item in raw or ():
        items.append(
            OperationOutcome(
                index=int(item.get('index', 0)),
                status=str(item.get('status', '')),
                applied_frame_no=(int(item['applied_frame_no']) if 'applied_frame_no' in item else None),
                sampled_frame_no=(int(item['sampled_frame_no']) if 'sampled_frame_no' in item else None),
                result=item.get('result') or {},
                error=item.get('error') or {},
            )
        )
    return tuple(items)


class NativeApiClient:
    def __init__(
        self,
        config: DrivingViewConfig,
        *,
        client: str = 'drisca-client',
        long_timeout: float | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.long_timeout = config.timeout if long_timeout is None else long_timeout
        self._socket: ClientConnection | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._world_id = 0
        self._road_graphs: dict[tuple[int, float], dict[str, Any]] = {}

    @property
    def url(self) -> str:
        return f'ws://{self.config.host}:{self.config.port}{API_PATH}'

    @property
    def world_id(self) -> int:
        return self._world_id

    def connect(self) -> ServerInfo:
        with self._lock:
            self._close_locked()
            try:
                # 地图加载期间 Unreal 游戏线程不推进网络，客户端保活 ping 会超时并关闭连接，
                # 因此关闭本机链路保活，请求截止时间仍由每次 recv 的 timeout 约束。
                self._socket = connect(
                    self.url,
                    max_size=MAX_MESSAGE_BYTES,
                    compression=None,
                    proxy=None,
                    open_timeout=self.config.timeout,
                    close_timeout=self.config.timeout,
                    ping_interval=None,
                )
                try:
                    self._socket.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
            except (OSError, TimeoutError, WebSocketException) as exc:
                raise ConnectionError(f'原生接口连接失败：{self.url}') from exc
            self._next_id = 1
            _, result = self._call(
                'hello',
                {'protocol_version': PROTOCOL_VERSION, 'client': self.client},
                self.config.timeout,
            )
            info = ServerInfo(
                protocol_version=int(result['protocol_version']),
                server_instance=str(result['server_instance']),
                world_id=int(result['world_id']),
                map_name=str(result['map_name']),
            )
            layout = (
                int(result['snapshot_header_bytes']),
                int(result['vehicle_record_bytes']),
                int(result['research_record_bytes']),
            )
            expected = (HEADER_BYTES, VEHICLE_RECORD_BYTES, RESEARCH_RECORD_BYTES)
            if info.protocol_version != PROTOCOL_VERSION or layout != expected:
                self._close_locked()
                raise NativeApiError(
                    'hello',
                    'version_mismatch',
                    f'原生协议版本 {info.protocol_version}、记录长度 {layout} 与客户端'
                    f'版本 {PROTOCOL_VERSION}、记录长度 {expected} 不一致',
                )
            self._world_id = info.world_id
            self._road_graphs.clear()
            return info

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._call(method, params or {}, self._timeout(timeout))[1]

    def status(self) -> dict[str, Any]:
        return self.request('server.status')

    def catalog(self) -> NativeCatalog:
        return NativeCatalog.from_native(
            self.request('scene.catalog', self._world(), timeout=self.long_timeout)
        )

    def environment_get(self) -> EnvironmentSnapshot:
        return EnvironmentSnapshot.model_validate(self.request('environment.get', self._world()))

    def environment_list(self) -> tuple[RegionSnapshot, ...]:
        result = self.request('environment.list', self._world())
        return EnvironmentList.model_validate(result).regions

    def environment_apply(
        self, weather: dict[str, Any], transition_seconds: float = 0.0
    ) -> EnvironmentSnapshot:
        return EnvironmentSnapshot.model_validate(
            self.request(
                'environment.apply',
                {**self._world(), 'weather': weather, 'transition_seconds': transition_seconds},
            )
        )

    def environment_update(
        self, weather: dict[str, Any], transition_seconds: float = 0.0
    ) -> EnvironmentSnapshot:
        return EnvironmentSnapshot.model_validate(
            self.request(
                'environment.update',
                {**self._world(), 'weather': weather, 'transition_seconds': transition_seconds},
            )
        )

    def environment_create(
        self,
        *,
        center_m: tuple[float, float, float],
        radius_m: float,
        density: float,
        transition_seconds: float = 0.0,
    ) -> RegionSnapshot:
        return RegionSnapshot.model_validate(
            self.request(
                'environment.create',
                {
                    **self._world(),
                    'center_m': list(center_m),
                    'radius_m': radius_m,
                    'weather': {'fog': {'density': density}},
                    'transition_seconds': transition_seconds,
                },
            )
        )

    def environment_update_region(
        self,
        region_id: int,
        *,
        center_m: tuple[float, float, float] | None = None,
        radius_m: float | None = None,
        density: float | None = None,
        transition_seconds: float = 0.0,
    ) -> RegionSnapshot:
        params: dict[str, Any] = {
            **self._world(),
            'region_id': region_id,
            'transition_seconds': transition_seconds,
        }
        if center_m is not None:
            params['center_m'] = list(center_m)
        if radius_m is not None:
            params['radius_m'] = radius_m
        if density is not None:
            params['weather'] = {'fog': {'density': density}}
        return RegionSnapshot.model_validate(self.request('environment.update', params))

    def environment_region(self, region_id: int) -> RegionSnapshot:
        return RegionSnapshot.model_validate(
            self.request('environment.get', {**self._world(), 'region_id': region_id})
        )

    def environment_delete(self, region_id: int, transition_seconds: float = 0.0) -> RegionSnapshot:
        return RegionSnapshot.model_validate(
            self.request(
                'environment.delete',
                {
                    **self._world(),
                    'region_id': region_id,
                    'transition_seconds': transition_seconds,
                },
            )
        )

    def set_world(self, simulation_fps: int) -> dict[str, Any]:
        return self.request('scene.set_world', {**self._world(), 'simulation_fps': simulation_fps})

    def clear_actors(self) -> dict[str, Any]:
        return self.request('scene.clear_actors', self._world())

    def load_map(self, map_name: str, *, suppress_screen_messages: bool = False) -> dict[str, Any]:
        with self._lock:
            _, result = self._call(
                'scene.load_map',
                {
                    **self._world(),
                    'map_name': map_name,
                    'suppress_screen_messages': suppress_screen_messages,
                },
                self.long_timeout,
            )
            self._world_id = int(result['world_id'])
            self._road_graphs.clear()
            return result

    def spawn_vehicle(
        self,
        *,
        blueprint: str,
        transform: dict[str, Any],
        role_name: str = '',
        attributes: dict[str, str] | None = None,
        mode: str = 'manual',
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            **self._world(),
            'blueprint': blueprint,
            'transform': transform,
            'mode': mode,
        }
        if role_name:
            params['role_name'] = role_name
        if attributes:
            params['attributes'] = attributes
        return self.request('vehicle.spawn', params)

    def start_view(
        self,
        *,
        session_id: str,
        ego_actor_id: int = 0,
        cameras: dict[str, Any],
        layout: dict[str, Any],
        keyboard: dict[str, str],
        mode: str = 'manual',
        view_mode: str = 'cockpit',
        suppress_screen_messages: bool = False,
        dynamic_speed_limit: bool = False,
        default_speed_limit_mps: float = 33.33,
    ) -> dict[str, Any]:
        return self.request(
            'driving_view.start',
            {
                **self._world(),
                'session_id': session_id,
                'ego_actor_id': ego_actor_id,
                'cameras': cameras,
                'layout': layout,
                'keyboard': keyboard,
                'mode': mode,
                'view_mode': view_mode,
                'suppress_screen_messages': suppress_screen_messages,
                'dynamic_speed_limit': dynamic_speed_limit,
                'default_speed_limit_mps': default_speed_limit_mps,
            },
        )

    def update_view(
        self,
        *,
        cameras: dict[str, Any] | None = None,
        layout: dict[str, Any] | None = None,
        view_mode: str | None = None,
        ego_actor_id: int | None = None,
        actor_id_space: str | None = None,
    ) -> dict[str, Any]:
        params = self._world()
        if cameras is not None:
            params['cameras'] = cameras
        if layout is not None:
            params['layout'] = layout
        if view_mode is not None:
            params['view_mode'] = view_mode
        if ego_actor_id is not None:
            params['ego_actor_id'] = ego_actor_id
        if actor_id_space is not None:
            params['actor_id_space'] = actor_id_space
        return self.request('driving_view.update', params)

    def exchange(
        self,
        operations: list[dict[str, Any]],
        *,
        session_id: str,
        timeout: float | None = None,
    ) -> ExchangeResult:
        limit = self._timeout(timeout)
        with self._lock:
            params = {**self._world(), 'session_id': session_id, 'operations': operations}
            request_id, result = self._call('exchange', params, limit)
            if result.get('snapshot') is not True:
                self._close_locked()
                raise NativeApiError('exchange', 'invalid_response', '成功响应缺少 snapshot=true')
            raw = self._receive_binary('exchange', limit)
            try:
                snapshot = decode_snapshot(raw)
            except ValueError as exc:
                self._close_locked()
                raise NativeApiError('exchange', 'invalid_snapshot', str(exc)) from exc
            world_id = int(result.get('world_id', 0))
            frame_no = int(result.get('frame_no', 0))
            self._check_snapshot(request_id, snapshot, world_id, frame_no)
            raw_selected = result.get('selected_actor_id')
            selected_actor_id = (
                int(raw_selected) if isinstance(raw_selected, int) and raw_selected > 0 else None
            )
            raw_signal = result.get('selected_signal_actor_id')
            selected_signal_actor_id = (
                int(raw_signal) if isinstance(raw_signal, int) and raw_signal > 0 else None
            )
            return ExchangeResult(
                request_id=request_id,
                world_id=world_id,
                frame_no=frame_no,
                outcomes=_outcomes(result.get('results')),
                events=tuple(result.get('events') or ()),
                control_state=tuple(result.get('control_state') or ()),
                traffic_lights=tuple(result.get('traffic_lights') or ()),
                traffic_controllers=tuple(result.get('traffic_controllers') or ()),
                snapshot=snapshot,
                selected_actor_id=selected_actor_id,
                selected_signal_actor_id=selected_signal_actor_id,
            )

    def set_traffic_light_state(self, actor_id: int, state: str) -> dict[str, Any]:
        return self.request(
            'traffic_light.set_state', {**self._world(), 'actor_id': actor_id, 'state': state}
        )

    def freeze_traffic_light_group(self, group_id: int, frozen: bool) -> dict[str, Any]:
        return self.request(
            'traffic_light_group.freeze', {**self._world(), 'group_id': group_id, 'frozen': frozen}
        )

    def stop_experiment(self, session_id: str) -> dict[str, Any]:
        return self.request('experiment.stop', {**self._world(), 'session_id': session_id})

    def recorder_start(self, absolute_path: str) -> dict[str, Any]:
        return self.request('recorder.start', {**self._world(), 'absolute_path': absolute_path})

    def recorder_stop(self) -> dict[str, Any]:
        """停止原生 API 归属的录像；无归属时服务端返回 invalid_state。"""
        return self.request('recorder.stop', self._world())

    def recorder_info(self, absolute_path: str, show_all: bool = False) -> dict[str, Any]:
        return self.request(
            'recorder.info',
            {**self._world(), 'absolute_path': absolute_path, 'show_all': show_all},
        )

    def recorder_replay(
        self,
        absolute_path: str,
        *,
        start_time: float = 0.0,
        duration: float = 0.0,
        follow_actor_id: int = 0,
        time_factor: float = 1.0,
        ignore_hero: bool = False,
    ) -> dict[str, Any]:
        """回放车辆与传感器；原生固定关闭天气回放，环境由 DRISCA 重启。"""
        return self.request(
            'recorder.replay',
            {
                **self._world(),
                'absolute_path': absolute_path,
                'start_time': start_time,
                'duration': duration,
                'follow_actor_id': follow_actor_id,
                'time_factor': time_factor,
                'ignore_hero': ignore_hero,
            },
        )

    def recorder_stop_replay(self) -> dict[str, Any]:
        """停止正在进行的原生录像回放并释放跟随视角。"""
        return self.request('recorder.stop_replay', self._world())

    def road_graph(
        self,
        *,
        sampling_step: float = 2.0,
        cursor: int = 0,
        max_lanes: int = 200,
    ) -> dict[str, Any]:
        return self.request(
            'scene.road_graph',
            {
                **self._world(),
                'sampling_step': sampling_step,
                'cursor': cursor,
                'max_lanes': max_lanes,
            },
            timeout=self.long_timeout,
        )

    def road_query(self, locations: list[tuple[float, float, float]]) -> dict[str, Any]:
        """按世界坐标批量查询道路投影，返回顺序与 locations 一致。"""
        return self.request(
            'road.query',
            {**self._world(), 'locations': [[x, y, z] for x, y, z in locations]},
        )

    def road_graph_all(self, sampling_step: float = 2.0) -> dict[str, Any]:
        """按页取回当前世界的完整车道图，缓存只保留最近一次世界与采样步长。"""
        key = (self._world_id, sampling_step)
        cached = self._road_graphs.get(key)
        if cached is not None:
            return cached
        lanes: list[dict[str, Any]] = []
        cursor = 0
        page: dict[str, Any] = {}
        while True:
            page = self.road_graph(sampling_step=sampling_step, cursor=cursor)
            lanes.extend(page['lanes'])
            cursor = int(page['cursor'])
            if page['done']:
                break
        graph = {
            'world_id': int(page['world_id']),
            'map_name': str(page['map_name']),
            'sampling_step': sampling_step,
            'lane_count': int(page['lane_count']),
            'lanes': lanes,
        }
        self._road_graphs = {key: graph}
        return graph

    def road_junctions(self) -> dict[str, Any]:
        return self.request('scene.road_junctions', self._world(), timeout=self.long_timeout)

    def road_signals(self) -> dict[str, Any]:
        return self.request('scene.road_signals', self._world(), timeout=self.long_timeout)

    def _world(self) -> dict[str, Any]:
        return {'world_id': self._world_id}

    def _timeout(self, timeout: float | None) -> float:
        return self.config.timeout if timeout is None else timeout

    def _require_socket(self, method: str) -> ClientConnection:
        if self._socket is None:
            raise ConnectionError(f'原生接口尚未连接，无法发送 {method}')
        return self._socket

    def _call(self, method: str, params: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
        socket = self._require_socket(method)
        if self._next_id >= MAX_REQUEST_ID:
            self._close_locked()
            raise RuntimeError('请求编号已耗尽，请重新连接原生接口')
        request_id = self._next_id
        self._next_id += 1
        payload = {'id': request_id, 'method': method, 'params': params}
        try:
            socket.send(json.dumps(payload, ensure_ascii=False))
            raw = socket.recv(timeout=timeout)
        except TimeoutError as exc:
            self._close_locked()
            raise TimeoutError(f'原生接口 {method} 响应超时（{timeout:g} 秒）') from exc
        except (OSError, WebSocketException) as exc:
            self._close_locked()
            raise ConnectionError(f'原生接口 {method} 通信中断：{exc}') from exc
        if not isinstance(raw, str):
            self._close_locked()
            raise NativeApiError(method, 'invalid_response', '收到非预期的二进制响应')
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._close_locked()
            raise NativeApiError(method, 'invalid_response', f'响应 JSON 解析失败：{exc}') from exc
        if response.get('id') != request_id:
            self._close_locked()
            raise NativeApiError(method, 'invalid_response', '响应编号与请求不一致')
        if not response.get('ok'):
            error = response.get('error') or {}
            results = error.get('results')
            raise NativeApiError(
                method,
                str(error.get('code') or ''),
                str(error.get('message') or ''),
                results if isinstance(results, list) else None,
            )
        result = response.get('result')
        return request_id, result if isinstance(result, dict) else {}

    def _receive_binary(self, method: str, timeout: float) -> bytes:
        socket = self._require_socket(method)
        try:
            raw = socket.recv(timeout=timeout)
        except TimeoutError as exc:
            self._close_locked()
            raise TimeoutError(f'原生接口 {method} 快照超时（{timeout:g} 秒）') from exc
        except (OSError, WebSocketException) as exc:
            self._close_locked()
            raise ConnectionError(f'原生接口 {method} 通信中断：{exc}') from exc
        if not isinstance(raw, (bytes, bytearray)):
            self._close_locked()
            raise NativeApiError(method, 'invalid_response', '快照应为二进制消息')
        return bytes(raw)

    def _check_snapshot(
        self,
        request_id: int,
        snapshot: Snapshot,
        world_id: int,
        frame_no: int,
    ) -> None:
        def fail(message: str) -> None:
            self._close_locked()
            raise NativeApiError('exchange', 'invalid_snapshot', message)

        if snapshot.request_id != request_id:
            fail(f'快照 request_id {snapshot.request_id} 与请求 {request_id} 不一致')
        if snapshot.world_id != world_id:
            fail(f'快照 world_id {snapshot.world_id} 与响应 {world_id} 不一致')
        if world_id != self._world_id:
            fail(f'快照 world_id {world_id} 与当前世界 {self._world_id} 不一致')
        if snapshot.frame_no != frame_no:
            fail(f'快照 frame_no {snapshot.frame_no} 与响应 {frame_no} 不一致')

    def _close_locked(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                socket.close()
            except OSError, WebSocketException:
                pass
