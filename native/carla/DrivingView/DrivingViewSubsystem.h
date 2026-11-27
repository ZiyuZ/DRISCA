#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "DrivingViewTypes.h"
#include "DrivingViewSubsystem.generated.h"

class ADrivingViewPawn;
class FJsonObject;

/// 原生驾驶视图的创建、配置与释放。协议入口在 DriscaApi，本子系统只管理视图。
UCLASS()
class UDrivingViewSubsystem : public UWorldSubsystem
{
  GENERATED_BODY()

public:

  virtual void Deinitialize() override;

  bool StartView(const TSharedPtr<FJsonObject> &Params, FString &OutError);
  bool UpdateView(const TSharedPtr<FJsonObject> &Params, FString &OutError);
  bool StopView(FString &OutError);
  bool GetViewConfig(TSharedPtr<FJsonObject> &OutResult, FString &OutError) const;
  /// 仅供回放释放视角使用；普通预览的自由视角保留原有恢复逻辑。
  void PrepareReplayFreeView(APawn *Spectator);

  bool IsActive() const
  {
    return ActivePawn != nullptr && IsValid(ActivePawn);
  }

  ADrivingViewPawn *GetPawn() const
  {
    return IsActive() ? ActivePawn : nullptr;
  }

  const ADrivingViewPawn *GetActiveViewPawn() const
  {
    return IsActive() ? ActivePawn : nullptr;
  }

  const FDrivingViewState *GetState() const;

private:

  bool StartViewInternal(const TSharedPtr<FJsonObject> &Params, FString &OutError);
  void ApplyViewMode(const FString &Mode, bool bInitial);

  static bool ParseCamera(const TSharedPtr<FJsonObject> &Object, FDrivingViewCamera &OutCamera);
  static bool ParseBox(const TSharedPtr<FJsonObject> &Object, FDrivingViewBox &OutBox);
  static bool ParseLayout(const TSharedPtr<FJsonObject> &Object, FDrivingViewLayout &OutLayout);
  static bool ParseViewport(const TSharedPtr<FJsonObject> &Object, FDrivingViewViewport &OutViewport);
  static FLinearColor ParseColor(
      const TSharedPtr<FJsonValue> &Value, const FLinearColor &Default);
  static TSharedPtr<FJsonObject> CameraToJson(const FDrivingViewCamera &Camera);
  static TSharedPtr<FJsonObject> ViewportToJson(const FDrivingViewViewport &Viewport);
  static FString ColorToHex(const FLinearColor &Color);

  UPROPERTY()
  TObjectPtr<ADrivingViewPawn> ActivePawn = nullptr;

  TWeakObjectPtr<APawn> PreviousPawn;
  TWeakObjectPtr<AActor> PreviousViewTarget;
  bool bPreviousAutoManageCamera = true;
  bool bPreviousShowMouseCursor = false;
  TWeakObjectPtr<APlayerController> PlayerController;
};
