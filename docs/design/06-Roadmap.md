# 开发路线图 (Roadmap)

本文档记录 DRISCA 的实施顺序、近期功能规划与远期技术探索方向。

## 当前主线：基础架构实现

按 `core / storage`、`simulator`、`launcher` 的顺序实现基础契约、驾驶模拟端与桌面管理端，建立清晰的进程边界与统一的操作入口：

- 代码分层与不可变配置
  - 按 `launcher / simulator / traffic / core / storage` 五个顶层包组织单向依赖。`traffic` 在当前阶段只保留占位，实现列入后续计划。
  - 采用 `MachineConfig` + `ControlConfig` + `PresetConfig` + `RunSettings` → 不可变 `RunConfig` 显式注入。
- SQLite 单库持久化
  - 使用标准库 `sqlite3`（WAL 模式 + 后台队列批量短事务写入）。
  - 实现 Schema 版本校验（`PRAGMA user_version`），按实验会话（`session`）组织主车数据（`data`）与实验事件（`event`）。
- 桌面管理端（`launcher`）与平板 HUD 整合
  - 基于 `PySide6` + `PySide6-Fluent-Widgets` 构建唯一用户入口：集成 CARLA 预检、预设管理、子进程启停与监控、历史会话浏览与 CSV 导出。
  - 内置轻量 `FastAPI` 服务：通过本地 WebSocket 接收 `simulator` 的日志、事件与遥测快照，并通过 SSE 驱动平板 HUD。
  - 桌面端提供数据面板（完整遥测）、调试面板（运行期控制、相机调节、出生点拾取并写回预设）与控制按键说明页。
- 客户端渲染路径提速
  - 采用 `pygame.image.frombuffer(..., 'BGRA')` 直接消费 CARLA 原始图像缓冲，将 4 路相机合成耗时降至 `1.5 ms/帧`。

## 近期规划（基础架构落地后推进）

- 罗技方向盘底层封装自维护与力反馈闭环
  - 在 `simulator` 内部参考 `LogitechSteeringWheelPy` 与 `logidrivepy` 自维护轻量 Windows DLL 绑定，消除第三方包功能缺失与打包阻碍。
  - 完善 Constant Force / Friction / Spring / Damper / 转速 LED 封装。
  - 实现 `set_physical_angle` 闭环控制：在自动驾驶模式下使物理方向盘实时跟随虚拟车辆转向角同步转动，支持平滑的人机接管切换。
- 场景导演与事件触发台（`launcher` 高级控制台，计划中）
  - 在 `launcher` 中新增集成「2D 矢量路网实时态势图 + 预定义实验事件手动触发面板 + 背景车轨迹控制」的高级控制台（见 [桌面管理端设计：场景导演与事件触发台](./04-LauncherDesign.md)）。
  - 支持操作者在实验过程中根据现场情况手动触发预先定义的事件：包含子进程控制命令的事件在子进程执行后上报入库，纯打点标记事件由 `launcher` 关联当前帧号直接写入 `event` 表。
- 背景交通流（`traffic`，计划中）
  - 当前阶段不实现。设计保留在 [系统架构](./01-Architecture.md) 中。
  - 在保持进程独立与接口解耦的基础上，实现背景车生成、路径规划与行为控制模型，并支持由 `launcher` 实时干预。
  - 引入基于主车距离的邻域裁剪策略：仅记录主车周边的背景车辆状态以降低大规模车流下的写入开销。

## 远期探索（方向性储备，暂不排期）

- 多机分布式多人联动（网络游戏状态同步模型）
  - 思路：每台驾驶台运行各自独立的本地 CARLA 服务端，本机画面直接本地渲染（避免跨网图像传输的延迟）；引入一个轻量权威同步服务广播各主车的位姿状态，其他玩家的车辆在本机世界中以无物理碰撞的代理对象（Ghost Actor + 插值/外推）呈现，碰撞由简化运动学仲裁。
  - 价值与代价：网络带宽低（每车约 100 Bytes @ 30Hz），画面不经过跨网传输；代价是需要自建一套状态同步与插值层。
- CARLA 服务端插件定制（硬件视频编码 / 共享内存传输）
  - 思路：修改 CARLA UE4 插件 `PixelReader.h`，将相机画面接入显卡硬件编码器（NVENC/AMF）或直接写入 Windows 共享内存，见 [渲染与画面传输链路](./05-RenderingPipeline.md)。
  - 前置条件：仅当单机多路相机回读被实测证实为硬瓶颈，且团队愿意承担 ~200 GB 的 UE4 源码分支维护成本时才启动评估。
