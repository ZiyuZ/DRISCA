"""可插拔跟驰模型集合：IDM、Gipps 与 Krauss。"""

import math
import random
from typing import Protocol

from .idm import IDMModel, LeadVehicle
from .planner import RoutePath
from .profiles import DrivingProfile
from .scene import TrafficScene


class CarFollowingModel(Protocol):
    """跟驰模型统一接口。"""

    def detect_lead(
        self,
        scene: TrafficScene,
        *,
        self_actor_id: int,
        x: float,
        y: float,
        yaw_deg: float,
        speed_mps: float = 0.0,
        path: RoutePath | None = None,
    ) -> LeadVehicle | None: ...

    def compute_accel(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
    ) -> float: ...

    def desired_speed(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        horizon_s: float = 0.6,
    ) -> float: ...


class GippsModel(IDMModel):
    """Gipps 安全速度跟驰模型：显式考虑反应时间与前车最大制动估计。"""

    def __init__(
        self,
        *,
        min_gap_m: float = 2.5,
        reaction_time_s: float = 0.8,
        max_accel: float = 2.2,
        comfort_decel: float = 2.8,
        est_lead_decel: float = 3.2,
        vehicle_length_m: float = 4.6,
        detection_range_m: float = 48.0,
        lateral_corridor_m: float = 1.9,
    ) -> None:
        super().__init__(
            min_gap_m=min_gap_m,
            time_headway_s=reaction_time_s,
            max_accel=max_accel,
            comfort_decel=comfort_decel,
            vehicle_length_m=vehicle_length_m,
            detection_range_m=detection_range_m,
            lateral_corridor_m=lateral_corridor_m,
        )
        self._tau = max(0.2, reaction_time_s)
        self._b_est = max(0.5, est_lead_decel)

    def desired_speed(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        horizon_s: float = 0.6,
    ) -> float:
        if free_speed_mps <= 0.05:
            return 0.0
        v = max(0.0, speed_mps)
        v0 = max(0.5, free_speed_mps)
        # 自由流加速分支
        v_acc = v + 2.5 * self._max_accel * self._tau * (1.0 - v / v0) * math.sqrt(0.025 + v / v0)
        if lead is None:
            return max(0.0, min(free_speed_mps, v_acc))

        # 安全跟驰分支
        b = self._comfort_decel
        effective_gap = max(0.0, lead.gap_m - self._s0)
        radicand = (b * self._tau) ** 2 + b * (
            2.0 * effective_gap - v * self._tau + (lead.speed_mps**2) / self._b_est
        )
        v_safe = -b * self._tau + math.sqrt(max(0.0, radicand))
        return max(0.0, min(free_speed_mps, v_acc, v_safe))

    def compute_accel(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
    ) -> float:
        target = self.desired_speed(
            speed_mps=speed_mps,
            free_speed_mps=free_speed_mps,
            lead=lead,
            horizon_s=self._tau,
        )
        return max(-6.0, min(self._max_accel, (target - speed_mps) / self._tau))


class KraussModel(IDMModel):
    """Krauss（SUMO 默认）随机安全速度模型：含随机松弛项（dawdling）。"""

    def __init__(
        self,
        *,
        min_gap_m: float = 2.5,
        time_headway_s: float = 1.2,
        max_accel: float = 2.2,
        comfort_decel: float = 3.0,
        dawdle: float = 0.18,
        rng: random.Random | None = None,
        vehicle_length_m: float = 4.6,
        detection_range_m: float = 48.0,
        lateral_corridor_m: float = 1.9,
    ) -> None:
        super().__init__(
            min_gap_m=min_gap_m,
            time_headway_s=time_headway_s,
            max_accel=max_accel,
            comfort_decel=comfort_decel,
            vehicle_length_m=vehicle_length_m,
            detection_range_m=detection_range_m,
            lateral_corridor_m=lateral_corridor_m,
        )
        self._dawdle = max(0.0, min(0.8, dawdle))
        self._rng = rng if rng is not None else random.Random(42)

    def desired_speed(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        horizon_s: float = 0.6,
    ) -> float:
        if free_speed_mps <= 0.05:
            return 0.0
        v = max(0.0, speed_mps)
        v_des = min(free_speed_mps, v + self._max_accel * horizon_s)
        if lead is not None:
            b = self._comfort_decel
            effective_gap = max(0.0, lead.gap_m - self._s0)
            denom = (v + lead.speed_mps) / (2.0 * b) + self._time_headway
            v_safe = lead.speed_mps + (effective_gap - lead.speed_mps * self._time_headway) / max(denom, 0.2)
            v_des = min(v_des, max(0.0, v_safe))

        # 随机松弛（dawdling），引入微小速度波动
        noise = self._dawdle * self._max_accel * horizon_s * self._rng.random()
        return max(0.0, v_des - noise)

    def compute_accel(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
    ) -> float:
        target = self.desired_speed(
            speed_mps=speed_mps,
            free_speed_mps=free_speed_mps,
            lead=lead,
            horizon_s=0.6,
        )
        return max(-6.0, min(self._max_accel, (target - speed_mps) / 0.6))


def create_car_following_model(
    model_name: str,
    profile: DrivingProfile,
    rng: random.Random | None = None,
) -> CarFollowingModel:
    """按模型名称和驾驶风格构造跟驰模型实例。"""
    if model_name == 'idm':
        return IDMModel(
            min_gap_m=profile.min_gap_m,
            time_headway_s=profile.time_headway_s,
            max_accel=profile.max_accel,
            comfort_decel=profile.comfort_decel,
        )
    if model_name == 'gipps':
        return GippsModel(
            min_gap_m=profile.min_gap_m,
            reaction_time_s=profile.gipps_reaction_s,
            max_accel=profile.max_accel,
            comfort_decel=profile.comfort_decel,
        )
    if model_name == 'krauss':
        return KraussModel(
            min_gap_m=profile.min_gap_m,
            time_headway_s=profile.time_headway_s,
            max_accel=profile.max_accel,
            comfort_decel=profile.comfort_decel,
            dawdle=profile.krauss_dawdle,
            rng=rng,
        )
    raise ValueError(f'未知的跟驰模型：{model_name}')
