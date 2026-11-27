"""交通场景事件上下文、结构化结果与装饰器注册表。"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from drisca.core.client import NativeApiClient
from drisca.core.traffic_models import LaneSide, TrafficAction
from drisca.core.types import JsonObject, TrafficLightSnapshot, op_highlight_actor

from ..geometry import world_to_local_xy
from ..planner import LocalRoutePlanner
from ..road_graph import LaneNode, LaneProjection
from ..scene import TrafficScene

if TYPE_CHECKING:
    from ..manager import ManagedVehicle, TrafficManager

HAZARD_LIGHT_MASK = 0x30  # CARLA VehicleLightState: LeftBlinker (0x20) | RightBlinker (0x10)


@dataclass(frozen=True, slots=True)
class EgoState:
    """触发交通场景事件时的主车状态快照。"""

    actor_id: int
    x: float
    y: float
    yaw_deg: float
    road_id: int
    lane_id: int
    speed_mps: float = 0.0


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """交通场景事件的结构化执行结果。"""

    action: TrafficAction
    payload: JsonObject
    target_actor_ids: tuple[int, ...] = ()

    def to_event_payload(self) -> JsonObject:
        return {'label': f'traffic:{self.action.value}', 'action': self.action.value, **self.payload}


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    """交通场景事件处理器共享的不可变执行上下文。"""

    manager: TrafficManager
    api: NativeApiClient
    ego: EgoState
    scene: TrafficScene | None
    traffic_lights: Sequence[TrafficLightSnapshot] = ()
    default_speed_limit_mps: float = 33.33
    debug: bool = False

    def locate_ego(self, error_message: str) -> LaneProjection:
        proj = self.manager.graph.locate(
            self.ego.x,
            self.ego.y,
            self.ego.yaw_deg,
            road_id=self.ego.road_id or None,
            lane_id=self.ego.lane_id or None,
        )
        if proj is None:
            raise RuntimeError(error_message)
        return proj

    def local_scene(self) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """将当前场景车辆坐标与朝向投影到主车局部坐标系，返回 (local_x, local_y, heading_dot)。"""
        if self.scene is None or self.scene.actor_ids.size <= 1:
            return None
        local_x, local_y, cos_y, sin_y = world_to_local_xy(
            self.scene.xy,
            x=self.ego.x,
            y=self.ego.y,
            yaw_deg=self.ego.yaw_deg,
        )
        heading_dot = self.scene.headings[:, 0] * cos_y + self.scene.headings[:, 1] * sin_y
        return local_x, local_y, heading_dot

    def spawn_along_ego(
        self,
        *,
        distance_m: float,
        speed_factor: float = 0.85,
        adjacent: LaneSide | None = None,
        initial_speed_mps: float = 0.0,
    ) -> tuple[ManagedVehicle, str]:
        """沿主车当前车道（或相邻同向车道）在指定前方距离生成托管车，返回 (entry, base_lane_key)。"""
        proj = self.locate_ego('主车当前不在可识别车道上，无法沿车道定位前方位置')
        temp_planner = LocalRoutePlanner(self.manager.graph, horizon_m=max(160.0, distance_m + 30.0))
        path = temp_planner.update(
            self.ego.x,
            self.ego.y,
            self.ego.yaw_deg,
            road_id=self.ego.road_id or None,
            lane_id=self.ego.lane_id or None,
        )
        if path is None or path.points.shape[0] < 2:
            raise RuntimeError('前方参考路径不足，无法生成目标车辆')

        idx = min(max(1, int(np.searchsorted(path.s_values, distance_m))), path.points.shape[0] - 1)
        pt = path.points[idx]
        prev = path.points[idx - 1]
        yaw_deg = math.degrees(math.atan2(float(pt[1] - prev[1]), float(pt[0] - prev[0])))
        base_proj = self.manager.graph.locate(float(pt[0]), float(pt[1]), yaw_deg)
        base_lane = base_proj.lane if base_proj is not None else proj.lane

        if adjacent is None:
            entry = self.manager.spawn_managed_vehicle(
                self.api,
                location=(float(pt[0]), float(pt[1]), float(pt[2])),
                yaw_deg=yaw_deg,
                default_speed_limit_mps=self.default_speed_limit_mps,
                speed_factor=speed_factor,
                initial_speed_mps=initial_speed_mps,
            )
            return entry, base_lane.lane_key

        side_lane_key = pick_adjacent_lane(base_lane, adjacent)
        if side_lane_key is None:
            raise RuntimeError('前方路段无相邻同向车道')
        side_lane = self.manager.graph.get(side_lane_key)
        if side_lane is None or side_lane.points.shape[0] < 2:
            raise RuntimeError('相邻车道几何数据缺失')

        dists = np.hypot(side_lane.points[:, 0] - pt[0], side_lane.points[:, 1] - pt[1])
        s_idx = int(np.argmin(dists))
        s_pt = side_lane.points[s_idx]
        s_prev = side_lane.points[max(0, s_idx - 1)]
        s_next = side_lane.points[min(side_lane.points.shape[0] - 1, s_idx + 1)]
        side_yaw = math.degrees(math.atan2(float(s_next[1] - s_prev[1]), float(s_next[0] - s_prev[0])))
        entry = self.manager.spawn_managed_vehicle(
            self.api,
            location=(float(s_pt[0]), float(s_pt[1]), float(s_pt[2])),
            yaw_deg=side_yaw,
            default_speed_limit_mps=self.default_speed_limit_mps,
            speed_factor=speed_factor,
            initial_speed_mps=initial_speed_mps,
        )
        return entry, base_lane.lane_key


def pick_adjacent_lane(base_lane: LaneNode, side: LaneSide) -> str | None:
    left = base_lane.left_lane if base_lane.left_lane and base_lane.left_same_direction else None
    right = base_lane.right_lane if base_lane.right_lane and base_lane.right_same_direction else None
    match side:
        case LaneSide.LEFT:
            return left
        case LaneSide.RIGHT:
            return right
        case LaneSide.PREFER_RIGHT:
            return right or left
        case LaneSide.ANY:
            return left or right


@dataclass(frozen=True, slots=True)
class TrafficActionSpec:
    action: TrafficAction
    params_model: type[BaseModel]
    invoke: Callable[[ScenarioContext, BaseModel], ScenarioResult]
    highlight_debug: bool = True


TRAFFIC_ACTIONS: dict[TrafficAction, TrafficActionSpec] = {}


def register_traffic_action[P: BaseModel](
    action: TrafficAction,
    *,
    params_model: type[P],
    highlight_debug: bool = True,
) -> Callable[
    [Callable[[ScenarioContext, P], ScenarioResult]], Callable[[ScenarioContext, P], ScenarioResult]
]:
    """将强类型交通场景事件处理器注册到动作映射表。"""

    def decorator(
        func: Callable[[ScenarioContext, P], ScenarioResult],
    ) -> Callable[[ScenarioContext, P], ScenarioResult]:
        def runner(ctx: ScenarioContext, raw_params: BaseModel) -> ScenarioResult:
            validated = (
                raw_params
                if isinstance(raw_params, params_model)
                else params_model.model_validate(raw_params.model_dump())
            )
            return func(ctx, validated)

        TRAFFIC_ACTIONS[action] = TrafficActionSpec(
            action=action,
            params_model=params_model,
            invoke=runner,
            highlight_debug=highlight_debug,
        )
        return func

    return decorator


def execute_traffic_action(
    ctx: ScenarioContext,
    action: TrafficAction | str,
    params: BaseModel | JsonObject,
) -> ScenarioResult:
    """按注册表校验参数并分派运行期交通场景事件。"""
    try:
        key = action if isinstance(action, TrafficAction) else TrafficAction(action)
    except ValueError as exc:
        raise ValueError(f'未知交通事件动作：{action}') from exc

    spec = TRAFFIC_ACTIONS[key]
    validated = params if isinstance(params, spec.params_model) else spec.params_model.model_validate(params)
    result = spec.invoke(ctx, validated)
    if ctx.debug and spec.highlight_debug:
        for aid in result.target_actor_ids:
            ctx.manager.queue_operation(op_highlight_actor(actor_id=aid, label=f'{key} #{aid}'))
    return result
