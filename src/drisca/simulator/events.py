"""原生事件到 DRISCA 实验事件的映射。"""

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
    UpdateViewModeEvent,
)
from drisca.core.types import JsonObject, as_int

_EVENT_MODELS = {
    'toggle_reverse': ToggleReverseEvent,
    'toggle_manual_gear': ToggleManualGearEvent,
    'change_gear': ChangeGearEvent,
    'toggle_handbrake': ToggleHandbrakeEvent,
    'toggle_light': ToggleLightEvent,
    'update_camera': UpdateCameraEvent,
    'update_layout': UpdateLayoutEvent,
    'update_view_mode': UpdateViewModeEvent,
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


def native_event_ref(raw: JsonObject) -> NativeEventRef:
    raw_req = raw.get('request_id')
    raw_op = raw.get('operation_index')
    return NativeEventRef(
        event_id=as_int(raw.get('event_id')),
        world_id=as_int(raw.get('world_id')),
        simulation_time_us=as_int(raw.get('simulation_time_us')),
        request_id=as_int(raw_req) if raw_req is not None else None,
        operation_index=as_int(raw_op) if raw_op is not None else None,
    )


def map_event(raw: JsonObject, *, command_id: str | None, source: str) -> ExperimentEvent:
    name = str(raw['name'])
    model = _EVENT_MODELS.get(name)
    if model is None:
        raise ValueError(f'未知原生事件：{name}')
    return model.model_validate(
        {
            'source': source,
            'frame_no': as_int(raw.get('frame_no')),
            'timestamp': as_int(raw.get('wall_time_us')) / 1e6,
            'command_id': command_id,
            'native': native_event_ref(raw).model_dump(mode='json'),
            'payload': raw.get('payload') or {},
        }
    )
