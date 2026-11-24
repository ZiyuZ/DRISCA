"""单车自动驾驶组合控制器（支持驾驶风格、IDM 跟驰、感知延迟与安全换道）。"""

import random
from collections import deque
from dataclasses import dataclass
from typing import Any

from .car_following import create_car_following_model
from .idm import LeadVehicle
from .lane_change import create_lane_change_decider
from .lateral import PurePursuitController
from .longitudinal import SpeedPIDController
from .planner import LocalRoutePlanner
from .profiles import BALANCED_PROFILE, DrivingProfile
from .road_graph import RoadGraph
from .scene import TrafficScene
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
    """组合车道图、局部路径规划、横向转向、纵向速度、IDM 跟驰、换道与信号灯响应。"""

    def __init__(
        self,
        graph: RoadGraph,
        signals: SignalTracker,
        *,
        default_speed_limit_mps: float = 33.33,
        dynamic_speed_limit: bool = False,
        speed_factor: float = 1.0,
        enable_lane_change: bool = False,
        profile: DrivingProfile = BALANCED_PROFILE,
        car_following_model: str = 'idm',
        lane_change_model: str = 'gap',
        random_seed: int | None = None,
    ) -> None:
        self._graph = graph
        self._profile = profile
        rng = random.Random(random_seed) if random_seed is not None else None
        self._planner = LocalRoutePlanner(graph, random_seed=random_seed)
        self._lateral = PurePursuitController(max_steer_rate=profile.max_steer_rate)
        self._longitudinal = SpeedPIDController(
            max_lateral_accel=profile.max_lateral_accel,
            comfort_decel=profile.comfort_decel,
            max_throttle=profile.max_throttle,
            max_brake=profile.max_brake,
        )
        self._cf = create_car_following_model(car_following_model, profile, rng=rng)
        self._lane_change = (
            create_lane_change_decider(lane_change_model, profile, self._cf) if enable_lane_change else None
        )
        self._signals = signals
        self._default_speed_limit_mps = default_speed_limit_mps
        self._dynamic_speed_limit = dynamic_speed_limit
        self._speed_factor = speed_factor * profile.speed_multiplier
        self._elapsed_s = 0.0
        self._perception_buffer: deque[tuple[float, LeadVehicle | None, float | None]] = deque()

    def reset(self) -> None:
        self._planner.reset()
        self._lateral.reset()
        self._longitudinal.reset()
        if self._lane_change is not None:
            self._lane_change.reset()
        self._elapsed_s = 0.0
        self._perception_buffer.clear()

    def _apply_reaction_delay(
        self,
        dt: float,
        lead: LeadVehicle | None,
        stop_distance: float | None,
    ) -> tuple[LeadVehicle | None, float | None]:
        delay = self._profile.reaction_delay_s
        if delay <= 0.0:
            return lead, stop_distance
        self._elapsed_s += max(dt, 0.0)
        self._perception_buffer.append((self._elapsed_s, lead, stop_distance))
        cutoff = self._elapsed_s - delay
        delayed_lead: LeadVehicle | None = None
        delayed_stop: float | None = None
        while len(self._perception_buffer) > 1 and self._perception_buffer[1][0] <= cutoff:
            self._perception_buffer.popleft()
        if self._perception_buffer[0][0] <= cutoff:
            _, delayed_lead, delayed_stop = self._perception_buffer[0]
        return delayed_lead, delayed_stop

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
        scene: TrafficScene | None = None,
        self_actor_id: int = 0,
    ) -> VehicleControl:
        """根据当前车辆状态、周边车辆场景与实时信号灯计算本步控制量。"""
        path = self._planner.update(x, y, yaw_deg, road_id=road_id, lane_id=lane_id)
        if path is None:
            return VehicleControl(throttle=0.0, steer=0.0, brake=0.6)

        speed_limit = self._default_speed_limit_mps
        if self._dynamic_speed_limit and road_speed_limit_mps > 0.1:
            speed_limit = road_speed_limit_mps
        speed_limit = max(0.0, speed_limit * self._speed_factor)

        raw_lead = (
            self._cf.detect_lead(scene, self_actor_id=self_actor_id, x=x, y=y, yaw_deg=yaw_deg)
            if scene is not None and self_actor_id > 0
            else None
        )
        raw_stop = self._signals.nearest_stop_distance(path, traffic_lights)
        lead, stop_distance = self._apply_reaction_delay(dt, raw_lead, raw_stop)

        if self._lane_change is not None and scene is not None and self_actor_id > 0:
            target_lane = self._lane_change.decide(
                graph=self._graph,
                current_lane=self._planner.current_lane(),
                scene=scene,
                self_actor_id=self_actor_id,
                x=x,
                y=y,
                yaw_deg=yaw_deg,
                speed_mps=speed_mps,
                free_speed_mps=speed_limit,
                lead=lead,
                dt=dt,
            )
            if target_lane is not None:
                self._planner.switch_lane(target_lane)
                switched = self._planner.update(x, y, yaw_deg, road_id=None, lane_id=None)
                if switched is not None:
                    path = switched

        free_target = self._longitudinal.target_speed(
            speed_limit_mps=speed_limit,
            speed_mps=speed_mps,
            path=path,
            stop_distance_m=stop_distance,
        )
        target_speed = self._cf.desired_speed(
            speed_mps=speed_mps,
            free_speed_mps=free_target,
            lead=lead,
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
