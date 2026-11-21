# 模块职责与 API 规范

> 文档定位：本文面向项目开发者，规定 DRISCA 的包目录结构、各模块内部文件划分以及跨模块调用的类与函数签名。具体的数据字段定义见 [核心数据结构与协议契约](./02-DataStructures.md)，管理端界面布局与交互流程见 [桌面管理端设计](./04-LauncherDesign.md)。

## 仓库源码目录

`src/drisca/` 下设 5 个顶层业务子包和静态资源目录：

```text
src/drisca/
├── __init__.py
├── assets/                   # 静态资源（图标、平板 HUD HTML 模板等）
├── core/                     # CARLA 接入、配置模型、IPC 协议、静态工具函数
│   ├── __init__.py
│   ├── paths.py              # 项目标准路径常量
│   ├── config.py             # MachineConfig / ControlConfig / PresetConfig / RunSettings / RunConfig 与读写函数
│   ├── protocol.py           # WorkerEvent / LauncherCommand 判别联合类型与序列化
│   ├── client.py             # CarlaSession：显式生命周期的 CARLA 客户端封装
│   ├── weather.py            # WeatherConfig <-> carla.WeatherParameters 转换与预设
│   └── tools.py              # 录像回放 (replay_recorder) 与路网拓扑导出/绘图静态工具
├── storage/                  # SQLite 单库持久化层
│   ├── __init__.py
│   ├── models.py             # SCHEMA_VERSION（由存储层维护）, SessionRow, FrameRow, EventRow, DDL 定义
│   ├── db.py                 # StorageDB：连接校验、会话与事件读写、查询与 CSV 导出
│   └── writer.py             # BatchDataWriter：后台队列 + BEGIN IMMEDIATE 批量写线程
├── simulator/                # 逐帧驾驶模拟子进程（画面合成 + 外设输入 + 物理推进）
│   ├── __init__.py
│   ├── __main__.py           # 子进程入口：解析 --config，运行 SimulatorApp
│   ├── app.py                # SimulatorApp：主循环编排、命令消费、生命周期管理
│   ├── state.py              # DrivingState：C++ 几何计算与 FrameRow/Telemetry 投影
│   ├── vehicle.py            # EgoVehicle：主车生成、手动/自动驾驶控制、车灯管理
│   ├── sensors.py            # SensorSuite & CameraRig：传感器监听与四路相机管理
│   ├── renderer.py           # ViewportRenderer：基于 frombuffer('BGRA') 的画面合成器
│   ├── input.py              # InputController：键盘与方向盘驾驶输入映射
│   ├── wheel_device.py       # WheelDevice：方向盘设备读写与力反馈
│   └── ws_client.py          # WorkerWSClient：后台同步 WebSocket 线程与 loguru sink
├── launcher/                 # Python 后端、Web 界面与桌面壳
│   ├── __main__.py           # 启动服务与可选的 pywebview 无边框窗口
│   ├── runtime.py            # 实验编排、Windows Job Object、语音与正常停机
│   ├── commands.py           # 实验指令库与参数
│   ├── dev.py                # Vite 开发服务启动与回收
│   ├── server.py             # HTTP 接口、SSE 与子进程 WebSocket
│   └── static/               # frontend/ 构建产物与被试 HUD 静态资源
└── traffic/                  # 背景交通流子包（当前阶段仅保留占位；设计见 Architecture）
    └── __init__.py
```

## `core` 模块 API 设计

`core` 层不在模块被 `import` 时连接 CARLA 或读取磁盘文件。

### 2.1 `core/paths.py`

集中管理项目路径：

```python
from pathlib import Path

PACKAGE_ROOT: Path
PROJECT_ROOT: Path
CACHE_ROOT: Path        # PROJECT_ROOT / '.cache'
RUN_CONFIG_DIR: Path    # CACHE_ROOT / 'run'
RECORDER_ROOT: Path     # PROJECT_ROOT / 'data' / 'recordings'
MAP_ROOT: Path          # CACHE_ROOT / 'map'
CONFIG_FILE: Path       # PROJECT_ROOT / 'configs' / 'machine.toml'
CONTROL_FILE: Path      # PROJECT_ROOT / 'configs' / 'control.toml'
PRESETS_DIR: Path       # PROJECT_ROOT / 'configs' / 'presets'

def resolve_db_path(configured_path: str) -> Path:
    """将机器配置中的数据库路径解析为绝对路径（供 launcher 生成 RunConfig.db_path）"""

def ensure_runtime_dirs() -> None:
    """确保 .cache/, .cache/run/, configs/, configs/presets/, data/ 等运行目录存在"""
```

### 2.2 `core/config.py`

负责配置模型的定义与 TOML/JSON 读写：

```python
def load_machine_config(path: Path = CONFIG_FILE) -> MachineConfig:
    """读取 machine.toml；缺少文件时提示复制 machine.example.toml"""

def save_machine_config(config: MachineConfig, path: Path = CONFIG_FILE) -> None:
    """将 MachineConfig 写入 machine.toml"""

def load_control_config(path: Path = CONTROL_FILE) -> ControlConfig:
    """读取 control.toml；缺少文件时提示复制 control.example.toml"""

def save_control_config(config: ControlConfig, path: Path = CONTROL_FILE) -> None:
    """将 ControlConfig 写入 control.toml，按键绑定按枚举字符串保存，unbound 表示未绑定"""

def list_presets(presets_dir: Path = PRESETS_DIR) -> list[str]:
    """列出 configs/presets/ 下实际预设的名称，按 .example.toml 后缀区分示例"""

def load_preset(name_or_path: str | Path) -> PresetConfig:
    """加载指定预设文件并校验为 PresetConfig"""

def save_preset(name: str, preset: PresetConfig, presets_dir: Path = PRESETS_DIR) -> Path:
    """保存预设到 configs/presets/<name>.toml（用于方案配置各标签共享的当前预设保存）"""

def write_run_config(run_config: RunConfig) -> Path:
    """将合成的 RunConfig 写入 .cache/run/<session_id>.json 并返回路径"""

def load_run_config(path: Path) -> RunConfig:
    """子进程启动时从 --config 路径加载不可变 RunConfig"""
```

### 2.3 `core/protocol.py`

负责 WebSocket 上下行消息的强类型序列化与反序列化（基于 Pydantic `TypeAdapter`）：

```python
def dump_worker_event(event: WorkerEvent) -> str: ...
def parse_worker_event(raw_json: str | bytes) -> WorkerEvent: ...

def dump_launcher_command(cmd: LauncherCommand) -> str: ...
def parse_launcher_command(raw_json: str | bytes) -> LauncherCommand: ...
```

### 2.4 `core/client.py`

CARLA 连接由显式创建的 `CarlaSession` 管理：

```python
@dataclass(slots=True, frozen=True)
class PreflightResult:
    ok: bool
    server_version: str = ''
    client_version: str = ''
    current_map: str = ''
    available_maps: tuple[str, ...] = ()
    error: str = ''


class CarlaSession:
    """显式管理单次 CARLA 连接的客户端封装"""
    def __init__(self, conn_cfg: CarlaConnectionConfig) -> None: ...

    def connect(self) -> None:
        """检查端口可达性并建立连接，失败抛出 ConnectionError"""

    def preflight_check(self) -> PreflightResult:
        """供 launcher 启动前预检：返回版本、当前地图与可用地图列表"""

    def prepare_world(self, world_cfg: WorldConfig) -> None:
        """供 launcher 启动实验前调用：按需加载地图、设置初始天气、清理残留车辆与行人"""

    def set_sync_mode(self, enabled: bool, simulation_fps: int = 60) -> None:
        """开启或关闭世界与 TrafficManager 的同步模式（fixed_delta_seconds = 1/simulation_fps 或 0）"""

    def force_reset_after_experiment(self, clear_actors: bool = True) -> None:
        """供 launcher 在子进程退出后调用：强制复位 synchronous_mode = False，并清理全部车辆与行人"""

    def apply_weather(self, weather_cfg: WeatherConfig) -> None:
        """将 WeatherConfig 转换为 carla.WeatherParameters 并应用到世界"""

    @property
    def world(self) -> carla.World: ...
    @property
    def map(self) -> carla.Map: ...
    @property
    def blueprint_library(self) -> carla.BlueprintLibrary: ...
```

### 2.5 `core/tools.py`

提供工具函数供 `launcher` 调用：

```python
def query_recorder_info(session: CarlaSession, rec_file: Path, show_all: bool = False) -> str:
    """读取 .rec 录像文件的摘要或完整帧信息"""

def replay_recorder(
    session: CarlaSession,
    rec_file: Path,
    start_time: float = 0.0,
    duration: float = 0.0,
    time_factor: float = 1.0,
    follow_actor_id: int = 0,
    ignore_hero: bool = True,
) -> None:
    """在 CARLA 服务端触发录像回放"""

```

路网导出与解析暂缓，接口和职责划分待后续确定。

## `storage` 模块 API 设计

### 3.1 `storage/db.py`

负责数据库文件初始化、Schema 版本校验、会话与事件记录的读写，以及查询与 CSV 导出：

```python
class SchemaMismatchError(RuntimeError):
    """当数据库 PRAGMA user_version 与代码 SCHEMA_VERSION 不一致时抛出"""


class StorageDB:
    def __init__(self, db_path: Path) -> None:
        """打开或初始化 SQLite 单库（设置 WAL, synchronous=NORMAL, busy_timeout=5000 并校验 user_version）"""

    # --- 会话与事件写入（由 launcher 调用） ---
    def create_session(self, row: SessionRow) -> None:
        """插入初始 status='running' 的会话记录"""

    def update_session_ego(self, session_id: str, ego_actor_id: int, ego_type_id: str) -> None:
        """收到 simulator 的 WorkerReadyEvent 后回填主车 Actor ID与实际蓝图"""

    def finish_session(self, session_id: str, status: SessionStatus, finished_at: float) -> None:
        """实验结束或异常中止时更新 finished_at 与最终状态 ('committed' | 'aborted')"""

    def update_session_note(self, session_id: str, note: str) -> None:
        """保存操作者在结束实验时填写的会话备注"""

    def delete_sessions(self, session_ids: list[str]) -> None:
        """在同一事务中删除选中会话的逐帧数据、事件与会话记录"""

    def append_events(self, rows: list[EventRow]) -> None:
        """写入事件表。launcher 把子进程上报的 ExperimentEvent 与自身产生的生命周期/状态事件通过此方法写入"""

    def abort_stale_running_sessions(self) -> int:
        """launcher 启动时将上次宿主机断电/崩溃遗留的 'running' 会话统一标记为 'aborted'"""

    # --- 只读浏览与导出（由 launcher 调用） ---
    def list_sessions(self, status_filter: SessionStatus | None = None) -> list[SessionRow]:
        """按启动时间倒序查询历史会话列表"""

    def list_session_events(self, session_id: str) -> list[EventRow]:
        """按时间顺序查询指定会话的全部事件记录"""

    def count_session_frames(self, session_id: str) -> int:
        """统计指定会话已落盘的帧数"""

    def export_sessions(self, output_dir: Path, session_ids: list[str]) -> None:
        """按所选会话导出三个 CSV，保持相同的会话范围"""
```

### 3.2 `storage/writer.py`

供 `simulator` 在运行期异步批量写库：

```python
class BatchDataWriter:
    """后台守护线程批量写入器（每满 500 行或间隔 0.5s 执行一次 BEGIN IMMEDIATE + executemany）"""
    def __init__(self, db_path: Path, batch_size: int = 500, flush_interval: float = 0.5) -> None: ...

    def start(self) -> None: ...

    def enqueue(self, row: FrameRow) -> None:
        """非阻塞入队；主循环按本次 save_data 选择是否调用"""

    def close(self) -> None:
        """通知后台线程提交全部剩余数据，等待线程结束并关闭连接后返回"""
```

## `simulator` 模块 API 设计

`simulator` 是模拟与画面合成子进程，不包含 Pygame 文字图层、不包含 TTS 语音合成、不包含实验剧本钩子、不轮询全图背景车辆。

### 4.1 `simulator/ws_client.py`

```python
class WorkerWSClient:
    """后台 WebSocket 同步客户端：负责上报快照/日志/事件并接收 LauncherCommand"""
    def __init__(self, ws_url: str, role: WorkerRole = WorkerRole.SIMULATOR) -> None:
        """使用 launcher 传入的本机 WebSocket 地址连接"""

    def start(self) -> None:
        """启动后台收发线程并挂载 loguru sink"""

    def publish_telemetry(self, snapshot: TelemetrySnapshotEvent) -> None:
        """替换最新遥测快照单槽（主线程不等待网络发送）"""

    def send_event(self, event: WorkerEvent) -> None:
        """发送一次性事件（如 WorkerReadyEvent、ExperimentEvent 子类）"""

    def poll_commands(self) -> list[LauncherCommand]:
        """供主循环每帧开头非阻塞取出所有待处理的下行控制命令"""

    def close(self) -> None:
        """发送完剩余日志与事件后关闭 WebSocket，并等待收发线程结束"""
```

### 4.2 `simulator/renderer.py`

负责相机画面合成：

```python
class ViewportRenderer:
    """pygame-ce 窗口渲染器：合成主视图与三路后视镜，不渲染任何文字面板"""
    def __init__(self, display_cfg: DisplayConfig) -> None: ...

    @property
    def actual_resolution(self) -> tuple[int, int]:
        """返回窗口实际像素尺寸（全屏模式下为显示器真实分辨率），供主相机初始化使用"""

    def update_layout(self, layout: DisplayLayoutConfig) -> None:
        """更新后视镜显隐、屏幕归一化位置与显示尺寸"""

    def render_frame(self, images: dict[str, carla.Image | None]) -> None:
        """使用 pygame.image.frombuffer(raw_data, size, 'BGRA') 将四路画面合成并 flip 上屏"""

    def close(self) -> None: ...
```

### 4.3 `simulator/app.py`

```python
class SimulatorApp:
    """模拟器主控类：管理逐帧驾驶循环与各组件生命周期"""
    def __init__(self, run_config: RunConfig) -> None: ...

    def run(self) -> None:
        """
        1. 初始化窗口、方向盘、CARLA 连接、主车与传感器，开启保存时打开 RunConfig.db_path 对应的 BatchDataWriter
        2. 发送 WorkerReadyEvent(ego_actor_id, ego_type_id)
        3. 按世界帧运行驾驶循环，同步步长取预设 simulation_fps：
           - poll_commands() 处理 Stop / SetAutopilot / SetTakeover / SetWeather / UpdateCamera / UpdateLayout，应用成功后上报对应的 ExperimentEvent 子类 (source='launcher')
           - 采集键盘与方向盘驾驶输入，施加车辆控制；离散驾驶动作（自动驾驶、接管、倒挡、档位、手刹、车灯）应用后上报对应的 ExperimentEvent 子类 (source='wheel'|'keyboard')
           - 推进或等待世界帧，更新 DrivingState
           - render_frame() 合成画面上屏
           - 按 save_data 选择是否 enqueue(to_frame_row())，按实际经过时间约 20 至 30 Hz publish_telemetry()
        4. 退出时按顺序 Flush 数据库、停止 CARLA Recorder、销毁传感器与主车、关闭窗口
        """
```

## `launcher` 模块职责

管理端使用 Web 界面与 Python 后端。页面划分见[管理端设计](./04-LauncherDesign.md)，通信方式见[前后端通信](./10-LauncherWeb.md)。上面的管理端文件划分用于说明职责，具体接口随实现确定。

`orchestrator.py` 组合使用 CARLA 接入、配置与存储组件，负责预检、准备世界、生成会话编号、合成运行配置、启动模拟器、接收消息与实验收尾。实验状态依次为 `idle`、`starting`、`running`、`stopping`。

进程使用 `subprocess.Popen`，以 `sys.executable -m drisca.simulator --config <path>` 启动，捕获标准输出、错误输出和退出码，并加入 Job Object。正常结束时发送已有停止命令，等待数据和事件提交、子进程退出，再复位世界、清理场景并完成会话记录。停机超时则强制结束进程并标记会话异常。

`web.py` 提供配置读写、实验操作、数据查询与目录导出接口，通过 SSE 推送状态、遥测、日志和事件，沿用本地 WebSocket 接收模拟器消息。桌面窗口与浏览器访问同一服务。

`speech.py` 负责管理端的语音播放。pywebview 桥负责窗口最小化、最大化与关闭，关闭窗口使用编排器的正常停机流程。

## 配套约定

配置读写按[配置模型](./08-ConfigurationModels.md)执行，保存使用临时文件替换。预设列表通过 `.example.toml` 后缀识别示例。子进程启动时以实际配置建立硬件和连接。

`SimulatorApp` 每帧分别记录驾驶人输入和车辆实际控制，维护控制模式与接管请求。碰撞与压线从传感器回调生成事件，上报后由 launcher 统一写库。`WorkerWSClient` 沿用事件上报，命令错误通过关联命令编号的日志报告，消息字段见[进程通信](./07-Protocol.md)。

管理端接入时，将现有 `export_sessions` 扩展为上述所选会话接口，三个 CSV 使用同一会话范围导出到配置目录。页面交互见[管理端设计](./04-LauncherDesign.md)。录像目录取机器配置的 `recorder_dir`，录像受保存总开关控制。

关闭保存时，管理端跳过会话和事件数据库操作，驾驶端跳过存储线程与 Recorder 的启动。正常停机只关闭本次实际打开的资源，关闭保存时保留实时遥测、事件时间线和日志显示。

方向盘使用单个 `WheelDevice` 封装 pygame 和罗技 SDK 的设备访问。输入模块组合使用该设备对象，方向盘随动配置保留，功能后续实现。

## 按键与设备映射

`core.config` 定义 `KeyboardKey`、`WheelButton`，以及名称到界面显示标签的纯数据表。配置字段使用单个枚举值。界面以枚举值保存选项，以标签显示名称。

`simulator/input.py` 使用 `KEYBOARD_CODES` 将 `KeyboardKey` 映射到 pygame 常量，例如 `KeyboardKey.SPACE → pygame.K_SPACE`、`KeyboardKey.KEYPAD_1 → pygame.K_KP1`。输入处理将动作对应的单个按键与事件或按下状态直接比较。

`simulator/wheel_device.py` 使用 `WHEEL_BUTTON_CODES` 和 `WHEEL_AXES` 保存按钮、物理轴的编号。当前设备布局如下，后续调整集中在该模块。

| 按钮名称 | 界面标签 | 当前编号 |
| --- | --- | --- |
| `cross` | X 键 | 0 |
| `square` | 方块键 | 1 |
| `circle` | 圆圈键 | 2 |
| `triangle` | 三角键 | 3 |
| `right_paddle` | 右换挡拨片 | 4 |
| `left_paddle` | 左换挡拨片 | 5 |
| `r2` | R2 键 | 6 |
| `l2` | L2 键 | 7 |
| `share` | Share 键 | 8 |
| `options` | Options 键 | 9 |
| `r3` | R3 键 | 10 |
| `l3` | L3 键 | 11 |
| `plus` | 加号键 | 19 |
| `minus` | 减号键 | 20 |
| `dial_right` | 红旋钮右旋 | 21 |
| `dial_left` | 红旋钮左旋 | 22 |
| `dial_press` | 红旋钮确认 | 23 |
| `logo` | Logo 键 | 24 |

物理轴使用 `steering → 0`、`throttle → 1`、`brake → 2`。配置保存动作到按钮名称的关系，轴号与按钮编号由设备模块维护。按钮编号日志继续由 `show_button_key` 控制。

## 前端源码

正式前端位于仓库根目录 `frontend/`，使用 Bun、Vite、React、TypeScript、Tailwind CSS 与 shadcn/ui，构建到 `src/drisca/launcher/static/`。管理端以同源 HTTP 提供静态资源与业务接口。定稿原型位于 `prototypes/launcher/`，保留 Basecoat 与 Alpine.js，作为布局和交互依据。
