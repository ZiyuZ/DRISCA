"""向量化前车检测与 IDM（Intelligent Driver Model）跟驰模型。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import world_to_local_xy
from .scene import TrafficScene


@dataclass(frozen=True, slots=True)
class LeadVehicle:
    """前方最近同向冲突车辆的净间距与车速。"""

    actor_id: int
    gap_m: float  # 扣除车身长度后的近似净间距 (m)
    speed_mps: float


class IDMModel:
    """标准 IDM 跟驰模型，用于主车自动驾驶与背景交通车防追尾。"""

    def __init__(
        self,
        *,
        min_gap_m: float = 2.5,
        time_headway_s: float = 1.5,
        max_accel: float = 2.2,
        comfort_decel: float = 2.8,
        vehicle_length_m: float = 4.6,
        detection_range_m: float = 48.0,
        lateral_corridor_m: float = 1.9,
    ) -> None:
        self._s0 = min_gap_m
        self._time_headway = time_headway_s
        self._max_accel = max_accel
        self._comfort_decel = comfort_decel
        self._vehicle_length_m = vehicle_length_m
        self._detection_range_m = detection_range_m
        self._lateral_corridor_m = lateral_corridor_m
        self._two_sqrt_ab = 2.0 * math.sqrt(max_accel * comfort_decel)

    def detect_lead(
        self,
        scene: TrafficScene,
        *,
        self_actor_id: int,
        x: float,
        y: float,
        yaw_deg: float,
    ) -> LeadVehicle | None:
        """在共享向量化场景中检测正前方同向最近车辆。"""
        if scene.actor_ids.size <= 1:
            return None

        local_x, local_y, cos_y, sin_y = world_to_local_xy(scene.xy, x=x, y=y, yaw_deg=yaw_deg)
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y

        mask = (
            (scene.actor_ids != self_actor_id)
            & (local_x > 1.0)
            & (local_x <= self._detection_range_m)
            & (np.abs(local_y) <= self._lateral_corridor_m)
            & (heading_dot > 0.35)
        )
        indices = np.flatnonzero(mask)
        if indices.size == 0:
            return None

        best_local = int(np.argmin(local_x[indices]))
        idx = int(indices[best_local])
        gap = max(0.1, float(local_x[idx]) - self._vehicle_length_m)
        return LeadVehicle(
            actor_id=int(scene.actor_ids[idx]),
            gap_m=gap,
            speed_mps=float(scene.speeds[idx]),
        )

    def compute_accel(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
    ) -> float:
        """计算 IDM 瞬时加速度 (m/s^2)。"""
        v = max(0.0, speed_mps)
        v0 = max(0.5, free_speed_mps)
        free_term = (v / v0) ** 4
        if lead is None:
            return max(-6.0, min(self._max_accel, self._max_accel * (1.0 - free_term)))
        dv = v - lead.speed_mps
        s_star = self._s0 + max(0.0, v * self._time_headway + (v * dv) / self._two_sqrt_ab)
        accel = self._max_accel * (1.0 - free_term - (s_star / max(lead.gap_m, 0.2)) ** 2)
        return max(-6.0, min(self._max_accel, accel))

    def desired_speed(
        self,
        *,
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        horizon_s: float = 0.6,
    ) -> float:
        """基于 IDM 加速度公式计算下一规划视界的目标速度 (m/s)。"""
        if lead is None or free_speed_mps <= 0.05:
            return free_speed_mps

        v = max(0.0, speed_mps)
        accel = self.compute_accel(speed_mps=v, free_speed_mps=free_speed_mps, lead=lead)
        target = max(0.0, min(free_speed_mps, v + accel * horizon_s))
        if lead.gap_m < self._s0 and lead.speed_mps < 0.5:
            return 0.0
        return target
