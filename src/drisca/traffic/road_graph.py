"""车道图索引与车辆道路投影。"""

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class LaneNode:
    """单条车道段及其按行驶方向排序的中心线采样。"""

    lane_key: str
    road_id: int
    section_id: int
    lane_id: int
    lane_type: str
    length: float
    section_start_s: float
    is_junction: bool
    is_positive_direction: bool
    successors: tuple[str, ...]
    predecessors: tuple[str, ...]
    left_lane: str | None
    right_lane: str | None
    left_same_direction: bool
    right_same_direction: bool
    left_allowed: bool
    right_allowed: bool
    points: np.ndarray  # shape (N, 3), 米
    directions: np.ndarray  # shape (N, 3), 单位方向向量
    s_values: np.ndarray  # shape (N,), 沿行驶方向起点算起的距离 (m)
    road_s_values: np.ndarray  # shape (N,), OpenDRIVE road_s (m)

    def road_s_to_travel_s(self, road_s: float) -> float:
        """将 OpenDRIVE road_s 转换为本车道沿行驶方向的距离 s。"""
        if self.is_positive_direction:
            return float(max(0.0, min(self.length, road_s - self.section_start_s)))
        section_end_s = self.section_start_s + self.length
        return float(max(0.0, min(self.length, section_end_s - road_s)))


@dataclass(frozen=True, slots=True)
class LaneProjection:
    """车辆位置在车道中心线上的最近投影。"""

    lane: LaneNode
    sample_index: int
    s: float
    lateral_distance: float


class RoadGraph:
    """基于原生 scene.road_graph 构建的车道图索引。"""

    def __init__(self, lanes: dict[str, LaneNode]) -> None:
        self._lanes = lanes
        by_road_lane: dict[tuple[int, int], list[LaneNode]] = {}
        driving_lanes: list[LaneNode] = []
        for node in lanes.values():
            by_road_lane.setdefault((node.road_id, node.lane_id), []).append(node)
            if node.lane_type == 'Driving' and node.points.shape[0] >= 2:
                driving_lanes.append(node)
        self._by_road_lane: dict[tuple[int, int], tuple[LaneNode, ...]] = {
            key: tuple(items) for key, items in by_road_lane.items()
        }
        self._driving_lanes: tuple[LaneNode, ...] = tuple(driving_lanes)

    @classmethod
    def from_native(cls, raw: dict[str, Any]) -> RoadGraph:
        lanes: dict[str, LaneNode] = {}
        for item in raw.get('lanes') or ():
            samples = item.get('centerline') or ()
            if not samples:
                continue
            points = np.array([[s['x'], s['y'], s['z']] for s in samples], dtype=np.float64)
            directions = np.array([s['dir'] for s in samples], dtype=np.float64)
            s_values = np.array([s['s'] for s in samples], dtype=np.float64)
            road_s_values = np.array([s['road_s'] for s in samples], dtype=np.float64)
            lane_key = str(item['id'])
            lanes[lane_key] = LaneNode(
                lane_key=lane_key,
                road_id=int(item['road_id']),
                section_id=int(item['section_id']),
                lane_id=int(item['lane_id']),
                lane_type=str(item.get('type', '')),
                length=float(item.get('length', 0.0)),
                section_start_s=float(item.get('section_start_s', 0.0)),
                is_junction=bool(item.get('is_junction', False)),
                is_positive_direction=bool(item.get('is_positive_direction', True)),
                successors=tuple(str(s) for s in (item.get('successors') or ())),
                predecessors=tuple(str(p) for p in (item.get('predecessors') or ())),
                left_lane=str(item['left_lane']) if item.get('left_lane') else None,
                right_lane=str(item['right_lane']) if item.get('right_lane') else None,
                left_same_direction=bool(item.get('left_same_direction', False)),
                right_same_direction=bool(item.get('right_same_direction', False)),
                left_allowed=bool(item.get('left_allowed', False)),
                right_allowed=bool(item.get('right_allowed', False)),
                points=points,
                directions=directions,
                s_values=s_values,
                road_s_values=road_s_values,
            )
        return cls(lanes)

    def get(self, lane_key: str) -> LaneNode | None:
        return self._lanes.get(lane_key)

    def project_on_lane(self, node: LaneNode, x: float, y: float) -> LaneProjection | None:
        """将世界坐标直接投影到指定车道中心线上。"""
        if node.points.shape[0] == 0:
            return None
        deltas = node.points[:, :2] - np.array([x, y], dtype=np.float64)
        dist_sq = np.einsum('ij,ij->i', deltas, deltas)
        idx = int(np.argmin(dist_sq))
        return LaneProjection(
            lane=node,
            sample_index=idx,
            s=float(node.s_values[idx]),
            lateral_distance=float(math.sqrt(float(dist_sq[idx]))),
        )

    def lanes_for_road(self, road_id: int, lane_id: int) -> tuple[LaneNode, ...]:
        return self._by_road_lane.get((road_id, lane_id), ())

    def locate(
        self,
        x: float,
        y: float,
        yaw_deg: float,
        *,
        road_id: int | None = None,
        lane_id: int | None = None,
        preferred_keys: tuple[str, ...] = (),
    ) -> LaneProjection | None:
        """定位车辆所在车道段与中心线投影，优先使用当前路径与快照 road/lane 线索。"""
        yaw_rad = math.radians(yaw_deg)
        heading = np.array([math.cos(yaw_rad), math.sin(yaw_rad)], dtype=np.float64)
        pos = np.array([x, y], dtype=np.float64)

        candidates: list[LaneNode] = []
        seen: set[str] = set()
        for key in preferred_keys:
            node = self._lanes.get(key)
            if node is not None and key not in seen:
                seen.add(key)
                candidates.append(node)
        if road_id is not None and lane_id is not None:
            for node in self._by_road_lane.get((road_id, lane_id), ()):
                if node.lane_key not in seen:
                    seen.add(node.lane_key)
                    candidates.append(node)

        best = self._best_projection(candidates, pos, heading, max_distance=8.0)
        if best is not None:
            return best
        return self._best_projection(self._driving_lanes, pos, heading, max_distance=15.0)

    def _best_projection(
        self,
        candidates: list[LaneNode] | tuple[LaneNode, ...],
        pos: np.ndarray,
        heading: np.ndarray,
        *,
        max_distance: float,
    ) -> LaneProjection | None:
        best_proj: LaneProjection | None = None
        best_score = float('inf')
        for node in candidates:
            if node.points.shape[0] == 0:
                continue
            deltas = node.points[:, :2] - pos
            dist_sq = np.einsum('ij,ij->i', deltas, deltas)
            idx = int(np.argmin(dist_sq))
            dist = float(math.sqrt(float(dist_sq[idx])))
            if dist > max_distance:
                continue
            dir_xy = node.directions[idx, :2]
            norm = float(np.linalg.norm(dir_xy))
            dot = float(np.dot(dir_xy, heading) / norm) if norm > 1e-6 else 1.0
            # 排除反向车道
            if dot < -0.2:
                continue
            score = dist + (1.0 - max(0.0, dot)) * 2.0
            if score < best_score:
                best_score = score
                best_proj = LaneProjection(
                    lane=node,
                    sample_index=idx,
                    s=float(node.s_values[idx]),
                    lateral_distance=dist,
                )
        return best_proj
