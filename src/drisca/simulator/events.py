"""原生事件到 DRISCA 实验事件的映射。"""

from typing import Any

from drisca.core.protocol import (
    ChangeGearEvent,
    CollisionEvent,
    ControlModeChangedEvent,
    DriverRequestEvent,
    EnvironmentAppliedEvent,
    EnvironmentCompletedEvent,
    EnvironmentReplacedEvent,
    ExperimentEvent,
    LaneInvasionEvent,
    NativeEventRef,
    ToggleHandbrakeEvent,
    ToggleLightEvent,
    ToggleManualGearEvent,
    ToggleReverseEvent,
    ToggleTakeoverEvent,
    TrafficControllerTimingChangedEvent,
    TrafficLightAllFrozenEvent,
    TrafficLightGroupFrozenEvent,
    TrafficLightGroupResetEvent,
    TrafficLightStateChangedEvent,
    UpdateCameraEvent,
    UpdateLayoutEvent,
)

_EVENT_MODELS = {
    'toggle_reverse': ToggleReverseEvent,
    'toggle_manual_gear': ToggleManualGearEvent,
    'change_gear': ChangeGearEvent,
    'toggle_handbrake': ToggleHandbrakeEvent,
    'toggle_light': ToggleLightEvent,
    'update_camera': UpdateCameraEvent,
    'update_layout': UpdateLayoutEvent,
    'environment_applied': EnvironmentAppliedEvent,
    'environment_completed': EnvironmentCompletedEvent,
    'environment_replaced': EnvironmentReplacedEvent,
    'collision': CollisionEvent,
    'lane_invasion': LaneInvasionEvent,
    'toggle_takeover': ToggleTakeoverEvent,
    'driver_request': DriverRequestEvent,
    'control_mode_changed': ControlModeChangedEvent,
    'traffic_light_state_changed': TrafficLightStateChangedEvent,
    'traffic_controller_timing_changed': TrafficControllerTimingChangedEvent,
    'traffic_light_group_frozen': TrafficLightGroupFrozenEvent,
    'traffic_light_group_reset': TrafficLightGroupResetEvent,
    'traffic_light_all_frozen': TrafficLightAllFrozenEvent,
}


def native_event_ref(raw: dict[str, Any]) -> NativeEventRef:
    return NativeEventRef(
        event_id=int(raw['event_id']),
        world_id=int(raw['world_id']),
        simulation_time_us=int(raw['simulation_time_us']),
        request_id=raw.get('request_id'),
        operation_index=raw.get('operation_index'),
    )


def map_event(raw: dict[str, Any], *, command_id: str | None, source: str) -> ExperimentEvent:
    name = str(raw['name'])
    model = _EVENT_MODELS.get(name)
    if model is None:
        raise ValueError(f'未知原生事件：{name}')
    return model.model_validate(
        {
            'source': source,
            'frame_no': int(raw['frame_no']),
            'timestamp': int(raw['wall_time_us']) / 1e6,
            'command_id': command_id,
            'native': native_event_ref(raw).model_dump(mode='json'),
            'payload': raw.get('payload') or {},
        }
    )
