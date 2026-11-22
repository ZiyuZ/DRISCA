# 开发路线图 (Roadmap)

本文档记录 DRISCA 的实施顺序、近期功能规划与远期技术探索方向。

## 当前主线：单机原生驾驶与专用接口

基础契约、原生驾驶接入与 Launcher 已形成单机键盘实验流程，下一步逐项迁移专用接口。整体阶段安排见[研究平台路线图](../research-platform/03-Roadmap.md)，已有基础如下：

- 代码分层与不可变配置
  - 按 `launcher / simulator / traffic / core / storage` 五个顶层包组织单向依赖。`traffic` 在当前阶段只保留占位，实现列入后续计划。
  - 采用 `MachineConfig` + `ControlConfig` + `PresetConfig` + `RunSettings` → 不可变 `RunConfig` 显式注入。
- SQLite 单库持久化
  - 使用标准库 `sqlite3`（WAL 模式 + 后台队列批量短事务写入）。
  - 实现 Schema 版本校验（`PRAGMA user_version`），按实验会话（`session`）组织主车数据（`data`）与实验事件（`event`）。
- 桌面管理端（`launcher`）与平板 HUD 整合
  - 采用 Web 控制台与 pywebview 无边框桌面壳，先制作 Basecoat + Alpine.js 静态原型，再连接 Python 后端：集成 CARLA 预检、预设管理、子进程启停与监控、历史会话浏览与 CSV 导出。
  - 内置轻量 `FastAPI` 服务：通过本地 WebSocket 接收 `simulator` 的日志、事件与遥测快照，并通过 SSE 驱动平板 HUD。
  - 管理端按控制台、方案配置、数据管理、主机配置、输入配置五页组织。桌面与局域网浏览器共用页面和后端，进程管理使用标准库 subprocess。正式前端使用 Bun、Vite、React、TypeScript、Tailwind CSS 与 shadcn/ui，原型保存在 `prototypes/launcher/`。
- Unreal 原生驾驶
  - 主视图、三路后视镜与键盘连续控制在 Unreal 内运行，Python 读取最新驾驶状态并保存研究数据。单机键盘驾驶、接管、语音、打点与导出已完成实际联调，后续阶段见[研究平台路线图](../research-platform/03-Roadmap.md)。
  - 旧 Python 画面合成的测量保存在[渲染参考资料](../reference/RenderingPipeline.md)，方向盘设备封装原位保留，硬件到位后接入。

## 后续功能规划

- 罗技方向盘底层封装自维护与力反馈闭环
  - 等硬件到位后推进，当前保留 `wheel_device.py`、方向盘配置及 pygame 与罗技 SDK 依赖。
  - 在 `simulator` 内部参考 `LogitechSteeringWheelPy` 与 `logidrivepy` 自维护轻量 Windows DLL 绑定，消除第三方包功能缺失与打包阻碍。
  - 完善 Constant Force / Friction / Spring / Damper / 转速 LED 封装。
  - 实现 `set_physical_angle` 闭环控制：在自动驾驶模式下使物理方向盘实时跟随虚拟车辆转向角同步转动，支持平滑的人机接管切换。
- 场景导演与事件触发台（`launcher` 高级控制台，计划中）
  - 在 `launcher` 中新增集成「2D 矢量路网实时态势图 + 预定义实验事件手动触发面板 + 背景车轨迹控制」的高级控制台（设计背景见本地开发记录中的管理端详细稿）。
  - 支持操作者在实验过程中根据现场情况手动触发预先定义的事件：包含子进程控制命令的事件在子进程执行后上报入库，纯打点标记事件由 `launcher` 关联当前帧号直接写入 `event` 表。
- 背景交通流（`traffic`，计划中）
  - 当前阶段不实现。设计保留在 [系统架构](./01-Architecture.md) 中。
  - 在保持进程独立与接口解耦的基础上，实现背景车生成、路径规划与行为控制模型，并支持由 `launcher` 实时干预。
  - 引入基于主车距离的邻域裁剪策略：仅记录主车周边的背景车辆状态以降低大规模车流下的写入开销。

## 技术探索资料

多人联动与 CARLA 服务端插件定制的方案移至[技术探索](../reference/TechnicalExplorations.md)，供相关需求出现时查阅。主线按基础契约、驾驶端、管理端的顺序推进。

配置操作说明见[配置管理](../guide/05-Configuration.md)，基础契约分别见[配置模型](./08-ConfigurationModels.md)、[进程通信](./07-Protocol.md)与[运行状态和实验数据](./02-DataStructures.md)。每阶段完成静态检查并汇报，经确认进入下一阶段。
