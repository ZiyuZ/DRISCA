"""向量化前车检测与 IDM（Intelligent Driver Model）跟驰模型。"""

import math
from dataclasses import dataclass

import numpy as np

from .geometry import world_to_local_xy
from .planner import RoutePath
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
        lateral_corridor_m: float = 2.15,
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
        speed_mps: float = 0.0,
        path: RoutePath | None = None,
    ) -> LeadVehicle | None:
        """在共享向量化场景中按车速与驾驶风格自适应探测前方冲突车辆（支持弯道路径走廊）。"""
        if scene.actor_ids.size <= 1:
            return None

        v = max(0.0, speed_mps)
        # 随车速与风格（车头时距、舒适减速度）自适应扩展前瞻探测距离
        stop_preview = (v * v) / (2.0 * max(self._comfort_decel, 0.8)) + v * (self._time_headway + 1.5)
        detect_range = max(self._detection_range_m, min(110.0, stop_preview * 1.8 + 18.0))

        best_idx = -1
        best_s = float('inf')
        best_heading_dot = 1.0

        # 1. 直线局部坐标系走廊探测
        local_x, local_y, cos_y, sin_y = world_to_local_xy(scene.xy, x=x, y=y, yaw_deg=yaw_deg)
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y
        in_straight = (
            (scene.actor_ids != self_actor_id)
            & (local_x > 1.0)
            & (local_x <= detect_range)
            & (np.abs(local_y) <= self._lateral_corridor_m)
        )
        for i in np.flatnonzero(in_straight):
            s_val = float(local_x[i])
            if s_val < best_s:
                best_s = s_val
                best_idx = int(i)
                best_heading_dot = float(heading_dot[i])

        # 2. 沿实际规划弯道路径的走廊探测（覆盖弯道与路口转向盲区）
        if path is not None and path.points.shape[0] >= 2:
            valid_mask = path.s_values <= detect_range
            pts_xy = path.points[valid_mask, :2]
            s_vals = path.s_values[valid_mask]
            if pts_xy.shape[0] >= 2:
                step = max(1, pts_xy.shape[0] // 32)
                sample_xy = pts_xy[::step]
                sample_s = s_vals[::step]
                # 计算每个采样点的切向单位向量
                diffs = np.diff(
                    sample_xy, axis=0, append=sample_xy[-1:] + (sample_xy[-1:] - sample_xy[-2:-1])
                )
                norms = np.hypot(diffs[:, 0], diffs[:, 1])
                norms = np.where(norms > 1e-6, norms, 1.0)
                tangents = diffs / norms[:, None]

                # 粗筛欧氏距离范围内的其他车辆
                dx_all = scene.xy[:, 0] - x
                dy_all = scene.xy[:, 1] - y
                near_mask = (scene.actor_ids != self_actor_id) & (
                    dx_all * dx_all + dy_all * dy_all <= (detect_range + 4.0) ** 2
                )
                for i in np.flatnonzero(near_mask):
                    vx = float(scene.xy[i, 0])
                    vy = float(scene.xy[i, 1])
                    d_sq = (sample_xy[:, 0] - vx) ** 2 + (sample_xy[:, 1] - vy) ** 2
                    k = int(np.argmin(d_sq))
                    s_val = float(sample_s[k])
                    if s_val <= 1.0 or s_val >= best_s:
                        continue
                    if float(d_sq[k]) <= self._lateral_corridor_m * self._lateral_corridor_m:
                        best_s = s_val
                        best_idx = int(i)
                        best_heading_dot = float(
                            scene.headings[i, 0] * tangents[k, 0] + scene.headings[i, 1] * tangents[k, 1]
                        )

        if best_idx < 0:
            return None

        gap = max(0.1, best_s - self._vehicle_length_m)
        # 保留沿路径切向的速度投影：逆行占道车辆为负值，可放大相对接近速度 dv 促使提前减速
        effective_speed = float(scene.speeds[best_idx]) * best_heading_dot
        return LeadVehicle(
            actor_id=int(scene.actor_ids[best_idx]),
            gap_m=gap,
            speed_mps=effective_speed,
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
        closing = max(0.0, v - lead.speed_mps)
        emerg_decel = max(self._comfort_decel * 1.7, 5.5)
        emerg_dist = (v * v) / (2.0 * emerg_decel) + self._s0
        ttc = lead.gap_m / closing if closing > 0.5 else float('inf')

        # 分级制动：危险 TTC 或紧急制动距离内触发急停，远距由 IDM 舒适减速度平滑预判减速
        if lead.speed_mps < -0.5 and (lead.gap_m <= emerg_dist or ttc <= 1.6):
            return 0.0
        if closing > 1.0 and ttc <= 1.2 and lead.gap_m <= emerg_dist:
            return 0.0

        accel = self.compute_accel(speed_mps=v, free_speed_mps=free_speed_mps, lead=lead)
        target = max(0.0, min(free_speed_mps, v + accel * horizon_s))
        if lead.gap_m < self._s0 and lead.speed_mps < 0.5:
            return 0.0
        return target
