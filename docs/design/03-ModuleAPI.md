# 模块职责与 API 规范

> 文档定位：本文面向项目开发者，规定 DRISCA 的包目录结构、各模块内部文件划分以及跨模块调用的类与函数签名。具体的数据字段定义见 [核心数据结构与协议契约](./02-DataStructures.md)，桌面界面布局与交互流程见 [桌面管理端设计](./04-LauncherDesign.md)。

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
│   ├── models.py             # SCHEMA_VERSION = 5, SessionRow, DataRow, EventRow, DDL 定义
│   ├── db.py                 # StorageDB：连接校验、会话与事件读写、查询与 CSV 导出
│   └── writer.py             # BatchDataWriter：后台队列 + BEGIN IMMEDIATE 批量写线程
├── simulator/                # 60Hz 模拟器子进程（画面合成 + 外设输入 + 物理推进）
│   ├── __init__.py
│   ├── __main__.py           # 子进程入口：解析 --config / --preset，运行 SimulatorApp
│   ├── app.py                # SimulatorApp：主循环编排、命令消费、生命周期管理
│   ├── state.py              # RuntimeFrameData：C++ 几何计算与 DataRow/Telemetry 投影
│   ├── vehicle.py            # EgoVehicle：主车生成、手动/自动驾驶控制、车灯管理
│   ├── sensors.py            # SensorSuite & CameraRig：传感器监听与四路相机管理
│   ├── renderer.py           # ViewportRenderer：基于 frombuffer('BGRA') 的画面合成器
│   ├── input.py              # InputController：键盘与方向盘驾驶输入映射
│   ├── wheel_device.py       # WheelDevice & LogitechWheelDevice：方向盘硬件封装
│   └── ws_client.py          # WorkerWSClient：后台同步 WebSocket 线程与 loguru sink
├── launcher/                 # 桌面管理端与 Web HUD 宿主（唯一对外入口）
│   ├── __init__.py
│   ├── __main__.py           # 唯一用户入口 (drisca)：启动 Qt 主循环与后台 uvicorn
│   ├── orchestrator.py       # ExperimentOrchestrator：预检、会话创建、QProcess 监管、同步模式复位
│   ├── jobobject.py          # Windows Job Object：子进程随 launcher 退出
│   ├── events.py             # TelemetryEventWatcher & TTSSpeaker：基于遥测流触发语音播报与接管命令
│   ├── web.py                # FastAPI 宿主：/ws/worker/{role}、HUDHub、SSE /stream 与平板页面
│   └── ui/                   # PySide6 + Fluent Widgets 桌面界面（详见 LauncherDesign.md）
│       ├── __init__.py
│       ├── main_window.py    # Fluent 主窗口导航（6 个一级页面）
│       ├── run_page.py       # 实验控制台：预检、启停、调试面板（运行期控制、实时调相机、拾取出生点、覆盖或另存预设）、数据面板、日志与事件流
│       ├── preset_page.py    # 预设页：静态读写 presets/*.toml（地图天气、主车与出生点、四路相机参数）
│       ├── session_page.py   # 历史数据：会话列表、事件时间线查看、导出 data.csv 与 events.csv
│       ├── tools_page.py     # CARLA 工具：录像回放 (.rec) 与路网图生成
│       ├── control_page.py   # 控制与按键：读写 control.toml（方向盘灵敏度、按钮映射、按键对照表）
│       └── settings_page.py  # 系统设置：读写 machine.toml（CARLA 连接、显示器、服务端口、TTS）
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
CACHE_ROOT: Path        # PROJECT_ROOT / 'cache'
RUN_CONFIG_DIR: Path    # CACHE_ROOT / 'run'
RECORDER_ROOT: Path     # CACHE_ROOT / 'carla_recorder'
MAP_ROOT: Path          # CACHE_ROOT / 'map'
CONFIG_FILE: Path       # PROJECT_ROOT / 'config' / 'machine.toml'
CONTROL_FILE: Path      # PROJECT_ROOT / 'config' / 'control.toml'
PRESETS_DIR: Path       # PROJECT_ROOT / 'presets'

def resolve_db_path(db_name_prefix: str = 'experiment', schema_version: int = 5) -> Path:
    """根据前缀与 Schema 版本号生成标准 SQLite 数据库文件路径（供 launcher 生成 RunConfig.db_path）"""

def ensure_runtime_dirs() -> None:
    """确保 cache/, cache/run/, config/, presets/ 等运行目录存在"""
```

### 2.2 `core/config.py`

负责配置模型的定义与 TOML/JSON 读写：

```python
def load_machine_config(path: Path = CONFIG_FILE) -> MachineConfig:
    """读取 machine.toml；文件不存在时返回默认 MachineConfig()"""

def save_machine_config(config: MachineConfig, path: Path = CONFIG_FILE) -> None:
    """将 MachineConfig 写入 machine.toml"""

def load_control_config(path: Path = CONTROL_FILE) -> ControlConfig:
    """读取 control.toml；文件不存在时返回默认 ControlConfig()"""

def save_control_config(config: ControlConfig, path: Path = CONTROL_FILE) -> None:
    """将 ControlConfig 写入 control.toml（注：TOML 无 null 字面量，方向盘按钮为 None 时在 TOML 中以 -1 存储并在读取时转回 None）"""

def list_presets(presets_dir: Path = PRESETS_DIR) -> list[str]:
    """列出 presets/ 下所有可用的预设名称（不含 .toml 后缀）"""

def load_preset(name_or_path: str | Path) -> PresetConfig:
    """加载指定预设文件并校验为 PresetConfig"""

def save_preset(name: str, preset: PresetConfig, presets_dir: Path = PRESETS_DIR) -> Path:
    """保存预设到 presets/<name>.toml（用于预设页保存、调试面板覆盖当前预设或另存为新预设）"""

def write_run_config(run_config: RunConfig) -> Path:
    """将合成的 RunConfig 写入 cache/run/<session_id>.json 并返回路径"""

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

    def set_sync_mode(self, enabled: bool, fps: int = 60) -> None:
        """开启或关闭世界与 TrafficManager 的同步模式（fixed_delta_seconds = 1/fps 或 0）"""

    def force_reset_after_experiment(self, clear_actors: bool = True) -> None:
        """供 launcher 在子进程退出后兜底调用：强制复位 synchronous_mode = False，并清理全部车辆与行人"""

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

def export_road_network_image(map_name: str, pickle_file: Path, output_dir: Path = MAP_ROOT) -> Path:
    """将路网拓扑数据绘制成 PNG 与坐标 JSON"""
```

## `storage` 模块 API 设计

### 3.1 `storage/db.py`

负责数据库文件初始化、Schema 版本校验、会话与事件记录的读写，以及查询与 CSV 导出：

```python
class SchemaMismatchError(RuntimeError):
    """当数据库 PRAGMA user_version 与代码 SCHEMA_VERSION (5) 不一致时抛出"""


class StorageDB:
    def __init__(self, db_path: Path) -> None:
        """打开或初始化 SQLite 单库（设置 WAL, synchronous=NORMAL, busy_timeout=5000 并校验 user_version）"""

    # --- 会话与事件写入（由 launcher 调用） ---
    def create_session(self, row: SessionRow) -> None:
        """插入初始 status='running' 的会话记录"""

    def update_session_ego(self, session_id: str, ego_actor_id: int, ego_type_id: str) -> None:
        """收到 simulator 的 WorkerReadyEvent 后回填主车 Actor ID 与实际蓝图"""

    def finish_session(self, session_id: str, status: SessionStatus, finished_at: float) -> None:
        """实验结束或异常中止时更新 finished_at 与最终状态 ('committed' | 'aborted')"""

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

    def export_session_to_csv(self, session_id: str, output_csv: Path) -> int:
        """流式查询 data 表，按数据库的列名与顺序写出 CSV 文件，返回导出的行数"""

    def export_events_to_csv(self, session_id: str, output_csv: Path) -> int:
        """查询指定会话的 event 表并按数据库列名写出 CSV 文件，返回导出的事件行数"""
```

### 3.2 `storage/writer.py`

供 `simulator` 在运行期异步批量写库：

```python
class BatchDataWriter:
    """后台守护线程批量写入器（每满 500 行或间隔 0.5s 执行一次 BEGIN IMMEDIATE + executemany）"""
    def __init__(self, db_path: Path, enabled: bool = True, batch_size: int = 500, flush_interval: float = 0.5) -> None: ...

    def start(self) -> None: ...

    def enqueue(self, row: DataRow) -> None:
        """非阻塞入队；当 enabled=False（不保存模式）时直接 return"""

    def close(self) -> None:
        """通知后台线程提交全部剩余数据，等待线程结束并关闭连接后返回"""
```

## `simulator` 模块 API 设计

`simulator` 是模拟与画面合成子进程，不包含 Pygame 文字图层、不包含 TTS 语音合成、不包含实验剧本钩子、不轮询全图背景车辆。

### 4.1 `simulator/ws_client.py`

```python
class WorkerWSClient:
    """后台 WebSocket 同步客户端：负责上报快照/日志/事件并接收 LauncherCommand"""
    def __init__(self, ws_url: str | None, role: WorkerRole = WorkerRole.SIMULATOR) -> None:
        """当 ws_url 为 None 时退化为空操作（独立命令行调试模式）"""

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
    def __init__(self, display_cfg: DisplayConfig, camera_rig_cfg: CameraRigConfig) -> None: ...

    @property
    def actual_resolution(self) -> tuple[int, int]:
        """返回窗口实际像素尺寸（全屏模式下为显示器真实分辨率），供主相机初始化使用"""

    def set_rearview_visible(self, visible: bool) -> None:
        """显隐三路后视镜"""

    def update_camera_mount(self, camera_name: str, mount: CameraMountConfig) -> None:
        """更新对应相机的屏幕归一化位置与显示尺寸"""

    def render_frame(self, images: dict[str, carla.Image | None]) -> None:
        """使用 pygame.image.frombuffer(raw_data, size, 'BGRA') 将四路画面合成并 flip 上屏"""

    def close(self) -> None: ...
```

### 4.3 `simulator/app.py`

```python
class SimulatorApp:
    """模拟器主控类：管理 60Hz 主循环与各组件生命周期"""
    def __init__(self, run_config: RunConfig) -> None: ...

    def run(self) -> None:
        """
        1. 初始化窗口、方向盘、CARLA 连接、主车与传感器，打开 RunConfig.db_path 对应的 BatchDataWriter
        2. 发送 WorkerReadyEvent(ego_actor_id, ego_type_id)
        3. 运行 60Hz 循环：
           - poll_commands() 处理 Stop / SetAutopilot / SetTakeover / SetWeather / UpdateCamera / SetRearview，应用成功后上报对应的 ExperimentEvent 子类 (source='launcher')
           - 采集键盘与方向盘驾驶输入，施加车辆控制；离散驾驶动作（自动驾驶、接管、倒挡、档位、手刹、车灯）应用后上报对应的 ExperimentEvent 子类 (source='wheel'|'keyboard')
           - 推进或等待世界帧，更新 RuntimeFrameData
           - render_frame() 合成画面上屏
           - enqueue(to_data_row()) 异步落盘，每 2 帧 publish_telemetry() 上报快照
        4. 退出时按顺序 Flush 数据库、停止 CARLA Recorder、销毁传感器与主车、关闭窗口
        """
```

## `launcher` 模块 API 设计

### 5.1 `launcher/events.py`

```python
class TTSSpeaker:
    """后台单队列 SAPI 语音播报线程（仅在 launcher 进程内运行）"""
    def __init__(self, enabled: bool = True) -> None: ...
    def speak(self, text: str) -> None: ...
    def close(self) -> None: ...


class TelemetryEventWatcher:
    """监听 simulator 上报的 TelemetrySnapshotEvent，触发语音提醒或自动下发接管命令"""
    def __init__(self, tts: TTSSpeaker, send_command: Callable[[LauncherCommand], None]) -> None: ...

    def on_telemetry(self, snapshot: TelemetrySnapshotEvent) -> None:
        """检查模式切换、超速提醒等规则"""
```

### 5.2 `launcher/orchestrator.py`

```python
class ExperimentOrchestrator(QObject):
    """管理一次实验从预检、启动子进程、运行期双向通信到停机清理的状态机"""
    # Qt 信号：供界面实时绑定
    state_changed = Signal(str)                     # 'idle' | 'starting' | 'running' | 'stopping'
    telemetry_updated = Signal(object)              # TelemetrySnapshotEvent -> 驱动桌面数据面板与出生点拾取
    log_received = Signal(object)                   # LogEvent -> 驱动日志视图
    experiment_event_received = Signal(object)      # ExperimentEvent -> 驱动事件时间线视图

    def start_experiment(
        self,
        machine_cfg: MachineConfig,
        control_cfg: ControlConfig,
        preset_cfg: PresetConfig,
        run_settings: RunSettings,
    ) -> None:
        """
        1. 调用 CarlaSession.preflight_check() 与 prepare_world()
        2. 生成 session_id 与 db_path，合成 RunConfig（含 run_settings），调用 StorageDB.create_session() 并向 event 表写入实验启动事件
        3. 使用 QProcess 启动 `sys.executable -m drisca.simulator --config <path>`，绑定 stdout/stderr，并把子进程加入 Job Object
        """

    def send_command(self, cmd: LauncherCommand) -> None:
        """向运行中的 simulator 子进程发送下行控制命令（切换自动驾驶、触发接管、改天气、实时调相机、开关后视镜、停机）。命令本身不写事件表，由 simulator 应用成功后上报对应的 ExperimentEvent"""

    def stop_experiment(self) -> None:
        """发送 StopCommand；子进程停止主循环、提交剩余数据并发送完日志与事件后退出。launcher 等待进程退出及已接收事件入库，再调用 CarlaSession.force_reset_after_experiment()，写入实验结束事件并更新 session 表；超时则 kill 并标记 aborted"""
```
