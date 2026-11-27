# CARLA 源码补丁

DRISCA 的驾驶渲染、三路后视镜、环境控制和高速遥测接口以 C++ 模块集成在 CARLA UE5 的 `Carla` 插件中。本文说明如何从零准备 CARLA UE5 源码并接入 DRISCA C++ 模块。

## 交付结构说明

DRISCA 将 Unreal 侧改动拆分为两部分存放在本仓库的 `native/carla/` 目录，与上游 CARLA 源码解耦维护：

```text
native/carla/
├── DrivingView/                     # DRISCA C++ 模块（24 个独立源码文件）
└── patches/
    ├── carla-drisca-native.patch    # 对既有 CARLA 源码的补丁（16 个文件）
    └── carla-windows-uv-setup.patch # 可选：Windows 环境下改用 uv 管理 CARLA 前置安装脚本的补丁
```

| 类别 | 目标位置（相对 CARLA 根目录） | 作用 |
| --- | --- | --- |
| C++ 模块（24 个文件） | `Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/DrivingView/` | 驾驶视图、三路后视镜 HUD、WebSocket 服务端（7910）、二进制快照投影、环境控制器、路网与信号查询 |
| 源码补丁（16 个文件） | `Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/` | 接入 `Carla.Build.cs`、HUD 绘制钩子、天气执行器单向投影、GNSS/IMU 帧时间记录、信号触发区及回放视角释放接口 |

## 1. 准备基础编译环境

在 Windows 环境中准备以下构建工具与源码：

- **Unreal Engine 5（CARLA 定制分支，当前验证版本 UE 5.8）**：完成源码拉取与引擎构建，记录引擎根目录（例如 `D:/Simulator/UnrealEngine5_carla`）。
- **CARLA UE5 源码与 Content 资产**：完成官方前置依赖配置，使 `Build/` 目录就绪 `LibCarla`、Boost、Recast 等依赖，并拉取配套 `Content/Carla` 资产（含 Git LFS 实体文件）。如需构建兼容官方 CARLA 1.0 预编译包的单 EXE 补丁，检出官方 1.0 基线提交 `3ea166118d`；如需最新上游修复与完整自托管打包，检出最新主线即可。
- **Visual Studio Build Tools（MSVC + Windows SDK）**、**CMake**、**Ninja** 与 **Git**。
- **磁盘空间**：建议预留 180 GiB 以上可用空间用于中间构建与 Cook 缓存。

> **二进制兼容约束**：UE5 `-iostore -unversioned` 打包模式按 `UPROPERTY` 顺序反序列化既有资产。16 文件补丁保持既有 CARLA C++ 类（如 `AWeather`、`UTrafficLightComponent`、`ATrafficLightBase` 等）的 `UPROPERTY` 布局不变；DRISCA 新增的运行期数据统一使用普通 C++ 成员变量或独立 `DrivingView` 类。保持该约束后，后续更新 DRISCA 代码只需重新编译单 EXE。
>
> `Carla.Build.cs` 中 Boost 扩展头文件路径（`beast`、`logic`、`static_string`）默认指向 CARLA 根目录下的 `Build/_deps/boost-src/libs/`。首次接入保持 CARLA 默认的 `Build/` 目录布局，先完成 CMake 依赖配置再编译插件。

## 2. 复制 DRISCA C++ 模块

在 PowerShell 中将 DRISCA 仓库内的 `native/carla/DrivingView/` 完整复制到 CARLA 源码目录：

```powershell
$DriscaRoot = "D:/dev/carla/DRISCA"
$CarlaRoot  = "D:/Simulator/CarlaUE5"
$TargetDir  = "$CarlaRoot/Unreal/CarlaUnreal/Plugins/Carla/Source/Carla/DrivingView"

if (Test-Path $TargetDir) { Remove-Item -Recurse -Force $TargetDir }
Copy-Item -Recurse -Force "$DriscaRoot/native/carla/DrivingView" $TargetDir
```

后续 DRISCA 更新 C++ 代码时，重新执行上述复制命令即可同步。

## 3. 应用 16 文件补丁

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
