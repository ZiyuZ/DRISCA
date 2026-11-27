# DRISCA WebSocket 接口

`launcher` 和 `simulator` 通过本机 WebSocket 访问 CARLA Unreal 内嵌的 `DriscaApi` 服务。Python 侧使用自有数值类型和 NumPy 零拷贝解析二进制快照，运行期不依赖官方 `carla` Python wheel。

## 连接与传输机制

- **服务地址**：`ws://127.0.0.1:7910/drisca/v1`（主机与端口由 `machine.toml` 的 `[driving_view]` 决定）。
- **生命周期**：`DriscaApi` 服务端由 `GameInstance` 托管，切换地图时保持 TCP/WS 连接不断开；每次世界切换递增 `world_id`，客户端据此刷新路网与对象缓存。
- **消息约束**：文本帧承载 UTF-8 JSON，二进制帧承载完整世界快照；单条消息上限 `8 MiB`，关闭 WebSocket 压缩与自动分片，服务端与 Python 客户端均启用 `TCP_NODELAY`。
- **帧内推进优化**：WebSocket 服务在游戏线程运行，除了常规的物理后推进外，新增了**物理前非阻塞网络推进**——及时到达的控制操作可在当帧物理更新前立即应用并在当帧结束后采样，显著降低 `exchange` 往返等待延迟；物理后受理的操作则等待下一次完整物理更新。

### 握手校验

连接建立后先发送 `hello` 确认协议版本与二进制记录字节长度：

```json
{"id": 1, "method": "hello", "params": {"protocol_version": 1, "client": "drisca-worker"}}
```

服务端返回 `protocol_version`、`server_instance`、`world_id`、`map_name` 以及固定的二进制布局尺寸：`snapshot_header_bytes=48`、`vehicle_record_bytes=96`、`research_record_bytes=128`。

## 批次与帧交换（`batch` / `exchange`）

- **`batch`**：按顺序执行多条 `operations`，仅返回 JSON 响应（含逐项 `results`）。
- **`exchange`**：执行 `operations` 后等待完整物理帧采样，先返回一条 JSON 响应（含 `results`、`events`、`traffic_lights`、`traffic_controllers`、`control_state`、`applied_frame_no`、`sampled_frame_no`、`selected_actor_id`、`selected_signal_actor_id`，以及 `snapshot: true`），紧接着发送一条二进制快照帧。
- **异步世界与物理子步**：异步世界保持 `FixedDeltaSeconds` 未设置，仿真时间取自 `World->GetTimeSeconds()`（与 IMU/GNSS 同源）；`simulation_fps` 控制物理子步最大步长，子步数覆盖最长 `0.2 s` 单帧。

## 二进制快照布局

每条二进制消息按小端序紧密排列，总长度为 `48 + 96 * N + 128 * M`（`M` 为 `0` 或 `1`）：

### 快照头（48 字节）

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | `request_id` | `uint32` |
| 4 | `vehicle_count` (`N`) | `uint32` |
| 8 | `world_id` | `uint64` |
| 16 | `frame_no` | `uint64` |
| 24 | `simulation_time_us` | `int64` |
| 32 | `wall_time_us` | `int64` |
| 40 | `delta_seconds` | `float32` |
| 44 | `research_count` (`M`) | `uint32` |

### 车辆记录（96 字节 × N）

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | `actor_id` | `uint32` |
| 4 | `flags` | `uint32` |
| 8 | `location` (`x, y, z`) | `float32 × 3` |
| 20 | `rotation` (`pitch, yaw, roll`) | `float32 × 3` |
| 32 | `velocity` | `float32 × 3` |
| 44 | `angular_velocity` | `float32 × 3` |
| 56 | `acceleration` | `float32 × 3` |
| 68 | `throttle, steer, brake` | `float32 × 3` |
| 80 | `gear` | `int32` |
| 84 | `speed_limit_mps` | `float32` |
| 88 | `road_id` | `int32` |
| 92 | `lane_id` | `int32` |

`flags` 位定义：`bit0=reverse`、`bit1=hand_brake`、`bit2=manual_gear_shift`、`bit3=dormant`、`bit4=road_valid`；`bits 8..9` 表示控制来源（`0=manual`、`1=reserved`、`2=external/python`、`3=unowned`）。

### 主车研究记录（128 字节 × M）

| 偏移 | 字段 | 类型 |
| --- | --- | --- |
| 0 | `actor_id` | `uint32` |
| 4 | `validity_flags` | `uint32` |
| 8 | `input_throttle, input_steer, input_brake` | `float32 × 3` |
| 20 | `input_flags` | `uint32` |
| 24 | `input_gear` | `int32` |
| 28 | `imu_frame_no` / `imu_simulation_time_us` | `uint64` / `int64` |
| 44 | `gnss_frame_no` / `gnss_simulation_time_us` | `uint64` / `int64` |
| 60 | `accelerometer` | `float32 × 3` |
| 72 | `gyroscope` | `float32 × 3` |
| 84 | `compass` | `float32` |
| 88 | `longitude, latitude, altitude` | `float32 × 3` |
| 100 | `road_direction` | `float32 × 3` |
| 112 | `lane_width` / `lane_offset` | `float32` / `float32` |
| 120 | `lane_type` | `uint32` |
| 124 | `collision_intensity` | `float32` |

`validity_flags`：`bit0=IMU`、`bit1=GNSS`、`bit2=road`、`bit3=view_active`、`bit4=research_ready`。坐标系沿用 CARLA（X 向前、Y 向右、Z 向上，位置单位 m，角度单位 deg，速度单位 m/s，加速度单位 m/s²）。

## 接口分组总览

| 分组 | 方法 |
| --- | --- |
| 服务与场景 | `hello`、`server.status`、`scene.catalog`、`scene.load_map`、`scene.set_world`、`scene.clear_actors` |
| 环境与局部雾 | `environment.get`、`environment.apply`、`environment.update`、`environment.create`、`environment.list`、`environment.delete` |
| 车辆控制 | `vehicle.spawn`、`vehicle.describe`、`vehicle.destroy`、`vehicle.set_mode`、`vehicle.apply_control`、`vehicle.set_lights` |
| 驾驶与观察视图 | `driving_view.start`、`driving_view.update`、`driving_view.get_config`、`driving_view.stop` |
| 路网与信号 | `road.query`、`scene.road_graph`、`scene.road_junctions`、`scene.road_signals`、`traffic_light.set_state`、`traffic_controller.set_timing`、`traffic_light_group.freeze`、`traffic_light_group.reset`、`traffic_light.freeze_all` |
| 录像与回放 | `recorder.start`、`recorder.stop`、`recorder.info`、`recorder.replay`、`recorder.stop_replay` |
| 调试与标注 | `debug.highlight_actor`、`debug.highlight_path`、`experiment.stop` |

### 关键特性说明

- **三视角与回放接管**：`driving_view.update` 支持在 `free`、`cockpit`、`chase` 三种视角间平滑切换。追尾视角内置相机去抖、滚轮调距（4–18 m）与右键环视自动回正；自由视角支持点击拾取车辆（`selected_actor_id`）与路口信号灯（`selected_signal_actor_id`）。录像回放期间可直接调用 `driving_view.update` 并传入 `actor_id_space: "recorded"` 接管三视角与切车，退出回放或切回 `free` 时自动将 Spectator 对齐到车尾上方高空位姿。
- **环境唯一权威**：环境子系统唯一持有全局天气状态（`current` / `target`）与过渡时钟，并管理世界空间球形局部雾（`ALocalFogVolume` 归一化径向衰减）。旧 CARLA RPC 天气写入已显式禁用。
- **调试与屏幕提示抑制**：`scene.set_world` 支持 `suppress_screen_messages` 控制 VSM 溢出等引擎调试文字显示；`debug.highlight_actor` 与 `debug.highlight_path` 用于运行期可视化标注车辆与规划轨迹。
