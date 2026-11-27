"""车辆交互类交通场景事件：前车急刹、邻车加塞、后车超车、前车故障、双车道缓行。"""

import math
import time
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

from drisca.core.traffic_models import (
    AdjacentCutInParams,
    BreakdownMode,
    CutInMode,
    DualLaneSlowdownParams,
    LaneSide,
    LeadBreakdownParams,
    LeadHardBrakeParams,
    OvertakeMode,
    RearOvertakeParams,
    TrafficAction,
)
from drisca.core.types import JsonValue, op_set_vehicle_lights

from .base import (
    HAZARD_LIGHT_MASK,
    ScenarioContext,
    ScenarioResult,
    pick_adjacent_lane,
    register_traffic_action,
)

if TYPE_CHECKING:
    from ..manager import ManagedVehicle


@register_traffic_action(TrafficAction.LEAD_HARD_BRAKE, params_model=LeadHardBrakeParams)
def _lead_hard_brake(ctx: ScenarioContext, params: LeadHardBrakeParams) -> ScenarioResult:
    candidates: list[tuple[float, int]] = []
    projected = ctx.local_scene()
    if projected is not None and ctx.scene is not None:
        local_x, local_y, heading_dot = projected
        mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x > 2.0)
            & (local_x <= params.max_distance_m)
            & (np.abs(local_y) <= 2.2)
            & (heading_dot > 0.35)
        )
        candidates = [
            (float(local_x[i]), int(ctx.scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
        ]

    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = ctx.manager.vehicles[target_id]
    elif ctx.debug:
        dist = min(25.0, params.max_distance_m)
        entry, _ = ctx.spawn_along_ego(distance_m=dist)
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 前方无托管车，已临时生成测试前车 actor_id={target_id}')
    else:
        raise RuntimeError(f'主车正前方 {params.max_distance_m:g} 米内没有托管背景车')

    entry.brake_override_until = time.monotonic() + params.duration_s
    entry.brake_override_value = params.brake_intensity
    logger.info(f'已触发前车急刹：actor_id={target_id}，距离={dist:.1f}m，持续={params.duration_s:g}s')
    return ScenarioResult(
        action=TrafficAction.LEAD_HARD_BRAKE,
        target_actor_ids=(target_id,),
        payload={'target_actor_id': target_id, 'distance_m': round(dist, 2)},
    )


@register_traffic_action(TrafficAction.ADJACENT_CUT_IN, params_model=AdjacentCutInParams)
def _adjacent_cut_in(ctx: ScenarioContext, params: AdjacentCutInParams) -> ScenarioResult:
    proj = ctx.locate_ego('主车当前不在可识别车道上，无法执行邻车切入')

    if params.mode is CutInMode.SPAWN_CUT_IN:
        init_speed = max(ctx.ego.speed_mps * 0.85, 6.0)
        entry, target_lane = ctx.spawn_along_ego(
            distance_m=params.spawn_distance_m,
            speed_factor=0.85,
            adjacent=params.side,
            initial_speed_mps=init_speed,
        )
        entry.pending_merge_lane = target_lane
        entry.merge_trigger_distance_m = params.trigger_distance_m
        logger.info(
            f'已布置邻道加塞待切入车：actor_id={entry.actor_id}，生成距={params.spawn_distance_m:g}m，'
            f'初速度={init_speed:.1f}m/s，触发距={params.trigger_distance_m:g}m，目标车道={target_lane}'
        )
        return ScenarioResult(
            action=TrafficAction.ADJACENT_CUT_IN,
            target_actor_ids=(entry.actor_id,),
            payload={
                'mode': params.mode.value,
                'target_actor_id': entry.actor_id,
                'target_lane': target_lane,
                'distance_m': params.spawn_distance_m,
                'trigger_distance_m': params.trigger_distance_m,
            },
        )

    candidates: list[tuple[float, int]] = []
    projected = ctx.local_scene()
    if projected is not None and ctx.scene is not None:
        local_x, local_y, heading_dot = projected
        match params.side:
            case LaneSide.LEFT:
                lat_mask = (local_y <= -1.8) & (local_y >= -5.5)
            case LaneSide.RIGHT:
                lat_mask = (local_y >= 1.8) & (local_y <= 5.5)
            case _:
                lat_mask = (np.abs(local_y) >= 1.8) & (np.abs(local_y) <= 5.5)
        mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x >= params.min_front_m)
            & (local_x <= params.max_front_m)
            & lat_mask
            & (heading_dot > 0.35)
        )
        candidates = [
            (float(local_x[i]), int(ctx.scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
        ]

    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = ctx.manager.vehicles[target_id]
    elif ctx.debug:
        dist = min(max(params.min_front_m + 6.0, 16.0), params.max_front_m)
        entry, _ = ctx.spawn_along_ego(distance_m=dist, adjacent=params.side)
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 相邻车道无托管车，已临时生成测试邻车 actor_id={target_id}')
    else:
        raise RuntimeError(
            f'主车相邻车道前方 {params.min_front_m:g}–{params.max_front_m:g} 米内没有托管背景车'
        )

    entry.controller.switch_lane(proj.lane.lane_key)
    logger.info(f'已触发邻车切入：actor_id={target_id} -> 车道 {proj.lane.lane_key}，前方距离={dist:.1f}m')
    return ScenarioResult(
        action=TrafficAction.ADJACENT_CUT_IN,
        target_actor_ids=(target_id,),
        payload={
            'target_actor_id': target_id,
            'target_lane': proj.lane.lane_key,
            'distance_m': round(dist, 2),
        },
    )


@register_traffic_action(TrafficAction.REAR_OVERTAKE, params_model=RearOvertakeParams)
def _rear_overtake(ctx: ScenarioContext, params: RearOvertakeParams) -> ScenarioResult:
    proj = ctx.locate_ego('主车当前不在可识别车道上，无法触发后车超车')
    overtake_speed_mps = max(ctx.ego.speed_mps + params.extra_speed_mps, 18.0)

    pass_lane_key = pick_adjacent_lane(proj.lane, params.side)
    if pass_lane_key is None:
        raise RuntimeError('当前路段没有可用于超车的相邻同向车道')
    return_side = LaneSide.RIGHT if pass_lane_key == proj.lane.left_lane else LaneSide.LEFT
    pass_lane = ctx.manager.graph.get(pass_lane_key)
    if pass_lane is None or pass_lane.points.shape[0] < 2:
        raise RuntimeError('超车相邻车道几何数据缺失')

    entry: ManagedVehicle | None = None
    actual_dist = params.rear_distance_m
    projected = ctx.local_scene()
    if params.mode is OvertakeMode.REUSE_REAR and projected is not None and ctx.scene is not None:
        local_x, local_y, heading_dot = projected
        mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x <= -3.0)
            & (local_x >= -max(params.rear_distance_m * 2.0, 50.0))
            & (np.abs(local_y) <= 5.5)
            & (heading_dot > 0.35)
        )
        candidates = [
            (abs(float(local_x[i])), int(ctx.scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
        ]
        if candidates:
            actual_dist, target_id = min(candidates, key=lambda item: item[0])
            entry = ctx.manager.vehicles[target_id]

    if entry is None:
        if params.mode is OvertakeMode.REUSE_REAR and not ctx.debug:
            raise RuntimeError(
                f'主车后方 {max(params.rear_distance_m * 2.0, 50.0):g} 米内没有可复用的托管背景车'
            )
        ego_rad = math.radians(ctx.ego.yaw_deg)
        rear_x = ctx.ego.x - math.cos(ego_rad) * params.rear_distance_m
        rear_y = ctx.ego.y - math.sin(ego_rad) * params.rear_distance_m
        dists = np.hypot(pass_lane.points[:, 0] - rear_x, pass_lane.points[:, 1] - rear_y)
        s_idx = int(np.argmin(dists))
        s_pt = pass_lane.points[s_idx]
        s_prev = pass_lane.points[max(0, s_idx - 1)]
        s_next = pass_lane.points[min(pass_lane.points.shape[0] - 1, s_idx + 1)]
        s_yaw = math.degrees(math.atan2(float(s_next[1] - s_prev[1]), float(s_next[0] - s_prev[0])))
        entry = ctx.manager.spawn_managed_vehicle(
            ctx.api,
            location=(float(s_pt[0]), float(s_pt[1]), float(s_pt[2])),
            yaw_deg=s_yaw,
            default_speed_limit_mps=ctx.default_speed_limit_mps,
            speed_factor=1.2,
            initial_speed_mps=overtake_speed_mps,
        )
        actual_dist = params.rear_distance_m

    entry.controller.switch_lane(pass_lane_key, lock_s=15.0)
    entry.target_speed_mps_override = overtake_speed_mps
    entry.target_speed_mps_override_until = time.monotonic() + 25.0
    entry.overtake_target_lane = proj.lane.lane_key if params.return_to_lane else None
    entry.overtake_return_side = return_side.value if params.return_to_lane else None
    entry.overtake_clear_front_m = params.clear_front_m
    entry.overtake_extra_speed_mps = params.extra_speed_mps
    logger.info(
        f'已触发后车超车（无视限速）：actor_id={entry.actor_id}，超车道={pass_lane_key}，'
        f'目标速度={overtake_speed_mps:.1f}m/s，切回车道={proj.lane.lane_key}，'
        f'安全前距={params.clear_front_m:g}m'
    )
    return ScenarioResult(
        action=TrafficAction.REAR_OVERTAKE,
        target_actor_ids=(entry.actor_id,),
        payload={
            'mode': params.mode.value,
            'target_actor_id': entry.actor_id,
            'pass_lane': pass_lane_key,
            'target_lane': proj.lane.lane_key,
            'target_speed_mps': round(overtake_speed_mps, 2),
            'rear_distance_m': round(actual_dist, 2),
        },
    )


@register_traffic_action(TrafficAction.LEAD_BREAKDOWN, params_model=LeadBreakdownParams)
def _lead_breakdown(ctx: ScenarioContext, params: LeadBreakdownParams) -> ScenarioResult:
    if params.mode is BreakdownMode.REUSE_LEAD:
        candidates: list[tuple[float, int]] = []
        projected = ctx.local_scene()
        if projected is not None and ctx.scene is not None:
            local_x, local_y, _ = projected
            mask = (
                (ctx.scene.actor_ids != ctx.ego.actor_id)
                & (local_x > 5.0)
                & (local_x <= params.distance_m)
                & (np.abs(local_y) < 2.4)
            )
            candidates = [
                (float(local_x[i]), int(ctx.scene.actor_ids[i]))
                for i in np.flatnonzero(mask)
                if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
            ]
        if candidates:
            dist, target_id = min(candidates, key=lambda item: item[0])
            entry = ctx.manager.vehicles[target_id]
        elif ctx.debug:
            dist = min(35.0, params.distance_m)
            entry, _ = ctx.spawn_along_ego(distance_m=dist)
            target_id = entry.actor_id
            logger.info(f'[DEBUG] 前方无托管车，已临时生成故障测试车 actor_id={target_id}')
        else:
            raise RuntimeError(f'主车前方 {params.distance_m:g} 米内没有可复用的托管前车')

        if params.speed_factor <= 0.01:
            entry.permanent_stop = True
        else:
            entry.speed_factor_override = params.speed_factor
            entry.speed_factor_override_until = time.monotonic() + 300.0
        ctx.manager.queue_operation(op_set_vehicle_lights(actor_id=target_id, light_state=HAZARD_LIGHT_MASK))
        logger.info(
            f'已触发前车故障停驶（复用前车）：actor_id={target_id}，距离={dist:.1f}m，'
            f'speed_factor={params.speed_factor:g}'
        )
        return ScenarioResult(
            action=TrafficAction.LEAD_BREAKDOWN,
            target_actor_ids=(target_id,),
            payload={
                'mode': params.mode.value,
                'target_actor_id': target_id,
                'distance_m': round(dist, 2),
                'speed_factor': params.speed_factor,
            },
        )

    entry, _ = ctx.spawn_along_ego(distance_m=params.distance_m, speed_factor=params.speed_factor)
    if params.speed_factor <= 0.01:
        entry.permanent_stop = True
        ctx.manager.queue_operation(
            op_set_vehicle_lights(actor_id=entry.actor_id, light_state=HAZARD_LIGHT_MASK)
        )
    logger.info(
        f'已触发远距离障碍车生成：actor_id={entry.actor_id}，距离={params.distance_m:g}m，'
        f'speed_factor={params.speed_factor:g}'
    )
    return ScenarioResult(
        action=TrafficAction.LEAD_BREAKDOWN,
        target_actor_ids=(entry.actor_id,),
        payload={
            'mode': params.mode.value,
            'target_actor_id': entry.actor_id,
            'distance_m': params.distance_m,
            'speed_factor': params.speed_factor,
        },
    )


@register_traffic_action(TrafficAction.DUAL_LANE_SLOWDOWN, params_model=DualLaneSlowdownParams)
def _dual_lane_slowdown(ctx: ScenarioContext, params: DualLaneSlowdownParams) -> ScenarioResult:
    selected: list[int] = []
    projected = ctx.local_scene()
    if projected is not None and ctx.scene is not None:
        local_x, local_y, _ = projected
        same_mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x > 4.0)
            & (local_x <= params.max_distance_m)
            & (np.abs(local_y) < 2.2)
        )
        adj_mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x > 4.0)
            & (local_x <= params.max_distance_m)
            & (np.abs(local_y) >= 2.2)
            & (np.abs(local_y) <= 6.2)
        )
        for mask in (same_mask, adj_mask):
            cands = [
                (float(local_x[i]), int(ctx.scene.actor_ids[i]))
                for i in np.flatnonzero(mask)
                if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
            ]
            if cands:
                selected.append(min(cands, key=lambda item: item[0])[1])
    if not selected and ctx.debug:
        entry, _ = ctx.spawn_along_ego(distance_m=min(30.0, params.max_distance_m))
        selected.append(entry.actor_id)
        logger.info(f'[DEBUG] 前方无托管车，已临时生成压速测试车 actor_id={entry.actor_id}')
    if not selected:
        raise RuntimeError(f'主车前方 {params.max_distance_m:g} 米内同车道与相邻车道均无托管背景车')

    until = time.monotonic() + params.duration_s
    for aid in selected:
        entry = ctx.manager.vehicles[aid]
        entry.speed_factor_override = params.speed_factor
        entry.speed_factor_override_until = until
    logger.info(
        f'已触发双车道并排压速：actor_ids={selected}，speed_factor={params.speed_factor:g}，'
        f'持续={params.duration_s:g}s'
    )
    wire_ids: list[JsonValue] = list(selected)
    return ScenarioResult(
        action=TrafficAction.DUAL_LANE_SLOWDOWN,
        target_actor_ids=tuple(selected),
        payload={
            'target_actor_ids': wire_ids,
            'speed_factor': params.speed_factor,
            'duration_s': params.duration_s,
        },
    )
