# 开发路线图

本文记录 DRISCA 当前已完成的核心能力以及后续规划方向。

## 已完成里程碑

- **基础契约与持久化（`core` / `storage`）**
  - 不可变配置分层（`MachineConfig` / `ControlConfig` / `PresetConfig` → `RunConfig`）与显式依赖注入。
  - SQLite WAL 持久化升级至 **Schema v2**（`session`、`data`、`traffic`、`event` 四表），后台独立线程批量写入，支持按会话导出 6 位精度 CSV。
- **CARLA UE5 驾驶与环境模块（`DrivingView` + `DriscaApi`）**
  - 主视图与三路后视镜 HUD 渲染，完全脱离官方 `carla` Python wheel 运行依赖。
  - 高速本地 WebSocket 服务（`7910`），启用 `TCP_NODELAY` 与物理前非阻塞网络推进，提供紧凑二进制快照。
  - 车内 / 第三人称（防抖、滚轮调距、右键环视）/ 自由视角（点击拾取车辆与红绿灯）平滑切换。
  - 唯一权威环境控制器（日照与天气独立组合、平滑过渡、归一化球形局部雾 `ALocalFogVolume`）。
- **背景交通流与交互场景（`traffic`）**
  - 完整路网索引、IDM 跟车、MOBIL 换道、急弯自适应 Pure Pursuit、阻塞实线绕行与开放地图掉落保护。
  - 四种驾驶风格分布与截断正态多样性控制，主车周边活动交通圈（`active_radius_m`）、七类运行期场景触发事件、运行期车流数量调节与独立交通流预览。
- **桌面管理端与录像回放（`launcher` + `frontend`）**
  - FastAPI + React/shadcn/ui + pywebview 无边框桌面壳与局域网平板 HUD。
  - 完整录像回放（`ReplayRunner`）：环境时间线自动同步、多视角切换与跟随车辆切换。
- **分发与部署工具链**
  - 完成官方 CARLA 1.0（`3ea166118d`）单 EXE 补丁（压缩约 73 MB）实机验证。
  - 内置 `drisca.maps` 命令行模块，覆盖 `.udatasmith` 导入、独立地图包烘焙与校验安装，并提供双击启动器 `DRISCA.exe`。

## 后续规划

- **方向盘硬件与力反馈闭环**
  - 在硬件到位后接通 `simulator/wheel_device.py`，维护 Windows 罗技 SDK 绑定。
  - 完善 Constant Force / Friction / Spring / Damper 效果，并实现自动驾驶模式下的方向盘物理转角随动闭环，支持平滑人机接管。
- **管理端静态资产管理扩展**
  - 按需在管理端增加独立静态管理页，支持在界面中直接校验、导入和管理 `.tar.gz` 独立地图包。
- **多终端与分布式实验（远期）**
  - 按后续课题需求评估多被试协同驾驶与跨机分布式同步方案。
