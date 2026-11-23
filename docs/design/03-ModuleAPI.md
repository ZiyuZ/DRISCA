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
│   ├── client.py             # NativeApiClient：原生 WebSocket 客户端
│   ├── driving_view.py       # 键盘名称到 Unreal FKey 的映射
│   ├── weather.py            # WeatherConfig 与原生天气 JSON 的转换
│   ├── snapshot.py           # 固定二进制快照的 NumPy 解码与位标记
│   └── tools.py              # 原生 Recorder 信息与回放调用
├── storage/                  # SQLite 单库持久化层
│   ├── __init__.py
│   ├── models.py             # SCHEMA_VERSION（由存储层维护）, SessionRow, FrameRow, EventRow, DDL 定义
│   ├── db.py                 # StorageDB：连接校验、会话与事件读写、查询与 CSV 导出
│   └── writer.py             # BatchDataWriter：后台队列 + BEGIN IMMEDIATE 批量写线程
├── simulator/                # 实验子进程（主车、传感器、原生驾驶视图接入与采样）
│   ├── __init__.py
│   ├── __main__.py           # 子进程入口：解析 --config，运行 SimulatorApp
│   ├── app.py                # SimulatorApp：主循环编排、命令消费、生命周期管理
│   ├── state.py              # DrivingState：数值状态与 FrameRow/Telemetry 投影
│   ├── events.py             # 原生事件映射、来源与命令关联
│   ├── wheel_device.py       # 保留的方向盘设备封装，硬件到位后接入
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

`NativeApiClient` 显式连接原生 WebSocket 服务。Launcher 使用管理连接，worker 使用独立控制连接；每连接的请求、JSON 响应与后续二进制快照在同一串行区间内完成。

```python
class NativeApiClient:
    def __init__(self, config: DrivingViewConfig, *,
                 client: str = 'drisca-client', long_timeout: float | None = None) -> None: ...
    def connect(self) -> ServerInfo: ...
    def close(self) -> None: ...
    def request(self, method: str, params: dict | None = None,
                *, timeout: float | None = None) -> dict: ...
    def catalog(self) -> dict: ...
    def load_map(self, map_name: str) -> dict: ...
    def exchange(self, operations: list[dict], *, session_id: str,
                 timeout: float | None = None) -> ExchangeResult: ...
    def stop_experiment(self, session_id: str) -> dict: ...
```

`ServerInfo` 包含协议版本、服务实例、世界标识和地图名；`ExchangeResult` 包含逐项结果、事件、逐车控制状态、信号状态和 `Snapshot`。普通请求使用 `DrivingViewConfig.timeout`，地图与目录使用 `long_timeout`。原生错误通过带 method、code、message、results 的 `NativeApiError` 暴露。

客户端还提供天气、车辆创建、视图、Recorder 和道路目录的薄方法。`road_graph_all()` 按页取得完整车道图，缓存按世界与采样步长失效。完整原生契约见[原生 WebSocket 接口](./11-NativeAPI.md)。

`core/snapshot.py` 使用明确的小端 dtype 解码 48 字节头、96 字节车辆记录和 128 字节研究记录；数组持有消息缓冲区并供本地数值计算。连接初始化与每次 exchange 校验协议和快照关联信息。

### 2.5 `core/tools.py`

提供工具函数供 `launcher` 调用：

```python
def query_recorder_info(session: NativeApiClient, rec_file: Path, show_all: bool = False) -> str:
    """读取 .rec 录像文件的摘要或完整帧信息"""

def replay_recorder(
    session: NativeApiClient,
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

`simulator` 管理实验主车、传感器、数据采样与原生驾驶视图连接。Unreal 负责异步世界推进、键盘连续控制和原生画面，Launcher 负责语音与实验操作。

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

### 4.2 原生驾驶视图与事件

`core/driving_view.py` 只负责 `KEYBOARD_FKEYS` 与 `keyboard_mapping()`，将输入配置转换为原生 FKey。视图启动、调整和实验停止通过 `NativeApiClient` 完成。

`simulator/events.py` 将已知原生事件转换为 `ExperimentEvent`，保留原生帧号、墙钟时间、车辆、控制版本与信号作用域。原生 request_id、operation_index 与当前批次的 Launcher command_id 对应，实际生效操作只记录一次。未知事件名直接报错。

### 4.3 `simulator/app.py`

`SimulatorApp.run()` 连接 Launcher 和原生 API，设置异步世界、创建主车、绑定视图，并按保存选项启动后台写入与 Recorder。传感器和道路计算由 Unreal 完成，首次研究采集就绪后上报 worker ready。

主循环以约 20 Hz 收集 Launcher 命令并调用 exchange；帧后响应中的最新完整快照由 `project_snapshot()` 投影为 `DrivingState`，按 frame_no 去重后分别送入数据写入队列和遥测通道。交换等待计入本轮周期，世界、键盘和画面由 Unreal 持续推进。

主车控制版本来自 control_state。主动接管在原生侧立即切人工；过期请求标记 control_superseded，worker 刷新状态后重新决策。自动驾驶算法安排在 traffic 阶段，当前启用请求明确报错，人工实验继续运行。

正常停止先调用 experiment.stop 并交付最后事件，再提交剩余数据与日志并关闭连接。连接异常直接退出，Unreal 释放本次实验对象与归属录像，Launcher 将会话记为 aborted。

## `launcher` 模块职责

管理端使用 Web 界面与 Python 后端。页面划分见[管理端设计](./04-LauncherDesign.md)，通信方式见[前后端通信](./10-LauncherWeb.md)。上面的管理端文件划分用于说明职责，具体接口随实现确定。

`runtime.py` 组合使用 CARLA 接入、配置与存储组件，负责预检、准备世界、生成会话编号、合成运行配置、启动模拟器、接收消息与实验收尾。实验状态依次为 `idle`、`starting`、`running`、`stopping`。

进程使用 `subprocess.Popen`，以 `sys.executable -m drisca.simulator --config <path>` 启动，捕获标准输出、错误输出和退出码，并加入 Job Object。正常结束时发送已有停止命令，等待数据和事件提交、子进程退出，再复位世界、清理场景并完成会话记录。停机超时则强制结束进程并标记会话异常。

`server.py` 提供配置读写、实验操作、数据查询与目录导出接口，通过 SSE 推送状态、遥测、日志和事件，沿用本地 WebSocket 接收模拟器消息。桌面窗口与浏览器访问同一服务。

`runtime.py` 负责管理端的语音播放。pywebview 桥负责窗口最小化、最大化与关闭，关闭窗口使用编排器的正常停机流程。

## 配套约定

配置读写按[配置模型](./08-ConfigurationModels.md)执行，保存使用临时文件替换。预设列表通过 `.example.toml` 后缀识别示例。子进程启动时以实际配置建立硬件和连接。

`SimulatorApp` 每帧分别记录驾驶人输入和车辆实际控制，维护控制模式与接管请求。碰撞与压线从传感器回调生成事件，上报后由 launcher 统一写库。`WorkerWSClient` 沿用事件上报，命令错误通过关联命令编号的日志报告，消息字段见[进程通信](./07-Protocol.md)。

管理端接入时，将现有 `export_sessions` 扩展为上述所选会话接口，三个 CSV 使用同一会话范围导出到配置目录。页面交互见[管理端设计](./04-LauncherDesign.md)。录像目录取机器配置的 `recorder_dir`，录像受保存总开关控制。

关闭保存时，管理端跳过会话和事件数据库操作，驾驶端跳过存储线程与 Recorder 的启动。正常停机只关闭本次实际打开的资源，关闭保存时保留实时遥测、事件时间线和日志显示。

方向盘使用单个 `WheelDevice` 保留 pygame 和罗技 SDK 的设备访问、轴与按钮映射及基础回正力。设备层原位保留，硬件接入整体后置；当前 `enable_wheel = false` 表示使用原生键盘驾驶。

## 按键与设备映射

`core.config` 定义 `KeyboardKey`、`WheelButton`，以及名称到界面显示标签的纯数据表。配置字段使用单个枚举值。界面以枚举值保存选项，以标签显示名称。

`core/driving_view.py` 的 `KEYBOARD_FKEYS` 将 `KeyboardKey` 映射为 Unreal 键名，例如 `KeyboardKey.SPACE → SpaceBar`、`KeyboardKey.KEYPAD_1 → NumPadOne`。`DrivingViewPawn` 在原生窗口处理键盘连续控制与离散动作。

`simulator/wheel_device.py` 使用 `WHEEL_BUTTONS` 和 `WHEEL_AXES` 保存按钮、物理轴的编号。当前设备布局如下，后续调整集中在该模块。

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
