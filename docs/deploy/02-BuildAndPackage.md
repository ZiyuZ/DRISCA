# 编译与基础包打包

完成源码复制与补丁应用后，先通过 Editor 目标验证编译链接，再构建 Shipping 可执行程序或基础包。

## 1. 编译 Editor 版本（开发与调试）

打开配置好 MSVC 工具链的 Visual Studio 开发者命令行（或 PowerShell），先关闭正在运行的 `UnrealEditor.exe`、`UnrealEditor-Cmd.exe` 和 `LiveCodingConsole.exe` 进程，再执行增量编译：

```powershell
cmake --build D:/Simulator/CarlaUE5/Build --target carla-unreal-editor
```

编译通过后，在 DRISCA 管理端的 **主机配置 → 连接与服务** 中选择 **编辑器模式 (Editor)**，填入 `UnrealEditor.exe` 与 `CarlaUnreal.uproject` 路径即可调试运行。

## 2. 构建单 EXE 增量补丁

当 CARLA 源码对齐官方 **CARLA 1.0（`3ea166118d`）** 且保持既有 CARLA 类的 `UPROPERTY` 布局不变时，直接增量编译 `CarlaUnreal-Win64-Shipping.exe`：

```powershell
D:/Simulator/UnrealEngine5_carla/Engine/Build/BatchFiles/Build.bat `
  CarlaUnreal Win64 Shipping `
  -Project="D:/Simulator/CarlaUE5/Unreal/CarlaUnreal/CarlaUnreal.uproject" `
  -WaitMutex -FromMsBuild
```

产物位于 `Unreal/CarlaUnreal/Binaries/Win64/CarlaUnreal-Win64-Shipping.exe`。将该文件覆盖到官方 CARLA 1.0 预编译包的 `<CARLA目录>/CarlaUnreal/Binaries/Win64/CarlaUnreal-Win64-Shipping.exe` 即可运行，保留官方全套地图与资源包。

## 3. 构建独立三地图 Shipping 基础包

如需脱离官方预编译包独立托管完整服务端，建议构建 **Shipping** 基础包。DRISCA 基础包默认只 Cook 三个基础地图以控制体积：

- `/Game/Carla/Maps/Town10HD_Opt`
- `/Game/Carla/Maps/TestMaps/EmptyMap`
- `/Game/Carla/Maps/OpenDriveMap`

自定义扩展地图按[自定义地图与独立地图包](./03-CustomMaps.md)单独打包安装。

执行基础 Shipping 打包命令：

```powershell
cmake --build D:/Simulator/CarlaUE5/Build --target package-shipping
```

打包流程会自动执行以下关键步骤：

1. 编译 `CarlaUnreal Win64 Shipping` 游戏可执行程序。
2. 调用 UAT `BuildCookRun`（启用 `-pak -iostore -culturesToStage=en`）完成三地图 Cook 与打包。
3. 自动暂存 `Carla/Config` 运行期配置与 OpenDRIVE / Nav 数据，并执行 `CheckNoPackLeak.cmake` 检查确保 `Plugins/Packs/*` 未泄漏进基础包。
4. 整理目录结构并输出最终产物。

## 4. 完整基础包产物说明

构建完成后，主要产物位于 `D:/Simulator/CarlaUE5/Build/Package/`：

| 产物 | 用途 |
| --- | --- |
| `Carla-1.0-Win64-Shipping/` | 解压即用的 Windows Shipping 服务端目录（含 `CarlaUnreal.exe`） |
| `Carla-1.0-Win64-Shipping.zip` | 便于分发的 Shipping 基础包压缩包 |
| `carla-1.0-Win64-release-metadata.tar.gz` | 基础包发布元数据，随基础包成套归档，用于后续构建兼容的独立地图内容包 |

> 每次构建的基础包目录与同一次生成的 `release-metadata.tar.gz` 成套配对使用。

## 5. Shipping 交付验收清单

在管理端配置为 **独立发布版 (Shipping)** 后，按以下顺序验收：

1. **连接与基础地图**：启动 CARLA 后，管理端成功连接端口 `2000` 和服务端口 `7910`，地图列表包含目标基础地图。
2. **道路与主车**：在 `Town10HD_Opt` 选择有效出生点启动实验，确认 `road_valid` 为真、主视图与三路后视镜渲染正常、车内 / 第三人称 / 自由视角切换顺畅。
3. **环境与交通流**：验证全局天气平滑过渡、局部球雾区域（`Medium` 及以上画质）以及背景交通流正常运行。
4. **数据与回放**：结束实验后确认数据库写入、CSV 导出与录像回放（含多视角与切车）均正常。
5. **扩展地图（如有）**：按下一节安装独立地图包，确认地图出现在列表且出生点与路网查询正常。
