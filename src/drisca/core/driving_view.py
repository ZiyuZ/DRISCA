"""Unreal 原生驾驶视图的本机 JSON-RPC 客户端。"""

import json
import socket
from typing import Literal

from pydantic import BaseModel

from drisca.core.config import (
    CameraRigConfig,
    DisplayLayoutConfig,
    DrivingViewConfig,
    KeyboardControlConfig,
    KeyboardKey,
)

KEYBOARD_FKEYS: dict[KeyboardKey, str] = {
    KeyboardKey.ESCAPE: 'Escape',
    KeyboardKey.P: 'P',
    KeyboardKey.BACKSLASH: 'Backslash',
    KeyboardKey.Q: 'Q',
    KeyboardKey.M: 'M',
    KeyboardKey.PERIOD: 'Period',
    KeyboardKey.COMMA: 'Comma',
    KeyboardKey.SPACE: 'SpaceBar',
    KeyboardKey.SEMICOLON: 'Semicolon',
    KeyboardKey.K: 'K',
    KeyboardKey.L: 'L',
    KeyboardKey.Z: 'Z',
    KeyboardKey.X: 'X',
    KeyboardKey.I: 'I',
    KeyboardKey.UP: 'Up',
    KeyboardKey.DOWN: 'Down',
    KeyboardKey.LEFT: 'Left',
    KeyboardKey.RIGHT: 'Right',
    KeyboardKey.W: 'W',
    KeyboardKey.S: 'S',
    KeyboardKey.A: 'A',
    KeyboardKey.D: 'D',
    KeyboardKey.KEYPAD_1: 'NumPadOne',
    KeyboardKey.KEYPAD_2: 'NumPadTwo',
}


def keyboard_mapping(config: KeyboardControlConfig) -> dict[str, str]:
    """将功能名到 KeyboardKey 的配置转换为 Unreal FKey 名称。"""
    return {name: KEYBOARD_FKEYS[key] for name, key in config if key != KeyboardKey.UNBOUND}


class DrivingViewControl(BaseModel, frozen=True):
    throttle: float = 0.0
    steer: float = 0.0
    brake: float = 0.0
    reverse: bool = False
    hand_brake: bool = False
    manual_gear_shift: bool = False
    gear: int = 0


class DrivingViewInput(DrivingViewControl, frozen=True):
    takeover_requested: bool = False
    toggle_autopilot_requested: bool = False


class DrivingViewState(BaseModel, frozen=True):
    timestamp: float
    wall_time: float
    frame_no: int
    delta: float
    input: DrivingViewInput
    control: DrivingViewControl
    location: tuple[float, float, float]
    rotation: tuple[float, float, float]
    velocity: tuple[float, float, float]
    mode: Literal['manual', 'autopilot'] = 'manual'
    active: bool = True
    ready: bool = True
    error: str = ''


class DrivingViewSetup(BaseModel, frozen=True):
    """Unreal 当前生效的驾驶视图配置。"""

    active: bool = True
    mode: Literal['manual', 'autopilot'] = 'manual'
    cameras: CameraRigConfig
    layout: DisplayLayoutConfig
    keyboard: dict[str, str] = {}


def _payload(value: BaseModel | dict | None) -> dict | None:
    """接受 pydantic 模型或普通字典，统一成 JSON-RPC 参数。"""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    return value


class DrivingViewClient:
    """通过 127.0.0.1 上的换行分隔 JSON 与 Unreal 驾驶视图通信。"""

    def __init__(self, config: DrivingViewConfig) -> None:
        self.config = config
        self._socket: socket.socket | None = None
        self._buffer = b''
        self._next_id = 1

    def connect(self) -> None:
        self._socket = socket.create_connection(
            (self.config.host, self.config.port), timeout=self.config.timeout
        )
        self._socket.settimeout(self.config.timeout)
        self._buffer = b''

    def _ensure_socket(self) -> socket.socket:
        if self._socket is None:
            self.connect()
        assert self._socket is not None
        return self._socket

    def _request(self, method: str, params: dict | None = None) -> dict:
        request_id = self._next_id
        self._next_id += 1
        payload = {'id': request_id, 'method': method}
        if params is not None:
            payload['params'] = params
        sock = self._ensure_socket()
        sock.sendall((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))
        while b'\n' not in self._buffer:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError('驾驶视图连接已关闭')
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b'\n', 1)
        response = json.loads(line)
        if response.get('id') != request_id:
            raise RuntimeError('驾驶视图响应编号不匹配')
        if not response.get('ok'):
            raise RuntimeError(f'驾驶视图调用 {method} 失败：{response.get("error", "未知错误")}')
        result = response.get('result')
        return result if isinstance(result, dict) else {}

    def ping(self) -> dict:
        return self._request('driving_view.ping')

    def start(
        self,
        ego_actor_id: int,
        box: dict,
        cameras: CameraRigConfig | dict,
        layout: DisplayLayoutConfig | dict,
        keyboard: dict[str, str],
        mode: str,
    ) -> dict:
        return self._request(
            'driving_view.start',
            {
                'ego_actor_id': ego_actor_id,
                'box': box,
                'cameras': _payload(cameras),
                'layout': _payload(layout),
                'keyboard': keyboard,
                'mode': mode,
            },
        )

    def update(
        self,
        cameras: CameraRigConfig | dict | None = None,
        layout: DisplayLayoutConfig | dict | None = None,
    ) -> dict:
        params: dict = {}
        cameras_payload = _payload(cameras)
        layout_payload = _payload(layout)
        if cameras_payload is not None:
            params['cameras'] = cameras_payload
        if layout_payload is not None:
            params['layout'] = layout_payload
        return self._request('driving_view.update', params)

    def get_config(self) -> DrivingViewSetup:
        return DrivingViewSetup.model_validate(self._request('driving_view.get_config'))

    def set_mode(self, mode: Literal['manual', 'autopilot']) -> dict:
        return self._request('driving_view.set_mode', {'mode': mode})

    def stop(self) -> dict:
        if self._socket is None:
            return {}
        try:
            return self._request('driving_view.stop')
        finally:
            self.close()

    def get_state(self) -> DrivingViewState:
        return DrivingViewState.model_validate(self._request('driving_view.get_state'))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._buffer = b''
