"""驾驶风格预设：用物理控制参数与感知反应延迟刻画异质交通流。"""

import random
from dataclasses import dataclass
from enum import StrEnum


class DrivingStyle(StrEnum):
    BALANCED = 'balanced'
    AGGRESSIVE = 'aggressive'
    CONSERVATIVE = 'conservative'
    SLUGGISH = 'sluggish'
    MIXED = 'mixed'


@dataclass(frozen=True, slots=True)
class DrivingProfile:
    """单车驾驶风格物理参数集合。"""

    name: str
    speed_multiplier: float = 1.0
    # IDM 跟驰参数
    min_gap_m: float = 2.5
    time_headway_s: float = 1.5
    max_accel: float = 2.2
    comfort_decel: float = 2.8
    # 纵向与弯道参数
    max_lateral_accel: float = 2.8
    max_throttle: float = 0.85
    max_brake: float = 0.9
    # 横向响应速率
    max_steer_rate: float = 2.5
    # 换道参数
    lane_change_cooldown_s: float = 4.0
    min_front_gap_m: float = 14.0
    min_rear_gap_m: float = 12.0
    slow_lead_ratio: float = 0.72
    politeness: float = 0.25  # MOBIL 礼让系数
    mobil_threshold: float = 0.2  # MOBIL 最小加速度收益阈值 (m/s^2)
    # Gipps / Krauss 专用参数
    gipps_reaction_s: float = 0.8
    krauss_dawdle: float = 0.18
    # 感知反应延迟 (s)，用于刻画反应迟钝/分心驾驶人
    reaction_delay_s: float = 0.0


BALANCED_PROFILE = DrivingProfile(name='balanced')

AGGRESSIVE_PROFILE = DrivingProfile(
    name='aggressive',
    speed_multiplier=1.15,
    min_gap_m=1.8,
    time_headway_s=0.9,
    max_accel=3.2,
    comfort_decel=3.8,
    max_lateral_accel=3.8,
    max_throttle=0.95,
    max_brake=1.0,
    max_steer_rate=3.4,
    lane_change_cooldown_s=2.0,
    min_front_gap_m=9.5,
    min_rear_gap_m=8.0,
    slow_lead_ratio=0.85,
    politeness=0.05,
    mobil_threshold=0.1,
    gipps_reaction_s=0.55,
    krauss_dawdle=0.08,
    reaction_delay_s=0.0,
)

CONSERVATIVE_PROFILE = DrivingProfile(
    name='conservative',
    speed_multiplier=0.85,
    min_gap_m=3.5,
    time_headway_s=2.4,
    max_accel=1.5,
    comfort_decel=2.0,
    max_lateral_accel=2.0,
    max_throttle=0.72,
    max_brake=0.85,
    max_steer_rate=2.0,
    lane_change_cooldown_s=8.0,
    min_front_gap_m=22.0,
    min_rear_gap_m=18.0,
    slow_lead_ratio=0.60,
    politeness=0.55,
    mobil_threshold=0.35,
    gipps_reaction_s=1.1,
    krauss_dawdle=0.28,
    reaction_delay_s=0.0,
)

SLUGGISH_PROFILE = DrivingProfile(
    name='sluggish',
    speed_multiplier=0.92,
    min_gap_m=3.0,
    time_headway_s=2.0,
    max_accel=1.4,
    comfort_decel=2.2,
    max_lateral_accel=2.3,
    max_throttle=0.75,
    max_brake=0.9,
    max_steer_rate=1.6,
    lane_change_cooldown_s=7.0,
    min_front_gap_m=20.0,
    min_rear_gap_m=16.0,
    slow_lead_ratio=0.62,
    politeness=0.35,
    mobil_threshold=0.3,
    gipps_reaction_s=1.25,
    krauss_dawdle=0.35,
    reaction_delay_s=0.6,
)

BASE_PROFILES: dict[str, DrivingProfile] = {
    DrivingStyle.BALANCED: BALANCED_PROFILE,
    DrivingStyle.AGGRESSIVE: AGGRESSIVE_PROFILE,
    DrivingStyle.CONSERVATIVE: CONSERVATIVE_PROFILE,
    DrivingStyle.SLUGGISH: SLUGGISH_PROFILE,
}

# 混合模式默认比例：50% 均衡、20% 激进、20% 保守、10% 反应迟钝
_MIXED_POOL: tuple[DrivingProfile, ...] = (
    BALANCED_PROFILE,
    AGGRESSIVE_PROFILE,
    CONSERVATIVE_PROFILE,
    SLUGGISH_PROFILE,
)
_MIXED_WEIGHTS: tuple[float, ...] = (0.5, 0.2, 0.2, 0.1)


def resolve_profile(style: str, rng: random.Random | None = None) -> DrivingProfile:
    """根据风格名称解析单车参数；mixed 模式按既定权重随机抽样。"""
    if style == DrivingStyle.MIXED:
        picker = rng if rng is not None else random.Random()
        return picker.choices(_MIXED_POOL, weights=_MIXED_WEIGHTS, k=1)[0]
    profile = BASE_PROFILES.get(style)
    if profile is None:
        raise ValueError(f'未知的驾驶风格：{style}')
    return profile
