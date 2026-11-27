"""DRISCA 核心公共类型定义：JSON 值别名、CARLA 批操作模型与信号灯快照。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | Sequence[JsonValue] | Mapping[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def as_int(value: JsonValue, default: int = 0) -> int:
    """将 JSON 标量值安全转换为 int。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        return int(value)
    return default


def as_float(value: JsonValue, default: float = 0.0) -> float:
    """将 JSON 标量值安全转换为 float。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return default


class TrafficLightState(StrEnum):
    """交通信号灯相位（与 CARLA 原生状态一致）。"""

    RED = 'red'
    YELLOW = 'yellow'
    GREEN = 'green'
    OFF = 'off'
    UNKNOWN = 'unknown'

    @classmethod
    def parse(cls, value: str) -> TrafficLightState:
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class TrafficLightSnapshot:
    """单帧中单个交通信号灯的结构化状态快照。"""

    actor_id: int | None
    signal_id: str
    state: TrafficLightState
    frozen: bool = False
    controller_id: str | None = None
    group_id: int | None = None

    @classmethod
    def from_wire(cls, raw: JsonObject) -> TrafficLightSnapshot:
        raw_actor = raw.get('actor_id')
        actor_id = int(raw_actor) if isinstance(raw_actor, int) and not isinstance(raw_actor, bool) else None
        raw_group = raw.get('group_id')
        group_id = int(raw_group) if isinstance(raw_group, int) and not isinstance(raw_group, bool) else None
        raw_ctrl = raw.get('controller_id')
        controller_id = str(raw_ctrl) if raw_ctrl is not None and raw_ctrl != '' else None
        return cls(
            actor_id=actor_id,
            signal_id=str(raw.get('signal_id') or ''),
            state=TrafficLightState.parse(str(raw.get('state') or '')),
            frozen=bool(raw.get('frozen', False)),
            controller_id=controller_id,
            group_id=group_id,
        )


@dataclass(frozen=True, slots=True)
class NativeOp:
    """发往 CARLA DriscaApi batch/exchange 的强类型操作基类。"""

    method: str
    params: JsonObject

    def to_wire(self) -> JsonObject:
        return {'method': self.method, 'params': self.params}


def op_apply_control(
    *,
    actor_id: int,
    expected_control_revision: int,
    throttle: float,
    steer: float,
    brake: float,
    hand_brake: bool = False,
    reverse: bool = False,
    manual_gear_shift: bool = False,
    gear: int = 0,
) -> NativeOp:
    return NativeOp(
        method='vehicle.apply_control',
        params={
            'actor_id': actor_id,
            'expected_control_revision': expected_control_revision,
            'throttle': throttle,
            'steer': steer,
            'brake': brake,
            'hand_brake': hand_brake,
            'reverse': reverse,
            'manual_gear_shift': manual_gear_shift,
            'gear': gear,
        },
    )


def op_set_vehicle_lights(*, actor_id: int, light_state: int) -> NativeOp:
    return NativeOp(
        method='vehicle.set_lights',
        params={'actor_id': actor_id, 'light_state': light_state},
    )


def op_set_vehicle_mode(
    *,
    actor_id: int,
    mode: str,
    controller: str | None = None,
    expected_control_revision: int | None = None,
) -> NativeOp:
    params: JsonObject = {'actor_id': actor_id, 'mode': mode}
    if controller is not None:
        params['controller'] = controller
    if expected_control_revision is not None:
        params['expected_control_revision'] = expected_control_revision
    return NativeOp(method='vehicle.set_mode', params=params)


def op_destroy_vehicles(actor_ids: list[int]) -> NativeOp:
    ids: list[JsonValue] = list(actor_ids)
    return NativeOp(method='vehicle.destroy', params={'actor_ids': ids})


def op_set_traffic_light_state(*, actor_id: int, state: str) -> NativeOp:
    return NativeOp(
        method='traffic_light.set_state',
        params={'actor_id': actor_id, 'state': state},
    )


def op_highlight_actor(*, actor_id: int, label: str, duration_s: float = 6.0) -> NativeOp:
    return NativeOp(
        method='debug.highlight_actor',
        params={'actor_id': actor_id, 'label': label, 'duration_s': duration_s},
    )


def op_highlight_path(*, actor_id: int, points: list[list[float]], duration_s: float = 0.35) -> NativeOp:
    wire_points: list[JsonValue] = [[float(c) for c in pt] for pt in points]
    return NativeOp(
        method='debug.highlight_path',
        params={'actor_id': actor_id, 'points': wire_points, 'duration_s': duration_s},
    )


def op_update_view(
    *,
    view_mode: str | None = None,
    ego_actor_id: int | None = None,
) -> NativeOp:
    params: JsonObject = {}
    if view_mode is not None:
        params['view_mode'] = view_mode
    if ego_actor_id is not None:
        params['ego_actor_id'] = ego_actor_id
    return NativeOp(method='driving_view.update', params=params)
