"""信号灯与全局车流调控类交通场景事件：前方信号变灯、闯红灯车辆、动态车流数量调节。"""

import math
import time

import numpy as np
from loguru import logger

from drisca.core.traffic_models import (
    AheadSignalChangeParams,
    RedLightRunnerParams,
    SetTrafficCountParams,
    TrafficAction,
)
from drisca.core.types import op_set_traffic_light_state

from ..planner import LocalRoutePlanner
from .base import ScenarioContext, ScenarioResult, register_traffic_action


@register_traffic_action(
    TrafficAction.AHEAD_SIGNAL_CHANGE,
    params_model=AheadSignalChangeParams,
    highlight_debug=False,
)
def _ahead_signal_change(ctx: ScenarioContext, params: AheadSignalChangeParams) -> ScenarioResult:
    temp_planner = LocalRoutePlanner(ctx.manager.graph, horizon_m=max(140.0, params.max_distance_m + 20.0))
    path = temp_planner.update(
        ctx.ego.x,
        ctx.ego.y,
        ctx.ego.yaw_deg,
        road_id=ctx.ego.road_id or None,
        lane_id=ctx.ego.lane_id or None,
    )
    if path is None:
        raise RuntimeError('主车当前不在可识别车道上，无法匹配前方信号灯')

    matched = ctx.manager.signals.nearest_signal(
        path,
        ctx.traffic_lights,
        max_distance_m=params.max_distance_m,
    )
    if matched is None:
        raise RuntimeError(f'主车前方 {params.max_distance_m:g} 米内未找到对应的交通信号灯')
    actor_id, signal_id, dist_m, prev_state = matched
    ctx.manager.queue_operation(
        op_set_traffic_light_state(actor_id=actor_id, state=params.target_state.value)
    )
    logger.info(
        f'已触发前方信号灯突变：actor_id={actor_id} ({signal_id}) '
        f'{prev_state.value} -> {params.target_state.value}，距离={dist_m:.1f}m'
    )
    return ScenarioResult(
        action=TrafficAction.AHEAD_SIGNAL_CHANGE,
        payload={
            'actor_id': actor_id,
            'signal_id': signal_id,
            'previous_state': prev_state.value,
            'target_state': params.target_state.value,
            'distance_m': round(dist_m, 2),
        },
    )


@register_traffic_action(TrafficAction.RED_LIGHT_RUNNER, params_model=RedLightRunnerParams)
def _red_light_runner(ctx: ScenarioContext, params: RedLightRunnerParams) -> ScenarioResult:
    candidates: list[tuple[float, int]] = []
    projected = ctx.local_scene()
    if projected is not None and ctx.scene is not None:
        local_x, local_y, _ = projected
        mask = (
            (ctx.scene.actor_ids != ctx.ego.actor_id)
            & (local_x > 2.0)
            & (local_x <= params.max_distance_m)
            & (np.abs(local_y) <= 35.0)
        )
        candidates = [
            (float(math.hypot(float(local_x[i]), float(local_y[i]))), int(ctx.scene.actor_ids[i]))
            for i in np.flatnonzero(mask)
            if int(ctx.scene.actor_ids[i]) in ctx.manager.vehicles
        ]

    if candidates:
        dist, target_id = min(candidates, key=lambda item: item[0])
        entry = ctx.manager.vehicles[target_id]
    elif ctx.debug:
        dist = min(28.0, params.max_distance_m)
        entry, _ = ctx.spawn_along_ego(distance_m=dist)
        target_id = entry.actor_id
        logger.info(f'[DEBUG] 前方无托管车，已临时生成闯红灯测试车 actor_id={target_id}')
    else:
        raise RuntimeError(f'主车前方 {params.max_distance_m:g} 米范围内没有可触发闯红灯/抢行的托管背景车')

    until = time.monotonic() + params.duration_s
    entry.ignore_signals_until = until
    entry.speed_factor_override = 1.15
    entry.speed_factor_override_until = until
    logger.info(
        f'已触发他车闯红灯/路口抢行：actor_id={target_id}，距离={dist:.1f}m，持续={params.duration_s:g}s'
    )
    return ScenarioResult(
        action=TrafficAction.RED_LIGHT_RUNNER,
        target_actor_ids=(target_id,),
        payload={
            'target_actor_id': target_id,
            'distance_m': round(dist, 2),
            'duration_s': params.duration_s,
        },
    )


@register_traffic_action(
    TrafficAction.SET_TRAFFIC_COUNT,
    params_model=SetTrafficCountParams,
    highlight_debug=False,
)
def _set_traffic_count(ctx: ScenarioContext, params: SetTrafficCountParams) -> ScenarioResult:
    prev_count, delta = ctx.manager.adjust_target_count(
        params.target_count,
        ego_xy=(ctx.ego.x, ctx.ego.y),
        scene=ctx.scene,
    )
    logger.info(f'已调整周边背景车目标数量：{prev_count} -> {params.target_count}（增量 {delta:+d}）')
    return ScenarioResult(
        action=TrafficAction.SET_TRAFFIC_COUNT,
        payload={
            'previous_count': prev_count,
            'target_count': params.target_count,
            'delta': delta,
        },
    )
