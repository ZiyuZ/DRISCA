"""空闲期交通流独立预览运行器：不写数据库、不启动实验会话，开始正式实验前自动清理。"""

import threading
import time
from collections.abc import Callable
from uuid import uuid4

from drisca.core.client import NativeApiClient
from drisca.core.config import (
    CameraRigConfig,
    ControlConfig,
    DisplayLayoutConfig,
    DrivingViewConfig,
    TrafficConfig,
)
from drisca.core.driving_view import keyboard_mapping
from drisca.core.types import JsonObject, NativeOp, TrafficLightSnapshot, op_update_view
from drisca.traffic import RoadGraph, SignalTracker, TrafficManager, TrafficScene

PREVIEW_INTERVAL = 1 / 20


class TrafficPreviewRunner:
    """在实验空闲期使用独立原生连接生成并驱动背景交通流，供实时观察不同风格与模型效果。"""

    def __init__(
        self,
        *,
        on_state: Callable[[bool, int, str | None, int | None], None],
        on_log: Callable[[str, str], None],
        on_signal: Callable[[JsonObject | None], None] | None = None,
    ) -> None:
        self._on_state = on_state
        self._on_log = on_log
        self._on_signal = on_signal
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_view_mode: str | None = None
        self._pending_follow_id: int | None = None
        self._pending_ops: list[NativeOp | JsonObject] = []
        self._actor_ids: tuple[int, ...] = ()
        self._follow_index = 0

    def queue_operation(self, op: NativeOp | JsonObject) -> None:
        with self._lock:
            self._pending_ops.append(op)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def set_view_mode(self, mode: str) -> None:
        with self._lock:
            self._pending_view_mode = mode

    def cycle_follow(self, delta: int) -> int:
        """在预览已生成的背景车之间切换跟随目标，返回新的 actor_id。"""
        with self._lock:
            if not self._actor_ids:
                raise RuntimeError('当前预览暂无可切换的背景车辆')
            self._follow_index = (self._follow_index + delta) % len(self._actor_ids)
            target_id = self._actor_ids[self._follow_index]
            self._pending_follow_id = target_id
            count = len(self._actor_ids)
        self._on_state(True, count, None, target_id)
        return target_id

    def start(
        self,
        driving_view: DrivingViewConfig,
        traffic: TrafficConfig,
        *,
        cameras: CameraRigConfig,
        layout: DisplayLayoutConfig,
        control: ControlConfig,
        default_speed_limit_mps: float = 13.89,
        suppress_screen_messages: bool = False,
    ) -> None:
        if traffic.vehicle_count <= 0:
            raise ValueError('预览背景车数量必须大于 0')
        with self._lock:
            if self.running:
                self._stop_locked()
            self._stop_event.clear()
            preview_cfg = traffic.model_copy(update={'enabled': True})
            self._actor_ids = ()
            self._follow_index = 0
            self._pending_follow_id = None
            self._on_state(True, 0, None, None)
            thread = threading.Thread(
                target=self._run,
                args=(
                    driving_view,
                    preview_cfg,
                    cameras,
                    layout,
                    control,
                    default_speed_limit_mps,
                    suppress_screen_messages,
                ),
                daemon=True,
                name='traffic-preview',
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=8.0)
        self._thread = None

    def _run(
        self,
        driving_view: DrivingViewConfig,
        traffic: TrafficConfig,
        cameras: CameraRigConfig,
        layout: DisplayLayoutConfig,
        control: ControlConfig,
        default_speed_limit_mps: float,
        suppress_screen_messages: bool,
    ) -> None:
        session_id = f'preview_{uuid4().hex[:8]}'
        api = NativeApiClient(driving_view, client='drisca-traffic-preview')
        started_view = False
        try:
            api.connect()
            api.clear_actors()
            raw_graph = api.road_graph_all(sampling_step=2.0)
            raw_signals = api.road_signals()
            graph = RoadGraph.from_native(raw_graph)
            signals = SignalTracker.from_native(raw_signals, graph)
            manager = TrafficManager(graph, signals, traffic)

            # 预览模式无主车，使用远端虚拟坐标避免过滤任何出生点
            spawned = manager.spawn_background(
                api,
                ego_location=(1e9, 1e9, 0.0),
                default_speed_limit_mps=default_speed_limit_mps,
            )
            if spawned <= 0:
                raise RuntimeError('当前地图未能生成任何预览背景车')

            with self._lock:
                self._actor_ids = manager.actor_ids
                self._follow_index = 0
                first_actor_id = self._actor_ids[0]
            view = api.start_view(
                session_id=session_id,
                ego_actor_id=first_actor_id,
                cameras=cameras.model_dump(mode='json'),
                layout=layout.model_dump(mode='json'),
                keyboard=keyboard_mapping(control.keyboard),
                mode='external',
                view_mode='free',
                suppress_screen_messages=suppress_screen_messages,
                dynamic_speed_limit=True,
                default_speed_limit_mps=default_speed_limit_mps,
            )
            started_view = True
            manager.apply_control_state(view.get('control_state'))
            self._on_state(True, spawned, None, first_actor_id)
            counts = traffic.style_counts
            self._on_log(
                f'交通流预览已启动：{spawned} 辆车（均衡={counts.balanced}，激进={counts.aggressive}，'
                f'保守={counts.conservative}，迟缓={counts.sluggish}；'
                f'跟驰={traffic.car_following_model}，换道={traffic.lane_change_model}）',
                'INFO',
            )

            last_snapshot = None
            last_scene = None
            last_lights: tuple[TrafficLightSnapshot, ...] = ()
            selected_actor_id: int | None = None
            last_signal_payload: JsonObject | None = None
            while not self._stop_event.is_set():
                deadline = time.monotonic() + PREVIEW_INTERVAL
                ops: list[NativeOp | JsonObject] = (
                    list(
                        manager.step_operations(
                            last_snapshot,
                            last_scene,
                            last_lights,
                            PREVIEW_INTERVAL,
                            selected_actor_id=selected_actor_id,
                        )
                    )
                    if last_snapshot is not None and last_scene is not None
                    else []
                )
                with self._lock:
                    next_mode, self._pending_view_mode = self._pending_view_mode, None
                    next_follow, self._pending_follow_id = self._pending_follow_id, None
                    extra_ops, self._pending_ops = self._pending_ops, []
                if next_mode is not None or next_follow is not None:
                    ops.append(op_update_view(view_mode=next_mode, ego_actor_id=next_follow))
                if extra_ops:
                    ops.extend(extra_ops)
                result = api.exchange(ops, session_id=session_id)
                manager.apply_control_state(result.control_state)
                last_snapshot = result.snapshot
                last_scene = TrafficScene.from_vehicles(result.snapshot.vehicles)
                last_lights = result.traffic_lights
                selected_actor_id = result.selected_actor_id
                signal_payload: JsonObject | None = None
                if result.selected_signal_actor_id is not None:
                    matched = next(
                        (
                            item
                            for item in result.traffic_lights
                            if item.actor_id == result.selected_signal_actor_id
                        ),
                        None,
                    )
                    signal_payload = {
                        'actor_id': result.selected_signal_actor_id,
                        'signal_id': matched.signal_id if matched is not None else '',
                        'state': matched.state.value if matched is not None else 'unknown',
                        'frozen': matched.frozen if matched is not None else False,
                        'group_id': matched.group_id if matched is not None else None,
                    }
                if signal_payload != last_signal_payload:
                    last_signal_payload = signal_payload
                    if self._on_signal is not None:
                        self._on_signal(signal_payload)
                if manager.respawn_lost(
                    api,
                    ego_xy=None,
                    scene=last_scene,
                    default_speed_limit_mps=default_speed_limit_mps,
                ):
                    with self._lock:
                        self._actor_ids = manager.actor_ids
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._stop_event.wait(remaining)
        except Exception as exc:
            self._on_log(f'交通流预览失败：{exc}', 'ERROR')
            self._on_state(False, 0, str(exc), None)
            return
        finally:
            with self._lock:
                self._actor_ids = ()
                self._pending_follow_id = None
                self._pending_ops.clear()
            if self._on_signal is not None:
                self._on_signal(None)
            try:
                if started_view:
                    # 停止预览前先切回自由视角，避免清理车辆期间视角停滞卡住
                    try:
                        api.update_view(view_mode='free')
                    except Exception:
                        pass
                    api.stop_experiment(session_id)
            except Exception as exc:
                self._on_log(f'交通流预览收尾异常：{exc}', 'WARNING')
            finally:
                api.close()
        self._on_state(False, 0, None, None)
        self._on_log('交通流预览已停止并清理车辆', 'INFO')
