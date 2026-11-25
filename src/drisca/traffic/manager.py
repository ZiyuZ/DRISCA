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
    ignore_signals_until: float = 0.0
    permanent_stop: bool = False
    pending_merge_lane: str | None = None
    merge_trigger_distance_m: float = 0.0


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
            self._respawn_styles.append(removed.style_name)
            logger.info(f'背景车 #{aid} 已离开场景控制范围，已移除并加入补充队列')

    def respawn_lost(
        self,
        api: NativeApiClient,
        *,
        ego_xy: tuple[float, float] | None,
        scene: TrafficScene | None,
        default_speed_limit_mps: float,
    ) -> int:
        """在非封闭地图上有背景车离开边界销毁后，于空闲出生点补充同等风格车辆。"""
        if not self._config.auto_respawn:
            self._respawn_styles.clear()
            return 0
        if not self._respawn_styles:
            return 0
        now = time.monotonic()
        if now - self._last_respawn_at < 1.5:
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
        respawned = 0
        while self._respawn_styles:
            style_name = self._respawn_styles[0]
            chosen = None
            for pt in spawn_points:
                if ego_xy is not None and math.hypot(pt.x - ego_xy[0], pt.y - ego_xy[1]) < 30.0:
                    continue
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
        for aid in out_of_bounds:
            removed = self.vehicles.pop(aid, None)
            if removed is not None:
                self._respawn_styles.append(removed.style_name)
                operations.append({'method': 'vehicle.destroy', 'params': {'actor_id': aid}})
                logger.info(f'背景车 #{aid} 坠出地图边界或侧翻，已销毁并安排补充')
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
            scene=scene,
            traffic_lights=traffic_lights,
            default_speed_limit_mps=default_speed_limit_mps,
            debug=debug,
        )
