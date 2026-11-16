"""实验配置模型。"""

import json
import tomllib
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import tomli_w
from pydantic import BaseModel, Field, field_validator

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
    """单路相机的安装与画面配置"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    screen_position: tuple[float, float] = (0.5, 0.5)  # 画面中心在窗口中的归一化坐标 (0~1)
    image_size: tuple[int, int] | None = None  # None 表示自动跟随模拟器主窗口分辨率（用于 front）
    fov: float = Field(default=100.0, gt=0, lt=180)

    @field_validator('screen_position')
    @classmethod
    def validate_screen_position(cls, value: tuple[float, float]) -> tuple[float, float]:
        if any(not 0 <= coordinate <= 1 for coordinate in value):
            raise ValueError('画面位置必须在 0 到 1 之间')
        return value

    @field_validator('image_size')
    @classmethod
    def validate_image_size(cls, value: tuple[int, int] | None) -> tuple[int, int] | None:
        if value is not None and any(size <= 0 for size in value):
            raise ValueError('画面尺寸必须为正数')
        return value


class CameraRigConfig(BaseModel, frozen=True, extra='forbid'):
    """主车四路相机组合配置（固定使用 sensor.camera.rgb）"""

    show_rearview: bool = True
    front: CameraConfig = CameraConfig(
        x=0.5,
        y=-0.35,
        z=1.35,
        pitch=5.8,
        screen_position=(0.5, 0.5),
        image_size=None,  # 运行时取窗口实际分辨率
        fov=120.0,
    )
    rear_top: CameraConfig = CameraConfig(
        x=0.34,
        y=0.0,
        z=1.27,
        pitch=5.8,
        yaw=180.0,
        screen_position=(0.5, 0.1),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_left: CameraConfig = CameraConfig(
        x=0.4,
        y=-0.93,
        z=1.03,
        pitch=5.8,
        yaw=180.0,
        screen_position=(0.12, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_right: CameraConfig = CameraConfig(
        x=0.4,
        y=0.93,
        z=1.03,
        pitch=5.8,
        yaw=180.0,
        screen_position=(0.88, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )


class CarlaConnectionConfig(BaseModel, frozen=True, extra='forbid'):
    host: str = '127.0.0.1'
    port: int = Field(default=2000, gt=1024, le=65535)
    tm_port: int = Field(default=8000, gt=1024, le=65535)
    timeout: float = Field(default=5.0, gt=0)


class DisplayConfig(BaseModel, frozen=True, extra='forbid'):
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


class MachineConfig(BaseModel, frozen=True, extra='forbid'):
    carla: CarlaConnectionConfig = CarlaConnectionConfig()
    display: DisplayConfig = DisplayConfig()
    service: ServiceConfig = ServiceConfig()
    db_path: str = 'data/experiments.sqlite3'
    recorder_dir: str = 'data/recordings'


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


class WeatherConfig(BaseModel, frozen=True, extra='forbid'):
    preset_name: str = 'Default'  # 如 'ClearNoon', 'WetNoon', 'HardRainNoon'；为 'Custom' 时使用下方参数
    cloudiness: float = 30.0
    wetness: float = 80.0
    precipitation: float = 80.0
    precipitation_deposits: float = 80.0
    wind_intensity: float = 20.0
    dust_storm: float = 0.0
    sun_azimuth_angle: float = 0.0
    sun_altitude_angle: float = 45.0
    fog_density: float = 0.0
    fog_distance: float = 0.0
    fog_falloff: float = 0.0
    scattering_intensity: float = 0.0
    mie_scattering_scale: float = 0.0
    rayleigh_scattering_scale: float = 0.0331


class WorldConfig(BaseModel, frozen=True, extra='forbid'):
    map_name: str = 'Town10HD_Opt'
    load_map: bool = False
    sync_mode: bool = True
    simulation_fps: int = Field(default=60, gt=0)
    weather: WeatherConfig = WeatherConfig()


class EgoVehicleConfig(BaseModel, frozen=True, extra='forbid'):
    role_name: str = 'hero'
    blueprint: str = 'vehicle.audi.a2'  # 本次使用的具体车辆蓝图
    spawn_point: SpawnPoint  # 预设指定的地图出生位姿
    default_speed_limit: float = Field(default=33.33, ge=0)
    dynamic_speed_limit: bool = False  # 开启时读取 actor.get_speed_limit() / 3.6 转为 m/s
    init_autopilot: bool = False  # 启动后是否默认进入 CARLA 自动驾驶


class PresetConfig(BaseModel, frozen=True, extra='forbid'):
    world: WorldConfig = WorldConfig()
    ego: EgoVehicleConfig
    cameras: CameraRigConfig = CameraRigConfig()


class RunSettings(BaseModel, frozen=True, extra='forbid'):
    """实验设置：每次实验启动时在 launcher 实验控制台中填写，随会话保存。
    与预设合并得到本次实验的设置，最终随 RunConfig 一起写入会话。"""

    subject_id: str = ''  # 被试编号
    note: str = ''  # 本次实验备注
    save_data: bool = True  # 本次运行唯一的实验数据保存总开关
    enable_carla_recorder: bool = False  # 本次是否启用 CARLA Recorder，受 save_data 控制


class RunConfig(BaseModel, frozen=True, extra='forbid'):
    """实验启动时由 launcher 合成并写入 cache/run/<session_id>.json 的不可变配置。
    由机器配置、控制配置、预设与实验设置四部分组成，运行期间的调整保存在运行状态中。"""

    session_id: str
    db_path: str | None  # 开启保存时使用的数据库绝对路径，调试运行时为空
    launcher_ws_url: str  # launcher 生成的本机回连地址
    machine: MachineConfig
    control: ControlConfig
    preset: PresetConfig
    run: RunSettings


def compose_run_config(
    machine: MachineConfig, control: ControlConfig, preset: PresetConfig, run: RunSettings
) -> RunConfig:
    from .weather import from_carla_weather, to_carla_weather

    weather = preset.world.weather
    if weather.preset_name != 'Custom':
        weather = from_carla_weather(to_carla_weather(weather), weather.preset_name)
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


def _save(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('wb') as stream:
        tomli_w.dump(model.model_dump(mode='json', exclude_none=True), stream)
    temporary.replace(path)


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
