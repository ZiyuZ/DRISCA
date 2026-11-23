"""基于同向相邻车道与向量化间隙检查的安全换道决策。"""

from __future__ import annotations

import math

import numpy as np

from .idm import LeadVehicle
from .road_graph import LaneNode, RoadGraph
from .scene import TrafficScene


class LaneChangeDecider:
    """当本车道前方存在低速障碍车且相邻同向车道安全时发起换道。"""

    def __init__(
        self,
        *,
        cooldown_s: float = 4.0,
        min_front_gap_m: float = 14.0,
        min_rear_gap_m: float = 12.0,
        lane_width_m: float = 3.5,
        slow_ratio: float = 0.72,
    ) -> None:
        self._cooldown_s = cooldown_s
        self._min_front_gap_m = min_front_gap_m
        self._min_rear_gap_m = min_rear_gap_m
        self._lane_width_m = lane_width_m
        self._slow_ratio = slow_ratio
        self._cooldown_remaining = 0.0

    def reset(self) -> None:
        self._cooldown_remaining = 0.0

    def decide(
        self,
        *,
        graph: RoadGraph,
        current_lane: LaneNode | None,
        scene: TrafficScene,
        self_actor_id: int,
        x: float,
        y: float,
        yaw_deg: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        dt: float,
    ) -> str | None:
        """若满足换道条件返回目标车道 key，否则返回 None。"""
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - max(dt, 0.0))
            return None
        if current_lane is None or current_lane.is_junction or lead is None:
            return None
        if lead.gap_m > 28.0 or lead.speed_mps >= free_speed_mps * self._slow_ratio:
            return None

        # 优先尝试向左超车，其次向右变道
        candidates: list[tuple[str, float]] = []
        if current_lane.left_lane and current_lane.left_same_direction and current_lane.left_allowed:
            candidates.append((current_lane.left_lane, -self._lane_width_m))
        if current_lane.right_lane and current_lane.right_same_direction and current_lane.right_allowed:
            candidates.append((current_lane.right_lane, self._lane_width_m))

        for target_key, lateral_offset in candidates:
            target_lane = graph.get(target_key)
            if target_lane is None or target_lane.lane_type != 'Driving':
                continue
            if self._is_side_clear(
                scene,
                self_actor_id=self_actor_id,
                x=x,
                y=y,
                yaw_deg=yaw_deg,
                lateral_center_m=lateral_offset,
            ):
                self._cooldown_remaining = self._cooldown_s
                return target_key
        return None

    def _is_side_clear(
        self,
        scene: TrafficScene,
        *,
        self_actor_id: int,
        x: float,
        y: float,
        yaw_deg: float,
        lateral_center_m: float,
    ) -> bool:
        if scene.actor_ids.size <= 1:
            return True
        dx = scene.xy[:, 0] - x
        dy = scene.xy[:, 1] - y
        yaw_rad = math.radians(yaw_deg)
        cos_y = math.cos(yaw_rad)
        sin_y = math.sin(yaw_rad)

        local_x = dx * cos_y + dy * sin_y
        local_y = -dx * sin_y + dy * cos_y

        in_target_lane = (
            (scene.actor_ids != self_actor_id)
            & (np.abs(local_y - lateral_center_m) <= 1.8)
            & (local_x >= -self._min_rear_gap_m)
            & (local_x <= self._min_front_gap_m)
        )
        return not bool(np.any(in_target_lane))
