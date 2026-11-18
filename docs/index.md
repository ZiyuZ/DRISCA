---
layout: home
hero:
  name: DRISCA
  text: 驾驶行为研究实验平台
  tagline: 基于 CARLA，连接实验配置、模拟驾驶与数据记录
  image:
    src: /assets/icon.png
    alt: DRISCA 标志
  actions:
    - theme: brand
      text: 探索系统设计
      link: /design/01-Architecture
    - theme: alt
      text: 查看开发路线图
      link: /design/06-Roadmap
features:
  - title: 准备与控制实验
    details: 在桌面端管理实验预设、调整场景并观察运行状态。
    link: /design/04-LauncherDesign
    linkText: 桌面管理端设计
  - title: 模拟驾驶体验
    details: 结合 CARLA 场景、车载画面和驾驶外设，开展驾驶行为实验。
    link: /design/01-Architecture
    linkText: 系统架构
  - title: 记录与分析
    details: 保存实验会话、车辆状态与事件，为后续分析提供数据。
    link: /design/02-DataStructures
    linkText: 数据结构与协议
---

## 从这里开始

DRISCA 当前处于实现与实验环境验证阶段。基础契约层、驾驶模拟端和管理端已有实现；管理端采用 React 与 shadcn/ui，桌面壳采用 pywebview 无边框窗口，交互原型保存在 `prototypes/launcher/`。[快速开始](./guide/01-QuickStart.md)提供环境准备与启动步骤；[系统架构](./design/01-Architecture.md)介绍平台的组成与实验流程；[开发路线图](./design/06-Roadmap.md)记录阶段目标。

配置文件位置与填写示例见[配置管理](./guide/05-Configuration.md)。开发者可分别查阅[配置模型](./design/08-ConfigurationModels.md)、[进程通信](./design/07-Protocol.md)和[运行状态与实验数据](./design/02-DataStructures.md)。
可从[快速开始](./guide/01-QuickStart.md)或 [CARLA 服务端](./guide/02-CarlaServer.md)进入。

渲染链路与已有测量收录在[参考资料](./reference/RenderingPipeline.md)。
