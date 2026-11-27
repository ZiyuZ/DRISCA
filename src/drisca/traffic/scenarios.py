"""运行期交通场景事件执行器：急刹、切入、故障停驶、信号突变、双车道压速与闯红灯。"""

import math
import time
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

from drisca.core.client import NativeApiClient

from .geometry import world_to_local_xy
from .planner import LocalRoutePlanner
from .scene import TrafficScene

if TYPE_CHECKING:
    from .manager import ManagedVehicle, TrafficManager

HAZARD_LIGHT_MASK = 0x30  # CARLA VehicleLightState: LeftBlinker (0x20) | RightBlinker (0x10)


def _spawn_along_ego(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    distance_m: float,
    default_speed_limit_mps: float,
    speed_factor: float = 0.85,
    adjacent: str | None = None,
    initial_speed_mps: float = 0.0,
) -> tuple[ManagedVehicle, str]:
    """沿主车当前车道（或相邻同向车道）在指定前方距离生成托管车，返回 (entry, base_lane_key)。"""
    proj = manager.graph.locate(
        ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
    )
    if proj is None:
        raise RuntimeError('主车当前不在可识别车道上，无法沿车道定位前方位置')

    temp_planner = LocalRoutePlanner(manager.graph, horizon_m=max(160.0, distance_m + 30.0))
    path = temp_planner.update(
        ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
    )
    if path is None or path.points.shape[0] < 2:
        raise RuntimeError('前方参考路径不足，无法生成目标车辆')

    idx = min(max(1, int(np.searchsorted(path.s_values, distance_m))), path.points.shape[0] - 1)
    pt = path.points[idx]
    prev = path.points[idx - 1]
    yaw_deg = math.degrees(math.atan2(float(pt[1] - prev[1]), float(pt[0] - prev[0])))
    base_proj = manager.graph.locate(float(pt[0]), float(pt[1]), yaw_deg)
    base_lane = base_proj.lane if base_proj is not None else proj.lane

    if adjacent is None:
        entry = manager.spawn_managed_vehicle(
            api,
            location=(float(pt[0]), float(pt[1]), float(pt[2])),
            yaw_deg=yaw_deg,
            default_speed_limit_mps=default_speed_limit_mps,
            speed_factor=speed_factor,
            initial_speed_mps=initial_speed_mps,
        )
        return entry, base_lane.lane_key

    side_lane_key: str | None = None
    if adjacent == 'left':
        if base_lane.left_lane and base_lane.left_same_direction:
            side_lane_key = base_lane.left_lane
    elif adjacent == 'right':
        if base_lane.right_lane and base_lane.right_same_direction:
            side_lane_key = base_lane.right_lane
    elif adjacent == 'prefer_right':
        if base_lane.right_lane and base_lane.right_same_direction:
            side_lane_key = base_lane.right_lane
        elif base_lane.left_lane and base_lane.left_same_direction:
            side_lane_key = base_lane.left_lane
    else:
        if base_lane.left_lane and base_lane.left_same_direction:
            side_lane_key = base_lane.left_lane
        elif base_lane.right_lane and base_lane.right_same_direction:
            side_lane_key = base_lane.right_lane
    if side_lane_key is None:
        raise RuntimeError('前方路段无相邻同向车道')

    side_lane = manager.graph.get(side_lane_key)
    if side_lane is None or side_lane.points.shape[0] < 2:
        raise RuntimeError('相邻车道几何数据缺失')
    dists = np.hypot(side_lane.points[:, 0] - pt[0], side_lane.points[:, 1] - pt[1])
    s_idx = int(np.argmin(dists))
    s_pt = side_lane.points[s_idx]
    s_prev = side_lane.points[max(0, s_idx - 1)]
    s_next = side_lane.points[min(side_lane.points.shape[0] - 1, s_idx + 1)]
    side_yaw = math.degrees(math.atan2(float(s_next[1] - s_prev[1]), float(s_next[0] - s_prev[0])))
    entry = manager.spawn_managed_vehicle(
        api,
        location=(float(s_pt[0]), float(s_pt[1]), float(s_pt[2])),
        yaw_deg=side_yaw,
        default_speed_limit_mps=default_speed_limit_mps,
        speed_factor=speed_factor,
        initial_speed_mps=initial_speed_mps,
    )
    return entry, base_lane.lane_key


def execute_traffic_action(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    action: str,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    default_speed_limit_mps: float,
    debug: bool = False,
) -> dict[str, Any]:
    """分派运行期交通场景事件；开发模式下自动补齐测试车并高亮标注。"""
    if action == 'lead_hard_brake':
        result = _lead_hard_brake(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'adjacent_cut_in':
        result = _adjacent_cut_in(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            ego_speed_mps=ego_speed_mps,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'rear_overtake':
        result = _rear_overtake(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            ego_speed_mps=ego_speed_mps,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'lead_breakdown':
        result = _lead_breakdown(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'ahead_signal_change':
        return _ahead_signal_change(
            manager,
            params=params,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            traffic_lights=traffic_lights,
        )
    elif action == 'dual_lane_slowdown':
        result = _dual_lane_slowdown(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'red_light_runner':
        result = _red_light_runner(
            manager,
            api,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            scene=scene,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
    elif action == 'set_traffic_count':
        target_count = int(params.get('target_count', 10))
        prev_count, delta = manager.adjust_target_count(
            target_count,
            ego_xy=(ego_x, ego_y),
            scene=scene,
        )
        logger.info(f'已调整周边背景车目标数量：{prev_count} -> {target_count}（增量 {delta:+d}）')
        return {
            'action': 'set_traffic_count',
            'previous_count': prev_count,
            'target_count': target_count,
            'delta': delta,
        }
    else:
        raise ValueError(f'未知交通事件动作：{action}')

    if debug:
        target_ids: list[int] = []
        if 'target_actor_id' in result:
            target_ids.append(int(result['target_actor_id']))
        if 'target_actor_ids' in result:
            target_ids.extend(int(aid) for aid in result['target_actor_ids'])
        for aid in target_ids:
            manager.queue_operation(
                {
                    'method': 'debug.highlight_actor',
                    'params': {'actor_id': aid, 'label': f'{action} #{aid}', 'duration_s': 6.0},
                }
            )
    return result


def _lead_hard_brake(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    max_dist = float(params.get('max_distance_m', 60.0))
    duration_s = float(params.get('duration_s', 2.5))
    brake = max(0.1, min(1.0, float(params.get('brake_intensity', 0.95))))

    candidates: list[tuple[float, int]] = []
    if scene is not None and scene.actor_ids.size > 1:
        local_x, local_y, cos_y, sin_y = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y
        mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x > 2.0)
            & (local_x <= max_dist)
            & (np.abs(local_y) <= 2.2)
            & (heading_dot > 0.35)
        )
        candidates = [
            (float(local_x[i]), int(scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(scene.actor_ids[i]) in manager.vehicles
        ]
    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = manager.vehicles[target_id]
    elif debug:
        dist = min(25.0, max_dist)
        entry, _ = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=dist,
            default_speed_limit_mps=default_speed_limit_mps,
        )
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 前方无托管车，已临时生成测试前车 actor_id={target_id}')
    else:
        raise RuntimeError(f'主车正前方 {max_dist:g} 米内没有托管背景车')

    entry.brake_override_until = time.monotonic() + duration_s
    entry.brake_override_value = brake
    logger.info(f'已触发前车急刹：actor_id={target_id}，距离={dist:.1f}m，持续={duration_s:g}s')
    return {'action': 'lead_hard_brake', 'target_actor_id': target_id, 'distance_m': round(dist, 2)}


def _adjacent_cut_in(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    proj = manager.graph.locate(
        ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
    )
    if proj is None:
        raise RuntimeError('主车当前不在可识别车道上，无法执行邻车切入')
    mode = str(params.get('mode', 'reuse_adjacent'))
    side = str(params.get('side', 'any'))
    min_front = float(params.get('min_front_m', 3.5))
    max_front = float(params.get('max_front_m', 28.0))
    spawn_distance_m = float(params.get('spawn_distance_m', 45.0))
    trigger_distance_m = float(params.get('trigger_distance_m', 14.0))

    if mode == 'spawn_cut_in':
        init_speed = max(ego_speed_mps * 0.85, 6.0)
        entry, target_lane = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=spawn_distance_m,
            default_speed_limit_mps=default_speed_limit_mps,
            speed_factor=0.85,
            adjacent=side,
            initial_speed_mps=init_speed,
        )
        entry.pending_merge_lane = target_lane
        entry.merge_trigger_distance_m = trigger_distance_m
        logger.info(
            f'已布置邻道加塞待切入车：actor_id={entry.actor_id}，生成距={spawn_distance_m:g}m，'
            f'初速度={init_speed:.1f}m/s，触发距={trigger_distance_m:g}m，目标车道={target_lane}'
        )
        return {
            'action': 'adjacent_cut_in',
            'mode': mode,
            'target_actor_id': entry.actor_id,
            'target_lane': target_lane,
            'distance_m': spawn_distance_m,
            'trigger_distance_m': trigger_distance_m,
        }

    candidates: list[tuple[float, int]] = []
    if scene is not None and scene.actor_ids.size > 1:
        local_x, local_y, cos_y, sin_y = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y
        if side == 'left':
            lat_mask = (local_y <= -1.8) & (local_y >= -5.5)
        elif side == 'right':
            lat_mask = (local_y >= 1.8) & (local_y <= 5.5)
        else:
            lat_mask = (np.abs(local_y) >= 1.8) & (np.abs(local_y) <= 5.5)
        mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x >= min_front)
            & (local_x <= max_front)
            & lat_mask
            & (heading_dot > 0.35)
        )
        candidates = [
            (float(local_x[i]), int(scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(scene.actor_ids[i]) in manager.vehicles
        ]
    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = manager.vehicles[target_id]
    elif debug:
        dist = min(max(min_front + 6.0, 16.0), max_front)
        entry, _ = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=dist,
            default_speed_limit_mps=default_speed_limit_mps,
            adjacent=side,
        )
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 相邻车道无托管车，已临时生成测试邻车 actor_id={target_id}')
    else:
        raise RuntimeError(f'主车相邻车道前方 {min_front:g}–{max_front:g} 米内没有托管背景车')

    entry.controller.switch_lane(proj.lane.lane_key)
    logger.info(f'已触发邻车切入：actor_id={target_id} -> 车道 {proj.lane.lane_key}，前方距离={dist:.1f}m')
    return {
        'action': 'adjacent_cut_in',
        'target_actor_id': target_id,
        'target_lane': proj.lane.lane_key,
        'distance_m': round(dist, 2),
    }


def _pick_adjacent_lane(base_lane: Any, side: str) -> str | None:
    if side == 'left':
        return base_lane.left_lane if base_lane.left_lane and base_lane.left_same_direction else None
    if side == 'right':
        return base_lane.right_lane if base_lane.right_lane and base_lane.right_same_direction else None
    if base_lane.left_lane and base_lane.left_same_direction:
        return base_lane.left_lane
    if base_lane.right_lane and base_lane.right_same_direction:
        return base_lane.right_lane
    return None


def _rear_overtake(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    proj = manager.graph.locate(
        ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
    )
    if proj is None:
        raise RuntimeError('主车当前不在可识别车道上，无法触发后车超车')

    mode = str(params.get('mode', 'reuse_rear'))
    side = str(params.get('side', 'any'))
    rear_dist_m = float(params.get('rear_distance_m', 22.0))
    extra_speed_mps = float(params.get('extra_speed_mps', 8.0))
    clear_front_m = float(params.get('clear_front_m', 18.0))
    return_to_lane = bool(params.get('return_to_lane', True))
    overtake_speed_mps = max(ego_speed_mps + extra_speed_mps, 18.0)

    pass_lane_key = _pick_adjacent_lane(proj.lane, side)
    if pass_lane_key is None:
        raise RuntimeError('当前路段没有可用于超车的相邻同向车道')
    return_side = 'right' if pass_lane_key == proj.lane.left_lane else 'left'
    pass_lane = manager.graph.get(pass_lane_key)
    if pass_lane is None or pass_lane.points.shape[0] < 2:
        raise RuntimeError('超车相邻车道几何数据缺失')

    entry: ManagedVehicle | None = None
    actual_dist = rear_dist_m
    if mode == 'reuse_rear' and scene is not None and scene.actor_ids.size > 1:
        local_x, local_y, cos_y, sin_y = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
        heading_dot = scene.headings[:, 0] * cos_y + scene.headings[:, 1] * sin_y
        mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x <= -3.0)
            & (local_x >= -max(rear_dist_m * 2.0, 50.0))
            & (np.abs(local_y) <= 5.5)
            & (heading_dot > 0.35)
        )
        candidates = [
            (abs(float(local_x[i])), int(scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(scene.actor_ids[i]) in manager.vehicles
        ]
        if candidates:
            actual_dist, target_id = min(candidates, key=lambda item: item[0])
            entry = manager.vehicles[target_id]

    if entry is None:
        if mode == 'reuse_rear' and not debug:
            raise RuntimeError(f'主车后方 {max(rear_dist_m * 2.0, 50.0):g} 米内没有可复用的托管背景车')
        ego_rad = math.radians(ego_yaw_deg)
        rear_x = ego_x - math.cos(ego_rad) * rear_dist_m
        rear_y = ego_y - math.sin(ego_rad) * rear_dist_m
        dists = np.hypot(pass_lane.points[:, 0] - rear_x, pass_lane.points[:, 1] - rear_y)
        s_idx = int(np.argmin(dists))
        s_pt = pass_lane.points[s_idx]
        s_prev = pass_lane.points[max(0, s_idx - 1)]
        s_next = pass_lane.points[min(pass_lane.points.shape[0] - 1, s_idx + 1)]
        s_yaw = math.degrees(math.atan2(float(s_next[1] - s_prev[1]), float(s_next[0] - s_prev[0])))
        entry = manager.spawn_managed_vehicle(
            api,
            location=(float(s_pt[0]), float(s_pt[1]), float(s_pt[2])),
            yaw_deg=s_yaw,
            default_speed_limit_mps=default_speed_limit_mps,
            speed_factor=1.2,
            initial_speed_mps=overtake_speed_mps,
        )
        actual_dist = rear_dist_m

    entry.controller.switch_lane(pass_lane_key, lock_s=15.0)
    entry.target_speed_mps_override = overtake_speed_mps
    entry.target_speed_mps_override_until = time.monotonic() + 25.0
    entry.overtake_target_lane = proj.lane.lane_key if return_to_lane else None
    entry.overtake_return_side = return_side if return_to_lane else None
    entry.overtake_clear_front_m = clear_front_m
    entry.overtake_extra_speed_mps = extra_speed_mps
    logger.info(
        f'已触发后车超车（无视限速）：actor_id={entry.actor_id}，超车道={pass_lane_key}，'
        f'目标速度={overtake_speed_mps:.1f}m/s，切回车道={proj.lane.lane_key}，安全前距={clear_front_m:g}m'
    )
    return {
        'action': 'rear_overtake',
        'mode': mode,
        'target_actor_id': entry.actor_id,
        'pass_lane': pass_lane_key,
        'target_lane': proj.lane.lane_key,
        'target_speed_mps': round(overtake_speed_mps, 2),
        'rear_distance_m': round(actual_dist, 2),
    }


def _lead_breakdown(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    mode = str(params.get('mode', 'reuse_lead'))
    distance_m = float(params.get('distance_m', 130.0))
    speed_factor = float(params.get('speed_factor', 0.0))

    if mode == 'reuse_lead':
        candidates: list[tuple[float, int]] = []
        if scene is not None and scene.actor_ids.size > 1:
            local_x, local_y, _, _ = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
            mask = (
                (scene.actor_ids != ego_actor_id)
                & (local_x > 5.0)
                & (local_x <= distance_m)
                & (np.abs(local_y) < 2.4)
            )
            candidates = [
                (float(local_x[i]), int(scene.actor_ids[i]))
                for i in np.flatnonzero(mask)
                if int(scene.actor_ids[i]) in manager.vehicles
            ]
        if candidates:
            dist, target_id = min(candidates, key=lambda item: item[0])
            entry = manager.vehicles[target_id]
        elif debug:
            dist = min(35.0, distance_m)
            entry, _ = _spawn_along_ego(
                manager,
                api,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                ego_road_id=ego_road_id,
                ego_lane_id=ego_lane_id,
                distance_m=dist,
                default_speed_limit_mps=default_speed_limit_mps,
            )
            target_id = entry.actor_id
            logger.info(f'[DEBUG] 前方无托管车，已临时生成故障测试车 actor_id={target_id}')
        else:
            raise RuntimeError(f'主车前方 {distance_m:g} 米内没有可复用的托管前车')
        if speed_factor <= 0.01:
            entry.permanent_stop = True
        else:
            entry.speed_factor_override = speed_factor
            entry.speed_factor_override_until = time.monotonic() + 300.0
        manager.queue_operation(
            {
                'method': 'vehicle.set_lights',
                'params': {'actor_id': target_id, 'light_state': HAZARD_LIGHT_MASK},
            }
        )
        logger.info(
            f'已触发前车故障停驶（复用前车）：actor_id={target_id}，距离={dist:.1f}m，'
            f'speed_factor={speed_factor:g}'
        )
        return {
            'action': 'lead_breakdown',
            'mode': mode,
            'target_actor_id': target_id,
            'distance_m': round(dist, 2),
            'speed_factor': speed_factor,
        }

    if mode == 'spawn_far':
        entry, _ = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=distance_m,
            default_speed_limit_mps=default_speed_limit_mps,
            speed_factor=speed_factor,
        )
        if speed_factor <= 0.01:
            entry.permanent_stop = True
            manager.queue_operation(
                {
                    'method': 'vehicle.set_lights',
                    'params': {'actor_id': entry.actor_id, 'light_state': HAZARD_LIGHT_MASK},
                }
            )
        logger.info(
            f'已触发远距离障碍车生成：actor_id={entry.actor_id}，距离={distance_m:g}m，'
            f'speed_factor={speed_factor:g}'
        )
        return {
            'action': 'lead_breakdown',
            'mode': mode,
            'target_actor_id': entry.actor_id,
            'distance_m': distance_m,
            'speed_factor': speed_factor,
        }

    raise ValueError(f'未知的故障/障碍车触发模式：{mode}')


def _ahead_signal_change(
    manager: TrafficManager,
    *,
    params: dict[str, Any],
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> dict[str, Any]:
    target_state = str(params.get('target_state', 'yellow'))
    max_distance_m = float(params.get('max_distance_m', 120.0))

    temp_planner = LocalRoutePlanner(manager.graph, horizon_m=max(140.0, max_distance_m + 20.0))
    path = temp_planner.update(
        ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
    )
    if path is None:
        raise RuntimeError('主车当前不在可识别车道上，无法匹配前方信号灯')

    matched = manager.signals.nearest_signal(path, traffic_lights, max_distance_m=max_distance_m)
    if matched is None:
        raise RuntimeError(f'主车前方 {max_distance_m:g} 米内未找到对应的交通信号灯')
    actor_id, signal_id, dist_m, prev_state = matched
    manager.queue_operation(
        {
            'method': 'traffic_light.set_state',
            'params': {'actor_id': actor_id, 'state': target_state},
        }
    )
    logger.info(
        f'已触发前方信号灯突变：actor_id={actor_id} ({signal_id}) '
        f'{prev_state.value} -> {target_state}，距离={dist_m:.1f}m'
    )
    return {
        'action': 'ahead_signal_change',
        'actor_id': actor_id,
        'signal_id': signal_id,
        'previous_state': prev_state.value,
        'target_state': target_state,
        'distance_m': round(dist_m, 2),
    }


def _dual_lane_slowdown(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    max_dist = float(params.get('max_distance_m', 100.0))
    speed_factor = float(params.get('speed_factor', 0.45))
    duration_s = float(params.get('duration_s', 10.0))

    selected: list[int] = []
    if scene is not None and scene.actor_ids.size > 1:
        local_x, local_y, _, _ = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
        same_mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x > 4.0)
            & (local_x <= max_dist)
            & (np.abs(local_y) < 2.2)
        )
        adj_mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x > 4.0)
            & (local_x <= max_dist)
            & (np.abs(local_y) >= 2.2)
            & (np.abs(local_y) <= 6.2)
        )
        for mask in (same_mask, adj_mask):
            cands = [
                (float(local_x[i]), int(scene.actor_ids[i]))
                for i in np.flatnonzero(mask)
                if int(scene.actor_ids[i]) in manager.vehicles
            ]
            if cands:
                selected.append(min(cands, key=lambda item: item[0])[1])
    if not selected and debug:
        entry, _ = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=min(30.0, max_dist),
            default_speed_limit_mps=default_speed_limit_mps,
        )
        selected.append(entry.actor_id)
        logger.info(f'[DEBUG] 前方无托管车，已临时生成压速测试车 actor_id={entry.actor_id}')
    if not selected:
        raise RuntimeError(f'主车前方 {max_dist:g} 米内同车道与相邻车道均无托管背景车')

    until = time.monotonic() + duration_s
    for aid in selected:
        entry = manager.vehicles[aid]
        entry.speed_factor_override = speed_factor
        entry.speed_factor_override_until = until
    logger.info(
        f'已触发双车道并排压速：actor_ids={selected}，speed_factor={speed_factor:g}，持续={duration_s:g}s'
    )
    return {
        'action': 'dual_lane_slowdown',
        'target_actor_ids': selected,
        'speed_factor': speed_factor,
        'duration_s': duration_s,
    }


def _red_light_runner(
    manager: TrafficManager,
    api: NativeApiClient,
    *,
    params: dict[str, Any],
    ego_actor_id: int,
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    ego_road_id: int,
    ego_lane_id: int,
    ego_speed_mps: float = 0.0,
    scene: TrafficScene | None,
    default_speed_limit_mps: float,
    debug: bool,
) -> dict[str, Any]:
    max_dist = float(params.get('max_distance_m', 120.0))
    duration_s = float(params.get('duration_s', 8.0))

    candidates: list[tuple[float, int]] = []
    if scene is not None and scene.actor_ids.size > 1:
        local_x, local_y, _, _ = world_to_local_xy(scene.xy, x=ego_x, y=ego_y, yaw_deg=ego_yaw_deg)
        mask = (
            (scene.actor_ids != ego_actor_id)
            & (local_x > 2.0)
            & (local_x <= max_dist)
            & (np.abs(local_y) <= 35.0)
        )
        candidates = [
            (float(math.hypot(float(local_x[i]), float(local_y[i]))), int(scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(scene.actor_ids[i]) in manager.vehicles
        ]
    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = manager.vehicles[target_id]
    elif debug:
        dist = min(28.0, max_dist)
        entry, _ = _spawn_along_ego(
            manager,
            api,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            distance_m=dist,
            default_speed_limit_mps=default_speed_limit_mps,
        )
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 前方无托管车，已临时生成闯红灯测试车 actor_id={target_id}')
    else:
        raise RuntimeError(f'主车前方 {max_dist:g} 米范围内没有可触发闯红灯/抢行的托管背景车')

    until = time.monotonic() + duration_s
    entry.ignore_signals_until = until
    entry.speed_factor_override = 1.15
    entry.speed_factor_override_until = until
    logger.info(f'已触发他车闯红灯/路口抢行：actor_id={target_id}，距离={dist:.1f}m，持续={duration_s:g}s')
    return {
        'action': 'red_light_runner',
        'target_actor_id': target_id,
        'distance_m': round(dist, 2),
        'duration_s': duration_s,
    }
