"""运行期交通场景事件枚举与强类型 Pydantic 参数模型（供 launcher、protocol、traffic 共享）。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TrafficAction(StrEnum):
    """运行期支持的交通场景与车流调控动作。"""

    LEAD_HARD_BRAKE = 'lead_hard_brake'
    ADJACENT_CUT_IN = 'adjacent_cut_in'
    REAR_OVERTAKE = 'rear_overtake'
    LEAD_BREAKDOWN = 'lead_breakdown'
    AHEAD_SIGNAL_CHANGE = 'ahead_signal_change'
    DUAL_LANE_SLOWDOWN = 'dual_lane_slowdown'
    RED_LIGHT_RUNNER = 'red_light_runner'
    SET_TRAFFIC_COUNT = 'set_traffic_count'


class LaneSide(StrEnum):
    """相邻同向车道选择方向。"""

    ANY = 'any'
    LEFT = 'left'
    RIGHT = 'right'
    PREFER_RIGHT = 'prefer_right'


class CutInMode(StrEnum):
    REUSE_ADJACENT = 'reuse_adjacent'
    SPAWN_CUT_IN = 'spawn_cut_in'


class OvertakeMode(StrEnum):
    REUSE_REAR = 'reuse_rear'
    SPAWN_REAR = 'spawn_rear'


class BreakdownMode(StrEnum):
    REUSE_LEAD = 'reuse_lead'
    SPAWN_FAR = 'spawn_far'


class SignalTargetState(StrEnum):
    YELLOW = 'yellow'
    RED = 'red'
    GREEN = 'green'


class LeadHardBrakeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=60.0, gt=0, le=300)
    duration_s: float = Field(default=2.5, gt=0, le=30)
    brake_intensity: float = Field(default=0.95, ge=0.1, le=1.0)


class AdjacentCutInParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: CutInMode = CutInMode.REUSE_ADJACENT
    side: LaneSide = LaneSide.ANY
    min_front_m: float = Field(default=3.5, ge=-20, le=100)
    max_front_m: float = Field(default=28.0, gt=0, le=200)
    spawn_distance_m: float = Field(default=45.0, ge=10, le=200)
    trigger_distance_m: float = Field(default=14.0, ge=4, le=80)


class RearOvertakeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: OvertakeMode = OvertakeMode.REUSE_REAR
    side: LaneSide = LaneSide.ANY
    rear_distance_m: float = Field(default=22.0, ge=6, le=120)
    extra_speed_mps: float = Field(default=8.0, ge=2.0, le=30.0)
    clear_front_m: float = Field(default=18.0, ge=8, le=60)
    return_to_lane: bool = True


class LeadBreakdownParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    mode: BreakdownMode = BreakdownMode.REUSE_LEAD
    distance_m: float = Field(default=130.0, ge=15, le=350)
    speed_factor: float = Field(default=0.0, ge=0.0, le=1.2)


class AheadSignalChangeParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    target_state: SignalTargetState = SignalTargetState.YELLOW
    max_distance_m: float = Field(default=120.0, ge=10, le=300)


class DualLaneSlowdownParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=100.0, ge=15, le=250)
    speed_factor: float = Field(default=0.45, ge=0.1, le=0.9)
    duration_s: float = Field(default=10.0, ge=2.0, le=60.0)


class RedLightRunnerParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_distance_m: float = Field(default=120.0, ge=15, le=250)
    duration_s: float = Field(default=8.0, ge=2.0, le=30.0)


class SetTrafficCountParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    target_count: int = Field(default=10, ge=0, le=100)


type TrafficActionParams = (
    LeadHardBrakeParams
    | AdjacentCutInParams
    | RearOvertakeParams
    | LeadBreakdownParams
    | AheadSignalChangeParams
    | DualLaneSlowdownParams
    | RedLightRunnerParams
    | SetTrafficCountParams
)
