"""多车背景交通流管理器：批量生成、共享快照控制与控制权同步。"""

import math
import random
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from drisca.core.client import NativeApiClient, NativeApiError
from drisca.core.config import TrafficConfig
from drisca.core.snapshot import Snapshot

from .controller import AutopilotController, VehicleControl
from .profiles import resolve_profile, sample_profile
from .road_graph import RoadGraph
from .scenarios import execute_traffic_action
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


@dataclass(slots=True)
class ManagedVehicle:
    actor_id: int
    controller: AutopilotController
    style_name: str = 'balanced'
    control_revision: int = 0
    control_mode: str = 'external'
    confirmed_in_session: bool = False
    brake_override_until: float = 0.0
    brake_override_value: float = 0.0
    speed_factor_override_until: float = 0.0
    speed_factor_override: float | None = None
    target_speed_mps_override_until: float = 0.0
    target_speed_mps_override: float | None = None
    ignore_signals_until: float = 0.0
    permanent_stop: bool = False
    pending_merge_lane: str | None = None
    merge_trigger_distance_m: float = 0.0
    overtake_target_lane: str | None = None
    overtake_return_side: str | None = None
    overtake_clear_front_m: float = 10.0
    overtake_extra_speed_mps: float = 0.0


class TrafficManager:
    """在单次 exchange 循环中高效驱动多辆背景交通车。"""

    def __init__(self, graph: RoadGraph, signals: SignalTracker, config: TrafficConfig) -> None:
        self.graph = graph
        self.signals = signals
        self._config = config
        self.vehicles: dict[int, ManagedVehicle] = {}
        self._queued_operations: list[dict[str, Any]] = []
        self._respawn_styles: list[str] = []
        self._last_respawn_at = 0.0
        self._respawn_rng = random.Random(config.seed + 7919)

    @property
    def vehicle_count(self) -> int:
        return len(self.vehicles)

    @property
    def actor_ids(self) -> tuple[int, ...]:
        return tuple(self.vehicles)

    def queue_operation(self, operation: dict[str, Any]) -> None:
        self._queued_operations.append(operation)

    def spawn_managed_vehicle(
        self,
        api: NativeApiClient,
        *,
        location: tuple[float, float, float],
        yaw_deg: float,
        default_speed_limit_mps: float,
        speed_factor: float,
        enable_lane_change: bool = False,
        initial_speed_mps: float = 0.0,
    ) -> ManagedVehicle:
        """动态生成单辆由 TrafficManager 托管的背景车。"""
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
            initial_speed_mps=initial_speed_mps,
        )
        actor_id = int(result['actor_id'])
        controller = AutopilotController(
            self.graph,
            self.signals,
            default_speed_limit_mps=default_speed_limit_mps,
            dynamic_speed_limit=True,
            speed_factor=max(0.0, speed_factor),
            enable_lane_change=enable_lane_change,
            profile=resolve_profile('balanced'),
            car_following_model=self._config.car_following_model,
            lane_change_model=self._config.lane_change_model,
        )
        entry = ManagedVehicle(actor_id=actor_id, controller=controller)
        self.vehicles[actor_id] = entry
        return entry

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
        radius = cfg.active_radius_m
        # 大地图优先在主车周边 [25 m, active_radius_m] 内生成，避免在数公里外未加载区块生成导致超时
        near_points = [
            pt
            for pt in spawn_points
            if 25.0 <= math.hypot(pt.x - ego_location[0], pt.y - ego_location[1]) <= radius
        ]
        mid_points = [
            pt
            for pt in spawn_points
            if radius < math.hypot(pt.x - ego_location[0], pt.y - ego_location[1]) <= radius * 1.5
        ]
        rng.shuffle(near_points)
        rng.shuffle(mid_points)
        ordered_points = near_points + mid_points
        if not ordered_points:
            ordered_points = sorted(
                spawn_points,
                key=lambda pt: math.hypot(pt.x - ego_location[0], pt.y - ego_location[1]),
            )

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
        for point in ordered_points:
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
                        'location': [px, py, pz + 0.5],
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
                self.graph,
                self.signals,
                default_speed_limit_mps=default_speed_limit_mps,
                dynamic_speed_limit=True,
                speed_factor=cfg.speed_factor,
                enable_lane_change=cfg.enable_lane_change,
                profile=profile,
                car_following_model=cfg.car_following_model,
                lane_change_model=cfg.lane_change_model,
                random_seed=rng.randint(1, 2_147_483_647),
            )
            self.vehicles[actor_id] = ManagedVehicle(
                actor_id=actor_id,
                controller=controller,
                style_name=profile.name,
            )
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
        if not control_state:
            return
        active_ids: set[int] = set()
        for item in control_state:
            actor_id = int(item.get('actor_id', 0))
            active_ids.add(actor_id)
            entry = self.vehicles.get(actor_id)
            if entry is None:
                continue
            entry.control_revision = int(item.get('revision', 0))
            entry.control_mode = str(item.get('mode', ''))
            entry.confirmed_in_session = True
        # 清理已被 UE 销毁或移出会话控制表的背景车（如开出非封闭地图边界掉入 KillZ）
        gone_ids = [
            aid
            for aid, entry in self.vehicles.items()
            if entry.confirmed_in_session and aid not in active_ids
        ]
        for aid in gone_ids:
            removed = self.vehicles.pop(aid)
            if self._config.auto_respawn:
                self._respawn_styles.append(removed.style_name)
            logger.info(f'背景车 #{aid} 已离开场景控制范围，已移除')

    def adjust_target_count(
        self,
        target_count: int,
        *,
        ego_xy: tuple[float, float] | None,
        scene: TrafficScene | None,
    ) -> tuple[int, int]:
        """运行期动态调整目标背景车数量：超额销毁最远车辆，不足则加入远处补车队列。"""
        current = len(self.vehicles)
        delta = target_count - current
        if delta > 0:
            styles = ('balanced', 'aggressive', 'conservative', 'sluggish')
            for _ in range(delta):
                self._respawn_styles.append(self._respawn_rng.choice(styles))
            return current, delta

        if delta < 0:
            self._respawn_styles.clear()
            to_remove = -delta
            pos_by_id: dict[int, tuple[float, float]] = {}
            if scene is not None:
                for idx, aid in enumerate(scene.actor_ids):
                    pos_by_id[int(aid)] = (float(scene.xy[idx, 0]), float(scene.xy[idx, 1]))

            def _dist_key(aid: int) -> float:
                if ego_xy is None or aid not in pos_by_id:
                    return 0.0
                px, py = pos_by_id[aid]
                return math.hypot(px - ego_xy[0], py - ego_xy[1])

            furthest = sorted(self.vehicles.keys(), key=_dist_key, reverse=True)[:to_remove]
            destroy_ids: list[int] = []
            for aid in furthest:
                if self.vehicles.pop(aid, None) is not None:
                    destroy_ids.append(aid)
            if destroy_ids:
                self._queued_operations.append(
                    {'method': 'vehicle.destroy', 'params': {'actor_ids': destroy_ids}}
                )
            return current, -len(destroy_ids)

        return current, 0

    def respawn_lost(
        self,
        api: NativeApiClient,
        *,
        ego_xy: tuple[float, float] | None,
        scene: TrafficScene | None,
        default_speed_limit_mps: float,
    ) -> int:
        """在主车周边外环空闲出生点补充背景车，维持目标交通规模。"""
        if not self._respawn_styles:
            return 0
        now = time.monotonic()
        if now - self._last_respawn_at < 1.0:
            return 0
        self._last_respawn_at = now
        catalog = api.catalog()
        raw_blueprints = list(catalog.vehicle_blueprints)
        blueprints = [
            bp for bp in raw_blueprints if not any(tok in bp.lower() for tok in _EXCLUDED_BLUEPRINT_TOKENS)
        ] or raw_blueprints
        spawn_points = list(catalog.spawn_points)
        if not blueprints or not spawn_points:
            return 0
        self._respawn_rng.shuffle(spawn_points)
        occupied: list[tuple[float, float]] = []
        if ego_xy is not None:
            occupied.append(ego_xy)
        if scene is not None and scene.xy.size > 0:
            occupied.extend((float(xy[0]), float(xy[1])) for xy in scene.xy)

        cfg = self._config
        radius = cfg.active_radius_m
        inner_min = min(max(45.0, radius * 0.35), 140.0)
        if ego_xy is not None:
            ring_points = [
                pt
                for pt in spawn_points
                if inner_min <= math.hypot(pt.x - ego_xy[0], pt.y - ego_xy[1]) <= radius
            ]
            fallback_points = [
                pt
                for pt in spawn_points
                if 30.0 <= math.hypot(pt.x - ego_xy[0], pt.y - ego_xy[1]) < inner_min
            ]
            candidate_points = ring_points + fallback_points
        else:
            candidate_points = spawn_points

        respawned = 0
        while self._respawn_styles:
            style_name = self._respawn_styles[0]
            chosen = None
            for pt in candidate_points:
                if any(math.hypot(pt.x - ox, pt.y - oy) < 15.0 for ox, oy in occupied):
                    continue
                chosen = pt
                break
            if chosen is None:
                break
            try:
                result = api.spawn_vehicle(
                    blueprint=self._respawn_rng.choice(blueprints),
                    transform={
                        'location': [chosen.x, chosen.y, chosen.z + 0.5],
                        'rotation': [chosen.pitch, chosen.yaw, chosen.roll],
                    },
                    role_name='autopilot',
                    mode='external',
                )
            except NativeApiError:
                break
            actor_id = int(result['actor_id'])
            profile = sample_profile(style_name, self._respawn_rng, diversity=cfg.diversity)
            controller = AutopilotController(
                self.graph,
                self.signals,
                default_speed_limit_mps=default_speed_limit_mps,
                dynamic_speed_limit=True,
                speed_factor=cfg.speed_factor,
                enable_lane_change=cfg.enable_lane_change,
                profile=profile,
                car_following_model=cfg.car_following_model,
                lane_change_model=cfg.lane_change_model,
                random_seed=self._respawn_rng.randint(1, 2_147_483_647),
            )
            self.vehicles[actor_id] = ManagedVehicle(
                actor_id=actor_id,
                controller=controller,
                style_name=style_name,
            )
            self._respawn_styles.pop(0)
            occupied.append((chosen.x, chosen.y))
            respawned += 1
            logger.info(f'已重新生成补充背景车 #{actor_id}（风格={style_name}）')
        return respawned

    def step_operations(
        self,
        snapshot: Snapshot,
        scene: TrafficScene,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        dt: float,
        *,
        ego_xy: tuple[float, float] | None = None,
        selected_actor_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """基于共享向量化场景批量计算全部背景车本步控制操作。"""
        operations: list[dict[str, Any]] = []
        if self._queued_operations:
            operations.extend(self._queued_operations)
            self._queued_operations.clear()

        if not self.vehicles or snapshot.vehicles.size == 0:
            return operations

        vehicles = snapshot.vehicles
        index_by_id = {int(aid): idx for idx, aid in enumerate(scene.actor_ids)}
        now = time.monotonic()
        ego_speed_live = 0.0
        if ego_xy is not None:
            for idx_all, aid_all in enumerate(scene.actor_ids):
                if int(aid_all) not in self.vehicles:
                    dx_e = float(scene.xy[idx_all, 0]) - ego_xy[0]
                    dy_e = float(scene.xy[idx_all, 1]) - ego_xy[1]
                    if dx_e * dx_e + dy_e * dy_e < 4.0:
                        ego_speed_live = float(scene.speeds[idx_all])
                        break

        out_of_bounds: list[int] = []
        for actor_id, entry in self.vehicles.items():
            if entry.control_mode != 'external':
                continue
            idx = index_by_id.get(actor_id)
            if idx is None:
                continue
            rec = vehicles[idx]
            vz = float(rec['location'][2])
            pitch_abs = abs(float(rec['rotation'][0]))
            roll_abs = abs(float(rec['rotation'][2]))
            if vz < -20.0 or pitch_abs > 75.0 or roll_abs > 75.0:
                out_of_bounds.append(actor_id)
                continue
            vx = float(scene.xy[idx, 0])
            vy = float(scene.xy[idx, 1])
            if ego_xy is not None:
                despawn_radius = self._config.active_radius_m * 1.25
                if math.hypot(vx - ego_xy[0], vy - ego_xy[1]) > despawn_radius:
                    out_of_bounds.append(actor_id)
                    continue

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

            if (
                entry.overtake_target_lane is not None or entry.overtake_return_side is not None
            ) and ego_xy is not None:
                # 动态跟踪主车实时车速，保证主车提速时超车车仍能持续拉快超越
                if entry.overtake_extra_speed_mps > 0.0:
                    entry.target_speed_mps_override = max(
                        ego_speed_live + entry.overtake_extra_speed_mps,
                        entry.target_speed_mps_override or 20.0,
                    )
                    entry.target_speed_mps_override_until = max(
                        entry.target_speed_mps_override_until, now + 3.0
                    )
                v_rad = math.radians(float(rec['rotation'][1]))
                ahead_of_ego = (vx - ego_xy[0]) * math.cos(v_rad) + (vy - ego_xy[1]) * math.sin(v_rad)
                if ahead_of_ego >= entry.overtake_clear_front_m:
                    # 优先基于超车车当前所在路段动态解析切回的相邻同向车道，避免跨路段后旧 lane_key 失效
                    resolved_target = entry.overtake_target_lane
                    cur_lane = entry.controller._planner.current_lane()
                    if cur_lane is not None and entry.overtake_return_side is not None:
                        if (
                            entry.overtake_return_side == 'left'
                            and cur_lane.left_lane
                            and cur_lane.left_same_direction
                        ):
                            resolved_target = cur_lane.left_lane
                        elif (
                            entry.overtake_return_side == 'right'
                            and cur_lane.right_lane
                            and cur_lane.right_same_direction
                        ):
                            resolved_target = cur_lane.right_lane
                    entry.overtake_target_lane = None
                    entry.overtake_return_side = None
                    entry.overtake_extra_speed_mps = 0.0
                    if resolved_target is not None:
                        entry.controller.switch_lane(resolved_target)
                        logger.info(
                            f'超车车辆拉出前距，触发切回：actor_id={actor_id} -> 车道 {resolved_target}，'
                            f'前距={ahead_of_ego:.1f}m'
                        )

            speed_override = entry.speed_factor_override if now < entry.speed_factor_override_until else None
            target_speed_override = (
                entry.target_speed_mps_override if now < entry.target_speed_mps_override_until else None
            )
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
                target_speed_mps_override=target_speed_override,
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
        destroy_ids: list[int] = []
        for aid in out_of_bounds:
            removed = self.vehicles.pop(aid, None)
            if removed is not None:
                if self._config.auto_respawn:
                    self._respawn_styles.append(removed.style_name)
                destroy_ids.append(aid)
                logger.info(f'背景车 #{aid} 超出活动半径或异常姿态，已销毁')
        if destroy_ids:
            operations.append({'method': 'vehicle.destroy', 'params': {'actor_ids': destroy_ids}})
        if selected_actor_id is not None and selected_actor_id in self.vehicles:
            pts = self.vehicles[selected_actor_id].controller.planned_points()
            if pts:
                operations.append(
                    {
                        'method': 'debug.highlight_path',
                        'params': {'actor_id': selected_actor_id, 'points': pts, 'duration_s': 0.35},
                    }
                )
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
        ego_speed_mps: float = 0.0,
        scene: TrafficScene | None,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
        default_speed_limit_mps: float,
        debug: bool = False,
    ) -> dict[str, Any]:
        """执行运行期交通场景事件并返回结构化结果载荷。"""
        return execute_traffic_action(
            self,
            api,
            action=action,
            params=params,
            ego_actor_id=ego_actor_id,
            ego_x=ego_x,
            ego_y=ego_y,
            ego_yaw_deg=ego_yaw_deg,
            ego_road_id=ego_road_id,
            ego_lane_id=ego_lane_id,
            ego_speed_mps=ego_speed_mps,
            scene=scene,
            traffic_lights=traffic_lights,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
