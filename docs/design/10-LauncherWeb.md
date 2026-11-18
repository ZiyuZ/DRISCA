# 管理端前后端通信

管理端由 Web 页面和 Python 后端组成。后端运行在实验主机，统一管理配置、实验进程、当前状态和数据库。pywebview 桌面窗口、本机浏览器与局域网平板访问同一个服务。

## 三条通信路径

| 路径 | 方式 | 内容 |
| --- | --- | --- |
| 页面 → 管理端后端 | HTTP，JSON 请求与响应 | 读取或保存配置、启动停止实验、发送运行操作、查询与导出数据 |
| 管理端后端 → 页面 | SSE | 实验状态、最新遥测、日志和实验事件 |
| 管理端后端 ↔ 模拟器 | 现有本地 WebSocket | 下行命令，上行状态、遥测、日志和已应用事件 |

页面与服务同源部署，页面通过相对地址请求接口。操作者控制台使用 `/`，被试 HUD 使用 `/hud`。HUD 继续读取精简的状态推送。前端连接与窗口数量各自独立，实验生命周期由后端管理。

## 页面操作

HTTP 接口按配置、实验、数据和工具四组组织。读取返回 JSON；保存和操作提交 JSON。配置接口沿用现有 Pydantic 模型校验，并向页面提供按键枚举及中文标签。界面显示用 km/h，协议中的速度保持 m/s。

启动、停止和发送命令的请求，在后端接受操作后返回。页面通过后续状态和事件更新显示结果。配置修改经 600ms 防抖自动提交，切换预设、启动实验和检查连接会先提交相关修改。相机、自动驾驶、接管与天气沿用现有命令模型；实际生效后以模拟器上报的事件更新界面。HTTP 接受命令表示该请求已交给后端处理。

HTTP 请求失败时，返回合适的状态码和简明错误信息；配置错误包含字段位置。模拟器执行错误继续使用现有 `LogEvent.command_id` 关联命令，后端将错误推送到页面。关键操作错误按已有实验停机约定处理。

导出请求提交所选会话编号，后端读取对应记录，将 `sessions.csv`、`data.csv` 和 `events.csv` 写入实验主机配置的导出目录。进度与完成路径通过 SSE 更新，前端展示结果。会话列表默认查询最近 30 天，日期与其他筛选共同决定表格内容；选择按会话编号独立保存，整批导出使用同一组编号。

停止实验请求直接执行停机。可选备注通过 `PUT /api/sessions/{id}/note` 独立提交，内容为 `{ "note": "本次备注" }`。启动配置快照保留启动时的内容，会话记录保存后续填写的备注。

## 实时更新

操作者页面使用一个 SSE 连接，消息按状态、遥测、日志和实验事件区分。建立连接时发送当前实验状态和最新遥测，随后推送变化。`carla_connecting` 标明 CARLA 连接过程；`clients` 记录控制台与 HUD 的在线页面数量，页面连接和断开时更新。遥测沿用约 20 至 30 Hz 的最新快照；日志和事件逐条推送。

历史会话与完整事件从查询接口读取。浏览器连接断开时显示连接状态，恢复连接后刷新当前状态。实验继续由后端运行，逐帧数据仍由模拟器的存储路径保存。

被试 HUD 使用独立的精简推送，只接收驾驶显示需要的字段。管理端当前快照同时服务于两类页面。

## 桌面窗口

业务操作统一走 HTTP 与 SSE。pywebview 的 Python 桥负责最小化、最大化、关闭等原生窗口操作。桌面与浏览器共用应用标题栏，桌面模式额外显示窗口操作按钮。

桌面关闭操作先提交当前配置修改，再调用管理端停机流程。桌面和服务退出共用同一个实验收尾入口，子进程结束后回收页面连接与窗口资源。浏览器关闭标签页只结束该页面连接。后端进程编排使用 `subprocess` 与 Windows Job Object，沿用已有启动配置、子进程协议和收尾顺序。

## 接口分组

| 接口 | 用途 |
| --- | --- |
| `GET /api/bootstrap` | 初始化配置、预设、指令库、按键名称、状态和连接地址 |
| `PUT /api/config/machine`、`PUT /api/config/control` | 保存机器配置与输入配置 |
| `PUT /api/presets/{name}`、`DELETE /api/presets/{name}` | 保存和删除实验预设 |
| `POST /api/connect` | 使用已保存配置连接 CARLA，连接期间拒绝重复请求 |
| `POST /api/world/map` | 空闲时加载服务器地图，正文为 `map_name` |
| `POST /api/experiment/start`、`POST /api/experiment/stop` | 启动和停止实验 |
| `POST /api/instructions/{id}/execute`、`POST /api/markers` | 执行预设指令和记录打点 |
| `POST /api/cameras/{name}`、`POST /api/display-layout` | 应用相机安装与后视镜布局 |
| `POST /api/weather` | 实时调整当前世界天气，实验中通过模拟器应用并记录事件 |
| `GET /api/sessions`、`GET /api/sessions/{id}` | 筛选会话与读取详情 |
| `PUT /api/sessions/{id}/note` | 独立保存会话备注 |
| `POST /api/sessions/delete` | 确认后删除所选会话及逐帧数据与事件 |
| `POST /api/export` | 将所选会话导出到实验主机 |
| `GET /api/recordings`、`POST /api/recordings/info`、`POST /api/recordings/replay` | 浏览、查询和回放应用管理的录像 |
| `GET /api/events`、`GET /stream` | 控制台与 HUD 的 SSE 推送 |
| `/ws/worker/simulator` | 模拟器双向通信 |

配置请求沿用 `core.config` 中的模型。控制台 SSE 消息以 `type` 区分 `state`、`log` 和 `experiment_event`，内容位于 `data`。`state` 包含实验阶段、CARLA 与驾驶端状态、最新遥测、相机安装状态、独立的画面布局状态、车辆包围盒、可选地图与车辆、导出进度。`active_preset_name` 标明本次采用的方案名，`active_preset` 与 `active_run` 保存本次运行采用的预设和实验设置，供控制台显示当前指令、打点和保存状态。编辑页单独维护待保存的配置。启动时获取的地图出生点同时标明所属地图，供预设编辑时核对。

`bootstrap.weather_presets` 提供当前 CARLA 客户端内置的天气预设及完整参数；`state.weather` 保存当前世界已应用的天气。模拟器应用后上报既有天气事件，管理端更新实际天气并记录事件。

`state.world_loading` 标明手动切换地图或实验启动准备世界的过程，经 SSE 推送到全部控制台。加载在现有后台任务中执行，期间修改请求返回 409，查询与状态推送继续工作。完成或失败后清除等待状态。空闲时的天气调整直接应用到 CARLA，并更新 `state.weather`；场景控制复用运行期的天气编辑组件。

交互原型位于 `prototypes/launcher/`，开发衔接记录放在 `.local/notes/`。

正式前端源码位于 `frontend/`，使用 Bun、Vite、React、TypeScript、Tailwind CSS 与 shadcn/ui。构建输出到 `src/drisca/launcher/static/`，由 Python 服务同源提供。实验机运行阶段使用构建后的静态资源。
