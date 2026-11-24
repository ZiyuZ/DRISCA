"""CARLA 左手系几何工具（X 向前、Y 向右、Z 向上）。"""

import math

import numpy as np


def world_to_local_xy(
    xy: np.ndarray,
    *,
    x: float,
    y: float,
    yaw_deg: float,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """将批量世界平面坐标 (N, 2) 转换到车身局部坐标 (local_x 向前, local_y 向右)。"""
    yaw_rad = math.radians(yaw_deg)
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)
    dx = xy[:, 0] - x
    dy = xy[:, 1] - y
    local_x = dx * cos_y + dy * sin_y
    local_y = -dx * sin_y + dy * cos_y
    return local_x, local_y, cos_y, sin_y


def point_to_local_xy(
    tx: float,
    ty: float,
    *,
    x: float,
    y: float,
    yaw_deg: float,
) -> tuple[float, float]:
    """将单个世界平面坐标转换到车身局部坐标 (local_x 向前, local_y 向右)。"""
    yaw_rad = math.radians(yaw_deg)
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)
    dx = tx - x
    dy = ty - y
    return dx * cos_y + dy * sin_y, -dx * sin_y + dy * cos_y
