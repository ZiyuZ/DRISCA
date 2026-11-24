"""多车背景交通流管理器：批量生成、共享快照控制与控制权同步。"""

import math
import random
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from loguru import logger

from drisca.core.client import NativeApiClient, NativeApiError
from drisca.core.config import TrafficConfig
from drisca.core.snapshot import Snapshot

from .controller import AutopilotController, VehicleControl
from .geometry import world_to_local_xy
from .profiles import resolve_profile, sample_profile
from .road_graph import RoadGraph
from .scene import TrafficScene
from .signals import SignalTracker

# 过滤非标准四轮乘用车，保持常规道路交通流形态一致
_EXCLUDED_BLUEPRINT_TOKENS = (
    'bike',
    'bicycle',
    'omafiets',
    'crossbike',
    'century',
    'motorcycle',
    'harley',
    'kawasaki',
    'yamaha',
    'vespa',
    'firetruck',
    'ambulance',
    'carlacola',
    'fuso',
)


_HAZARD_LIGHT_MASK = 0x30  # CARLA VehicleLightState: LeftBlinker (0x20) | RightBlinker (0x10)


@dataclass(slots=True)
class _ManagedVehicle:
    actor_id: int
    controller: AutopilotController
    control_revision: int = 0
    control_mode: str = 'external'
    brake_override_until: float = 0.0
    brake_override_value: float = 0.0
    speed_factor_override_until: float = 0.0
    speed_factor_override: float | None = None
    ignore_signals_until: float = 0.0
    permanent_stop: bool = False
    pending_merge_lane: str | None = None
    merge_trigger_distance_m: float = 0.0


class TrafficManager:
    """在单次 exchange 循环中高效驱动多辆背景交通车。"""

    def __init__(self, graph: RoadGraph, signals: SignalTracker, config: TrafficConfig) -> None:
        self._graph = graph
        self._signals = signals
        self._config = config
        self._vehicles: dict[int, _ManagedVehicle] = {}
        self._queued_operations: list[dict[str, Any]] = []

    @property
    def vehicle_count(self) -> int:
        return len(self._vehicles)

    @property
    def actor_ids(self) -> tuple[int, ...]:
        return tuple(self._vehicles)

    def spawn_background(
        self,
        api: NativeApiClient,
        *,
        ego_location: tuple[float, float, float],
        default_speed_limit_mps: float,
    ) -> int:
        """按预设配置在空闲出生点批量生成背景车，返回实际生成数量。"""
        cfg = self._config
        if not cfg.enabled or cfg.vehicle_count <= 0:
            return 0

        catalog = api.catalog()
        raw_blueprints = list(catalog.vehicle_blueprints)
        blueprints = [
            bp for bp in raw_blueprints if not any(tok in bp.lower() for tok in _EXCLUDED_BLUEPRINT_TOKENS)
        ] or raw_blueprints
        spawn_points = list(catalog.spawn_points)
        if not blueprints or not spawn_points:
            logger.warning('地图无可用车型或出生点，跳过背景交通流生成')
            return 0

        rng = random.Random(cfg.seed)
        rng.shuffle(spawn_points)

        counts = cfg.style_counts
        style_queue: list[str] = (
            ['balanced'] * counts.balanced
            + ['aggressive'] * counts.aggressive
            + ['conservative'] * counts.conservative
            + ['sluggish'] * counts.sluggish
        )
        rng.shuffle(style_queue)

        occupied: list[tuple[float, float]] = [(ego_location[0], ego_location[1])]
        spawned = 0
        style_counts: dict[str, int] = {}
        for point in spawn_points:
            if spawned >= len(style_queue):
                break
            px, py, pz = point.x, point.y, point.z
            if any(math.hypot(px - ox, py - oy) < 15.0 for ox, oy in occupied):
                continue
            bp = rng.choice(blueprints)
            try:
                result = api.spawn_vehicle(
                    blueprint=bp,
                    transform={
                        'location': [px, py, pz],
                        'rotation': [point.pitch, point.yaw, point.roll],
                    },
                    role_name='autopilot',
                    mode='external',
                )
            except NativeApiError as exc:
                logger.debug(f'跳过不可用背景车出生点 ({px:.1f}, {py:.1f})：{exc}')
                continue

            actor_id = int(result['actor_id'])
            profile = sample_profile(style_queue[spawned], rng, diversity=cfg.diversity)
            style_counts[profile.name] = style_counts.get(profile.name, 0) + 1
            controller = AutopilotController(
                self._graph,
                self._signals,
                default_speed_limit_mps=default_speed_limit_mps,
                dynamic_speed_limit=True,
                speed_factor=cfg.speed_factor,
                enable_lane_change=cfg.enable_lane_change,
                profile=profile,
                car_following_model=cfg.car_following_model,
                lane_change_model=cfg.lane_change_model,
                random_seed=rng.randint(1, 2_147_483_647),
            )
            self._vehicles[actor_id] = _ManagedVehicle(actor_id=actor_id, controller=controller)
            occupied.append((px, py))
            spawned += 1

        logger.info(
            f'背景交通流已生成：目标 {cfg.vehicle_count} 辆，实际 {spawned} 辆'
            f'（seed={cfg.seed}，跟驰={cfg.car_following_model}，'
            f'换道={cfg.lane_change_model}，分布={style_counts}）'
        )
        return spawned

    def apply_control_state(
        self, control_state: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None
    ) -> None:
        for item in control_state or ():
            actor_id = int(item.get('actor_id', 0))
            entry = self._vehicles.get(actor_id)
            if entry is None:
                continue
            entry.control_revision = int(item.get('revision', 0))
            entry.control_mode = str(item.get('mode', ''))

    def step_operations(
        self,
        snapshot: Snapshot,
        scene: TrafficScene,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        dt: float,
        *,
        ego_xy: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """基于共享向量化场景批量计算全部背景车本步控制操作。"""
        operations: list[dict[str, Any]] = []
        if self._queued_operations:
            operations.extend(self._queued_operations)
            self._queued_operations.clear()

        if not self._vehicles or snapshot.vehicles.size == 0:
            return operations

        vehicles = snapshot.vehicles
        index_by_id = {int(aid): idx for idx, aid in enumerate(scene.actor_ids)}
        now = time.monotonic()

        for actor_id, entry in self._vehicles.items():
            if entry.control_mode != 'external':
                continue
            idx = index_by_id.get(actor_id)
            if idx is None:
                continue
            rec = vehicles[idx]
            vx = float(scene.xy[idx, 0])
            vy = float(scene.xy[idx, 1])

            if entry.pending_merge_lane is not None and ego_xy is not None:
                dist_to_ego = math.hypot(vx - ego_xy[0], vy - ego_xy[1])
                if dist_to_ego <= entry.merge_trigger_distance_m:
                    target_lane = entry.pending_merge_lane
                    entry.pending_merge_lane = None
                    entry.permanent_stop = False
                    entry.controller.switch_lane(target_lane)
                    operations.append(
                        {
                            'method': 'vehicle.set_lights',
                            'params': {'actor_id': actor_id, 'light_state': 0},
                        }
                    )
                    logger.info(
                        f'路侧停靠车触发起步切入：actor_id={actor_id} -> 车道 {target_lane}，'
                        f'距离={dist_to_ego:.1f}m'
                    )

            speed_override = entry.speed_factor_override if now < entry.speed_factor_override_until else None
            ignore_signals = now < entry.ignore_signals_until

            control = entry.controller.step(
                x=vx,
                y=vy,
                yaw_deg=float(rec['rotation'][1]),
                speed_mps=float(scene.speeds[idx]),
                dt=dt,
                road_id=int(scene.road_ids[idx]),
                lane_id=int(scene.lane_ids[idx]),
                road_speed_limit_mps=float(rec['speed_limit_mps']),
                traffic_lights=traffic_lights,
                scene=scene,
                self_actor_id=actor_id,
                ignore_signals=ignore_signals,
                speed_factor_override=speed_override,
            )
            if entry.permanent_stop:
                control = VehicleControl(throttle=0.0, steer=0.0, brake=0.85, hand_brake=True)
            elif now < entry.brake_override_until:
                control = VehicleControl(
                    throttle=0.0,
                    steer=control.steer,
                    brake=entry.brake_override_value,
                )
            operations.append(control.to_operation(actor_id, entry.control_revision))
        return operations

    def trigger_action(
        self,
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
        scene: TrafficScene | None,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
        default_speed_limit_mps: float,
    ) -> dict[str, Any]:
        """执行运行期交通场景事件并返回结构化结果载荷。"""
        if action == 'lead_hard_brake':
            return self._trigger_lead_hard_brake(
                params=params,
                ego_actor_id=ego_actor_id,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                scene=scene,
            )
        if action == 'adjacent_cut_in':
            return self._trigger_adjacent_cut_in(
                params=params,
                ego_actor_id=ego_actor_id,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                ego_road_id=ego_road_id,
                ego_lane_id=ego_lane_id,
                scene=scene,
            )
        if action == 'lead_breakdown':
            return self._trigger_lead_breakdown(
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
            )
        if action == 'ahead_signal_change':
            return self._trigger_ahead_signal_change(
                params=params,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                ego_road_id=ego_road_id,
                ego_lane_id=ego_lane_id,
                traffic_lights=traffic_lights,
            )
        if action == 'dual_lane_slowdown':
            return self._trigger_dual_lane_slowdown(
                params=params,
                ego_actor_id=ego_actor_id,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                scene=scene,
            )
        if action == 'red_light_runner':
            return self._trigger_red_light_runner(
                params=params,
                ego_actor_id=ego_actor_id,
                ego_x=ego_x,
                ego_y=ego_y,
                ego_yaw_deg=ego_yaw_deg,
                scene=scene,
            )
        raise ValueError(f'未知交通事件动作：{action}')

    def _trigger_lead_hard_brake(
        self,
        *,
        params: dict[str, Any],
        ego_actor_id: int,
        ego_x: float,
        ego_y: float,
        ego_yaw_deg: float,
        scene: TrafficScene | None,
    ) -> dict[str, Any]:
        if scene is None or scene.actor_ids.size <= 1:
            raise RuntimeError('当前场景没有可触发急刹的背景前车')
        max_dist = float(params.get('max_distance_m', 60.0))
        duration_s = float(params.get('duration_s', 2.5))
        brake = max(0.1, min(1.0, float(params.get('brake_intensity', 0.95))))

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
            if int(scene.actor_ids[i]) in self._vehicles
        ]
        if not candidates:
            raise RuntimeError(f'主车正前方 {max_dist:g} 米内没有托管背景车')
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = self._vehicles[target_id]
        entry.brake_override_until = time.monotonic() + duration_s
        entry.brake_override_value = brake
        logger.info(f'已触发前车急刹：actor_id={target_id}，距离={dist:.1f}m，持续={duration_s:g}s')
        return {'action': 'lead_hard_brake', 'target_actor_id': target_id, 'distance_m': round(dist, 2)}

    def _trigger_adjacent_cut_in(
        self,
        *,
        params: dict[str, Any],
        ego_actor_id: int,
        ego_x: float,
        ego_y: float,
        ego_yaw_deg: float,
        ego_road_id: int,
        ego_lane_id: int,
        scene: TrafficScene | None,
    ) -> dict[str, Any]:
        if scene is None or scene.actor_ids.size <= 1:
            raise RuntimeError('当前场景没有可触发切入的相邻背景车')
        proj = self._graph.locate(
            ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
        )
        if proj is None:
            raise RuntimeError('主车当前不在可识别车道上，无法执行邻车切入')
        side = str(params.get('side', 'any'))
        min_front = float(params.get('min_front_m', 6.0))
        max_front = float(params.get('max_front_m', 35.0))

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
            if int(scene.actor_ids[i]) in self._vehicles
        ]
        if not candidates:
            raise RuntimeError(f'主车相邻车道前方 {min_front:g}–{max_front:g} 米内没有托管背景车')
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = self._vehicles[target_id]
        entry.controller.switch_lane(proj.lane.lane_key)
        logger.info(
            f'已触发邻车切入：actor_id={target_id} -> 车道 {proj.lane.lane_key}，前方距离={dist:.1f}m'
        )
        return {
            'action': 'adjacent_cut_in',
            'target_actor_id': target_id,
            'target_lane': proj.lane.lane_key,
            'distance_m': round(dist, 2),
        }

    def _spawn_managed_vehicle(
        self,
        api: NativeApiClient,
        *,
        location: tuple[float, float, float],
        yaw_deg: float,
        default_speed_limit_mps: float,
        speed_factor: float,
        enable_lane_change: bool = False,
    ) -> _ManagedVehicle:
        catalog = api.catalog()
        raw_blueprints = list(catalog.vehicle_blueprints)
        blueprints = [
            bp for bp in raw_blueprints if not any(tok in bp.lower() for tok in _EXCLUDED_BLUEPRINT_TOKENS)
        ] or raw_blueprints
        if not blueprints:
            raise RuntimeError('地图无可用车型蓝图')
        result = api.spawn_vehicle(
            blueprint=blueprints[0],
            transform={
                'location': [location[0], location[1], location[2] + 0.5],
                'rotation': [0.0, yaw_deg, 0.0],
            },
            role_name='autopilot',
            mode='external',
        )
        actor_id = int(result['actor_id'])
        profile = resolve_profile('balanced')
        controller = AutopilotController(
            self._graph,
            self._signals,
            default_speed_limit_mps=default_speed_limit_mps,
            dynamic_speed_limit=True,
            speed_factor=max(0.0, speed_factor),
            enable_lane_change=enable_lane_change,
            profile=profile,
            car_following_model=self._config.car_following_model,
            lane_change_model=self._config.lane_change_model,
        )
        entry = _ManagedVehicle(actor_id=actor_id, controller=controller)
        self._vehicles[actor_id] = entry
        return entry

    def _trigger_lead_breakdown(
        self,
        api: NativeApiClient,
        *,
        params: dict[str, Any],
        ego_actor_id: int,
        ego_x: float,
        ego_y: float,
        ego_yaw_deg: float,
        ego_road_id: int,
        ego_lane_id: int,
        scene: TrafficScene | None,
        default_speed_limit_mps: float,
    ) -> dict[str, Any]:
        mode = str(params.get('mode', 'reuse_lead'))
        distance_m = float(params.get('distance_m', 130.0))
        speed_factor = float(params.get('speed_factor', 0.0))
        trigger_distance_m = float(params.get('trigger_distance_m', 35.0))

        if mode == 'reuse_lead':
            if scene is None or scene.actor_ids.size <= 1:
                raise RuntimeError('当前场景无可用背景车辆')
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
                if int(scene.actor_ids[i]) in self._vehicles
            ]
            if not candidates:
                raise RuntimeError(f'主车前方 {distance_m:g} 米内没有可复用的托管前车')
            dist, target_id = min(candidates, key=lambda item: item[0])
            entry = self._vehicles[target_id]
            if speed_factor <= 0.01:
                entry.permanent_stop = True
            else:
                entry.speed_factor_override = speed_factor
                entry.speed_factor_override_until = time.monotonic() + 300.0
            self._queued_operations.append(
                {
                    'method': 'vehicle.set_lights',
                    'params': {'actor_id': target_id, 'light_state': _HAZARD_LIGHT_MASK},
                }
            )
            logger.info(
                f'已触发前车故障停驶（复用前车）：actor_id={target_id}，距离={dist:.1f}m，speed_factor={speed_factor:g}'
            )
            return {
                'action': 'lead_breakdown',
                'mode': mode,
                'target_actor_id': target_id,
                'distance_m': round(dist, 2),
                'speed_factor': speed_factor,
            }

        proj = self._graph.locate(
            ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
        )
        if proj is None:
            raise RuntimeError('主车当前不在可识别车道上，无法沿车道定位前方位置')

        from .planner import LocalRoutePlanner

        temp_planner = LocalRoutePlanner(self._graph, horizon_m=max(160.0, distance_m + 30.0))
        path = temp_planner.update(
            ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
        )
        if path is None or path.points.shape[0] < 2:
            raise RuntimeError('前方参考路径不足，无法生成障碍车')

        idx = min(max(1, int(np.searchsorted(path.s_values, distance_m))), path.points.shape[0] - 1)
        pt = path.points[idx]
        prev = path.points[idx - 1]
        yaw_deg = math.degrees(math.atan2(float(pt[1] - prev[1]), float(pt[0] - prev[0])))

        if mode == 'spawn_far':
            entry = self._spawn_managed_vehicle(
                api,
                location=(float(pt[0]), float(pt[1]), float(pt[2])),
                yaw_deg=yaw_deg,
                default_speed_limit_mps=default_speed_limit_mps,
                speed_factor=speed_factor,
            )
            if speed_factor <= 0.01:
                entry.permanent_stop = True
                self._queued_operations.append(
                    {
                        'method': 'vehicle.set_lights',
                        'params': {'actor_id': entry.actor_id, 'light_state': _HAZARD_LIGHT_MASK},
                    }
                )
            logger.info(
                f'已触发远距离障碍车生成：actor_id={entry.actor_id}，距离={distance_m:g}m，speed_factor={speed_factor:g}'
            )
            return {
                'action': 'lead_breakdown',
                'mode': mode,
                'target_actor_id': entry.actor_id,
                'distance_m': distance_m,
                'speed_factor': speed_factor,
            }

        if mode == 'roadside_merge':
            # 优先选择目标位置对应的右侧相邻同向车道，无右侧时退选左侧
            target_proj = self._graph.locate(float(pt[0]), float(pt[1]), yaw_deg)
            base_lane = target_proj.lane if target_proj is not None else proj.lane
            side_lane_key = (
                base_lane.right_lane
                if base_lane.right_lane and base_lane.right_same_direction
                else (base_lane.left_lane if base_lane.left_lane and base_lane.left_same_direction else None)
            )
            if side_lane_key is None:
                raise RuntimeError('前方路段无相邻同向车道可用于路侧停靠切入')
            side_lane = self._graph.get(side_lane_key)
            if side_lane is None or side_lane.points.shape[0] < 2:
                raise RuntimeError('相邻车道几何数据缺失')
            # 在相邻车道上找距离目标点最近的中心线点
            dists = np.hypot(side_lane.points[:, 0] - pt[0], side_lane.points[:, 1] - pt[1])
            s_idx = int(np.argmin(dists))
            s_pt = side_lane.points[s_idx]
            s_prev = side_lane.points[max(0, s_idx - 1)]
            s_next = side_lane.points[min(side_lane.points.shape[0] - 1, s_idx + 1)]
            side_yaw = math.degrees(math.atan2(float(s_next[1] - s_prev[1]), float(s_next[0] - s_prev[0])))
            entry = self._spawn_managed_vehicle(
                api,
                location=(float(s_pt[0]), float(s_pt[1]), float(s_pt[2])),
                yaw_deg=side_yaw,
                default_speed_limit_mps=default_speed_limit_mps,
                speed_factor=max(0.5, speed_factor if speed_factor > 0.01 else 0.7),
            )
            entry.permanent_stop = True
            entry.pending_merge_lane = base_lane.lane_key
            entry.merge_trigger_distance_m = trigger_distance_m
            self._queued_operations.append(
                {
                    'method': 'vehicle.set_lights',
                    'params': {'actor_id': entry.actor_id, 'light_state': _HAZARD_LIGHT_MASK},
                }
            )
            logger.info(
                f'已布置路侧停靠待切入车：actor_id={entry.actor_id}，距离={distance_m:g}m，'
                f'触发距={trigger_distance_m:g}m，目标车道={base_lane.lane_key}'
            )
            return {
                'action': 'lead_breakdown',
                'mode': mode,
                'target_actor_id': entry.actor_id,
                'distance_m': distance_m,
                'trigger_distance_m': trigger_distance_m,
                'target_lane': base_lane.lane_key,
            }

        raise ValueError(f'未知的故障/障碍车触发模式：{mode}')

    def _trigger_ahead_signal_change(
        self,
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

        from .planner import LocalRoutePlanner

        temp_planner = LocalRoutePlanner(self._graph, horizon_m=max(140.0, max_distance_m + 20.0))
        path = temp_planner.update(
            ego_x, ego_y, ego_yaw_deg, road_id=ego_road_id or None, lane_id=ego_lane_id or None
        )
        if path is None:
            raise RuntimeError('主车当前不在可识别车道上，无法匹配前方信号灯')

        matched = self._signals.nearest_signal(path, traffic_lights, max_distance_m=max_distance_m)
        if matched is None:
            raise RuntimeError(f'主车前方 {max_distance_m:g} 米内未找到对应的交通信号灯')
        actor_id, signal_id, dist_m, prev_state = matched
        self._queued_operations.append(
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

    def _trigger_dual_lane_slowdown(
        self,
        *,
        params: dict[str, Any],
        ego_actor_id: int,
        ego_x: float,
        ego_y: float,
        ego_yaw_deg: float,
        scene: TrafficScene | None,
    ) -> dict[str, Any]:
        if scene is None or scene.actor_ids.size <= 1:
            raise RuntimeError('当前场景无可用背景车辆')
        max_dist = float(params.get('max_distance_m', 100.0))
        speed_factor = float(params.get('speed_factor', 0.45))
        duration_s = float(params.get('duration_s', 10.0))

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

        selected: list[int] = []
        for mask in (same_mask, adj_mask):
            cands = [
                (float(local_x[i]), int(scene.actor_ids[i]))
                for i in np.flatnonzero(mask)
                if int(scene.actor_ids[i]) in self._vehicles
            ]
            if cands:
                selected.append(min(cands, key=lambda item: item[0])[1])
        if not selected:
            raise RuntimeError(f'主车前方 {max_dist:g} 米内同车道与相邻车道均无托管背景车')

        until = time.monotonic() + duration_s
        for aid in selected:
            entry = self._vehicles[aid]
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

    def _trigger_red_light_runner(
        self,
        *,
        params: dict[str, Any],
        ego_actor_id: int,
        ego_x: float,
        ego_y: float,
        ego_yaw_deg: float,
        scene: TrafficScene | None,
    ) -> dict[str, Any]:
        if scene is None or scene.actor_ids.size <= 1:
            raise RuntimeError('当前场景无可用背景车辆')
        max_dist = float(params.get('max_distance_m', 120.0))
        duration_s = float(params.get('duration_s', 8.0))

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
            if int(scene.actor_ids[i]) in self._vehicles
        ]
        if not candidates:
            raise RuntimeError(f'主车前方 {max_dist:g} 米范围内没有可触发闯红灯/抢行的托管背景车')
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = self._vehicles[target_id]
        until = time.monotonic() + duration_s
        entry.ignore_signals_until = until
        entry.speed_factor_override = 1.15
        entry.speed_factor_override_until = until
        logger.info(
            f'已触发他车闯红灯/路口抢行：actor_id={target_id}，距离={dist:.1f}m，持续={duration_s:g}s'
        )
        return {
            'action': 'red_light_runner',
            'target_actor_id': target_id,
            'distance_m': round(dist, 2),
            'duration_s': duration_s,
        }
