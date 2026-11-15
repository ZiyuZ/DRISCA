<!-- rumdl-disable MD033 MD041 -->

<div align="center">
  <img src="docs/assets/icon.png" alt="DRISCA 标志" width="160" height="160">
  <h1>DRISCA</h1>
  <p><strong>基于 CARLA 的驾驶行为研究实验平台</strong></p>
  <p>Driving Simulator based on CARLA<br>An Experimental Platform for Human Driving Behavior Research</p>
  <p>
    <img src="https://img.shields.io/badge/platform-Windows-0078D4?style=flat-square" alt="平台：Windows">
    <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square" alt="Python 3.14">
  </p>
  <p>
    <a href="docs/index.md">文档首页</a> ·
    <a href="docs/design/01-Architecture.md">系统架构</a> ·
    <a href="docs/design/04-LauncherDesign.md">桌面管理端设计</a> ·
    <a href="docs/design/06-Roadmap.md">开发路线图</a>
  </p>
</div>

---

> [!IMPORTANT]
> DRISCA 当前处于设计阶段，仓库文档描述目标架构与接口，应用功能尚未实现。

## 项目目标

DRISCA 基于 CARLA，为驾驶行为研究提供实验环境。平台支持实验配置、模拟驾驶、运行状态监测和实验数据记录，供研究人员组织和开展驾驶实验。

平台由桌面管理端和驾驶模拟端组成。操作者通过桌面端准备和控制实验、查看遥测数据并导出记录；被试通过驾驶画面、方向盘和踏板参与实验。

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [快速开始](docs/guide/01-QuickStart.md) | 环境准备与启动流程 |
| [常见问题](docs/guide/04-FAQ.md) | 常见问题与处理方法 |
| [CARLA 服务端](docs/guide/02-CarlaServer.md) | 服务端启动与配置 |
| [自定义地图](docs/guide/03-CarlaUE.md) | Unreal 编辑器与地图导入 |
| [系统架构](docs/design/01-Architecture.md) | 进程、模块、实验流程与存储设计 |
| [核心数据结构与协议契约](docs/design/02-DataStructures.md) | 配置、通信协议与数据模型 |
| [模块职责与 API 规范](docs/design/03-ModuleAPI.md) | 模块职责与接口设计 |
| [桌面管理端设计](docs/design/04-LauncherDesign.md) | 页面布局与操作流程 |
| [渲染与画面传输链路](docs/design/05-RenderingPipeline.md) | 相机画面处理与渲染 |
| [开发路线图](docs/design/06-Roadmap.md) | 阶段目标与规划 |
