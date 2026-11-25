#include "DrivingViewHUD.h"

#include "DrivingViewPawn.h"
#include "DrivingViewSubsystem.h"

#include <util/ue-header-guard-begin.h>
#include "CanvasItem.h"
#include "Engine/Canvas.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/HUD.h"
#include <util/ue-header-guard-end.h>

namespace
{
  void DrawBorder(UCanvas &Canvas, const FVector2D &Position, const FVector2D &Size, float Width,
      const FLinearColor &Color)
  {
    const float Thickness = FMath::Min(Width, FMath::Min(Size.X, Size.Y) * 0.5f);
    if (Thickness <= 0.0f)
    {
      return;
    }

    const FVector2D Horizontal(Size.X, Thickness);
    const FVector2D Vertical(Thickness, FMath::Max(0.0f, Size.Y - 2.0f * Thickness));

    const FVector2D Edges[4] = {
        Position,
        Position + FVector2D(0.0f, Size.Y - Thickness),
        Position + FVector2D(0.0f, Thickness),
        Position + FVector2D(Size.X - Thickness, Thickness)};
    const FVector2D Sizes[4] = {
        Horizontal, Horizontal, Vertical, Vertical};

    for (int32 Index = 0; Index < 4; ++Index)
    {
      FCanvasTileItem Tile(Edges[Index], Sizes[Index], Color);
      Tile.BlendMode = SE_BLEND_Translucent;
      Canvas.DrawItem(Tile);
    }
  }
}

void DrivingViewHUD::DrawMirrors(const AHUD &HUD, UCanvas &Canvas)
{
  UWorld *World = HUD.GetWorld();
  if (World == nullptr)
  {
    return;
  }

  const UDrivingViewSubsystem *Subsystem = World->GetSubsystem<UDrivingViewSubsystem>();
  const ADrivingViewPawn *View = Subsystem != nullptr ? Subsystem->GetActiveViewPawn() : nullptr;
  if (View == nullptr)
  {
    return;
  }

  const FVector2D ViewportSize(Canvas.SizeX, Canvas.SizeY);
  for (const FDrivingViewMirror &Mirror : View->GetMirrors())
  {
    if (!Mirror.bVisible || Mirror.RenderTarget == nullptr)
    {
      continue;
    }

    FTextureRenderTargetResource *Resource = Mirror.RenderTarget->GameThread_GetRenderTargetResource();
    if (Resource == nullptr || Resource->TextureRHI == nullptr)
    {
      continue;
    }

    const FVector2D Size(Mirror.ImageSize.X, Mirror.ImageSize.Y);
    const FVector2D Position(
        Mirror.ScreenPosition.X * ViewportSize.X - Size.X * 0.5f,
        Mirror.ScreenPosition.Y * ViewportSize.Y - Size.Y * 0.5f);

    FCanvasTileItem Tile(Position, Resource, Size, FLinearColor::White);
    Tile.BlendMode = SE_BLEND_Opaque;
    Canvas.DrawItem(Tile);

    DrawBorder(Canvas, Position, Size, Mirror.BorderWidth, Mirror.BorderColor);
  }
}
