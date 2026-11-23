"""交通信号灯停止线索引与前方红黄灯距离估算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .planner import RoutePath
from .road_graph import RoadGraph


@dataclass(frozen=True, slots=True)
class SignalStopEntry:
    """单条车道上的信号灯停止位置。"""

    lane_key: str
    stop_s: float  # 本车道沿行驶方向的距离 (m)
    signal_id: str
    actor_id: int | None


class SignalTracker:
    """结合静态 road_signals 与每帧 traffic_lights 判定前方停止距离。"""

    def __init__(self, by_lane: dict[str, tuple[SignalStopEntry, ...]]) -> None:
        self._by_lane = by_lane

    @classmethod
    def from_native(cls, raw_signals: dict[str, Any], graph: RoadGraph) -> SignalTracker:
        entries_by_lane: dict[str, list[SignalStopEntry]] = {}
        seen: set[tuple[str, str]] = set()

        for sig in raw_signals.get('signals') or ():
            signal_id = str(sig.get('signal_id') or sig.get('id') or '')
            raw_actor = sig.get('actor_id')
            actor_id = int(raw_actor) if raw_actor is not None else None
            if not signal_id and actor_id is None:
                continue

            zones = sig.get('trigger_zones') or ()
            if zones:
                for zone in zones:
                    road_id = int(zone['road_id'])
                    section_id = int(zone['section_id'])
                    lane_id = int(zone['lane_id'])
                    key = f'{road_id}:{section_id}:{lane_id}'
                    lane = graph.get(key)
                    if lane is None or (key, signal_id) in seen:
                        continue
                    seen.add((key, signal_id))
                    stop_s = lane.road_s_to_travel_s(float(zone['s']))
                    entries_by_lane.setdefault(key, []).append(
                        SignalStopEntry(
                            lane_key=key,
                            stop_s=stop_s,
                            signal_id=signal_id,
                            actor_id=actor_id,
                        )
                    )
                continue

            # 缺少 trigger_zones 时根据 OpenDRIVE signal references 推导停止线
            for ref in sig.get('references') or ():
                road_id = int(ref['road_id'])
                ref_s = float(ref['s'])
                for validity in ref.get('validities') or ():
                    from_lane = int(validity['from_lane'])
                    to_lane = int(validity['to_lane'])
                    lo, hi = min(from_lane, to_lane), max(from_lane, to_lane)
                    for lid in range(lo, hi + 1):
                        if lid == 0:
                            continue
                        for lane in graph.lanes_for_road(road_id, lid):
                            if not (
                                lane.section_start_s - 1.0
                                <= ref_s
                                <= lane.section_start_s + lane.length + 1.0
                            ):
                                continue
                            key = lane.lane_key
                            if (key, signal_id) in seen:
                                continue
                            seen.add((key, signal_id))
                            stop_s = lane.road_s_to_travel_s(ref_s)
                            entries_by_lane.setdefault(key, []).append(
                                SignalStopEntry(
                                    lane_key=key,
                                    stop_s=stop_s,
                                    signal_id=signal_id,
                                    actor_id=actor_id,
                                )
                            )

        return cls({key: tuple(items) for key, items in entries_by_lane.items()})

    def nearest_stop_distance(
        self,
        path: RoutePath,
        traffic_lights: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        *,
        max_distance_m: float = 55.0,
    ) -> float | None:
        """返回前方参考路径上最近红/黄灯停止线距离 (m)，无须停车时返回 None。"""
        if not self._by_lane or not traffic_lights or not path.lane_keys:
            return None

        by_actor: dict[int, str] = {}
        by_signal: dict[str, str] = {}
        for item in traffic_lights:
            state = str(item.get('state', ''))
            if item.get('actor_id') is not None:
                by_actor[int(item['actor_id'])] = state
            if item.get('signal_id'):
                by_signal[str(item['signal_id'])] = state

        nearest: float | None = None
        for idx, lane_key in enumerate(path.lane_keys):
            base_offset = path.lane_start_s[idx]
            if base_offset > max_distance_m:
                break
            entries = self._by_lane.get(lane_key)
            if not entries:
                continue
            for entry in entries:
                state = by_actor.get(entry.actor_id, '') if entry.actor_id is not None else ''
                if not state and entry.signal_id:
                    state = by_signal.get(entry.signal_id, '')
                if state not in ('Red', 'Yellow'):
                    continue
                if idx == 0:
                    dist = entry.stop_s - path.current_lane_s
                else:
                    dist = base_offset + entry.stop_s
                if 0.5 <= dist <= max_distance_m:
                    if nearest is None or dist < nearest:
                        nearest = dist
        return nearest
