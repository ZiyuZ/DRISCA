"""管理端 HTTP 接口请求模型。"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drisca.core.config import RunSettings, WeatherConfig


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset_name: str
    run: RunSettings


class MapRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    map_name: str


class CarlaStartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['editor', 'packaged'] | None = None


class ViewModeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['free', 'cockpit', 'chase']


class PreviewFollowRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    delta: Literal[-1, 1] = 1


class TrafficLightStateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: Literal['red', 'yellow', 'green', 'off']


class TrafficLightFreezeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    frozen: bool


class MarkerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str


class SessionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_ids: list[str]


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    start_time: float = 0.0
    duration: float = 0.0
    time_factor: float = 1.0
    follow_actor_id: int = 0
    follow_ego: bool = False


class ReplayFollowRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: Literal['free', 'hero', 'prev', 'next']


class RecorderInfoRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str


def _finite_non_negative(value: float, label: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{label}必须是非负有限数值')
    return value


class WeatherApplyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    weather: WeatherConfig
    transition_seconds: float = Field(default=0.0, ge=0)

    @field_validator('transition_seconds')
    @classmethod
    def check_transition(cls, value: float) -> float:
        return _finite_non_negative(value, '渐变时长')


class FogRegionCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    center_m: tuple[float, float, float]
    radius_m: float = Field(gt=0, le=100_000)
    density: float = Field(default=0.0, ge=0, le=1)
    transition_seconds: float = Field(default=0.0, ge=0)

    @field_validator('center_m')
    @classmethod
    def check_center(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(item) for item in value):
            raise ValueError('局部球雾中心坐标必须是有限数值')
        return value

    @field_validator('transition_seconds')
    @classmethod
    def check_transition(cls, value: float) -> float:
        return _finite_non_negative(value, '渐变时长')


class FogRegionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    center_m: tuple[float, float, float] | None = None
    radius_m: float | None = Field(default=None, gt=0, le=100_000)
    density: float | None = Field(default=None, ge=0, le=1)
    transition_seconds: float = Field(default=0.0, ge=0)

    @field_validator('center_m')
    @classmethod
    def check_center(cls, value: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
        if value is not None and not all(math.isfinite(item) for item in value):
            raise ValueError('局部球雾中心坐标必须是有限数值')
        return value

    @field_validator('transition_seconds')
    @classmethod
    def check_transition(cls, value: float) -> float:
        return _finite_non_negative(value, '渐变时长')

    @model_validator(mode='after')
    def require_change(self) -> FogRegionUpdateRequest:
        if self.center_m is None and self.radius_m is None and self.density is None:
            raise ValueError('局部球雾更新至少需要一个待修改字段')
        return self
