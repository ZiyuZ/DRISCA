# 桌面管理端（`launcher`）界面与功能设计

> 文档定位：本文面向项目开发者，定义桌面管理端 `launcher` 的职责边界、窗口导航结构、六个功能页面的组件布局以及交互工作流。数据模型与类接口签名见 [核心数据结构与协议契约](./02-DataStructures.md) 与 [模块职责与 API 规范](./03-ModuleAPI.md)。

## 设计定位：操作者控制台与被试驾驶端分离

在驾驶行为实验中，系统面对两类角色：

1. 被试（Subject）：坐在驾驶模拟器座椅上，面对驾驶屏幕（`simulator` 窗口）、方向盘和踏板，以及平板 HUD。被试只需要驾驶视野和车辆操控输入。驾驶屏幕上不显示调试参数，被试也不会通过键盘或方向盘改动相机视角或关闭后视镜。
2. 操作者（Operator）：坐在主控台前操作 `launcher` 桌面界面。实验准备、地图与天气切换、车载镜头调节、主车出生点拾取、运行期接管控制、遥测监控和数据导出都在 `launcher` 中完成。

## 主窗口导航结构（`launcher/ui/main_window.py`）

采用 `PySide6-Fluent-Widgets` 的 `FluentWindow` 侧边栏导航布局，设 6 个一级导航页面：

```text
FluentWindow (DRISCA Launcher)
├── 1. 实验控制台 (run_page.py)       —— 预检、启动/停止、调试面板（运行期控制与标定）、数据面板、日志与事件流
├── 2. 预设页     (preset_page.py)    —— 静态编辑与管理 configs/presets/*.toml（地图天气、主车与出生点、四路相机参数）
├── 3. 历史数据   (session_page.py)   —— 浏览 session 表、查看事件时间线、导出 data.csv 与 events.csv
├── 4. CARLA 工具 (tools_page.py)     —— .rec 录像信息查看与回放、路网拓扑图生成
├── 5. 控制与按键 (control_page.py)   —— 读写 configs/control.toml、按键名称绑定、按键说明对照表
└── 6. 系统设置   (settings_page.py)  —— 读写 configs/machine.toml（CARLA 地址、显示器分辨率、服务端口、TTS 开关）
```

## 各页面功能与交互设计

### 3.1 实验控制台页（`run_page.py`）

操作者在实验运行期间停留的主页面，分为四个区域：

1. 顶部启动与会话信息栏：
   - CARLA 服务状态卡片：显示 `CarlaSession.preflight_check()` 的连接状态、服务端版本、当前已加载地图；提供「重新检测」和「清理车辆与行人」按钮；手动清理与实验开始、结束时的自动清理并存。
   - 本次实验参数输入：
     - 预设选择下拉框（读取 `configs/presets/*.toml`）；
     - 被试编号（`subject_id`）输入框（属于实验设置 `RunSettings`，每次启动时填写，用于生成导出文件名与写入 `session` 表）；
     - 实验备注（`note`）输入框，同属实验设置；
     - 「保存实验数据（`RunSettings.save_data`）」总开关与「CARLA 录像（`RunSettings.enable_carla_recorder`）」选项。
   - 主控按钮与平板入口：
     - 「开始实验」/「结束实验」按钮（跟随 `ExperimentOrchestrator.state_changed` 信号切换状态）；
     - 「平板 HUD 连接」按钮：点击弹出局域网 URL（如 `http://192.168.1.x:7777/`）及二维码，供平板扫码连接。
2. 调试面板（运行期控制与标定，仅在 `running` 状态下激活）：
   - 集中放置运行期对 `simulator` 的全部实时干预与现场标定功能。操作者下发的所有控制命令（`LauncherCommand`）本身不直接写入事件表，由 `simulator` 收到并应用成功后上报对应的实验事件（`source='launcher'`），再由 `launcher` 写入 `event` 表：
     - 驾驶状态与环境控制：
       - 自动驾驶开关：发送 `SetAutopilotCommand(enabled=...)`，`simulator` 应用后上报 `ToggleAutopilotEvent`；
       - 接管请求开关：发送 `SetTakeoverCommand(enabled=...)`（可配合 `TTSSpeaker` 播报语音提示），`simulator` 应用后上报 `ToggleTakeoverEvent`；
       - 后视镜显隐开关：发送 `SetRearviewCommand(enabled=...)`，`simulator` 应用后上报 `SetRearviewEvent`；
       - 动态切换天气：下拉选择天气预设并发送 `SetWeatherCommand`，`simulator` 应用后上报 `SetWeatherEvent`。
     - 四路车载相机实时调节：
       - 选择 `front`、`rear_top`、`rear_left` 或 `rear_right`，调整安装位置 `(x, y, z)`、旋转角 `(pitch, yaw, roll)`、视野角 `fov`、屏幕中心归一化位置 `screen_position` 与画面尺寸 `image_size`；
       - 操作者修改数值后，`launcher` 发送 `UpdateCameraCommand`，`simulator` 应用后上报 `UpdateCameraEvent`，驾驶屏幕上的对应镜头随之移动，事件表记录每次调整。
     - 出生点实时拾取：
       - 点击「拾取当前位置为出生点」，读取最新收到的 `TelemetrySnapshotEvent` 中的主车三维位姿 `(location_x, location_y, location_z, rotation_pitch, rotation_yaw, rotation_roll)`，填入当前调试面板的出生点字段。
     - 写回预设（覆盖或另存）：
       - 当在调试面板中调整了相机参数或拾取了主车出生点后，提供「覆盖当前预设」和「另存为新预设」两个按钮；
       - 点击「覆盖当前预设」将更新后的相机参数和出生点写回当前选中的 `configs/presets/<name>.toml`；点击「另存为新预设」弹出名称输入框，保存为新的预设文件，避免修改原基准预设。
3. 数据面板：
   - 绑定 `telemetry_updated` 信号（20~30 Hz 刷新）：
     - 基础状态区：控制模式（手动 / 自动驾驶）与接管请求状态、车速（同时显示 `km/h` 与 `m/s`）、当前限速、挡位、模拟器 FPS 与 CARLA 服务端 FPS；
     - 控制量实时条：油门（`0~1`）、刹车（`0~1`）、归一化转向（`-1~1` 双向条）以及手刹、倒挡、手自一体状态指示；
     - 位姿与道路区：世界坐标 `(X, Y, Z)`、姿态角 `(Pitch, Yaw, Roll)`、罗盘朝向、当前 `road_id` / `lane_id`、车道中心横向偏移（`lane_offset`）；
     - 告警状态区：最近一次碰撞强度与压线类型提示。
4. 底部实时日志与实验事件双栏视图：
   - 「运行日志」页签：绑定 `log_received` 信号，按级别着色滚动显示子进程上报的 `LogEvent` 及异常退出时的 `stdout/stderr` 管道输出；
   - 「事件时间线」页签：绑定 `experiment_event_received` 信号，实时列出本次实验已记录的 `ExperimentEvent`（帧号、时间戳、事件名、触发源、负载摘要）。

### 3.2 预设页（`preset_page.py`）

用于实验前静态查看、编辑和管理 `configs/presets/*.toml` 文件（运行期的实时调相机与拾取出生点统一在实验控制台的调试面板中进行，预设页不重复放置运行期控制逻辑）：

1. 预设文件管理栏：
   - 下拉切换预设、新建预设、覆盖保存当前预设、另存为新预设、删除预设。
2. 世界与环境配置卡片（`WorldConfig` & `WeatherConfig`）：
   - 地图名称选择（若已连接 CARLA，从 `PreflightResult.available_maps` 填充下拉列表）、启动时重载地图开关（`load_map`）、同步模式开关（`sync_mode`）与同步推进频率（`simulation_fps`）；
   - 天气预设选择（`Default`、`ClearNoon`、`WetNoon`、`HardRainNoon` 等，或选择 `Custom` 编辑云量、降雨、积水、起雾、太阳高度角等参数）。
3. 主车与出生点配置卡片（`EgoVehicleConfig`）：
   - 车辆角色名（`role_name`）与车辆蓝图 ID（输入或下拉选择具体车辆）；
   - 默认限速（界面按 `km/h` 展示输入，保存时换算为 `m/s`）、动态道路限速开关、启动后默认开启自动驾驶开关；
   - 出生点（`spawn_point`）：从地图出生点列表选择或编辑六个位姿字段，保存为 `SpawnPoint`。
4. 四路车载相机静态配置卡片（`CameraRigConfig`）：
   - 默认显示后视镜开关（`show_rearview`）；
   - 分页签编辑 `front`、`rear_top`、`rear_left`、`rear_right` 四路相机的安装相对位置 `(x, y, z)`、旋转角 `(pitch, yaw, roll)`、视野角 `fov`、屏幕中心归一化坐标 `screen_position` 与画面尺寸 `image_size`。

### 3.3 历史数据与导出页（`session_page.py`）

读取本地 SQLite 数据库，提供实验记录的检索、查看与导出：

1. 会话列表表格：
   - 按状态（全部 / `committed` / `aborted`）筛选；
   - 展示列：会话 ID（`session_id`）、被试编号（`subject_id`）、状态、开始时间、持续时长、地图名、主车蓝图、总帧数（`count_session_frames`）、备注。
2. 会话详情查看：
   - 选中某一行后，查看该次实验锁定的 `RunConfig` JSON 快照，以及该次实验的全部事件表条目（`list_session_events`）。
3. 批量导出（后台线程执行）：
   - 提供“导出全部会话”；
   - 选择输出目录，生成 `sessions.csv`、`data.csv` 和 `events.csv`，通过 `session_id` 关联。

### 3.4 CARLA 工具箱页（`tools_page.py`）

通过图形界面调用 `core/tools.py` 提供的工具函数：

1. 实验录像回放（`.rec`）：
   - 扫描并列出 `data/recordings/` 下的 `.rec` 文件（也支持浏览选择外部文件）；
   - 点击「读取录像信息」调用 `query_recorder_info()` 显示录像摘要或详情；
   - 设置起始时间（`start_time`）、播放时长（`duration`）、倍速（`time_factor`）、跟随 Actor ID，点击「在 CARLA 中回放」调用 `replay_recorder()`。
2. 路网拓扑图导出：
   - 选择路网数据文件，调用 `export_road_network_image()` 生成路网 PNG 图片与坐标 JSON，并在界面内预览或打开输出目录。

### 3.5 控制与按键配置页（`control_page.py`）

管理 `configs/control.toml`，同时展示按键说明对照表：

1. 方向盘硬件设置（`WheelControlConfig`）：
   - 启用方向盘开关（`enable_wheel`）、调试打印按钮编号开关（`show_button_key`）；
   - 本机方向盘设备选择（`device_index`）。
2. 方向盘动作按钮绑定：
   - 列出自动驾驶切换、接管、倒挡、手刹、左/右转向灯、双闪灯；
   - 每个动作选择一个按钮，选项使用 `WheelButton` 的显示标签，例如“右换挡拨片”“红旋钮确认”和“未绑定”；保存对应的枚举字符串。
3. 键盘按键绑定与说明表（`KeyboardControlConfig`）：
   - 列出所有驾驶动作对应的键盘按键与方向盘按钮，每个动作在每种设备上绑定一个键；通过 `KeyboardKey` 与 `WheelButton` 的标签显示名称，并保存到 `configs/control.toml`。

### 3.6 系统设置页（`settings_page.py`）

管理每台实验主机的机器配置 `configs/machine.toml`：

1. CARLA 连接设置（`CarlaConnectionConfig`）：服务端 IP、RPC 端口（默认 `2000`）、Traffic Manager 端口（默认 `8000`）、超时时间。
2. 驾驶显示窗口设置（`DisplayConfig`）：窗口分辨率（建议宽度为 64 的倍数）、全屏模式开关、无边框窗口开关、显示目标帧率（`target_fps`，默认 `60`）。
3. 本地服务与语音设置（`ServiceConfig`）：内置 HTTP/WebSocket 监听地址与端口（默认 `0.0.0.0:7777`）、数据库文件路径与录像目录、TTS 语音播报开关（`enable_tts`）、调试日志开关（`debug`）。

## 远期扩展预留：场景导演与事件触发台（后续规划）

在实际的驾驶实验中，仅靠固定坐标或车距阈值的自动触发规则，难以应对被试车速变化或提前变道等现场情况。后续版本计划在 `launcher` 中扩展面向操作者的「场景导演与事件触发台（Director Console）」：

1. 预定义事件手动/半自动触发面板：
   - 实验前在预设中定义一组实验事件动作包（例如：`[事件 A：请求紧急接管 + 播报危险提示音]`、`[事件 B：前方背景车急刹切入]`、`[事件 C：突变暴雨天气]`、`[事件 D：自定义标记打点]`）。
   - 实验进行时，操作者根据被试的实际表现点击对应事件按钮，由 `launcher` 完成本地语音或音效播报，并按事件性质分两种方式记录：
     - 若该事件包含发往子进程的控制命令（如 `SetTakeoverCommand`、`SetWeatherCommand`），`launcher` 发送该命令，由 `simulator`（或 `traffic`）应用成功后上报对应的实验事件（`source='launcher'`），再由 `launcher` 写入 `event` 表；
     - 纯打点标记（如事件 D）由 `launcher` 生成 `CustomExperimentEvent`，使用打点时的时间戳，并关联最新遥测帧；开启保存时写入 `event` 表。
2. 2D 路网顶视图与轨迹可视化：
   - 基于 CARLA 地图 Waypoint / OpenDRIVE 数据绘制 2D 矢量路网底图；
   - 实时绘制主车位置、朝向与速度矢量，并在接入 `traffic` 模块后展示周围背景车辆的分布与预设轨迹。
3. 背景车辆实时干预（配合 计划中的 `traffic` 模块）：
   - 支持在 2D 地图上选中指定背景车或点击预设动作，向 `traffic` 发送命令控制背景车加减速、变道或沿指定路径行驶。
4. 当前设计中的接口：
   - 协议层：`LauncherCommand` 判别联合类型支持按需新增下行命令子类；`ExperimentEvent` 支持 `CustomExperimentEvent` 与自定义 JSON 负载。
   - 存储层：`event` 表包含 `frame_no`、`timestamp`、`kind`、`name`、`source` 与 `payload_json`，可记录各类剧本事件。
   - 编排层：`ExperimentOrchestrator` 与 `launcher/speech.py` 负责遥测接收、操作者触发语音、命令下发与事件接收。

## 配置与运行状态

文件填写方法见[配置管理](../guide/05-Configuration.md)。数据面板分别展示驾驶人输入和实际车辆控制；自动驾驶期间两组值持续更新。接管请求与控制模式分别显示，切换人工驾驶后解除请求。

相机调整生效后更新界面，点击覆盖或另存直接保存预设。出生点拾取使用最新遥测。系统设置和控制设置在下一次实验启动时使用；服务监听地址与端口在重启管理端后生效。

关闭保存时，控制台显示“调试运行”，实时面板、事件时间线和日志照常显示，本次运行跳过数据库与录像写入。普通调试命令失败时显示错误并继续实验，控制权等关键操作失败时停止实验。
