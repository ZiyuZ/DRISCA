"""实验配置模型。"""

import json
import math
import shutil
import tomllib
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

import tomli_w
from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator

from drisca.core.paths import CONFIG_FILE, CONTROL_FILE, PRESETS_DIR, RUN_CONFIG_DIR, resolve_db_path


class SpawnPoint(BaseModel, frozen=True, extra='forbid'):
    """地图中的固定出生位置，单位 m 与 deg"""

    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float


class CameraConfig(BaseModel, frozen=True, extra='forbid'):
    """单路相机的安装与视野配置"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    fov: float = Field(default=100.0, gt=0, lt=180)


class CameraViewportConfig(BaseModel, frozen=True, extra='forbid'):
    screen_position: tuple[float, float]
    image_size: tuple[int, int]

    @field_validator('screen_position')
    @classmethod
    def validate_screen_position(cls, value: tuple[float, float]) -> tuple[float, float]:
        if any(not 0 <= coordinate <= 1 for coordinate in value):
            raise ValueError('画面位置必须在 0 到 1 之间')
        return value

    @field_validator('image_size')
    @classmethod
    def validate_image_size(cls, value: tuple[int, int]) -> tuple[int, int]:
        if any(size <= 0 for size in value):
            raise ValueError('画面尺寸必须为正数')
        return value


class DisplayLayoutConfig(BaseModel, frozen=True, extra='forbid'):
    show_rearview: bool = True
    border_width: int = Field(default=0, ge=0, le=32, description='后视镜边框宽度（视口像素，0 表示不画）')
    border_color: str = Field(default='#000000', description='后视镜边框颜色 #RRGGBB 或 #RRGGBBAA')

    @field_validator('border_color')
    @classmethod
    def validate_border_color(cls, value: str) -> str:
        text = value.strip().upper()
        if len(text) not in (7, 9) or not text.startswith('#'):
            raise ValueError('边框颜色必须是 #RRGGBB 或 #RRGGBBAA')
        if any(character not in '0123456789ABCDEF' for character in text[1:]):
            raise ValueError('边框颜色只能包含十六进制字符')
        return text

    rear_top: CameraViewportConfig = CameraViewportConfig(screen_position=(0.5, 0.1), image_size=(320, 150))
    rear_left: CameraViewportConfig = CameraViewportConfig(screen_position=(0.12, 0.9), image_size=(320, 150))
    rear_right: CameraViewportConfig = CameraViewportConfig(
        screen_position=(0.88, 0.9), image_size=(320, 150)
    )


class CameraRigConfig(BaseModel, frozen=True, extra='forbid'):
    """主车四路相机组合配置（固定使用 sensor.camera.rgb）"""

    front: CameraConfig = CameraConfig(
        x=0.5,
        y=-0.35,
        z=0.8,
        pitch=5.8,
        fov=120.0,
    )
    rear_top: CameraConfig = CameraConfig(
        x=0.34,
        y=0.0,
        z=0.7,
        pitch=5.8,
        yaw=180.0,
        fov=100.0,
    )
    rear_left: CameraConfig = CameraConfig(
        x=0.4,
        y=-0.93,
        z=0.5,
        pitch=5.8,
        yaw=180.0,
        fov=100.0,
    )
    rear_right: CameraConfig = CameraConfig(
        x=0.4,
        y=0.93,
        z=0.5,
        pitch=5.8,
        yaw=180.0,
        fov=100.0,
    )


class CarlaConnectionConfig(BaseModel, frozen=True, extra='forbid'):
    """CARLA 服务端参数，仅用于启动 Unreal 的 RPC 与流传输端口。"""

    host: str = '127.0.0.1'
    port: int = Field(default=2000, gt=1024, le=65535)


class DrivingViewConfig(BaseModel, frozen=True, extra='forbid'):
    """Unreal 原生 WebSocket API 与驾驶视图的监听地址。"""

    host: str = '127.0.0.1'
    port: int = Field(default=7910, gt=1024, le=65535)
    timeout: float = Field(default=5.0, gt=0)


class DisplayConfig(BaseModel, frozen=True, extra='forbid'):
    layout: DisplayLayoutConfig = DisplayLayoutConfig()
    position: tuple[int, int] = (0, 0)
    resolution: tuple[int, int] = (1600, 900)  # 宽度建议为 64 的倍数以避免 CARLA 相机画面撕裂
    fullscreen: bool = False
    borderless: bool = False
    target_fps: int = Field(default=60, gt=0)

    @field_validator('resolution')
    @classmethod
    def validate_resolution(cls, value: tuple[int, int]) -> tuple[int, int]:
        if any(size <= 0 for size in value):
            raise ValueError('显示分辨率必须为正数')
        return value


class ServiceConfig(BaseModel, frozen=True, extra='forbid'):
    launcher_host: str = '0.0.0.0'  # 监听局域网以便平板连接
    launcher_port: int = Field(default=7900, ge=1, le=65535)
    enable_tts: bool = True  # 由 launcher 托管的语音播报开关
    debug: bool = False


class CarlaRuntimeConfig(BaseModel, frozen=True, extra='forbid'):
    kind: Literal['editor', 'packaged'] = 'editor'
    editor_executable: str = ''
    project: str = ''
    packaged_executable: str = ''
    quality: Literal['Low', 'Medium', 'High', 'Epic'] = 'Medium'
    startup_timeout: float = Field(default=120.0, gt=0)


class MachineConfig(BaseModel, frozen=True, extra='forbid'):
    carla: CarlaConnectionConfig = CarlaConnectionConfig()
    driving_view: DrivingViewConfig = DrivingViewConfig()
    carla_runtime: CarlaRuntimeConfig = CarlaRuntimeConfig()
    display: DisplayConfig = DisplayConfig()
    service: ServiceConfig = ServiceConfig()
    db_path: str = 'data/experiments.sqlite3'
    recorder_dir: str = 'data/recordings'
    export_dir: str = 'data/exports'


class KeyboardKey(StrEnum):
    UNBOUND = 'unbound'
    ESCAPE = 'escape'
    P = 'p'
    BACKSLASH = 'backslash'
    Q = 'q'
    M = 'm'
    PERIOD = 'period'
    COMMA = 'comma'
    SPACE = 'space'
    SEMICOLON = 'semicolon'
    K = 'k'
    L = 'l'
    Z = 'z'
    X = 'x'
    I = 'i'  # noqa: E741
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'
    W = 'w'
    S = 's'
    A = 'a'
    D = 'd'
    KEYPAD_1 = 'keypad_1'
    KEYPAD_2 = 'keypad_2'


class WheelButton(StrEnum):
    UNBOUND = 'unbound'
    CROSS = 'cross'
    SQUARE = 'square'
    CIRCLE = 'circle'
    TRIANGLE = 'triangle'
    RIGHT_PADDLE = 'right_paddle'
    LEFT_PADDLE = 'left_paddle'
    R2 = 'r2'
    L2 = 'l2'
    SHARE = 'share'
    OPTIONS = 'options'
    R3 = 'r3'
    L3 = 'l3'
    PLUS = 'plus'
    MINUS = 'minus'
    DIAL_RIGHT = 'dial_right'
    DIAL_LEFT = 'dial_left'
    DIAL_PRESS = 'dial_press'
    LOGO = 'logo'


KEYBOARD_KEY_LABELS: dict[KeyboardKey, str] = {
    KeyboardKey.UNBOUND: '未绑定',
    KeyboardKey.ESCAPE: 'Esc',
    KeyboardKey.P: 'P',
    KeyboardKey.BACKSLASH: '反斜杠',
    KeyboardKey.Q: 'Q',
    KeyboardKey.M: 'M',
    KeyboardKey.PERIOD: '句号',
    KeyboardKey.COMMA: '逗号',
    KeyboardKey.SPACE: '空格',
    KeyboardKey.SEMICOLON: '分号',
    KeyboardKey.K: 'K',
    KeyboardKey.L: 'L',
    KeyboardKey.Z: 'Z',
    KeyboardKey.X: 'X',
    KeyboardKey.I: 'I',
    KeyboardKey.UP: '上',
    KeyboardKey.DOWN: '下',
    KeyboardKey.LEFT: '左',
    KeyboardKey.RIGHT: '右',
    KeyboardKey.W: 'W',
    KeyboardKey.S: 'S',
    KeyboardKey.A: 'A',
    KeyboardKey.D: 'D',
    KeyboardKey.KEYPAD_1: '小键盘 1',
    KeyboardKey.KEYPAD_2: '小键盘 2',
}

WHEEL_BUTTON_LABELS: dict[WheelButton, str] = {
    WheelButton.UNBOUND: '未绑定',
    WheelButton.CROSS: 'X 键 (Cross)',
    WheelButton.SQUARE: '方块键 (Square)',
    WheelButton.CIRCLE: '圆圈键 (Circle)',
    WheelButton.TRIANGLE: '三角键 (Triangle)',
    WheelButton.RIGHT_PADDLE: '右换挡拨片 (R1)',
    WheelButton.LEFT_PADDLE: '左换挡拨片 (L1)',
    WheelButton.R2: 'R2 键',
    WheelButton.L2: 'L2 键',
    WheelButton.SHARE: 'Share 键',
    WheelButton.OPTIONS: 'Options 键',
    WheelButton.R3: 'R3 键',
    WheelButton.L3: 'L3 键',
    WheelButton.PLUS: '加号键 (+)',
    WheelButton.MINUS: '减号键 (-)',
    WheelButton.DIAL_RIGHT: '红旋钮右旋',
    WheelButton.DIAL_LEFT: '红旋钮左旋',
    WheelButton.DIAL_PRESS: '红旋钮确认键 (Enter)',
    WheelButton.LOGO: 'PS / Logo 键',
}


class KeyboardControlConfig(BaseModel, frozen=True, extra='forbid'):
    """键盘动作与按键名称。"""

    quit: KeyboardKey = KeyboardKey.ESCAPE
    toggle_autopilot: KeyboardKey = KeyboardKey.P
    takeover: KeyboardKey = KeyboardKey.BACKSLASH
    toggle_reverse: KeyboardKey = KeyboardKey.Q
    toggle_manual_transmission: KeyboardKey = KeyboardKey.M
    gear_up: KeyboardKey = KeyboardKey.PERIOD
    gear_down: KeyboardKey = KeyboardKey.COMMA
    toggle_handbrake: KeyboardKey = KeyboardKey.SPACE
    toggle_light_double_blinker: KeyboardKey = KeyboardKey.SEMICOLON
    toggle_light_low_beam: KeyboardKey = KeyboardKey.K
    toggle_light_high_beam: KeyboardKey = KeyboardKey.L
    toggle_light_left_blinker: KeyboardKey = KeyboardKey.Z
    toggle_light_right_blinker: KeyboardKey = KeyboardKey.X
    toggle_light_interior: KeyboardKey = KeyboardKey.I
    drive_forward: KeyboardKey = KeyboardKey.UP
    drive_backward: KeyboardKey = KeyboardKey.DOWN
    drive_left: KeyboardKey = KeyboardKey.LEFT
    drive_right: KeyboardKey = KeyboardKey.RIGHT


class WheelControlConfig(BaseModel, frozen=True, extra='forbid'):
    """方向盘硬件开关与按钮绑定。"""

    enable_wheel: bool = True
    show_button_key: bool = False
    autopilot_wheel_sync: bool = False  # 自动驾驶方向盘随动，后续实现
    device_index: int = 0
    toggle_autopilot: WheelButton = WheelButton.DIAL_PRESS
    takeover: WheelButton = WheelButton.CROSS
    toggle_reverse: WheelButton = WheelButton.LEFT_PADDLE
    toggle_handbrake: WheelButton = WheelButton.RIGHT_PADDLE
    toggle_light_left_blinker: WheelButton = WheelButton.L2
    toggle_light_right_blinker: WheelButton = WheelButton.R2
    toggle_light_double_blinker: WheelButton = WheelButton.TRIANGLE


class ControlConfig(BaseModel, frozen=True, extra='forbid'):
    keyboard: KeyboardControlConfig = KeyboardControlConfig()
    wheel: WheelControlConfig = WheelControlConfig()


class SunConfig(BaseModel, frozen=True, extra='forbid'):
    """太阳方位与高度，单位度。"""

    azimuth_deg: float = Field(default=0.0, ge=0, lt=360)
    elevation_deg: float = Field(default=75.0, ge=-90, le=90)


class PrecipitationConfig(BaseModel, frozen=True, extra='forbid'):
    rain: float = Field(default=0.0, ge=0, le=1)
    snow: float = Field(default=0.0, ge=0, le=1)

    @field_validator('snow')
    @classmethod
    def validate_snow(cls, value: float) -> float:
        if value != 0:
            raise ValueError('原生尚未提供雪效资源，snow 只能为 0')
        return value


class SurfaceConfig(BaseModel, frozen=True, extra='forbid'):
    wetness: float = Field(default=0.0, ge=0, le=1)
    puddles: float = Field(default=0.0, ge=0, le=1)


class FogConfig(BaseModel, frozen=True, extra='forbid'):
    density: float = Field(default=0.0, ge=0)  # UE 高度雾密度；不设硬上限，超过 20 记警告
    distance_m: float = Field(default=0.0, ge=0, le=1_000_000)
    height_falloff: float = Field(default=0.2, ge=0, le=10_000)

    @field_validator('density')
    @classmethod
    def _warn_extreme_density(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError('雾密度必须是有限数值')
        if value > 20.0:
            from loguru import logger

            logger.warning(f'全局雾密度 {value:g} 超过建议上限 20，可能导致车内出现雾效')
        return value


class ScatteringConfig(BaseModel, frozen=True, extra='forbid'):
    light: float = Field(default=1.0, ge=0, le=1000)
    mie: float = Field(default=0.003996, ge=0, le=1000)
    rayleigh: float = Field(default=0.0331, ge=0, le=1000)


class GlobalWeather(BaseModel, frozen=True, extra='forbid'):
    """全局环境状态。云雨等强度为 0 到 1，雾密度使用 UE 原始参数。"""

    sun: SunConfig = SunConfig()
    cloudiness: float = Field(default=0.0, ge=0, le=1)
    wind: float = Field(default=0.0, ge=0, le=1)
    dust: float = Field(default=0.0, ge=0, le=1)
    precipitation: PrecipitationConfig = PrecipitationConfig()
    surface: SurfaceConfig = SurfaceConfig()
    fog: FogConfig = FogConfig()
    scattering: ScatteringConfig = ScatteringConfig()


class WeatherConfig(GlobalWeather, frozen=True, extra='forbid'):
    preset_name: str = 'Default'  # 命名预设启动前展开为完整值；'Custom' 使用本对象中的数值


class FogRegionConfig(BaseModel, frozen=True, extra='forbid'):
    """固定世界空间的球形局部雾，由 worker 在实验启动前创建。"""

    center_m: tuple[float, float, float]
    radius_m: float = Field(gt=0, le=100_000)
    density: float = Field(default=0.0, ge=0, le=1)
    transition_seconds: float = Field(default=0.0, ge=0)

    @field_validator('center_m')
    @classmethod
    def validate_center_m(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(not math.isfinite(item) for item in value):
            raise ValueError('球雾中心必须是有限数值')
        return value

    @field_validator('transition_seconds')
    @classmethod
    def validate_transition_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError('球雾渐入时长必须是有限数值')
        return value


class WorldConfig(BaseModel, frozen=True, extra='forbid'):
    map_name: str = 'Town10HD_Opt'
    load_map: bool = False
    sync_mode: bool = True
    simulation_fps: int = Field(default=60, gt=0)
    weather: WeatherConfig = WeatherConfig()
    fog_regions: tuple[FogRegionConfig, ...] = ()


class EgoVehicleConfig(BaseModel, frozen=True, extra='forbid'):
    role_name: str = 'hero'
    blueprint: str = ''  # 从已连接 CARLA 的车辆列表选择
    spawn_point: SpawnPoint  # 预设指定的地图出生位姿
    spawn_map: str = ''  # 出生点所属地图；为空或与目标地图不一致时视为未选择
    default_speed_limit: float = Field(default=33.33, ge=0)
    dynamic_speed_limit: bool = False  # 开启时使用车辆记录的限速（原生已换算为 m/s），手动主车为 0
    init_autopilot: bool = False  # 开启后在实验就绪时切入自研自动驾驶


class TrafficStyleCounts(BaseModel, frozen=True, extra='forbid'):
    """按驾驶风格划分的背景车数量。"""

    balanced: int = Field(default=0, ge=0, le=100)
    aggressive: int = Field(default=0, ge=0, le=100)
    conservative: int = Field(default=0, ge=0, le=100)
    sluggish: int = Field(default=0, ge=0, le=100)

    @property
    def total(self) -> int:
        return self.balanced + self.aggressive + self.conservative + self.sluggish


class TrafficConfig(BaseModel, frozen=True, extra='forbid'):
    """背景交通流配置，保存于实验预设的 [traffic] 节。"""

    enabled: bool = False
    style_counts: TrafficStyleCounts = TrafficStyleCounts()
    seed: int = 42
    speed_factor: float = Field(default=1.0, ge=0.3, le=1.5)
    diversity: float = Field(default=0.12, ge=0.0, le=0.35)  # 同风格车辆的个体参数随机离散度
    enable_lane_change: bool = True
    car_following_model: Literal['idm', 'gipps', 'krauss'] = 'idm'
    lane_change_model: Literal['gap', 'mobil'] = 'gap'

    @property
    def vehicle_count(self) -> int:
        return self.style_counts.total

    @model_validator(mode='after')
    def _validate_total_vehicles(self) -> TrafficConfig:
        if self.vehicle_count > 100:
            raise ValueError(f'背景车总数不能超过 100 辆（当前 {self.vehicle_count} 辆）')
        return self


class ExperimentInstructionConfig(BaseModel, frozen=True, extra='forbid'):
    id: str
    name: str
    command: str
    params: dict[str, JsonValue]


class PresetConfig(BaseModel, frozen=True, extra='forbid'):
    world: WorldConfig = WorldConfig()
    ego: EgoVehicleConfig
    traffic: TrafficConfig = TrafficConfig()
    cameras: CameraRigConfig = CameraRigConfig()
    instructions: tuple[ExperimentInstructionConfig, ...] = ()
    markers: tuple[str, ...] = ('进入路段', '离开路段', '任务完成', '异常情况')


class RunSettings(BaseModel, frozen=True, extra='forbid'):
    """实验设置：每次实验启动时在 launcher 实验控制台中填写，随会话保存。
    与预设合并得到本次实验的设置，最终随 RunConfig 一起写入会话。"""

    subject_id: str = ''  # 被试编号
    note: str = ''  # 本次实验备注
    save_data: bool = True  # 本次运行唯一的实验数据保存总开关
    enable_carla_recorder: bool = False  # 本次是否启用 CARLA Recorder，受 save_data 控制


class RunConfig(BaseModel, frozen=True, extra='forbid'):
    """实验启动时由 launcher 合成并写入 .cache/run/<session_id>.json 的不可变配置。
    由机器配置、控制配置、预设与实验设置四部分组成，运行期间的调整保存在运行状态中。"""

    session_id: str
    db_path: str | None  # 开启保存时使用的数据库绝对路径，调试运行时为空
    launcher_ws_url: str  # launcher 生成的本机回连地址
    machine: MachineConfig
    control: ControlConfig
    preset: PresetConfig
    run: RunSettings


def compose_run_config(
    machine: MachineConfig,
    control: ControlConfig,
    preset: PresetConfig,
    run: RunSettings,
    weather_presets: dict[str, WeatherConfig],
) -> RunConfig:
    from .weather import resolve_weather

    weather = resolve_weather(preset.world.weather, weather_presets)
    if weather is not preset.world.weather:
        preset = preset.model_copy(update={'world': preset.world.model_copy(update={'weather': weather})})
    return RunConfig(
        session_id=f'{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}',
        db_path=str(resolve_db_path(machine.db_path)) if run.save_data else None,
        launcher_ws_url=f'ws://127.0.0.1:{machine.service.launcher_port}/ws/worker/simulator',
        machine=machine,
        control=control,
        preset=preset,
        run=run,
    )


def _load(path: Path, model: type[BaseModel]) -> BaseModel:
    try:
        with path.open('rb') as stream:
            data = tomllib.load(stream)
        return model.model_validate(data)
    except (ValueError, OSError) as exc:
        raise ValueError(f'读取配置 {path} 失败：{exc}') from exc


def _preset_toml(preset: PresetConfig) -> str:
    """天气短分组使用内联表，主要配置保留独立节。"""
    data = preset.model_dump(mode='json', exclude_none=True)
    world = data.pop('world')
    weather = world.pop('weather')
    prefix = {'markers': data.pop('markers'), 'instructions': data.pop('instructions'), 'world': world}
    text = tomli_w.dumps(prefix) + '\n[world.weather]\n'
    for name, value in weather.items():
        if isinstance(value, dict):
            fields = ', '.join(tomli_w.dumps(value).strip().splitlines())
            text += f'{name} = {{ {fields} }}\n'
        else:
            text += tomli_w.dumps({name: value})
    return text + '\n' + tomli_w.dumps(data)


def _save(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    text = (
        _preset_toml(model)
        if isinstance(model, PresetConfig)
        else tomli_w.dumps(model.model_dump(mode='json', exclude_none=True))
    )
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def initialize_configs() -> None:
    """启动时从示例创建缺少的实际配置。"""
    for target in (CONFIG_FILE, CONTROL_FILE, PRESETS_DIR / 'basic.toml'):
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target.with_suffix('.example.toml'), target)


def load_machine_config(path: Path = CONFIG_FILE) -> MachineConfig:
    if not path.exists():
        raise FileNotFoundError(f'配置文件 {path} 不存在，请复制 machine.example.toml 并填写。')
    return MachineConfig.model_validate(_load(path, MachineConfig))


def save_machine_config(config: MachineConfig, path: Path = CONFIG_FILE) -> None:
    _save(path, config)


def load_control_config(path: Path = CONTROL_FILE) -> ControlConfig:
    if not path.exists():
        raise FileNotFoundError(f'配置文件 {path} 不存在，请复制 control.example.toml 并填写。')
    return ControlConfig.model_validate(_load(path, ControlConfig))


def save_control_config(config: ControlConfig, path: Path = CONTROL_FILE) -> None:
    _save(path, config)


def list_presets(presets_dir: Path = PRESETS_DIR) -> list[str]:
    return sorted(path.stem for path in presets_dir.glob('*.toml') if not path.name.endswith('.example.toml'))


def load_preset(name_or_path: str | Path) -> PresetConfig:
    path = Path(name_or_path)
    if path.suffix != '.toml':
        path = PRESETS_DIR / f'{path}.toml'
    return PresetConfig.model_validate(_load(path, PresetConfig))


def save_preset(name: str, preset: PresetConfig, presets_dir: Path = PRESETS_DIR) -> Path:
    path = presets_dir / f'{name}.toml'
    _save(path, preset)
    return path


def write_run_config(run_config: RunConfig) -> Path:
    RUN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_CONFIG_DIR / f'{run_config.session_id}.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(run_config.model_dump_json(indent=2), encoding='utf-8')
    temporary.replace(path)
    return path


def load_run_config(path: Path) -> RunConfig:
    return RunConfig.model_validate(json.loads(path.read_text(encoding='utf-8')))
