"""抗饱和 PID 纵向速度控制与弯道、停止线减速。"""

import math

import numpy as np

from .planner import RoutePath


class SpeedPIDController:
    """结合道路限速、前方曲率与信号灯停止距离计算油门和刹车。"""

    def __init__(
        self,
        *,
        kp: float = 0.45,
        ki: float = 0.08,
        kd: float = 0.04,
        integral_limit: float = 4.0,
        max_lateral_accel: float = 2.8,
        comfort_decel: float = 2.5,
        stop_margin_m: float = 2.5,
        max_throttle: float = 0.85,
        max_brake: float = 0.9,
    ) -> None:
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._integral_limit = integral_limit
        self._max_lateral_accel = max_lateral_accel
        self._comfort_decel = comfort_decel
        self._stop_margin_m = stop_margin_m
        self._max_throttle = max_throttle
        self._max_brake = max_brake
        self._integral = 0.0
        self._prev_error: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = None

    def target_speed(
        self,
        *,
        speed_limit_mps: float,
        speed_mps: float,
        path: RoutePath | None,
        stop_distance_m: float | None,
    ) -> float:
        """综合限速、前方弯道与停止线距离得到当前期望速度 (m/s)。"""
        target = max(0.0, speed_limit_mps)
        if path is not None and path.curvatures.size > 0:
            horizon = max(15.0, speed_mps * 2.5)
            mask = path.s_values <= horizon
            if np.any(mask):
                max_curv = float(np.max(path.curvatures[mask]))
                if max_curv > 1e-4:
                    curve_speed = math.sqrt((self._max_lateral_accel * 0.8) / max_curv)
                    target = min(target, max(3.0, curve_speed))
        if stop_distance_m is not None:
            effective = stop_distance_m - self._stop_margin_m
            if effective <= 0.0:
                return 0.0
            stop_speed = math.sqrt(2.0 * self._comfort_decel * effective)
            target = min(target, stop_speed)
        return target

    def compute(
        self,
        *,
        speed_mps: float,
        target_speed_mps: float,
        dt: float,
    ) -> tuple[float, float]:
        """返回 (throttle, brake)，范围均为 [0.0, 1.0]。"""
        if target_speed_mps <= 0.05 and speed_mps < 0.3:
            self._integral = 0.0
            self._prev_error = 0.0
            return 0.0, 0.5

        error = target_speed_mps - speed_mps
        derivative = 0.0
        if self._prev_error is not None and dt > 1e-4:
            derivative = (error - self._prev_error) / dt
        self._prev_error = error

        candidate_integral = max(
            -self._integral_limit,
            min(self._integral_limit, self._integral + error * max(dt, 0.0)),
        )
        output = self._kp * error + self._ki * candidate_integral + self._kd * derivative
        # 仅在未饱和或积分趋向回退时更新积分项，避免抗饱和抖动
        if -self._max_brake < output < self._max_throttle or (error * self._integral < 0):
            self._integral = candidate_integral
            output = self._kp * error + self._ki * self._integral + self._kd * derivative

        if output >= 0.0:
            return min(self._max_throttle, output), 0.0
        return 0.0, min(self._max_brake, -output)
