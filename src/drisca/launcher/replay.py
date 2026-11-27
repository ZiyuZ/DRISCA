"""录像回放环境同步器：在 CARLA 车辆回放期间按时间轴重现初始与运行期天气和团雾。"""

import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from drisca.core.client import NativeApiClient, NativeApiError
from drisca.core.config import RunConfig
from drisca.core.types import JsonObject, as_float, as_int
from drisca.core.weather import to_payload
from drisca.storage.models import EventRow, SessionRow

_VEHICLE_ID_RE = re.compile(r'Create\s+(\d+):\s+vehicle\.')
_DURATION_RE = re.compile(r'Duration:\s*([0-9]+(?:\.[0-9]+)?)\s*seconds', re.IGNORECASE)


class ReplayRunner:
    """配合原生 recorder.replay 同步重放初始环境与运行期 environment_applied 事件。"""

    def __init__(
        self,
        *,
        on_log: Callable[[str, str], None],
        on_state: Callable[[bool, str | None, str | None], None] | None = None,
    ) -> None:
        self._on_log = on_log
        self._on_state = on_state
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_api: NativeApiClient | None = None
        self._running = False
        self._rec_path: Path | None = None
        self._start_time = 0.0
        self._duration = 0.0
        self._time_factor = 1.0
        self._started_monotonic = 0.0
        self._hero_id = 0
        self._follow_id = 0
        self._view_mode = 'free'
        self._vehicle_ids: tuple[int, ...] = ()

    @property
    def running(self) -> bool:
        return self._running

    def set_view_mode(self, mode: str) -> None:
        """回放期间切换 DRISCA 三视角（free / cockpit / chase）。"""
        ended = False
        with self._lock:
            if not self._running or self._active_api is None:
                raise RuntimeError('当前未在录像回放中')
            target_id = self._follow_id or self._hero_id or (self._vehicle_ids[0] if self._vehicle_ids else 0)
            try:
                if mode != 'free' and target_id > 0:
                    self._follow_id = target_id
                    self._active_api.update_view(
                        view_mode=mode,
                        ego_actor_id=target_id,
                        actor_id_space='recorded',
                    )
                else:
                    self._active_api.update_view(view_mode=mode)
                self._view_mode = mode
            except NativeApiError as exc:
                if exc.code == 'invalid_state':
                    ended = True
                else:
                    raise
        if ended:
            self.stop()
            raise RuntimeError('录像已播放结束，请重新开始回放')

    def set_follow(self, target: str) -> int:
        """回放期间平滑切换跟随车辆（free / hero / prev / next），不中断回放进度。"""
        ended = False
        next_id = 0
        with self._lock:
            if not self._running or self._active_api is None or self._rec_path is None:
                raise RuntimeError('当前未在录像回放中')
            try:
                if target == 'free':
                    self._active_api.update_view(view_mode='free')
                    self._follow_id = 0
                    self._view_mode = 'free'
                    return 0
                if target == 'hero':
                    if self._hero_id <= 0:
                        raise RuntimeError('该录像未记录主车编号，请使用切车按钮选择车辆')
                    next_id = self._hero_id
                elif target in ('prev', 'next'):
                    if not self._vehicle_ids:
                        raise RuntimeError('未从录像中解析到可切换车辆')
                    step = -1 if target == 'prev' else 1
                    if self._follow_id in self._vehicle_ids:
                        idx = (self._vehicle_ids.index(self._follow_id) + step) % len(self._vehicle_ids)
                    else:
                        idx = 0 if step > 0 else len(self._vehicle_ids) - 1
                    next_id = self._vehicle_ids[idx]
                else:
                    raise ValueError(f'未知的回放视角目标：{target}')
                mode = self._view_mode if self._view_mode != 'free' else 'chase'
                self._active_api.update_view(
                    view_mode=mode,
                    ego_actor_id=next_id,
                    actor_id_space='recorded',
                )
                self._follow_id = next_id
                self._view_mode = mode
            except NativeApiError as exc:
                if exc.code == 'invalid_state':
                    ended = True
                else:
                    raise
        if ended:
            self.stop()
            raise RuntimeError('录像已播放结束，请重新开始回放')
        return next_id

    def stop(self, api: NativeApiClient | None = None) -> None:
        with self._lock:
            was_running = self._running
            target_api = api or self._active_api
            self._stop_locked()
            self._active_api = None
            self._running = False
        if was_running and target_api is not None:
            self._cleanup_world(target_api)
        if self._on_state is not None:
            self._on_state(False, None, None)
        if was_running:
            self._on_log('录像回放已停止', 'INFO')

    def _cleanup_world(self, api: NativeApiClient) -> None:
        """停止回放并清理场景中残留的回放车辆、行人与团雾。"""
        try:
            api.recorder_stop_replay()
        except Exception as exc:
            self._on_log(f'停止录像回放异常：{exc}', 'WARNING')
        try:
            api.clear_actors()
        except Exception as exc:
            self._on_log(f'清理回放车辆异常：{exc}', 'WARNING')
        try:
            for region in api.environment_list():
                try:
                    api.environment_delete(region.region_id, 0.0)
                except Exception:
                    pass
        except Exception:
            pass

    def _stop_locked(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None

    def start(
        self,
        api: NativeApiClient,
        *,
        rec_path: Path,
        session: SessionRow | None,
        events: list[EventRow],
        start_time: float = 0.0,
        duration: float = 0.0,
        time_factor: float = 1.0,
        follow_actor_id: int = 0,
        follow_ego: bool = False,
    ) -> None:
        with self._lock:
            self._stop_locked()
            self._stop_event.clear()
            self._active_api = api

            # 启动新回放前先停止旧回放并清理残留车辆、行人与团雾，避免重复生成堆叠
            self._cleanup_world(api)

            initial_region_map: dict[int, int] = {}
            resolved_follow = follow_actor_id
            if resolved_follow == 0 and follow_ego and session is not None and session.ego_actor_id:
                resolved_follow = int(session.ego_actor_id)
            if session is not None:
                try:
                    run_cfg = RunConfig.model_validate_json(session.run_config_json)
                    api.environment_apply(to_payload(run_cfg.preset.world.weather), 0.0)
                    for idx, fog in enumerate(run_cfg.preset.world.fog_regions, start=1):
                        created = api.environment_create(
                            center_m=fog.center_m,
                            radius_m=fog.radius_m,
                            density=fog.density,
                            transition_seconds=0.0,
                        )
                        initial_region_map[idx] = created.region_id
                except Exception as exc:
                    self._on_log(f'回放初始环境恢复失败（继续车辆回放）：{exc}', 'WARNING')

            api.recorder_replay(
                str(rec_path.resolve()),
                start_time=start_time,
                duration=duration,
                follow_actor_id=resolved_follow,
                time_factor=time_factor,
                ignore_hero=False,
            )
            self._rec_path = rec_path
            self._start_time = start_time
            self._duration = duration
            self._time_factor = max(0.05, float(time_factor))
            self._started_monotonic = time.monotonic()
            self._hero_id = int(session.ego_actor_id) if session is not None and session.ego_actor_id else 0
            self._follow_id = resolved_follow
            total_duration = 0.0
            try:
                info_text = str(api.recorder_info(str(rec_path.resolve()), show_all=False).get('info') or '')
                ids = list(dict.fromkeys(int(m) for m in _VEHICLE_ID_RE.findall(info_text)))
                if self._hero_id > 0 and self._hero_id not in ids:
                    ids.insert(0, self._hero_id)
                self._vehicle_ids = tuple(ids)
                dur_match = _DURATION_RE.search(info_text)
                if dur_match is not None:
                    total_duration = float(dur_match.group(1))
            except Exception:
                self._vehicle_ids = (self._hero_id,) if self._hero_id > 0 else ()
            self._running = True
            if self._on_state is not None:
                self._on_state(True, rec_path.name, None)

            timeline = self._build_timeline(session, events)
            factor = max(0.05, float(time_factor))
            if timeline:
                self._on_log(
                    f'已启动录像回放：{rec_path.name}（同步 {len(timeline)} 条环境变化，倍速 {factor:g}x）',
                    'INFO',
                )
            else:
                self._on_log(f'已启动录像回放：{rec_path.name}', 'INFO')

            play_duration = duration if duration > 0 else max(0.0, total_duration - start_time)
            if timeline or play_duration > 0:
                thread = threading.Thread(
                    target=self._run_timeline,
                    args=(api, timeline, initial_region_map, start_time, duration, factor, play_duration),
                    daemon=True,
                    name='replay-environment',
                )
                self._thread = thread
                thread.start()

    def _build_timeline(
        self,
        session: SessionRow | None,
        events: list[EventRow],
    ) -> list[tuple[float, JsonObject]]:
        """提取按仿真/墙钟相对秒数排序的 environment_applied 事件列表。"""
        base_ts = session.started_at if session is not None else None
        base_sim_us: int | None = None
        items: list[tuple[float, JsonObject]] = []
        for row in events:
            if row.name != 'environment_applied':
                continue
            try:
                payload = json.loads(row.payload_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            native = payload.get('native')
            sim_us = native.get('simulation_time_us') if isinstance(native, dict) else None
            if isinstance(sim_us, (int, float)):
                if base_sim_us is None:
                    base_sim_us = int(sim_us)
                rel_s = max(0.0, (int(sim_us) - base_sim_us) / 1e6)
            elif base_ts is not None:
                rel_s = max(0.0, row.timestamp - base_ts)
            else:
                rel_s = 0.0
            items.append((rel_s, payload))
        items.sort(key=lambda pair: pair[0])
        return items

    def _run_timeline(
        self,
        api: NativeApiClient,
        timeline: list[tuple[float, JsonObject]],
        region_map: dict[int, int],
        start_time: float,
        duration: float,
        time_factor: float,
        play_duration: float = 0.0,
    ) -> None:
        started = time.monotonic()
        end_time = (start_time + duration) if duration > 0 else None
        for rel_s, payload in timeline:
            if self._stop_event.is_set():
                return
            if end_time is not None and rel_s > end_time:
                break
            if rel_s < start_time:
                # 快进应用 start_time 之前的环境状态（零时长瞬间到位）
                self._apply_event(api, payload, region_map, time_factor, instant=True)
                continue
            wait_s = (rel_s - start_time) / time_factor - (time.monotonic() - started)
            if wait_s > 0 and self._stop_event.wait(wait_s):
                return
            self._apply_event(api, payload, region_map, time_factor, instant=False)
        if play_duration > 0:
            remaining = play_duration / time_factor - (time.monotonic() - started) + 0.5
            if remaining > 0 and self._stop_event.wait(remaining):
                return
            if not self._stop_event.is_set():
                self._finish_naturally()

    def _finish_naturally(self) -> None:
        with self._lock:
            if not self._running:
                return
            target_api = self._active_api
            self._active_api = None
            self._running = False
            self._thread = None
        if target_api is not None:
            self._cleanup_world(target_api)
        if self._on_state is not None:
            self._on_state(False, None, None)
        self._on_log('录像回放已完成', 'INFO')

    def _apply_event(
        self,
        api: NativeApiClient,
        payload: JsonObject,
        region_map: dict[int, int],
        time_factor: float,
        *,
        instant: bool,
    ) -> None:
        op = str(payload.get('operation') or '')
        region_id = payload.get('region_id')
        raw_target = payload.get('target')
        target: JsonObject = raw_target if isinstance(raw_target, dict) else {}
        raw_trans = as_float(payload.get('transition_seconds'))
        trans = 0.0 if instant else max(0.0, raw_trans / time_factor)
        try:
            if region_id is None:
                weather = target.get('weather')
                if isinstance(weather, dict):
                    api.environment_apply(weather, transition_seconds=trans)
                return
            orig_id = as_int(region_id)
            if op == 'create':
                center = target.get('center_m')
                radius = target.get('radius_m')
                raw_w = target.get('weather')
                raw_f = raw_w.get('fog') if isinstance(raw_w, dict) else None
                density = raw_f.get('density') if isinstance(raw_f, dict) else None
                if (
                    isinstance(center, list)
                    and len(center) == 3
                    and radius is not None
                    and density is not None
                ):
                    created = api.environment_create(
                        center_m=(as_float(center[0]), as_float(center[1]), as_float(center[2])),
                        radius_m=as_float(radius),
                        density=as_float(density),
                        transition_seconds=trans,
                    )
                    region_map[orig_id] = created.region_id
            elif op == 'update':
                live_id = region_map.get(orig_id)
                if live_id is not None:
                    center = target.get('center_m')
                    radius = target.get('radius_m')
                    raw_w = target.get('weather')
                    raw_f = raw_w.get('fog') if isinstance(raw_w, dict) else None
                    density = raw_f.get('density') if isinstance(raw_f, dict) else None
                    api.environment_update_region(
                        live_id,
                        center_m=(as_float(center[0]), as_float(center[1]), as_float(center[2]))
                        if isinstance(center, list) and len(center) == 3
                        else None,
                        radius_m=as_float(radius) if radius is not None else None,
                        density=as_float(density) if density is not None else None,
                        transition_seconds=trans,
                    )
            elif op == 'delete':
                live_id = region_map.pop(orig_id, None)
                if live_id is not None:
                    api.environment_delete(live_id, transition_seconds=trans)
        except Exception as exc:
            self._on_log(f'回放环境事件同步失败（{op}）：{exc}', 'WARNING')
