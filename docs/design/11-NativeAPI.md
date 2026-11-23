# 原生 WebSocket 接口

Launcher 和 simulator 通过本机 WebSocket 访问 CARLA Unreal。Launcher 管理场景与实验流程，simulator 持有当前实验的驾驶视图、采集数据并转发事件。Python 使用自己的数值类型和 NumPy 数组，原生侧复用 CARLA 的地图、车辆、传感器与 Recorder。

## 连接与消息

地址为 `ws://127.0.0.1:7910/drisca/v1`，主机与端口来自机器配置的 driving_view。原生服务由 GameInstance 管理，地图切换保留连接。每个服务实例有 server_instance，每次世界切换更新 world_id，客户端据此清理地图与对象缓存。

WebSocket 文本消息承载 UTF-8 JSON，二进制消息承载完整快照。两端完整消息上限为 8 MiB，关闭消息压缩。Python 使用 websockets，原生使用 Beast/Asio。每连接同时只有一个业务请求，完整发送与响应读取串行执行。

原生网络在游戏线程推进，地图加载期间暂停响应。Python 本机连接关闭主动 keepalive，以地图加载请求的启动超时等待完成；普通请求仍使用请求超时，断线直接报错。地图加载完成后继续使用原连接和新的 world_id。

连接后首先校验 hello：

```json
{"id":1,"method":"hello","params":{"protocol_version":1,"client":"drisca-worker"}}
```

响应包含 protocol_version、server_instance、world_id、map_name，以及 snapshot_header_bytes=48、vehicle_record_bytes=96、research_record_bytes=128。两端采用同一协议版本和字段布局。

普通请求包含 id、method、params。成功响应为 id、ok=true、result；失败为 id、ok=false、error，error 含 code、message，批次错误还保留逐项 results。世界相关请求携带 world_id，活动实验操作携带 session_id。

## 批次与帧关联

batch 按顺序提交多项操作，仅返回 JSON；exchange 提交同样的 operations，成功后先返回 JSON，再返回一条二进制快照。JSON 包含逐项 results、events、traffic_lights、traffic_controllers、control_state，并以 snapshot=true 声明后续快照。

每项操作包含 method 与 params。原生在游戏线程受理操作，等待下一次物理更新结束后完成 exchange，frame_no 表示刚完成的物理帧。applied_frame_no 表示操作生效的物理更新，sampled_frame_no 表示查询所依据的完整采样。世界在网络等待期间继续异步推进。

异步世界的 FixedDeltaSeconds 保持未设置，仿真时间来自当前世界的 GetTimeSeconds，与 IMU/GNSS 同源。simulation_fps 控制物理子步最大间隔，子步数覆盖最长 0.2 秒帧；例如 60 Hz 对应最多 12 个子步。该设置维持低帧率时的物理时间推进，实际画面与交换频率由运行负载决定。

```json
{"id":20,"method":"exchange","params":{"world_id":1,"session_id":"session-id","operations":[{"method":"environment.update","params":{"weather":{"cloudiness":0.5},"transition_seconds":3}}]}}
```

格式错误直接报错，执行错误保留此前成功操作，后续操作标记 skipped。过期控制的 skipped/control_superseded 是可识别结果，客户端刷新模式后重新决策。发生协议漂移、非法快照、连接中断或事件队列溢出时，实验按失败路径收尾。

## 二进制布局与单位

一条二进制消息由 48 字节头、N 条 96 字节车辆记录、M 条 128 字节研究记录组成；M 为 0 或 1，消息长度为 `48 + 96 * N + 128 * M`。所有字段紧密排列、小端序。物理量为 float32，时间为 int64 微秒，整数身份使用明确宽度。

### 快照头

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | request_id | uint32 |
| 4 | vehicle_count | uint32 |
| 8 | world_id | uint64 |
| 16 | frame_no | uint64 |
| 24 | simulation_time_us | int64 |
| 32 | wall_time_us | int64 |
| 40 | delta_seconds | float32 |
| 44 | research_count | uint32 |

### 车辆记录

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | actor_id | uint32 |
| 4 | flags | uint32 |
| 8 | location | float32 × 3 |
| 20 | rotation | float32 × 3 |
| 32 | velocity | float32 × 3 |
| 44 | angular_velocity | float32 × 3 |
| 56 | acceleration | float32 × 3 |
| 68 | throttle、steer、brake | float32 × 3 |
| 80 | gear | int32 |
| 84 | speed_limit_mps | float32 |
| 88 | road_id | int32 |
| 92 | lane_id | int32 |

flags 的 bit0 为 reverse、bit1 为 hand_brake、bit2 为 manual_gear_shift、bit3 为 dormant、bit4 为 road_valid。bits8..9 表示来源：0=manual/human，1=官方 TM 保留，2=external/python，3=未归属。每帧返回当前有效车辆，按 actor_id 排序；静态包围盒、蓝图和属性通过 vehicle.describe 获取。

### 主车研究记录

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | actor_id | uint32 |
| 4 | validity_flags | uint32 |
| 8 | input_throttle、input_steer、input_brake | float32 × 3 |
| 20 | input_flags | uint32 |
| 24 | input_gear | int32 |
| 28 | imu_frame_no | uint64 |
| 36 | imu_simulation_time_us | int64 |
| 44 | gnss_frame_no | uint64 |
| 52 | gnss_simulation_time_us | int64 |
| 60 | accelerometer | float32 × 3 |
| 72 | gyroscope | float32 × 3 |
| 84 | compass | float32 |
| 88 | longitude、latitude、altitude | float32 × 3 |
| 100 | road_direction | float32 × 3 |
| 112 | lane_width | float32 |
| 116 | lane_offset | float32 |
| 120 | lane_type | uint32 |
| 124 | collision_intensity | float32 |

validity_flags 的 bit0 为 IMU 有效、bit1 为 GNSS 有效、bit2 为道路有效、bit3 为视图 active、bit4 为研究 ready。input_flags 的 bit0 为 reverse、bit1 为 hand_brake、bit2 为 manual_gear_shift、bit3 为主动接管动作。

坐标沿用 CARLA：X 向前、Y 向右、Z 向上，位置为米。rotation 顺序是 pitch/yaw/roll，单位度；角速度为度每秒，IMU 陀螺仪为 rad/s，compass 为 rad，加速度为 m/s²，经纬度为度。wall_time_us 是 Unix UTC 时间，simulation_time_us 自当前世界开始累计。GNSS 经纬度 float32 有量化误差，几何计算使用世界位置。

Python 使用显式 dtype 和 numpy.frombuffer，研究记录按上表偏移解释。原生显式写入字段，数组持有完整消息缓冲区。客户端核对 JSON 与二进制的 request_id、world_id 和 frame_no，投影时验证主车身份、研究有效性和有限数值。

## 操作范围

| 分组 | 方法 |
| --- | --- |
| 服务 | hello、server.status |
| 场景 | scene.catalog、scene.load_map、scene.set_world、scene.clear_actors |
| 环境 | environment.get、environment.apply、environment.update、environment.create、environment.list、environment.delete |
| 车辆 | vehicle.spawn、vehicle.describe、vehicle.destroy、vehicle.set_mode、vehicle.apply_control、vehicle.set_lights |
| 视图 | driving_view.start、driving_view.update、driving_view.get_config、driving_view.stop |
| 道路 | road.query、scene.road_graph、scene.road_junctions、scene.road_signals |
| 信号 | traffic_light.set_state、traffic_controller.set_timing、traffic_light_group.freeze、traffic_light_group.reset、traffic_light.freeze_all |
| 录像 | recorder.start、recorder.stop、recorder.info、recorder.replay |
| 实验 | experiment.stop |

环境接口取代旧的 scene.get_weather、scene.set_weather 与 RPC 天气写入，旧入口返回 unsupported。相机、镜面与键盘参数沿用配置模型。道路与信号目录使用独立请求，在实验准备时获取；运行期信号与车辆状态按完整帧返回。

## 环境控制

原生子系统持有唯一的全局环境状态（`current` / `target`）与过渡时钟，直接驱动天空、光照、雾和降水。

### 全局环境

`environment.apply` 提交完整全局 `weather`，`environment.update` 提交部分字段；嵌套对象同样按提供字段部分更新，其余字段沿用原目标。`transition_seconds` 为非负有限秒数（默认 `0`），按世界仿真时钟插值。新命令以当前状态为起点向合并后的目标重新开始过渡；太阳方位按最短弧插值，恰好差 180 度时沿正向转动。

`environment.get` 不带 `region_id` 时返回 `{region_id: null, current: {weather: ...}, target: {weather: ...}, remaining_seconds, deleting: false}`。`scene.catalog` 的 `weather_presets` 返回新全局结构加同级 `preset_name`，`Default` 展开为明确全值。Python 在提交前将命名预设展开为完整 `weather`。

全局 `weather` 包含 14 项功能字段与 1 项雪效占位字段（`precipitation.snow`，当前固定为 `0`，非零返回 `unsupported`）：

| 字段 | 范围或单位 | 含义 |
| --- | --- | --- |
| sun.azimuth_deg | [0, 360) 度 | 太阳方位 |
| sun.elevation_deg | [-90, 90] 度 | 太阳高度 |
| cloudiness | [0, 1] | 云量强度 |
| wind | [0, 1] | 视觉风强度（独立于车辆侧向物理力） |
| dust | [0, 1] | 尘暴效果输入 |
| precipitation.rain | [0, 1] | 降雨粒子与后处理强度 |
| precipitation.snow | 仅 0 | 雪效占位，非零返回 `unsupported` |
| surface.wetness | [0, 1] | 路面湿润外观 |
| surface.puddles | [0, 1] | 路面材质积水强度 |
| fog.density | [0, 100] | 直接写入 UE 高度雾密度（无旧 0.001 缩放） |
| fog.distance_m | [0, 1000000] 米 | 高度雾起始距离 |
| fog.height_falloff | [0, 10000] | UE 高度雾衰减系数 |
| scattering.light | [0, 1000] | 太阳光体积散射强度 |
| scattering.mie | [0, 1000] | 大气 Mie 散射缩放 |
| scattering.rayleigh | [0, 1000] | 大气 Rayleigh 散射缩放 |

上述数值均为原生引擎渲染参数，能见距离与降水量标定在后续校准阶段建立映射关系。

### 局部球雾

局部区域表示固定在世界空间中的球形雾区，对应 UE `ALocalFogVolume` 组件：

- `environment.create` 接收 `center_m`（米）、`radius_m`（`(0, 100000]` 米）、`weather.fog.density`（`[0, 1]`）和可选 `transition_seconds`；局部雨雪与地表通道返回 `unsupported`。
- `environment.get`、`environment.update`、`environment.delete` 按 `region_id` 操作，`environment.list` 返回全部活跃区域 `regions`。
- `current` 与 `target` 统一使用 `{center_m, radius_m, weather: {fog: {density}}}` 结构。
- 密度 `0–1` 线性映射为 UE 径向消光 `0–2`；高度项在球内设为均匀饱和（`HeightFogFalloff=1`、`HeightFogOffset=2`、`HeightFogExtinction=50`）以由径向消光独立控制浓淡，并将局部雾全局起始距离 `r.LocalFogVolume.GlobalStartDistance` 下调至 `10 cm`。多个球雾按原生光学叠加合成，重叠区域浓度自然叠加。
- `environment.delete` 支持渐隐时长，渐隐期间区域保持 `deleting: true` 并拒绝再次修改，完成后销毁。

### 生命周期与事件

- **归属与清理**：同一 worker 控制连接在 `driving_view.start` 前创建的区域随 `start` 转入会话；管理连接在空闲期创建的区域归属原连接。实验停止、控制连接异常和地图加载按归属清理区域；地图加载同时将全局环境重置为新地图默认值，下次实验由 Python 重新提交初始环境。
- **环境事件**：包括 `environment_applied`、`environment_completed`、`environment_replaced`，外层 `native` 元数据与其他事件一致；全局事件 `region_id` 为 `null`，局部事件为数字。
  - `applied` 携带 `operation`、`previous`、`transition_seconds`；零时长操作仅触发 `applied`。
  - `completed` 沿用原 `operation`。
  - `replaced` 记录旧 `current` / `target` / `operation` 以及新 `request_id`、`operation_index`、`operation`、`target`；实验停止时被中断的全局过渡携带 `reason=session_ended`，不含 `new_*`。
  - 完成与替换事件可跨 `exchange` 到达，客户端按请求关联维护未完成操作表并在终态释放。

### 录像与环境重现

普通车辆录像的 `recorder.replay` 固定关闭 `ReplayWeather`，仅回放车辆与传感器；请求 `replay_weather=true` 返回错误。全局与局部环境通过 DRISCA 保存的初始配置和环境事件记录独立重现。

## 车道图与信号

scene.road_graph 按 world_id 与 sampling_step 构建缓存，cursor 分页，max_lanes 默认 200、上限 500。服务在发送前核对实际 UTF-8 消息大小，页预算约 6 MiB；单条超限明确报错。每个节点以 road:section:lane 标识，包含车道类型、前驱后继、相邻与同向关系、沿 s 变化的 marking_segments，以及有序中心线。

方向采用原生 IsPositiveDirection，左右采用驾驶人视角；车道编号符号本身不决定方向。s 是从行驶起点算的参考线距离，road_s 是 OpenDRIVE 参考线坐标。换道判断同时使用当前位置的分段标记和同向关系。

road_signals 分别保留 OpenDRIVE signal/controller/junction 身份与运行期 actor/controller/group 身份。association 和 unmapped 明确表示映射情况；运行期相位以真实控制器为准。地图中已放置灯可能缺少触发盒元数据，Python 根据信号引用、有效车道与中心线推导停止位置，标注 derived 并保留配置偏移。

exchange 中 traffic_lights 返回实际灯色与冻结状态，traffic_controllers 返回真实阶段、配时与计时。非激活控制器的阶段状态为 null，冻结时计时保持。信号操作按单灯、控制器、组或全部组的真实作用域执行并记录事件。

## 控制归属、事件与停止

成功 start 的 worker 连接持有活动视图。重复 start 返回 `driving view is already active, use update to change it`。management 连接使用 batch 查询与调参，控制连接使用 exchange 取得实验事件。

每辆受控车维护独立 revision。活动实验的 set_mode 与 apply_control 必须携带 expected_control_revision；模式变化与原生接管递增对应车辆版本，其他车辆保持自己的版本。control_state 返回 actor_id、mode、controller 与 revision。

P 产生 driver_request，由 Python 决定是否启用模型；反斜杠原生立即恢复人工并产生 toggle_takeover。external 期间仍持续采样人工输入。已接管车辆的旧控制被跳过，客户端根据当前模式重新决策。

离散事件按 event_id 累计交付，保留发生帧、仿真时间、墙钟时间与请求关联。正常 experiment.stop 交付最后事件，停止归属 Recorder、释放实验对象并恢复自由视角；Unreal 留给下一次实验。控制连接异常断开由原生完成收尾，Python 报错退出，Launcher 记录 aborted。普通管理连接断开只释放连接。

recorder.start 拒绝抢占其他来源的活动录像。正常停止和异常收尾只处理本服务归属录像；recorder.stop 在无归属时返回 invalid_state。客户端据此维护明确生命周期。
