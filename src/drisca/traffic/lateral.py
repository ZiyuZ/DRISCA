"""自适应前瞻 Pure Pursuit 横向转向控制器。"""

from __future__ import annotations

import math

import numpy as np

from .geometry import point_to_local_xy
from .planner import RoutePath


class PurePursuitController:
    """基于参考路径与 CARLA 坐标系（X 向前、Y 向右、Z 向上）的横向转向控制。"""

    def __init__(
        self,
        *,
        wheelbase_m: float = 2.85,
        max_steer_deg: float = 55.0,
        lookahead_gain: float = 0.55,
        min_lookahead_m: float = 4.5,
        max_lookahead_m: float = 18.0,
        max_steer_rate: float = 2.5,
    ) -> None:
        self._wheelbase_m = wheelbase_m
        self._max_steer_rad = math.radians(max_steer_deg)
        self._lookahead_gain = lookahead_gain
        self._min_lookahead_m = min_lookahead_m
        self._max_lookahead_m = max_lookahead_m
        self._max_steer_rate = max_steer_rate
        self._last_steer = 0.0

    def reset(self) -> None:
        self._last_steer = 0.0

    def compute(
        self,
        *,
        x: float,
        y: float,
        yaw_deg: float,
        speed_mps: float,
        dt: float,
        path: RoutePath,
    ) -> float:
        """计算归一化转向指令 [-1.0, 1.0]，右转为正。"""
        if path.points.shape[0] < 2:
            return self._rate_limit(0.0, dt)

        lookahead = max(
            self._min_lookahead_m,
            min(self._max_lookahead_m, self._lookahead_gain * abs(speed_mps) + self._min_lookahead_m),
        )
        target = self._select_target(path, x, y, lookahead)
        local_x, local_y = point_to_local_xy(float(target[0]), float(target[1]), x=x, y=y, yaw_deg=yaw_deg)
        dist = math.hypot(local_x, local_y)
        if dist < 1e-4:
            return self._rate_limit(0.0, dt)

        alpha = math.atan2(local_y, max(local_x, 0.2))
        delta = math.atan2(2.0 * self._wheelbase_m * math.sin(alpha), dist)
        raw_steer = max(-1.0, min(1.0, delta / self._max_steer_rad))
        return self._rate_limit(raw_steer, dt)

    def _select_target(self, path: RoutePath, x: float, y: float, lookahead: float) -> np.ndarray:
        deltas = path.points[:, :2] - np.array([x, y], dtype=np.float64)
        dists = np.hypot(deltas[:, 0], deltas[:, 1])
        indices = np.flatnonzero(dists >= lookahead)
        if indices.size > 0:
            return path.points[int(indices[0])]
        return path.points[-1]

    def _rate_limit(self, target_steer: float, dt: float) -> float:
        if dt <= 0.0:
            self._last_steer = target_steer
            return target_steer
        max_delta = self._max_steer_rate * dt
        delta = max(-max_delta, min(max_delta, target_steer - self._last_steer))
        self._last_steer = max(-1.0, min(1.0, self._last_steer + delta))
        return self._last_steer
