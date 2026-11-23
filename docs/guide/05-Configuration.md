# 配置管理

配置统一放在项目根目录 `configs/`。主机配置描述实验主机，输入配置描述键盘和方向盘，实验预设描述地图、车辆、相机。管理端提供对应的编辑页面，也可以直接修改 TOML 文件。

## 准备文件

```text
configs/
├── machine.example.toml      # 主机配置示例
├── control.example.toml      # 输入配置示例
├── machine.toml              # 本机使用的设置
├── control.toml              # 当前输入设备设置
└── presets/
    ├── basic.example.toml    # 实验预设示例
    └── basic.toml            # 启动时可选择的预设
```

管理端启动时，将缺少的机器和输入配置从示例复制为同目录下的 `machine.toml`、`control.toml`，并从预设示例生成缺少的 `basic.toml`。已有配置继续保留。预设列表按 `.example.toml` 后缀区分示例和实际配置。

配置中的相对路径以项目根目录为起点。开启保存时，数据库默认写入 `data/experiments.sqlite3`，CARLA 录像默认写入 `data/recordings/`，导出默认写入 `data/exports/`。`.cache/run/` 保存传给驾驶端的本次运行配置，路网等可重新生成的文件也放在 `.cache/`。

## 主机配置

`machine.toml` 保存每台主机的连接、显示和输出位置。

| 位置 | 内容 |
| --- | --- |
| `db_path`、`recorder_dir`、`export_dir` | 数据库、录像与导出目录 |
| `[carla]` | `host`、`port`，用于 Unreal 的 CARLA RPC 启动参数 |
| `[display]` | 窗口 `resolution`、`fullscreen`、`borderless` 和显示目标帧率 `target_fps` |
| `[display.layout]` 与三个后视镜子表 | 后视镜初始显隐、边框、屏幕中心位置与图像尺寸 |
| `[service]` | `launcher_host`、`launcher_port`、语音开关 `enable_tts`、调试日志 `debug` |

CARLA 在本机运行时，`host` 填写 `127.0.0.1`。服务监听地址 `0.0.0.0` 用于接受平板连接，平板通过实验主机的局域网 IP 和服务端口访问 HUD。

`resolution = [1600, 900]` 表示窗口宽高。主相机采用窗口实际尺寸，全屏时使用显示器实际分辨率。显示目标帧率和同步世界推进频率分别设置，常用值均为 `60`。

## 输入配置

`control.toml` 分为 `[keyboard]` 与 `[wheel]`。每个动作在每种设备上绑定一个按键，值为按键名称字符串。界面显示“空格”“左换挡拨片”等名称，文件保存 `space`、`left_paddle` 等对应名称。

键盘驾驶时，持续按住油门与方向键使控制量逐渐增加，刹车更快增加，松开方向键后平滑回正。方向盘输入直接使用设备采样值。

```toml
[keyboard]
takeover = "backslash"
toggle_handbrake = "space"
drive_forward = "up"

[wheel]
takeover = "cross"
toggle_reverse = "left_paddle"
```

`unbound` 表示该动作保持未绑定。键盘名称和方向盘按钮名称由程序中的枚举定义，输入错误时会指出配置字段。可选键盘名称包括方向键、当前驾驶字母键、空格、标点和小键盘 1、2；完整默认绑定见示例文件。

当前原生驾驶使用键盘，保持 `wheel.enable_wheel = false`。方向盘接入整体后置，配置与设备封装保留，硬件到位后接通连续输入和按钮动作。

| 字段 | 内容 |
| --- | --- |
| `device_index` | 本机设备编号 |
| 动作名称，如 `takeover` | 一个方向盘按钮名称 |
| `show_button_key` | 在调试日志中显示按钮编号 |
| `autopilot_wheel_sync` | 保留的自动驾驶方向盘随动设置，功能后续实现 |

方向盘的物理轴与按钮编号保存在 `simulator/wheel_device.py`，设备封装使用 pygame 和罗技 SDK，包含踏板方向转换和基础回正力。设置页面保留按钮名称选项，随动配置留待后续实现。

## 实验预设

预设放在 `configs/presets/<名称>.toml`。被试编号在控制台填写；保存总开关和 CARLA 录像选项在标题栏的实验预设对话框设置，归入本次运行设置；本次备注在结束实验时填写，保存到会话记录。预设内容按以下分组编辑。

| 分组 | 内容 |
| --- | --- |
| `[world]` | 地图名、重载地图、同步模式、世界推进频率 |
| `[world.weather]` | 全局天气预设名与完整天气参数 |
| `[[world.fog_regions]]` | 实验启动前的固定世界空间球雾区域 |
| `[ego]` | 主车蓝图、角色名、出生点所属地图、限速和初始自动驾驶选项；当前保持 `init_autopilot = false` |
| `[ego.spawn_point]` | 固定出生位置，六个位姿字段完整填写 |
| `[cameras.front]` 等 | 每路相机的比例安装位置、角度和 FOV |
| `[[instructions]]` | 实验指令的编号、名称、指令标识与参数 |
| `markers` | 实验打点名称列表，放在文件根层级 |

### 地图和主车

`world.map_name` 指定实验地图。当前地图与预设相同时，`load_map = true` 表示重新加载；当前地图不同则加载预设地图。实验开始和结束统一清理场景中的车辆与行人。

`sync_mode = true` 时，`simulation_fps` 指定世界推进频率，固定步长为其倒数。

`ego.blueprint` 保存从当前 CARLA 动态获取的具体车辆蓝图，例如 `vehicle.ue4.audi.tt`。连接 CARLA 后在车辆下拉列表中选择，新预设的车型初始为空。`init_autopilot` 指定初始控制模式。

固定出生点直接填写六个值：

```toml
[ego.spawn_point]
x = 120.0
y = 30.0
z = 0.5
pitch = 0.0
yaw = 90.0
roll = 0.0
```

出生点采用地图世界坐标，位置单位 m，角度单位 deg。示例坐标用于说明格式，操作者可从地图出生点列表选择位置，或在方案配置页拾取当前位置后保存。

`ego.spawn_map` 记录出生点所属地图。它与 `world.map_name` 不一致或为空时，启动前需要在方案配置的出生点对话框中确认：目标地图已加载且有点时随机预选，目标地图没有预设点时填写完整坐标。确认后界面把目标地图写入该字段。启动前还会用原生道路查询校验坐标落在道路上，道路外直接报错，不生成车辆。

### 天气和限速

天气编辑器将日照与天气类型分开选择，可组合白天浓雾、夜间暴雨等场景。日照只调整太阳高度；选择天气保留当前太阳设置。太阳方位、高度和各项天气参数均可继续微调。

`world.weather.preset_name` 选择原生环境目录中的天气预设，例如 `ClearNoon`，实验启动前展开为完整数值；选择 `Custom` 时使用同一表中的数值。云雨、风和地表强度为 0 到 1，界面按 0–100 百分比显示；全局雾密度范围为 0 到 100，直接作为 UE 高度雾密度，起始距离（`distance_m`）和高度衰减（`height_falloff`）为原生高度雾渲染参数。雪效列入后续计划，`precipitation.snow` 当前固定为 0。

```toml
[world.weather]
preset_name = "Custom"
cloudiness = 0.3
wind = 0.2
dust = 0.0

sun = { azimuth_deg = 0.0, elevation_deg = 45.0 }
precipitation = { rain = 0.0, snow = 0.0 }
surface = { wetness = 0.0, puddles = 0.0 }
fog = { density = 0.1, distance_m = 10.0, height_falloff = 0.2 }
scattering = { light = 1.0, mie = 0.003996, rayleigh = 0.0331 }
```

`world.fog_regions` 保存实验启动前的局部球雾。每个区域由 worker 在驾驶视图启动前创建，实验结束、连接中断或切换地图时清理。中心使用世界坐标米，半径大于 0 且不超过 100000 米，密度为 0 到 1，`transition_seconds` 控制渐入时长。

```toml
[[world.fog_regions]]
center_m = [10.0, 20.0, 2.0]
radius_m = 80.0
density = 0.8
transition_seconds = 0.0
```

旧预设中的 `cloudiness`、`wetness`、`precipitation` 等 0–100 字段和 `fog_density` 已由一次性迁移脚本转换为上述结构：百分比除以 100，旧雾密度乘以 0.001。迁移前的文件备份在 `.local/backup/weather-presets-*`。

`ego.dynamic_speed_limit = false` 时使用 `default_speed_limit`，文件单位为 m/s；设为 `true` 时使用原生快照中的道路限速（m/s），手动驾驶的主车通常为 0。界面以 km/h 展示和输入。

### 背景交通流

`[traffic]` 控制实验启动时由自研交通模块批量生成的背景车辆：

```toml
[traffic]
enabled = false
vehicle_count = 10
seed = 42
speed_factor = 1.0
enable_lane_change = true
```

开启后在避开主车出生点的空闲位置生成指定数量的背景车，沿道路图自动选路、按 IDM 模型跟驰防追尾、遵守红绿灯并在安全间隙允许时换道；实验结束时自动清理。

### 相机

四路名称为 `front`、`rear_top`、`rear_left`、`rear_right`。每路直接填写 `x/y/z/pitch/yaw/roll` 与 `fov`。安装位置使用车辆包围盒比例，X 向前、Y 向右、Z 向上，0 表示包围盒中心，±1 表示相应边界；界面显示为 ±100%。simulator 按实际车辆尺寸换算安装坐标，姿态与水平视野单位为 deg。

`machine.toml` 的 `[display.layout]` 保存后视镜显隐，`[display.layout.rear_top]` 等子表用 `screen_position = [0.5, 0.1]` 表示归一化画面中心，用 `image_size = [320, 150]` 指定像素尺寸。`border_width` 为边框宽度（视口像素，0 表示不画），`border_color` 为边框颜色（`#RRGGBB` 或 `#RRGGBBAA`），深色边框便于在明亮场景中分辨镜面边界。布局在主机配置的驾驶显示标签编辑；主视图采用窗口实际大小。四路镜头统一采用刚性安装，随车辆保持固定位置。

换车型后在方案配置的相机安装标签微调驾驶位与后视镜，修改自动保存到当前方案，点击应用观察本次实验中的实际效果。

### 数据保存

实验预设对话框中的 `save_data` 是整次运行唯一的保存总开关，属于 `RunSettings`。开启后写入会话、逐帧数据、事件和启动配置，并按 `enable_carla_recorder` 决定是否保存录像。关闭后以调试方式运行，数据库和 Recorder 保持关闭，实时界面和日志照常显示，临时运行配置在结束后删除。

## 修改与维护

主机配置和输入配置在下次启动实验时生效。服务监听地址与端口在重启管理端后生效。预设页编辑下一次实验所用的设置。

运行期调整相机、天气或后视镜后，控制台显示实际生效结果，并记录事件。相机安装保存到实验预设，后视镜布局保存到主机配置，原有会话保留启动时的配置快照。

配置读取错误会指出文件、字段和原因。启动时自动复制示例建立缺少的实际配置，日常调整在对应页面经 600ms 防抖自动保存，标签行显示保存状态。切换预设、启动实验和检查连接前提交相关修改。示例随配置字段一同维护，各实验主机的实际设置单独保存。

完整运行配置由管理端将主机配置、输入配置、实验预设和本次运行设置自动组合生成，供驾驶端启动使用。日常编辑集中在上述配置文件和控制台。

## 指令与打点

实验指令从程序提供的指令库中选择并填写参数。方案配置的指令与打点标签负责定义按钮及参数；实验开始后在控制台点击执行。接管请求可同时播放预定语音。默认打点为进入路段、离开路段、任务完成和异常情况。

主机配置中的导出目录由实验主机管理。实验记录默认显示最近 30 天，勾选所需会话后点击导出，界面显示进度与输出目录。录像列表读取应用管理的录像，点击行选择并设置回放参数。

原生连接地址和请求超时由 `[driving_view]` 的 `host`、`port`、`timeout` 管理，默认端口为 7910。地图加载和目录请求使用 Unreal 启动超时。
