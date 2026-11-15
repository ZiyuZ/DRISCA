# 配置模型与读写约定

配置按职责划分为机器配置（`MachineConfig`）、控制配置（`ControlConfig`）、实验预设（`PresetConfig`）与单次实验设置（`RunSettings`），并在启动实验时由 `launcher` 合成为不可变的 `RunConfig`。

## 相机安装与出生点

车载四路相机（主视图 `front` + 三路后视镜 `rear_top` / `rear_left` / `rear_right`）的安装位置因车型而异。预设页提供静态编辑；实验运行期可通过实验控制台的调试面板发送 `UpdateCameraCommand` 实时微调相机，并选择覆盖当前预设或另存为新预设：

```python
from pydantic import BaseModel


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
    image_size: tuple[int, int] | None = None          # None 表示自动跟随模拟器主窗口分辨率（用于 front）
    fov: float = 100.0


class CameraRigConfig(BaseModel, frozen=True, extra='forbid'):
    """主车四路相机组合配置（固定使用 sensor.camera.rgb）"""
    show_rearview: bool = True
    front: CameraConfig = CameraConfig(
        x=0.5, y=-0.35, z=1.35, pitch=5.8,
        screen_position=(0.5, 0.5),
        image_size=None,  # 运行时取窗口实际分辨率
        fov=120.0,
    )
    rear_top: CameraConfig = CameraConfig(
        x=0.34, y=0.0, z=1.27, pitch=5.8, yaw=180.0,
        screen_position=(0.5, 0.1),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_left: CameraConfig = CameraConfig(
        x=0.4, y=-0.93, z=1.03, pitch=5.8, yaw=180.0,
        screen_position=(0.12, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )
    rear_right: CameraConfig = CameraConfig(
        x=0.4, y=0.93, z=1.03, pitch=5.8, yaw=180.0,
        screen_position=(0.88, 0.9),
        image_size=(320, 150),
        fov=100.0,
    )
```

## 机器配置（`MachineConfig` ↔ `configs/machine.toml`）

存放与运行主机网络、显示器及本地服务绑定的环境参数，每台实验机器配置一次：

```python
class CarlaConnectionConfig(BaseModel, frozen=True, extra='forbid'):
    host: str = '127.0.0.1'
    port: int = 2000
    tm_port: int = 8000
    timeout: float = 5.0


class DisplayConfig(BaseModel, frozen=True, extra='forbid'):
    resolution: tuple[int, int] = (1600, 900)  # 宽度建议为 64 的倍数以避免 CARLA 相机画面撕裂
    fullscreen: bool = False
    borderless: bool = False
    target_fps: int = 60  # 窗口显示目标帧率


class ServiceConfig(BaseModel, frozen=True, extra='forbid'):
    launcher_host: str = '0.0.0.0'  # 监听局域网以便平板连接
    launcher_port: int = 7777
    enable_tts: bool = True         # 由 launcher 托管的语音播报开关
    debug: bool = False


class MachineConfig(BaseModel, frozen=True, extra='forbid'):
    carla: CarlaConnectionConfig = CarlaConnectionConfig()
    display: DisplayConfig = DisplayConfig()
    service: ServiceConfig = ServiceConfig()
    db_path: str = 'data/experiments.sqlite3'
    recorder_dir: str = 'data/recordings'
```

## 控制配置（`ControlConfig` ↔ `configs/control.toml`）

将键盘与方向盘的参数（开关、轴号、按钮映射）统一收归 `configs/control.toml`。项目使用罗技 G29，实验机器之间可复用相同的按钮与轴号配置。

`simulator` 负责面向被试的驾驶控制输入；运行期调试由操作者通过 `launcher` 界面完成。

```python
# 罗技 G29 DirectInput 物理按钮编号与名称对照表（供 launcher 界面与按键说明展示）
G29_BUTTON_NAMES: dict[int, str] = {
    0: 'X 键 (Cross)',
    1: '方块键 (Square)',
    2: '圆圈键 (Circle)',
    3: '三角键 (Triangle)',
    4: '右换挡拨片 (R1)',
    5: '左换挡拨片 (L1)',
    6: 'R2 键',
    7: 'L2 键',
    8: 'Share 键',
    9: 'Options 键',
    10: 'R3 键',
    11: 'L3 键',
    19: '加号键 (+)',
    20: '减号键 (-)',
    21: '红旋钮右旋',
    22: '红旋钮左旋',
    23: '红旋钮确认键 (Enter)',
    24: 'PS / Logo 键',
}


class KeyboardControlConfig(BaseModel, frozen=True, extra='forbid'):
    """键盘按键绑定（使用 pygame.key.name 名称，元组内任一按键均可触发）"""
    quit: tuple[str, ...] = ('escape',)
    toggle_autopilot: tuple[str, ...] = ('p', 'keypad 1')
    takeover: tuple[str, ...] = ('backslash', 'keypad 2')
    toggle_reverse: tuple[str, ...] = ('q',)
    toggle_manual_transmission: tuple[str, ...] = ('m',)
    gear_up: tuple[str, ...] = ('period',)
    gear_down: tuple[str, ...] = ('comma',)
    toggle_handbrake: tuple[str, ...] = ('space',)
    toggle_light_double_blinker: tuple[str, ...] = ('semicolon',)
    toggle_light_low_beam: tuple[str, ...] = ('k',)
    toggle_light_high_beam: tuple[str, ...] = ('l',)
    toggle_light_left_blinker: tuple[str, ...] = ('z',)
    toggle_light_right_blinker: tuple[str, ...] = ('x',)
    toggle_light_interior: tuple[str, ...] = ('i',)
    drive_forward: tuple[str, ...] = ('up', 'w')
    drive_backward: tuple[str, ...] = ('down', 's')
    drive_left: tuple[str, ...] = ('left', 'a')
    drive_right: tuple[str, ...] = ('right', 'd')


class WheelControlConfig(BaseModel, frozen=True, extra='forbid'):
    """方向盘硬件开关、轴号与按钮绑定（空元组表示未绑定）"""
    enable_wheel: bool = True
    show_button_key: bool = False
    autopilot_wheel_sync: bool = False  # 自动驾驶方向盘随动，后续实现
    device_index: int = 0
    # 轴序号
    steering_axis: int = 0
    throttle_axis: int = 1
    brake_axis: int = 2
    # 动作按钮绑定（TOML 使用数组，空数组表示未绑定）
    toggle_autopilot: tuple[int, ...] = (23,)
    takeover: tuple[int, ...] = (0,)
    toggle_reverse: tuple[int, ...] = (5,)
    toggle_handbrake: tuple[int, ...] = (4,)
    toggle_light_left_blinker: tuple[int, ...] = (7,)
    toggle_light_right_blinker: tuple[int, ...] = (6,)
    toggle_light_double_blinker: tuple[int, ...] = (3,)


class ControlConfig(BaseModel, frozen=True, extra='forbid'):
    keyboard: KeyboardControlConfig = KeyboardControlConfig()
    wheel: WheelControlConfig = WheelControlConfig()
```

## 实验预设、单次实验设置与合成运行配置（`PresetConfig`、`RunSettings`、`RunConfig`）

`PresetConfig` 对应 `configs/presets/*.toml`：

```python
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
    simulation_fps: int = 60  # 同步模式的世界推进频率
    weather: WeatherConfig = WeatherConfig()


class EgoVehicleConfig(BaseModel, frozen=True, extra='forbid'):
    role_name: str = 'hero'
    blueprint: str = 'vehicle.audi.a2'  # 本次使用的具体车辆蓝图
    spawn_point: SpawnPoint                  # 预设指定的地图出生位姿
    default_speed_limit: float = 33.33         # 默认限速 (m/s，对应 120 km/h)
    dynamic_speed_limit: bool = False          # 开启时读取 actor.get_speed_limit() / 3.6 转为 m/s
    init_autopilot: bool = False               # 启动后是否默认进入 CARLA 自动驾驶


class PresetConfig(BaseModel, frozen=True, extra='forbid'):
    world: WorldConfig = WorldConfig()
    ego: EgoVehicleConfig
    cameras: CameraRigConfig = CameraRigConfig()


class RunSettings(BaseModel, frozen=True, extra='forbid'):
    """实验设置：每次实验启动时在 launcher 实验控制台中填写，随会话保存。
    与预设合并得到本次实验的设置，最终随 RunConfig 一起写入会话。"""
    subject_id: str = ''  # 被试编号
    note: str = ''        # 本次实验备注
    save_data: bool = True  # 本次运行唯一的实验数据保存总开关
    enable_carla_recorder: bool = False  # 本次是否启用 CARLA Recorder，受 save_data 控制


class RunConfig(BaseModel, frozen=True, extra='forbid'):
    """实验启动时由 launcher 合成并写入 cache/run/<session_id>.json 的不可变配置。
    由机器配置、控制配置、预设与实验设置四部分组成，运行期间的调整保存在运行状态中。"""
    session_id: str
    db_path: str | None                 # 开启保存时使用的数据库绝对路径，调试运行时为空
    launcher_ws_url: str                # launcher 生成的本机回连地址
    machine: MachineConfig
    control: ControlConfig
    preset: PresetConfig
    run: RunSettings
```

## 读取、保存与运行期修改

文件位置与填写方法见[配置管理](../guide/05-Configuration.md)。配置字段名与 TOML 表对应，按业务分组定义模型。相机直接保存六个位姿字段；固定出生点通过 `SpawnPoint` 表达地图坐标，运行时在 CARLA 接入处构造原生对象。

方向盘输入直接读取 pygame 返回的轴值，转向使用 -1 至 1，踏板按设备方向转换为 CARLA 使用的 0 至 1。设备对应的方向转换放在输入模块中。配置保存轴号与按钮绑定，键盘连续控制使用具名模块常量定义响应速度。

读取配置时校验字段名称、类型与有效范围，错误信息包含文件和字段位置。缺少实际设置文件时，提示复制对应示例。保存采用同目录临时文件替换。模型冻结覆盖嵌套集合，按键和按钮使用元组。

预设明确指定车辆和出生位姿。天气选择 CARLA 预设时，启动前展开为完整参数；选择 `Custom` 时使用文件中的自定义参数。启动配置保存本次采用的设置。

系统设置和控制设置在下一次实验启动时生效。服务监听地址和端口在重启 launcher 后生效。运行期相机与天气调整保存在运行状态中，应用后记录事件。操作者点击覆盖或另存时，直接更新选定的预设文件。

`world.load_map` 表示当前地图与预设相同时是否重载，地图不同时加载目标地图。保存函数在可空字段为 None 时省略对应 TOML 项，按钮空绑定写为空数组。

`SpawnPoint` 专门表达固定出生点，`CameraConfig` 将相机位姿平铺保存，两者在使用处转换为 CARLA 对象。开关事件共用 `EnabledPayload`，各事件继续通过名称区分。

驾驶位和三路后视镜统一采用 CARLA 刚性安装。方向盘随动保留配置字段，功能安排在后续硬件工作中实现。

`RunSettings.save_data` 是本次实验的保存总开关，关闭时跳过数据库、会话、事件和录像写入。运行配置文件用于子进程启动，调试运行结束后删除该临时文件。记录模式将启动配置存入会话。

## 组合生成运行配置

操作者编辑机器配置、控制配置和实验预设，并在控制台填写 `RunSettings`。`launcher` 将这四部分组合为完整的 `RunConfig`，自动填入会话编号、数据库路径与回连地址，再交给 `simulator`。运行配置由程序生成，作为本次启动结果使用。

保存总开关和 Recorder 选项统一属于 `RunSettings`。预设保存场景、车辆与相机设置。模型采用组合组织，类继承最多四层；事件采用公共基类与具体事件类两层结构。
