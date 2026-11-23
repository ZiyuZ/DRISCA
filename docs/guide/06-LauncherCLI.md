# 管理端命令行

命令行和界面调用同一个管理服务，使用同一份状态与配置。先启动一次 Launcher，再从其他终端发送操作命令。命令结果以 JSON 输出，失败返回非零退出码。

## 启动管理端

```bash
just launcher
```

纯命令行调试可用 `just launcher --web`，保持该终端运行。前端调试沿用 `just launcher --dev`。一组实验启动一次 Launcher，由它持有 Unreal 和实验子进程。关闭 Launcher 时先结束当前实验，再关闭自己启动的 Unreal。

## 配置 Unreal

在主机配置的“连接与服务”标签填写运行程序，也可以编辑 configs/machine.toml 的 carla_runtime 节。

| 字段 | 用途 |
| --- | --- |
| kind | editor 为 UE 编辑器运行游戏，packaged 为打包版 |
| editor_executable | UnrealEditor.exe 路径 |
| project | CarlaUnreal.uproject 路径，编辑器版使用 |
| packaged_executable | 已打包的 CarlaUnreal.exe 路径 |
| quality | Low、Medium、High 或 Epic |
| startup_timeout | 等待服务就绪的秒数 |

相对路径以 DRISCA 根目录为起点。两种运行版本各自保存路径，切换 kind 后使用对应设置。打包版需包含原生驾驶模块和所需地图。

窗口分辨率、位置、全屏、边框和目标帧率来自 display 节。display.position 保存窗口 X、Y，支持负坐标。这些值作为 Unreal 窗口参数传入，实际桌面尺寸受当前系统与引擎 DPI 行为影响。开发机使用适合屏幕的分辨率。

CARLA RPC 端口来自 carla.port，流传输端口使用其后一位，原生 WebSocket 接口端口来自 driving_view.port。本机启动使用本机服务地址。修改启动配置后，下次启动 Unreal 生效。

## Unreal 与实验操作

```bash
just launcher carla start --wait
just launcher presets
just launcher experiment start --preset basic --subject P001 --wait
just launcher status
just launcher experiment stop --wait
just launcher experiment start --preset basic --subject P002 --wait
```

左下角“Unreal”按钮提供启动与关闭操作，也可进入运行配置。启动成功后管理端连接 CARLA。实验之间共用同一个 Unreal，停止实验按现有流程收尾数据并释放实验对象。

临时选择运行版本、测试时关闭保存、启用录像：

```bash
just launcher carla start --kind packaged --wait
just launcher experiment start --preset basic --subject debug --no-save --wait
just launcher experiment start --preset basic --subject P001 --record --wait
```

--record 受保存总开关控制。--wait 等待操作完成后输出最终状态，默认等待 180 秒，可用 --timeout 调整。省略 --wait 时输出请求接受结果。

结束全部实验后，关闭本次 Launcher 启动的 Unreal：

```bash
just launcher carla stop --wait
```

关闭操作针对所持有的进程树。外部启动的 CARLA 使用 `just launcher carla connect` 接入，其进程仍由原启动方管理。

## 状态、日志与其他接口

```bash
just launcher status
just launcher logs
just launcher request GET /api/status
just launcher request POST /api/world/map --data-file .local/map-request.json
```

地图请求正文包含 map_name。复杂请求参数写成 UTF-8 JSON 文件，避免命令行转义。天气、相机、指令和数据操作沿用已有 HTTP 接口，见[管理端通信](../design/10-LauncherWeb.md)。Unreal 日志写到 .cache/logs/carla-unreal.log。

默认地址读取主机配置中的管理服务地址和端口。连接其他地址时，将 --url 放在操作命令之前：

```bash
just launcher --url http://127.0.0.1:7900 status
```

各级命令可用 --help 查看参数，例如 `just launcher experiment start --help`。
