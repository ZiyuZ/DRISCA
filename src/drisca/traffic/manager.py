"""多车背景交通流管理器：批量生成、共享快照控制与控制权同步。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from loguru import logger

from drisca.core.client import NativeApiClient, NativeApiError
from drisca.core.config import TrafficConfig
from drisca.core.snapshot import Snapshot

from .controller import AutopilotController
from .profiles import resolve_profile
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


@dataclass(slots=True)
class _ManagedVehicle:
    actor_id: int
    controller: AutopilotController
    control_revision: int = 0
    control_mode: str = 'external'


class TrafficManager:
    """在单次 exchange 循环中高效驱动多辆背景交通车。"""

    def __init__(self, graph: RoadGraph, signals: SignalTracker, config: TrafficConfig) -> None:
        self._graph = graph
        self._signals = signals
        self._config = config
        self._vehicles: dict[int, _ManagedVehicle] = {}

    @property
    def vehicle_count(self) -> int:
        return len(self._vehicles)

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
        raw_blueprints = [
            str(item['id']) if isinstance(item, dict) else str(item)
            for item in (catalog.get('vehicle_blueprints') or ())
        ]
        blueprints = [
            bp for bp in raw_blueprints if not any(tok in bp.lower() for tok in _EXCLUDED_BLUEPRINT_TOKENS)
        ] or raw_blueprints
        spawn_points = list(catalog.get('spawn_points') or ())
        if not blueprints or not spawn_points:
            logger.warning('地图无可用车型或出生点，跳过背景交通流生成')
            return 0

        rng = random.Random(cfg.seed)
        rng.shuffle(spawn_points)

        occupied: list[tuple[float, float]] = [(ego_location[0], ego_location[1])]
        spawned = 0
        style_counts: dict[str, int] = {}
        for point in spawn_points:
            if spawned >= cfg.vehicle_count:
                break
            loc = point['location']
            rot = point['rotation']
            px, py, pz = float(loc[0]), float(loc[1]), float(loc[2])
            if any(math.hypot(px - ox, py - oy) < 15.0 for ox, oy in occupied):
                continue
            bp = rng.choice(blueprints)
            try:
                result = api.spawn_vehicle(
                    blueprint=bp,
                    transform={
                        'location': [px, py, pz],
                        'rotation': [float(rot[0]), float(rot[1]), float(rot[2])],
                    },
                    role_name='autopilot',
                    mode='external',
                )
            except NativeApiError as exc:
                logger.debug(f'跳过不可用背景车出生点 ({px:.1f}, {py:.1f})：{exc}')
                continue

            actor_id = int(result['actor_id'])
            profile = resolve_profile(cfg.style, rng)
            style_counts[profile.name] = style_counts.get(profile.name, 0) + 1
            # 每辆背景车分配独立派生速度微调与选路种子，避免车流完全同质化
            jitter = rng.uniform(0.92, 1.05)
            controller = AutopilotController(
                self._graph,
                self._signals,
                default_speed_limit_mps=default_speed_limit_mps,
                dynamic_speed_limit=True,
                speed_factor=cfg.speed_factor * jitter,
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
            f'（seed={cfg.seed}，风格={cfg.style}，跟驰={cfg.car_following_model}，'
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
    ) -> list[dict[str, Any]]:
        """基于共享向量化场景批量计算全部背景车本步控制操作。"""
        if not self._vehicles or snapshot.vehicles.size == 0:
            return []

        operations: list[dict[str, Any]] = []
        vehicles = snapshot.vehicles
        index_by_id = {int(aid): idx for idx, aid in enumerate(scene.actor_ids)}

        for actor_id, entry in self._vehicles.items():
            if entry.control_mode != 'external':
                continue
            idx = index_by_id.get(actor_id)
            if idx is None:
                continue
            rec = vehicles[idx]
            control = entry.controller.step(
                x=float(scene.xy[idx, 0]),
                y=float(scene.xy[idx, 1]),
                yaw_deg=float(rec['rotation'][1]),
                speed_mps=float(scene.speeds[idx]),
                dt=dt,
                road_id=int(scene.road_ids[idx]),
                lane_id=int(scene.lane_ids[idx]),
                road_speed_limit_mps=float(rec['speed_limit_mps']),
                traffic_lights=traffic_lights,
                scene=scene,
                self_actor_id=actor_id,
            )
            operations.append(control.to_operation(actor_id, entry.control_revision))
        return operations
