# 配置模型与读写约定

配置按职责划分为机器配置（`MachineConfig`）、输入配置（`ControlConfig`）、实验预设（`PresetConfig`）与单次实验设置（`RunSettings`），并在启动实验时由 `launcher` 合成为不可变的 `RunConfig`。

相机安装界面以车辆包围盒中心和各轴半尺寸表示位置百分比，边界对应 ±100%。`CameraConfig.x`、`y`、`z` 保存比例坐标，1 对应 100%；simulator 使用实际车辆包围盒的中心、旋转和半尺寸换算安装坐标。旋转与 FOV 使用角度。相机与布局页的撤销操作分别恢复进入本页时的当前相机参数或整套布局。地图出生点继续使用米制坐标。

## 相机安装与出生点

车载四路相机（主视图 `front` + 三路后视镜 `rear_top` / `rear_left` / `rear_right`）的安装位置因车型而异。方案配置的相机安装标签提供编辑，实验运行期通过同页发送 `UpdateCameraCommand` 实时微调相机，并保存到当前预设：

```python
from pydantic import BaseModel, JsonValue


class SpawnPoint(BaseModel, frozen=True, extra='forbid'):
    """地图中的固定出生位置，单位 m 与 deg"""
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float


class CameraConfig(BaseModel, frozen=True, extra='forbid'):
    """单路相机；x/y/z 为比例，旋转和 FOV 为角度"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    fov: float = 100.0


class CameraRigConfig(BaseModel, frozen=True, extra='forbid'):
    """四路 RGB 相机；位置字段使用车身包围盒比例"""
    front: CameraConfig
    rear_top: CameraConfig
    rear_left: CameraConfig
    rear_right: CameraConfig

```

## 机器配置（`MachineConfig` ↔ `configs/machine.toml`）

存放与运行主机网络、Unreal 程序、显示器及本地服务绑定的环境参数，每台实验机器配置一次。`carla_runtime` 分别保存 UE 编辑器、CARLA 工程与打包程序路径，由 `kind` 选择启动方式。Launcher 为一组实验启动一次 Unreal，每次实验单独创建和释放实验对象。

```python
class CarlaConnectionConfig(BaseModel, frozen=True, extra='forbid'):
    host: str = '127.0.0.1'
    port: int = 2000


class DrivingViewConfig(BaseModel, frozen=True, extra='forbid'):
    host: str = '127.0.0.1'
    port: int = 7910
    timeout: float = 5.0  # 原生 WebSocket 普通请求超时，秒


class CameraViewportConfig(BaseModel, frozen=True, extra='forbid'):
    screen_position: tuple[float, float]
    image_size: tuple[int, int]


class DisplayLayoutConfig(BaseModel, frozen=True, extra='forbid'):
    show_rearview: bool = True
    border_width: int = 0  # 后视镜边框宽度（视口像素），0 表示不画
    border_color: str = '#000000'  # 后视镜边框颜色 #RRGGBB 或 #RRGGBBAA
    rear_top: CameraViewportConfig
    rear_left: CameraViewportConfig
    rear_right: CameraViewportConfig


class DisplayConfig(BaseModel, frozen=True, extra='forbid'):
    layout: DisplayLayoutConfig
    resolution: tuple[int, int] = (1600, 900)  # 宽度建议为 64 的倍数以避免 CARLA 相机画面撕裂
    position: tuple[int, int] = (0, 0)
    fullscreen: bool = False
    borderless: bool = False
    target_fps: int = 60  # 窗口显示目标帧率


class ServiceConfig(BaseModel, frozen=True, extra='forbid'):
    launcher_host: str = '0.0.0.0'  # 监听局域网以便平板连接
    launcher_port: int = 7900
    enable_tts: bool = True         # 由 launcher 托管的语音播报开关
    debug: bool = False


class CarlaRuntimeConfig(BaseModel, frozen=True, extra='forbid'):
    kind: Literal['editor', 'packaged'] = 'editor'
    editor_executable: str = ''
    project: str = ''
    packaged_executable: str = ''
    quality: Literal['Low', 'Medium', 'High', 'Epic'] = 'Medium'
    startup_timeout: float = Field(default=120, gt=0)


class MachineConfig(BaseModel, frozen=True, extra='forbid'):
    carla: CarlaConnectionConfig = CarlaConnectionConfig()
    carla_runtime: CarlaRuntimeConfig = CarlaRuntimeConfig()
    display: DisplayConfig = DisplayConfig()
    service: ServiceConfig = ServiceConfig()
    db_path: str = 'data/experiments.sqlite3'
    recorder_dir: str = 'data/recordings'
    export_dir: str = 'data/exports'
```

## 输入配置（`ControlConfig` ↔ `configs/control.toml`）

配置保存“动作名称 → 按键名称”，每个动作绑定一个键。`core` 使用 `KeyboardKey` 和 `WheelButton` 两个 `StrEnum` 定义名称，Pydantic 将 TOML 字符串解析为枚举值。界面通过纯数据名称表显示“空格”“右换挡拨片”等标签。

`core/driving_view.py` 将键盘名称映射为 Unreal `FKey` 名称，每次实验开始时传给原生驾驶视图，由 `DrivingViewPawn` 处理键盘与连续控制。`simulator/wheel_device.py` 保留方向盘轴号、按钮编号以及 pygame 和罗技 SDK 的设备封装，硬件接入后继续使用当前设备布局。

```python
from enum import StrEnum


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
    I = 'i'
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


class KeyboardControlConfig(BaseModel, frozen=True, extra='forbid'):
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
```

`unbound` 表示该动作保持未绑定。键盘与方向盘的绑定字段均保存单个枚举值。按键显示标签与 Unreal 键盘映射属于 `core`，方向盘设备编号属于 `simulator/wheel_device.py`。

## 实验预设、单次实验设置与合成运行配置（`PresetConfig`、`RunSettings`、`RunConfig`）

`PresetConfig` 对应 `configs/presets/*.toml`。下列参数对象使用 Pydantic 的 `JsonValue` 表达 JSON 值：

```python
class SunConfig(BaseModel, frozen=True, extra='forbid'):
    azimuth_deg: float = Field(default=0.0, ge=0, lt=360)
    elevation_deg: float = Field(default=75.0, ge=-90, le=90)


class PrecipitationConfig(BaseModel, frozen=True, extra='forbid'):
    rain: float = Field(default=0.0, ge=0, le=1)
    snow: float = Field(default=0.0, ge=0, le=1)  # 原生尚未提供雪效，非零报错


class SurfaceConfig(BaseModel, frozen=True, extra='forbid'):
    wetness: float = Field(default=0.0, ge=0, le=1)
    puddles: float = Field(default=0.0, ge=0, le=1)


class FogConfig(BaseModel, frozen=True, extra='forbid'):
    density: float = Field(default=0.0, ge=0, le=100)
    distance_m: float = Field(default=0.0, ge=0, le=1_000_000)
    height_falloff: float = Field(default=0.2, ge=0, le=10_000)


class ScatteringConfig(BaseModel, frozen=True, extra='forbid'):
    light: float = Field(default=1.0, ge=0, le=1000)
    mie: float = Field(default=0.003996, ge=0, le=1000)
    rayleigh: float = Field(default=0.0331, ge=0, le=1000)


class GlobalWeather(BaseModel, frozen=True, extra='forbid'):
    sun: SunConfig = SunConfig()
    cloudiness: float = Field(default=0.0, ge=0, le=1)
    wind: float = Field(default=0.0, ge=0, le=1)
    dust: float = Field(default=0.0, ge=0, le=1)
    precipitation: PrecipitationConfig = PrecipitationConfig()
    surface: SurfaceConfig = SurfaceConfig()
    fog: FogConfig = FogConfig()
    scattering: ScatteringConfig = ScatteringConfig()


class WeatherConfig(GlobalWeather, frozen=True, extra='forbid'):
    preset_name: str = 'Default'  # 命名预设启动前展开；'Custom' 使用本对象数值


class FogRegionConfig(BaseModel, frozen=True, extra='forbid'):
    center_m: tuple[float, float, float]
    radius_m: float = Field(gt=0, le=100_000)
    density: float = Field(default=0.0, ge=0, le=1)
    transition_seconds: float = Field(default=0.0, ge=0)


class WorldConfig(BaseModel, frozen=True, extra='forbid'):
    map_name: str = 'Town10HD_Opt'
    load_map: bool = False
    sync_mode: bool = True
    simulation_fps: int = 60  # 同步模式的世界推进频率
    weather: WeatherConfig = WeatherConfig()
    fog_regions: tuple[FogRegionConfig, ...] = ()


class EgoVehicleConfig(BaseModel, frozen=True, extra='forbid'):
    role_name: str = 'hero'
    blueprint: str = ''  # 从已连接 CARLA 的车辆列表选择
    spawn_point: SpawnPoint                  # 预设指定的地图出生位姿
    spawn_map: str = ''                       # 出生点所属地图；为空或与目标地图不一致时视为未选择
    default_speed_limit: float = 33.33         # 默认限速 (m/s，对应 120 km/h)
    dynamic_speed_limit: bool = False          # 开启时使用原生快照中的道路限速 (m/s)，手动主车为 0
    init_autopilot: bool = False               # 开启后在实验就绪时切入自研自动驾驶（external/python）


class ExperimentInstructionConfig(BaseModel, frozen=True, extra='forbid'):
    id: str
    name: str
    command: str
    params: dict[str, JsonValue]


class PresetConfig(BaseModel, frozen=True, extra='forbid'):
    world: WorldConfig = WorldConfig()
    ego: EgoVehicleConfig
    cameras: CameraRigConfig
    instructions: tuple[ExperimentInstructionConfig, ...] = ()
    markers: tuple[str, ...] = ()


class RunSettings(BaseModel, frozen=True, extra='forbid'):
    """实验设置：每次实验启动时在 launcher 控制台中填写，随会话保存。
    与预设合并得到本次实验的设置，最终随 RunConfig 一起写入会话。"""
    subject_id: str = ''  # 被试编号
    note: str = ''        # 本次实验备注
    save_data: bool = True  # 本次运行唯一的实验数据保存总开关
    enable_carla_recorder: bool = False  # 本次是否启用 CARLA Recorder，受 save_data 控制


class RunConfig(BaseModel, frozen=True, extra='forbid'):
    """实验启动时由 launcher 合成并写入 .cache/run/<session_id>.json 的不可变配置。
    由机器配置、输入配置、预设与实验设置四部分组成，运行期间的调整保存在运行状态中。"""
    session_id: str
    db_path: str | None                 # 开启保存时使用的数据库绝对路径，调试运行时为空
    launcher_ws_url: str                # launcher 生成的本机回连地址
    machine: MachineConfig
    control: ControlConfig
    preset: PresetConfig
    run: RunSettings
```

## 读取、保存与运行期修改

文件位置与填写方法见[配置管理](../guide/05-Configuration.md)。配置字段名与 TOML 表对应，按业务分组定义模型。相机保存三个比例位置和三个角度字段；固定出生点通过 `SpawnPoint` 表达地图坐标，运行时在 CARLA 接入处构造原生对象。

键盘连续控制由 Unreal 原生驾驶视图按实际更新时间处理。保留的方向盘设备层读取 pygame 轴值，转向使用 -1 至 1，踏板按设备方向转换为 0 至 1。方向盘接入后继续使用这些轴与按钮约定；当前 `enable_wheel = false` 表示使用键盘，启动实验时只初始化当前驾驶链路。

读取配置时校验字段名称、类型与有效范围，错误信息包含文件和字段位置。缺少实际设置文件时，提示复制对应示例。保存采用同目录临时文件替换。按键和按钮使用单个枚举值。

预设明确指定车辆和出生位姿。天气选择命名预设时，启动前从目录展开为完整数值；选择 `Custom` 时使用文件中的数值。天气编辑器将日照与天气类型独立选择：日照仅调整太阳高度，天气类型保留当前太阳方位与高度，组合结果以 `Custom` 完整保存。全局状态包含 14 项功能字段与 1 项雪效占位字段（`precipitation.snow` 固定为 0）；云雨、风和地表强度为 0 到 1，界面按百分比显示；全局雾密度范围为 0 到 100，直接写入 UE 高度雾密度，`distance_m` 与 `height_falloff` 为原生高度雾参数。预设 TOML 中的太阳、降水、地表、雾和散射分组采用内联表格式，解析后的模型结构保持一致。`world.fog_regions` 保存实验启动前由 worker 创建的世界空间球雾，每个区域指定中心、半径、密度和渐入时长。启动配置保存本次采用的设置。

主机配置和输入配置在下一次实验启动时生效。服务监听地址和端口在重启 launcher 后生效。运行期相机、画面布局与天气调整保存在运行状态中，应用后记录事件。方案配置页保存安装参数到预设文件；主机配置页保存画面布局到 machine.toml。

`world.load_map` 表示当前地图与预设相同时是否重载，地图不同时加载目标地图。保存函数在可空字段为 None 时省略对应 TOML 项，未绑定按键写为 `unbound`。

`ego.spawn_map` 记录出生点所属地图。启动前要求它与 `world.map_name` 一致，并在目标地图加载后通过原生道路查询确认坐标落在道路上；不一致或道路外直接报错，不生成车辆。旧预设没有该字段时读作空串，视为尚未选择出生点，需要在方案配置中确认一次。

`SpawnPoint` 专门表达固定出生点，`CameraConfig` 将相机位姿平铺保存，两者在使用处转换为 CARLA 对象。开关事件共用 `EnabledPayload`，各事件继续通过名称区分。

驾驶位和三路后视镜统一采用 CARLA 刚性安装。方向盘随动保留配置字段，功能安排在后续硬件工作中实现。

`RunSettings.save_data` 是本次实验的保存总开关，关闭时跳过数据库、会话、事件和录像写入。运行配置文件用于子进程启动，调试运行结束后删除该临时文件。记录模式将启动配置存入会话。

## 组合生成运行配置

操作者编辑机器配置、输入配置和实验预设，并在控制台填写 `RunSettings`。`launcher` 将这四部分组合为完整的 `RunConfig`，自动填入会话编号、数据库路径与回连地址，再交给 `simulator`。运行配置由程序生成，作为本次启动结果使用。

保存总开关和 Recorder 选项统一属于 `RunSettings`。预设保存场景、车辆与相机设置。模型采用组合组织，类继承最多四层；事件采用公共基类与具体事件类两层结构。

## 实验指令与打点

预设的 `instructions` 保存按钮编号、名称、已知指令标识与参数，`markers` 保存打点名称。已知指令由 launcher 的 Python 代码显式声明，参数类型、约束和执行方式与定义放在一起。core 负责配置结构，launcher 读取后按已知指令定义校验参数。

停止时编辑或添加当前预设的实验指令，运行时执行本次启动配置中的指令。请求接管可携带语音参数，一次执行完成接管提示与播报。纯打点生成自定义事件，保存总开关控制写库。

相机比例坐标、导出目录和实验指令属于此次管理端设计确定的配置约定，接入实现时同步更新 `core/config.py`、配置示例和全部调用方。
