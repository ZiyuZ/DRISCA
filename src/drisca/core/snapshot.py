"""原生 API 二进制快照解码。

一条快照消息由 48 字节头、N 条 96 字节车辆记录和 M 条 128 字节研究记录组成，
N 与 M 由头部给出，M 为 0 或 1。所有物理量是小端 float32，时间是小端 int64 微秒。
研究记录的 8 字节字段位于非 8 字节对齐偏移，因此用显式偏移 dtype 解释。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

HEADER_BYTES: Final = 48
VEHICLE_RECORD_BYTES: Final = 96
RESEARCH_RECORD_BYTES: Final = 128

HEADER_DTYPE: Final = np.dtype(
    [
        ('request_id', '<u4'),
        ('vehicle_count', '<u4'),
        ('world_id', '<u8'),
        ('frame_no', '<u8'),
        ('simulation_time_us', '<i8'),
        ('wall_time_us', '<i8'),
        ('delta_seconds', '<f4'),
        ('research_count', '<u4'),
    ]
)

VEHICLE_DTYPE: Final = np.dtype(
    [
        ('actor_id', '<u4'),
        ('flags', '<u4'),
        ('location', '<f4', (3,)),
        ('rotation', '<f4', (3,)),
        ('velocity', '<f4', (3,)),
        ('angular_velocity', '<f4', (3,)),
        ('acceleration', '<f4', (3,)),
        ('throttle', '<f4'),
        ('steer', '<f4'),
        ('brake', '<f4'),
        ('gear', '<i4'),
        ('speed_limit_mps', '<f4'),
        ('road_id', '<i4'),
        ('lane_id', '<i4'),
    ]
)

RESEARCH_DTYPE: Final = np.dtype(
    {
        'names': [
            'actor_id',
            'validity_flags',
            'input_throttle',
            'input_steer',
            'input_brake',
            'input_flags',
            'input_gear',
            'imu_frame_no',
            'imu_simulation_time_us',
            'gnss_frame_no',
            'gnss_simulation_time_us',
            'accelerometer',
            'gyroscope',
            'compass',
            'longitude',
            'latitude',
            'altitude',
            'road_direction',
            'lane_width',
            'lane_offset',
            'lane_type',
            'collision_intensity',
        ],
        'formats': [
            '<u4',
            '<u4',
            '<f4',
            '<f4',
            '<f4',
            '<u4',
            '<i4',
            '<u8',
            '<i8',
            '<u8',
            '<i8',
            ('<f4', (3,)),
            ('<f4', (3,)),
            '<f4',
            '<f4',
            '<f4',
            '<f4',
            ('<f4', (3,)),
            '<f4',
            '<f4',
            '<u4',
            '<f4',
        ],
        'offsets': [
            0,
            4,
            8,
            12,
            16,
            20,
            24,
            28,
            36,
            44,
            52,
            60,
            72,
            84,
            88,
            92,
            96,
            100,
            112,
            116,
            120,
            124,
        ],
        'itemsize': RESEARCH_RECORD_BYTES,
    }
)

VEHICLE_FLAG_REVERSE: Final = 1 << 0
VEHICLE_FLAG_HAND_BRAKE: Final = 1 << 1
VEHICLE_FLAG_MANUAL_GEAR_SHIFT: Final = 1 << 2
VEHICLE_FLAG_DORMANT: Final = 1 << 3
VEHICLE_FLAG_ROAD_VALID: Final = 1 << 4
VEHICLE_CONTROL_SOURCE_SHIFT: Final = 8
VEHICLE_CONTROL_SOURCE_MASK: Final = 0b11 << VEHICLE_CONTROL_SOURCE_SHIFT

CONTROL_SOURCE_MANUAL_HUMAN: Final = 0
CONTROL_SOURCE_TRAFFIC_MANAGER: Final = 1
CONTROL_SOURCE_EXTERNAL_PYTHON: Final = 2
CONTROL_SOURCE_EXTERNAL_UNASSIGNED: Final = 3

CONTROL_SOURCE_NAMES: Final[dict[int, str]] = {
    CONTROL_SOURCE_MANUAL_HUMAN: 'manual-human',
    CONTROL_SOURCE_TRAFFIC_MANAGER: 'traffic-manager',
    CONTROL_SOURCE_EXTERNAL_PYTHON: 'external-python',
    CONTROL_SOURCE_EXTERNAL_UNASSIGNED: 'external-unassigned',
}

RESEARCH_VALID_IMU: Final = 1 << 0
RESEARCH_VALID_GNSS: Final = 1 << 1
RESEARCH_VALID_ROAD: Final = 1 << 2
RESEARCH_VALID_VIEW_ACTIVE: Final = 1 << 3
RESEARCH_VALID_READY: Final = 1 << 4

INPUT_FLAG_REVERSE: Final = 1 << 0
INPUT_FLAG_HAND_BRAKE: Final = 1 << 1
INPUT_FLAG_MANUAL_GEAR_SHIFT: Final = 1 << 2
INPUT_FLAG_TAKEOVER: Final = 1 << 3

LANE_TYPE_NAMES: Final[dict[int, str]] = {
    1: 'NONE',
    2: 'Driving',
    4: 'Stop',
    8: 'Shoulder',
    16: 'Biking',
    32: 'Sidewalk',
    64: 'Border',
    128: 'Restricted',
    256: 'Parking',
    512: 'Bidirectional',
    1024: 'Median',
    2048: 'Special1',
    4096: 'Special2',
    8192: 'Special3',
    16384: 'RoadWorks',
    32768: 'Tram',
    65536: 'Rail',
    131072: 'Entry',
    262144: 'Exit',
    524288: 'OffRamp',
    1048576: 'OnRamp',
    4294967294: 'Any',
}

VEHICLE_FLOAT_FIELDS: Final = (
    'location',
    'rotation',
    'velocity',
    'angular_velocity',
    'acceleration',
    'throttle',
    'steer',
    'brake',
    'speed_limit_mps',
)

RESEARCH_FLOAT_FIELDS: Final = (
    'input_throttle',
    'input_steer',
    'input_brake',
    'accelerometer',
    'gyroscope',
    'compass',
    'longitude',
    'latitude',
    'altitude',
    'road_direction',
    'lane_width',
    'lane_offset',
    'collision_intensity',
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """一条完整快照，数组是与消息字节共享内存的只读视图。"""

    request_id: int
    world_id: int
    frame_no: int
    simulation_time_us: int
    wall_time_us: int
    delta_seconds: float
    vehicles: np.ndarray
    research: np.ndarray

    def vehicle_index(self, actor_id: int) -> int | None:
        matches = np.flatnonzero(self.vehicles['actor_id'] == actor_id)
        return int(matches[0]) if matches.size else None

    @property
    def research_record(self) -> np.void | None:
        return None if self.research.size == 0 else self.research[0]


def decode_snapshot(data: bytes) -> Snapshot:
    if len(data) < HEADER_BYTES:
        raise ValueError(f'快照长度 {len(data)} 小于头部 {HEADER_BYTES} 字节')
    header = np.frombuffer(data, dtype=HEADER_DTYPE, count=1)[0]
    vehicle_count = int(header['vehicle_count'])
    research_count = int(header['research_count'])
    if research_count > 1:
        raise ValueError(f'研究记录数量 {research_count} 超过 1')
    expected = HEADER_BYTES + vehicle_count * VEHICLE_RECORD_BYTES + research_count * RESEARCH_RECORD_BYTES
    if len(data) != expected:
        raise ValueError(
            f'快照长度 {len(data)} 与头部计数不符，车辆 {vehicle_count} 条、研究 {research_count} 条，'
            f'期望 {expected} 字节'
        )
    vehicles = np.frombuffer(data, dtype=VEHICLE_DTYPE, count=vehicle_count, offset=HEADER_BYTES)
    research = np.frombuffer(
        data,
        dtype=RESEARCH_DTYPE,
        count=research_count,
        offset=HEADER_BYTES + vehicle_count * VEHICLE_RECORD_BYTES,
    )
    return Snapshot(
        request_id=int(header['request_id']),
        world_id=int(header['world_id']),
        frame_no=int(header['frame_no']),
        simulation_time_us=int(header['simulation_time_us']),
        wall_time_us=int(header['wall_time_us']),
        delta_seconds=float(header['delta_seconds']),
        vehicles=vehicles,
        research=research,
    )


def control_source(flags: int) -> int:
    return (flags & VEHICLE_CONTROL_SOURCE_MASK) >> VEHICLE_CONTROL_SOURCE_SHIFT


def control_source_name(source: int) -> str:
    name = CONTROL_SOURCE_NAMES.get(source)
    if name is None:
        raise ValueError(f'未知控制来源 {source}')
    return name


def lane_type_name(value: int) -> str:
    name = LANE_TYPE_NAMES.get(value)
    if name is None:
        raise ValueError(f'未知车道类型 {value}')
    return name


def require_finite(record: np.void, fields: Sequence[str], label: str) -> None:
    for name in fields:
        if not np.all(np.isfinite(record[name])):
            raise ValueError(f'{label}的 {name} 包含非有限数值')
