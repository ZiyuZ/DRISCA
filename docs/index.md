---
layout: home
hero:
  name: DRISCA
  text: 驾驶行为研究实验平台
  tagline: 基于 CARLA UE5，连接实验编排、模拟驾驶、交通流控制与数据记录
  image:
    src: /icon.png
    alt: DRISCA 标志
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/01-QuickStart
    - theme: alt
      text: 构建与部署
      link: /deploy/01-CarlaSourceAndPatch
    - theme: alt
      text: 系统设计
      link: /design/01-Architecture
features:
  - title: 桌面实验管理
    details: 在桌面管理端准备实验预设、调整天气与交通流、下发语音指令并记录实验标记。
    link: /guide/02-ExperimentWorkflow
    linkText: 查看实验流程
  - title: 驾驶渲染与交通流
    details: 在 CARLA Unreal 内直接渲染主视图与三路后视镜，支持多视角切换、背景交通流与交互场景触发。
    link: /guide/03-SceneAndTraffic
    linkText: 场景与交通流
  - title: 记录、回放与导出
    details: 自动落盘主车数据、背景车轨迹与实验事件，支持一键导出 CSV 和多视角录像回放。
    link: /guide/04-DataAndReplay
    linkText: 数据与回放
  - title: 从零构建与地图扩展
    details: 提供完整的 CARLA 补丁接入、Shipping 打包流程以及独立地图包的制作与安装说明。
    link: /deploy/01-CarlaSourceAndPatch
    linkText: 构建与部署指南
---

<div class="drisca-hero-showcase" align="center" style="margin-top: 24px;">
  <img src="./assets/screenshots/running.webp" alt="DRISCA 运行界面：CARLA 驾驶窗口与桌面管理端" style="border-radius: 10px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);" />
  <p style="margin-top: 10px; font-size: 0.875rem; color: var(--vp-c-text-2);">DRISCA 运行界面：左侧 CARLA 驾驶窗口与三路后视镜，右侧桌面管理端控制台</p>
</div>
