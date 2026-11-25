#pragma once

#include "CoreMinimal.h"

class AHUD;
class UCanvas;

/// 把驾驶视图的三张后视镜画在 CARLA HUD 的 Canvas 上。
///
/// Canvas 使用视口物理像素坐标，因此不受 Slate DPI 缩放影响；同样的原因也让
/// 布局里的 screen_position / image_size / border_width 都能按像素直接理解。
namespace DrivingViewHUD
{
  void DrawMirrors(const AHUD &HUD, UCanvas &Canvas);
}
