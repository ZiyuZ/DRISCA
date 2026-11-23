"""单车自动驾驶组合控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lateral import PurePursuitController
from .longitudinal import SpeedPIDController
from .planner import LocalRoutePlanner
from .road_graph import RoadGraph
from .signals import SignalTracker


@dataclass(frozen=True, slots=True)
class VehicleControl:
    """发送给原生 vehicle.apply_control 的连续控制量。"""

    throttle: float
    steer: float
    brake: float
    hand_brake: bool = False
    reverse: bool = False
    manual_gear_shift: bool = False
    gear: int = 0

    def to_operation(self, actor_id: int, expected_control_revision: int) -> dict[str, Any]:
        return {
            'method': 'vehicle.apply_control',
            'params': {
                'actor_id': actor_id,
                'expected_control_revision': expected_control_revision,
                'throttle': self.throttle,
                'steer': self.steer,
                'brake': self.brake,
                'hand_brake': self.hand_brake,
                'reverse': self.reverse,
                'manual_gear_shift': self.manual_gear_shift,
                'gear': self.gear,
            },
        }


class AutopilotController:
    """组合车道图、局部路径规划、横向转向、纵向速度与信号灯响应的单车自动驾驶控制器。"""

    def __init__(
        self,
        graph: RoadGraph,
        signals: SignalTracker,
        *,
        default_speed_limit_mps: float = 33.33,
        dynamic_speed_limit: bool = False,
        random_seed: int | None = None,
    ) -> None:
        self._planner = LocalRoutePlanner(graph, random_seed=random_seed)
        self._lateral = PurePursuitController()
        self._longitudinal = SpeedPIDController()
        self._signals = signals
        self._default_speed_limit_mps = default_speed_limit_mps
        self._dynamic_speed_limit = dynamic_speed_limit

    def reset(self) -> None:
        self._planner.reset()
        self._lateral.reset()
        self._longitudinal.reset()

    def step(
        self,
        *,
        x: float,
        y: float,
        yaw_deg: float,
        speed_mps: float,
        dt: float,
        road_id: int | None,
        lane_id: int | None,
        road_speed_limit_mps: float,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> VehicleControl:
        """根据当前车辆状态与实时信号灯计算本步控制量。"""
        path = self._planner.update(x, y, yaw_deg, road_id=road_id, lane_id=lane_id)
        if path is None:
            return VehicleControl(throttle=0.0, steer=0.0, brake=0.6)

        speed_limit = self._default_speed_limit_mps
        if self._dynamic_speed_limit and road_speed_limit_mps > 0.1:
            speed_limit = road_speed_limit_mps

        stop_distance = self._signals.nearest_stop_distance(path, traffic_lights)
        target_speed = self._longitudinal.target_speed(
            speed_limit_mps=speed_limit,
            speed_mps=speed_mps,
            path=path,
            stop_distance_m=stop_distance,
        )
        throttle, brake = self._longitudinal.compute(
            speed_mps=speed_mps,
            target_speed_mps=target_speed,
            dt=dt,
        )
        steer = self._lateral.compute(
            x=x,
            y=y,
            yaw_deg=yaw_deg,
            speed_mps=speed_mps,
            dt=dt,
            path=path,
        )
        return VehicleControl(throttle=throttle, steer=steer, brake=brake)
