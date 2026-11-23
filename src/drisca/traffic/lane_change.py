"""可插拔换道决策模型：安全间隙规则（gap）与 MOBIL 激励换道（mobil）。"""

from __future__ import annotations

import math

import numpy as np

from .car_following import CarFollowingModel
from .idm import LeadVehicle
from .profiles import DrivingProfile
from .road_graph import LaneNode, RoadGraph
from .scene import TrafficScene


class LaneChangeDecider:
    """安全间隙规则：本车道前方存在低速障碍车且相邻同向车道前后净距安全时换道。"""

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
        speed_mps: float,
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

        for target_key, lateral_offset in self._candidate_lanes(graph, current_lane):
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

    def _candidate_lanes(self, graph: RoadGraph, current_lane: LaneNode) -> list[tuple[str, float]]:
        candidates: list[tuple[str, float]] = []
        if current_lane.left_lane and current_lane.left_same_direction and current_lane.left_allowed:
            target = graph.get(current_lane.left_lane)
            if target is not None and target.lane_type == 'Driving':
                candidates.append((current_lane.left_lane, -self._lane_width_m))
        if current_lane.right_lane and current_lane.right_same_direction and current_lane.right_allowed:
            target = graph.get(current_lane.right_lane)
            if target is not None and target.lane_type == 'Driving':
                candidates.append((current_lane.right_lane, self._lane_width_m))
        return candidates

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


class MobilLaneChangeDecider(LaneChangeDecider):
    """MOBIL 激励换道模型：权衡本车加速度增益与目标车道后车减速代价。"""

    def __init__(
        self,
        *,
        car_following: CarFollowingModel,
        politeness: float = 0.25,
        threshold: float = 0.2,
        max_safe_decel: float = 4.0,
        cooldown_s: float = 4.0,
        min_front_gap_m: float = 8.0,
        min_rear_gap_m: float = 8.0,
        lane_width_m: float = 3.5,
        vehicle_length_m: float = 4.6,
    ) -> None:
        super().__init__(
            cooldown_s=cooldown_s,
            min_front_gap_m=min_front_gap_m,
            min_rear_gap_m=min_rear_gap_m,
            lane_width_m=lane_width_m,
        )
        self._cf = car_following
        self._politeness = politeness
        self._threshold = threshold
        self._max_safe_decel = max_safe_decel
        self._vehicle_length_m = vehicle_length_m

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
        speed_mps: float,
        free_speed_mps: float,
        lead: LeadVehicle | None,
        dt: float,
    ) -> str | None:
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - max(dt, 0.0))
            return None
        if current_lane is None or current_lane.is_junction:
            return None

        a_ego_old = self._cf.compute_accel(
            speed_mps=speed_mps,
            free_speed_mps=free_speed_mps,
            lead=lead,
        )
        best_lane: str | None = None
        best_incentive = self._threshold

        for target_key, lateral_offset in self._candidate_lanes(graph, current_lane):
            new_lead, new_rear = self._neighbors_in_lane(
                scene,
                self_actor_id=self_actor_id,
                x=x,
                y=y,
                yaw_deg=yaw_deg,
                lateral_center_m=lateral_offset,
            )
            # 硬安全净距门槛，防止紧贴并线
            if new_lead is not None and new_lead.gap_m < self._min_front_gap_m:
                continue
            if new_rear is not None and new_rear.gap_m < self._min_rear_gap_m:
                continue

            a_ego_new = self._cf.compute_accel(
                speed_mps=speed_mps,
                free_speed_mps=free_speed_mps,
                lead=new_lead,
            )

            rear_disadvantage = 0.0
            if new_rear is not None:
                # 评估目标车道后车换道前（跟 new_lead）与换道后（跟本车）的加速度差
                rear_old_lead = (
                    LeadVehicle(
                        actor_id=new_lead.actor_id,
                        gap_m=new_rear.gap_m + self._vehicle_length_m + new_lead.gap_m,
                        speed_mps=new_lead.speed_mps,
                    )
                    if new_lead is not None
                    else None
                )
                rear_new_lead = LeadVehicle(
                    actor_id=self_actor_id,
                    gap_m=new_rear.gap_m,
                    speed_mps=speed_mps,
                )
                a_rear_old = self._cf.compute_accel(
                    speed_mps=new_rear.speed_mps,
                    free_speed_mps=free_speed_mps,
                    lead=rear_old_lead,
                )
                a_rear_new = self._cf.compute_accel(
                    speed_mps=new_rear.speed_mps,
                    free_speed_mps=free_speed_mps,
                    lead=rear_new_lead,
                )
                # MOBIL 安全约束：不得迫使目标车道后车以超过 max_safe_decel 的减速度急刹
                if a_rear_new < -self._max_safe_decel:
                    continue
                rear_disadvantage = a_rear_old - a_rear_new

            incentive = (a_ego_new - a_ego_old) - self._politeness * rear_disadvantage
            if incentive > best_incentive:
                best_incentive = incentive
                best_lane = target_key

        if best_lane is not None:
            self._cooldown_remaining = self._cooldown_s
        return best_lane

    def _neighbors_in_lane(
        self,
        scene: TrafficScene,
        *,
        self_actor_id: int,
        x: float,
        y: float,
        yaw_deg: float,
        lateral_center_m: float,
    ) -> tuple[LeadVehicle | None, LeadVehicle | None]:
        """向量化查找目标相邻车道最近前车与最近后车。"""
        if scene.actor_ids.size <= 1:
            return None, None
        dx = scene.xy[:, 0] - x
        dy = scene.xy[:, 1] - y
        yaw_rad = math.radians(yaw_deg)
        cos_y = math.cos(yaw_rad)
        sin_y = math.sin(yaw_rad)

        local_x = dx * cos_y + dy * sin_y
        local_y = -dx * sin_y + dy * cos_y
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y

        same_lane = (
            (scene.actor_ids != self_actor_id)
            & (np.abs(local_y - lateral_center_m) <= 1.8)
            & (heading_dot > 0.35)
        )

        lead: LeadVehicle | None = None
        front_idx = np.flatnonzero(same_lane & (local_x > 0.0) & (local_x <= 55.0))
        if front_idx.size > 0:
            i = int(front_idx[int(np.argmin(local_x[front_idx]))])
            lead = LeadVehicle(
                actor_id=int(scene.actor_ids[i]),
                gap_m=max(0.1, float(local_x[i]) - self._vehicle_length_m),
                speed_mps=float(scene.speeds[i]),
            )

        rear: LeadVehicle | None = None
        rear_idx = np.flatnonzero(same_lane & (local_x <= 0.0) & (local_x >= -55.0))
        if rear_idx.size > 0:
            i = int(rear_idx[int(np.argmax(local_x[rear_idx]))])
            rear = LeadVehicle(
                actor_id=int(scene.actor_ids[i]),
                gap_m=max(0.1, float(-local_x[i]) - self._vehicle_length_m),
                speed_mps=float(scene.speeds[i]),
            )

        return lead, rear


def create_lane_change_decider(
    model_name: str,
    profile: DrivingProfile,
    car_following: CarFollowingModel,
) -> LaneChangeDecider:
    """按换道模型名称与驾驶风格构造换道决策器。"""
    if model_name == 'gap':
        return LaneChangeDecider(
            cooldown_s=profile.lane_change_cooldown_s,
            min_front_gap_m=profile.min_front_gap_m,
            min_rear_gap_m=profile.min_rear_gap_m,
            slow_ratio=profile.slow_lead_ratio,
        )
    if model_name == 'mobil':
        return MobilLaneChangeDecider(
            car_following=car_following,
            politeness=profile.politeness,
            threshold=profile.mobil_threshold,
            cooldown_s=profile.lane_change_cooldown_s,
            min_front_gap_m=max(6.0, profile.min_front_gap_m * 0.6),
            min_rear_gap_m=max(6.0, profile.min_rear_gap_m * 0.6),
        )
    raise ValueError(f'未知的换道模型：{model_name}')
