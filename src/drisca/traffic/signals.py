"""交通信号灯停止线索引与前方红黄灯距离估算。"""

from collections.abc import Sequence
from dataclasses import dataclass

from drisca.core.types import JsonObject, TrafficLightSnapshot, TrafficLightState, as_float, as_int

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
    def from_native(cls, raw_signals: JsonObject, graph: RoadGraph) -> SignalTracker:
        entries_by_lane: dict[str, list[SignalStopEntry]] = {}
        seen: set[tuple[str, str]] = set()

        raw_list = raw_signals.get('signals')
        if not isinstance(raw_list, list):
            return cls({})

        for sig in raw_list:
            if not isinstance(sig, dict):
                continue
            signal_id = str(sig.get('signal_id') or sig.get('id') or '')
            raw_actor = sig.get('actor_id')
            actor_id = (
                int(raw_actor) if isinstance(raw_actor, int) and not isinstance(raw_actor, bool) else None
            )
            if not signal_id and actor_id is None:
                continue

            zones = sig.get('trigger_zones')
            if isinstance(zones, list) and zones:
                for zone in zones:
                    if not isinstance(zone, dict):
                        continue
                    road_id = as_int(zone.get('road_id', 0))
                    section_id = as_int(zone.get('section_id', 0))
                    lane_id = as_int(zone.get('lane_id', 0))
                    key = f'{road_id}:{section_id}:{lane_id}'
                    lane = graph.get(key)
                    if lane is None or (key, signal_id) in seen:
                        continue
                    seen.add((key, signal_id))
                    stop_s = lane.road_s_to_travel_s(as_float(zone.get('s', 0.0)))
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
            refs = sig.get('references')
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                road_id = as_int(ref.get('road_id', 0))
                ref_s = as_float(ref.get('s', 0.0))
                validities = ref.get('validities')
                if not isinstance(validities, list):
                    continue
                for validity in validities:
                    if not isinstance(validity, dict):
                        continue
                    from_lane = as_int(validity.get('from_lane', 0))
                    to_lane = as_int(validity.get('to_lane', 0))
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
        traffic_lights: Sequence[TrafficLightSnapshot],
        *,
        max_distance_m: float = 55.0,
    ) -> float | None:
        """返回前方参考路径上最近红/黄灯停止线距离 (m)，无须停车时返回 None。"""
        if not self._by_lane or not traffic_lights or not path.lane_keys:
            return None

        by_actor: dict[int, TrafficLightState] = {}
        by_signal: dict[str, TrafficLightState] = {}
        for item in traffic_lights:
            if item.actor_id is not None:
                by_actor[item.actor_id] = item.state
            if item.signal_id:
                by_signal[item.signal_id] = item.state

        nearest: float | None = None
        for idx, lane_key in enumerate(path.lane_keys):
            base_offset = path.lane_start_s[idx]
            if base_offset > max_distance_m:
                break
            entries = self._by_lane.get(lane_key)
            if not entries:
                continue
            for entry in entries:
                state = (
                    by_actor.get(entry.actor_id, TrafficLightState.UNKNOWN)
                    if entry.actor_id is not None
                    else TrafficLightState.UNKNOWN
                )
                if state is TrafficLightState.UNKNOWN and entry.signal_id:
                    state = by_signal.get(entry.signal_id, TrafficLightState.UNKNOWN)
                if state not in (TrafficLightState.RED, TrafficLightState.YELLOW):
                    continue
                if idx == 0:
                    dist = entry.stop_s - path.current_lane_s
                else:
                    dist = base_offset + entry.stop_s
                if 0.5 <= dist <= max_distance_m:
                    if nearest is None or dist < nearest:
                        nearest = dist
        return nearest

    def nearest_signal(
        self,
        path: RoutePath,
        traffic_lights: Sequence[TrafficLightSnapshot],
        *,
        max_distance_m: float = 120.0,
    ) -> tuple[int, str, float, TrafficLightState] | None:
        """返回前方参考路径上最近的任意颜色信号灯 (actor_id, signal_id, distance_m, state)。"""
        if not self._by_lane or not path.lane_keys:
            return None

        by_actor: dict[int, tuple[str, TrafficLightState]] = {}
        by_signal: dict[str, tuple[int, TrafficLightState]] = {}
        for item in traffic_lights:
            if item.actor_id is not None:
                by_actor[item.actor_id] = (item.signal_id, item.state)
                if item.signal_id:
                    by_signal[item.signal_id] = (item.actor_id, item.state)

        best: tuple[int, str, float, TrafficLightState] | None = None
        for idx, lane_key in enumerate(path.lane_keys):
            base_offset = path.lane_start_s[idx]
            if base_offset > max_distance_m:
                break
            entries = self._by_lane.get(lane_key)
            if not entries:
                continue
            for entry in entries:
                actor_id = entry.actor_id
                state = TrafficLightState.UNKNOWN
                if actor_id is not None and actor_id in by_actor:
                    _, state = by_actor[actor_id]
                elif entry.signal_id and entry.signal_id in by_signal:
                    actor_id, state = by_signal[entry.signal_id]
                if actor_id is None:
                    continue
                dist = (entry.stop_s - path.current_lane_s) if idx == 0 else (base_offset + entry.stop_s)
                if 0.5 <= dist <= max_distance_m:
                    if best is None or dist < best[2]:
                        best = (actor_id, entry.signal_id, dist, state)
        return best
