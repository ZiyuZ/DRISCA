"""局部前瞻路径拼接与弯道曲率计算。"""

import random
from dataclasses import dataclass

import numpy as np

from .road_graph import LaneNode, LaneProjection, RoadGraph


@dataclass(frozen=True, slots=True)
class RoutePath:
    """从车辆当前位置向前延伸的连续参考路径。"""

    points: np.ndarray  # shape (M, 3), 米
    s_values: np.ndarray  # shape (M,), 相对车辆当前位置的累计距离 (m)
    curvatures: np.ndarray  # shape (M,), 离散平面曲率 (1/m)
    lane_keys: tuple[str, ...]
    lane_start_s: tuple[float, ...]  # 每段车道在整条路径中的起始偏移 (m)
    current_lane_s: float  # 车辆在首段车道中的行驶距离 s (m)


class LocalRoutePlanner:
    """维护单车前瞻车道链，并在路口按直行优先或随机种子选择后继车道。"""

    def __init__(
        self,
        graph: RoadGraph,
        *,
        horizon_m: float = 80.0,
        random_seed: int | None = None,
    ) -> None:
        self._graph = graph
        self._horizon_m = horizon_m
        self._rng = random.Random(random_seed) if random_seed is not None else None
        self._queue: list[str] = []

    def reset(self) -> None:
        self._queue.clear()

    def current_lane(self) -> LaneNode | None:
        if not self._queue:
            return None
        return self._graph.get(self._queue[0])

    def switch_lane(self, target_lane_key: str) -> None:
        """发起换道，将目标车道置为前瞻队列首段。"""
        if self._graph.get(target_lane_key) is not None:
            self._queue = [target_lane_key]

    def update(
        self,
        x: float,
        y: float,
        yaw_deg: float,
        *,
        road_id: int | None = None,
        lane_id: int | None = None,
    ) -> RoutePath | None:
        """根据当前车辆位姿更新前瞻路径。"""
        proj = self._graph.locate(
            x,
            y,
            yaw_deg,
            road_id=road_id,
            lane_id=lane_id,
            preferred_keys=tuple(self._queue[:3]),
        )
        if proj is None:
            return None
        self._sync_queue(proj)
        return self._build_path(proj)

    def _sync_queue(self, proj: LaneProjection) -> None:
        key = proj.lane.lane_key
        if key in self._queue:
            idx = self._queue.index(key)
            if idx > 0:
                del self._queue[:idx]
        else:
            self._queue = [key]

        remaining = max(0.0, proj.lane.length - proj.s)
        for existing in self._queue[1:]:
            node = self._graph.get(existing)
            if node is not None:
                remaining += node.length

        # 向前补充后继车道，直到满足前瞻距离或无后继
        visited_tail = 0
        while remaining < self._horizon_m and visited_tail < 32:
            tail = self._graph.get(self._queue[-1])
            if tail is None:
                break
            nxt = self._pick_successor(tail)
            if nxt is None:
                break
            self._queue.append(nxt.lane_key)
            remaining += nxt.length
            visited_tail += 1

    def _pick_successor(self, lane: LaneNode) -> LaneNode | None:
        valid = [
            node
            for key in lane.successors
            if (node := self._graph.get(key)) is not None and node.points.shape[0] >= 2
        ]
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0]
        if self._rng is not None:
            return self._rng.choice(valid)
        # 默认优先选择与当前车道末端方向夹角最小（最接近直行）的后继
        end_dir = lane.directions[-1, :2]
        end_norm = float(np.linalg.norm(end_dir))
        if end_norm < 1e-6:
            return valid[0]
        end_unit = end_dir / end_norm
        best_node = valid[0]
        best_dot = -2.0
        for candidate in valid:
            cand_dir = candidate.directions[0, :2]
            cand_norm = float(np.linalg.norm(cand_dir))
            dot = float(np.dot(end_unit, cand_dir / cand_norm)) if cand_norm > 1e-6 else 0.0
            if dot > best_dot:
                best_dot = dot
                best_node = candidate
        return best_node

    def _build_path(self, proj: LaneProjection) -> RoutePath:
        point_chunks: list[np.ndarray] = []
        lane_keys: list[str] = []
        lane_start_s: list[float] = []
        offset = 0.0

        for idx, key in enumerate(self._queue):
            node = self._graph.get(key)
            if node is None or node.points.shape[0] == 0:
                continue
            lane_keys.append(key)
            lane_start_s.append(offset)
            if idx == 0:
                pts = node.points[proj.sample_index :]
                offset += max(0.0, node.length - proj.s)
            else:
                pts = node.points
                offset += node.length
            if pts.shape[0] == 0:
                continue
            # 去掉与上一段末端几乎重合的首点
            if point_chunks and float(np.linalg.norm(pts[0, :2] - point_chunks[-1][-1, :2])) < 0.2:
                pts = pts[1:]
            if pts.shape[0] > 0:
                point_chunks.append(pts)

        if not point_chunks:
            empty = np.zeros((0, 3), dtype=np.float64)
            empty_1d = np.zeros((0,), dtype=np.float64)
            return RoutePath(
                points=empty,
                s_values=empty_1d,
                curvatures=empty_1d,
                lane_keys=tuple(lane_keys),
                lane_start_s=tuple(lane_start_s),
                current_lane_s=proj.s,
            )

        points = np.vstack(point_chunks)
        if points.shape[0] == 1:
            s_values = np.array([0.0], dtype=np.float64)
            curvatures = np.array([0.0], dtype=np.float64)
        else:
            diffs = np.diff(points[:, :2], axis=0)
            seg_len = np.hypot(diffs[:, 0], diffs[:, 1])
            s_values = np.concatenate(([0.0], np.cumsum(seg_len)))
            curvatures = _compute_curvatures(points[:, :2])

        return RoutePath(
            points=points,
            s_values=s_values,
            curvatures=curvatures,
            lane_keys=tuple(lane_keys),
            lane_start_s=tuple(lane_start_s),
            current_lane_s=proj.s,
        )


def _compute_curvatures(xy: np.ndarray) -> np.ndarray:
    """向量化三点外接圆近似计算离散路径平面曲率绝对值 (1/m)。"""
    n = xy.shape[0]
    curvatures = np.zeros(n, dtype=np.float64)
    if n < 3:
        return curvatures
    p0, p1, p2 = xy[:-2], xy[1:-1], xy[2:]
    v1 = p1 - p0
    v2 = p2 - p1
    v3 = p2 - p0
    a = np.hypot(v1[:, 0], v1[:, 1])
    b = np.hypot(v2[:, 0], v2[:, 1])
    c = np.hypot(v3[:, 0], v3[:, 1])
    denom = a * b * c
    cross = np.abs(v1[:, 0] * v3[:, 1] - v1[:, 1] * v3[:, 0])
    valid = denom >= 1e-6
    curvatures[1:-1] = np.where(valid, 2.0 * cross / np.where(valid, denom, 1.0), 0.0)
    curvatures[0] = curvatures[1]
    curvatures[-1] = curvatures[-2]
    return curvatures
