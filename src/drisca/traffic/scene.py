"""每帧共享的向量化车辆场景视图，供跟驰与换道零重复计算查询。"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class TrafficScene:
    """从原生 Snapshot.vehicles 一次性提取的只读向量化几何视图。"""

    actor_ids: np.ndarray  # shape (N,), uint32
    xy: np.ndarray  # shape (N, 2), float64 (m)
    headings: np.ndarray  # shape (N, 2), float64 单位航向向量
    speeds: np.ndarray  # shape (N,), float64 (m/s)
    road_ids: np.ndarray  # shape (N,), int32
    lane_ids: np.ndarray  # shape (N,), int32

    @classmethod
    def from_vehicles(cls, vehicles: np.ndarray) -> TrafficScene:
        n = int(vehicles.shape[0])
        if n == 0:
            empty_u4 = np.empty((0,), dtype=np.uint32)
            empty_2d = np.empty((0, 2), dtype=np.float64)
            empty_1d = np.empty((0,), dtype=np.float64)
            empty_i4 = np.empty((0,), dtype=np.int32)
            return cls(
                actor_ids=empty_u4,
                xy=empty_2d,
                headings=empty_2d,
                speeds=empty_1d,
                road_ids=empty_i4,
                lane_ids=empty_i4,
            )
        xy = vehicles['location'][:, :2].astype(np.float64, copy=False)
        yaws = np.radians(vehicles['rotation'][:, 1].astype(np.float64, copy=False))
        headings = np.column_stack((np.cos(yaws), np.sin(yaws)))
        vel = vehicles['velocity'].astype(np.float64, copy=False)
        speeds = np.sqrt(np.einsum('ij,ij->i', vel, vel))
        return cls(
            actor_ids=vehicles['actor_id'],
            xy=xy,
            headings=headings,
            speeds=speeds,
            road_ids=vehicles['road_id'],
            lane_ids=vehicles['lane_id'],
        )
