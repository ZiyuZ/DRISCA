"""原生环境接口的状态模型、事件载荷与局部球雾配置转换。"""

from typing import Any, Literal

from pydantic import BaseModel

from drisca.core.config import FogRegionConfig, GlobalWeather

EnvironmentOperation = Literal['apply', 'update', 'create', 'delete']


class RegionFogState(BaseModel, frozen=True, extra='forbid'):
    density: float


class RegionWeatherState(BaseModel, frozen=True, extra='forbid'):
    fog: RegionFogState


class EnvironmentRegionState(BaseModel, frozen=True, extra='forbid'):
    """局部球雾实体的当前值或目标值。"""

    center_m: tuple[float, float, float]
    radius_m: float
    weather: RegionWeatherState


class GlobalWeatherState(BaseModel, frozen=True, extra='forbid'):
    """全局环境的当前值或目标值，与局部实体同为实体的外层形状。"""

    weather: GlobalWeather


EnvironmentState = GlobalWeatherState | EnvironmentRegionState


class EnvironmentSnapshot(BaseModel, frozen=True, extra='forbid'):
    """environment.get 的全局返回；global 的 region_id 为 null。"""

    region_id: None = None
    current: GlobalWeatherState
    target: GlobalWeatherState
    remaining_seconds: float
    deleting: bool = False


class RegionSnapshot(BaseModel, frozen=True, extra='forbid'):
    """environment.get/list 的局部返回。"""

    region_id: int
    current: EnvironmentRegionState
    target: EnvironmentRegionState
    remaining_seconds: float
    deleting: bool = False


class EnvironmentList(BaseModel, frozen=True, extra='forbid'):
    regions: tuple[RegionSnapshot, ...]


class EnvironmentAppliedPayload(BaseModel, frozen=True, extra='forbid'):
    region_id: int | None
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: EnvironmentOperation
    previous: EnvironmentState
    transition_seconds: float


class EnvironmentCompletedPayload(BaseModel, frozen=True, extra='forbid'):
    region_id: int | None
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: EnvironmentOperation


class EnvironmentReplacedPayload(BaseModel, frozen=True, extra='forbid'):
    region_id: int | None
    current: EnvironmentState
    target: EnvironmentState
    remaining_seconds: float
    deleting: bool
    operation: EnvironmentOperation
    new_request_id: int | None = None
    new_operation_index: int | None = None
    new_operation: EnvironmentOperation | None = None
    new_target: EnvironmentState | None = None
    reason: str | None = None  # 实验停止时为 session_ended，此时不带 new_* 字段


def region_payload(region: FogRegionConfig) -> dict[str, Any]:
    """把预设中的球雾条目转换为 environment.create 的参数。"""
    return {
        'center_m': list(region.center_m),
        'radius_m': region.radius_m,
        'weather': {'fog': {'density': region.density}},
        'transition_seconds': region.transition_seconds,
    }
