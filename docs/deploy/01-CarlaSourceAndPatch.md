# CARLA 源码与补丁接入

DRISCA 的驾驶渲染、三路后视镜、环境控制和高速遥测接口以原生 C++ 模块集成在 CARLA UE5 的 `Carla` 插件中。本文说明如何从零准备 CARLA UE5 源码并接入 DRISCA 原生模块。

## 交付结构说明

DRISCA 将 Unreal 侧改动拆分为两部分存放在本仓库的 `native/carla/` 目录，尽量减少对上游 CARLA 源码的侵入：

```text
native/carla/
├── DrivingView/                     # DRISCA 自研模块（24 个独立 C++ 源码文件）
└── patches/
    └── carla-drisca-native.patch    # 对既有 CARLA 源码的轻量补丁（16 个文件）
```

| 类别 | 目标位置（相对 CARLA 根目录） | 作用 |
| --- | --- | --- |
| 自研模块（24 个文件） | `Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/DrivingView/` | 驾驶视图、三路后视镜 HUD、WebSocket 服务端（7910）、二进制快照投影、环境控制器、路网与信号查询 |
| 轻量补丁（16 个文件） | `Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/` | 接入 `Carla.Build.cs`、HUD 绘制钩子、天气执行器单向投影、GNSS/IMU 帧时间记录、信号触发区及回放视角释放接口 |

## 1. 准备基础编译环境

在 Windows 开发机上准备以下基础环境（只需维护一套 UE 引擎与一套 CARLA 源码目录，即可同时承担日常开发、单 EXE 补丁编译与自定义地图烘焙）：

- **Unreal Engine 5（CARLA 定制分支，当前验证版本 UE 5.8）**：完成源码拉取与引擎构建，记录引擎根目录（例如 `D:/Simulator/UnrealEngine5_carla`）。
- **CARLA UE5 源码与 Content 资产**：**推荐直接检出官方 CARLA 1.0 基线提交（`3ea166118d`）** 及配套 `Content/Carla` 资产（含 Git LFS 实体文件），并运行官方前置依赖配置，使 `Build/` 目录完成 CMake 配置及 `LibCarla`、Boost、Recast 等依赖拉取。对齐官方 1.0 基线后，编译出的单个 `CarlaUnreal-Win64-Shipping.exe` 可直接覆盖进官方预编译包运行，无需重编或分发 7–12 GB 资源包。
- **Visual Studio Build Tools（MSVC + Windows SDK）**、**CMake**、**Ninja** 与 **Git**。
- **磁盘空间**：建议预留 180 GiB 以上可用空间用于中间构建与 Cook 缓存。

> **二进制兼容红线（面向开发者）**：UE5 `-iostore -unversioned` 打包模式按 `UPROPERTY` 顺序反序列化旧资产。16 文件补丁中严禁向任何既有 CARLA 原生类（如 `AWeather`、`UTrafficLightComponent`、`ATrafficLightBase` 等）新增、删除或重排 `UPROPERTY`；DRISCA 新增的运行期数据统一使用普通 C++ 成员变量或独立 `DrivingView` 类。遵守该约束后，后续升级 DRISCA 代码只需重编单 EXE，无需重 Cook 资源或地图包。
>
> `Carla.Build.cs` 中 Boost 扩展头文件路径（`beast`、`logic`、`static_string`）默认指向 CARLA 根目录下的 `Build/_deps/boost-src/libs/`。首次接入请保持 CARLA 默认的 `Build/` 目录布局，并先完成 CMake 依赖配置后再编译插件。

## 2. 复制 DRISCA 自研源码

在 PowerShell 中将 DRISCA 仓库内的 `native/carla/DrivingView/` 完整复制到 CARLA 源码目录：

```powershell
$DriscaRoot = "D:/dev/carla/DRISCA"
$CarlaRoot  = "D:/Simulator/CarlaUE5"
$TargetDir  = "$CarlaRoot/Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/DrivingView"

if (Test-Path $TargetDir) { Remove-Item -Recurse -Force $TargetDir }
Copy-Item -Recurse -Force "$DriscaRoot/native/carla/DrivingView" $TargetDir
```

后续 DRISCA 更新自研 C++ 代码时，重新执行上述复制命令即可同步，不会干扰 CARLA 仓库的 Git 历史。

## 3. 应用 16 文件轻量补丁

进入 CARLA 根目录，先使用 `--check` 验证补丁与当前基线完全匹配，再正式应用：

```powershell
Set-Location $CarlaRoot
git apply --check "$DriscaRoot/native/carla/patches/carla-drisca-native.patch"
git apply "$DriscaRoot/native/carla/patches/carla-drisca-native.patch"
```

该补丁仅修改 `Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/` 下的 16 个核心文件：

- 构建与服务入口：`Carla.Build.cs`、`Game/CarlaGameModeBase.cpp`、`Game/CarlaHUD.cpp`、`Server/CarlaServer.cpp`
- 传感器与回放：`Sensor/GnssSensor.{h,cpp}`、`Sensor/InertialMeasurementUnit.{h,cpp}`、`Recorder/CarlaReplayer.h`
- 交通信号：`Traffic/TrafficLightComponent.{h,cpp}`、`Traffic/TrafficLightController.h`、`Traffic/TrafficLightGroup.h`
- 环境与天空：`Weather/Sky.cpp`、`Weather/Weather.{h,cpp}`

接入完成后，继续前往[编译与基础包打包](./02-BuildAndPackage.md)完成 Editor 编译和 Shipping 打包。
