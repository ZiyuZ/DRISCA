#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "InputCoreTypes.h"
#include "DrivingViewTypes.h"
#include "DrivingViewPawn.generated.h"

class ACarlaWheeledVehicle;
class UCameraComponent;
class USceneCaptureComponent2D;
class UTextureRenderTarget2D;

DECLARE_MULTICAST_DELEGATE_OneParam(FDrivingViewActionDelegate, const FString &);

/// Unreal 侧的原生驾驶视图：主相机、键盘输入、连续控制和最新状态。
UCLASS()
class ADrivingViewPawn : public APawn
{
  GENERATED_BODY()

public:

  ADrivingViewPawn();

  virtual void Tick(float DeltaSeconds) override;
  virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

  bool Start(
      ACarlaWheeledVehicle *InEgo,
      const FDrivingViewBox &Box,
      const FDrivingViewCamera &InFront,
      const FDrivingViewCamera &InRearTop,
      const FDrivingViewCamera &InRearLeft,
      const FDrivingViewCamera &InRearRight,
      const FDrivingViewLayout &InLayout,
      const TMap<FString, FString> &InKeyboard,
      bool bInAutopilot);

  void UpdateConfig(
      const FDrivingViewCamera &InFront,
      const FDrivingViewCamera &InRearTop,
      const FDrivingViewCamera &InRearLeft,
      const FDrivingViewCamera &InRearRight,
      const FDrivingViewLayout &InLayout);
  void SetMode(bool bEnableAutopilot);
  void SetExternalControl(bool bExternal);
  void Stop();
  void UpdateState(float DeltaSeconds);
  void SetViewMode(const FString &InMode);
  const FString &GetViewMode() const { return ViewMode; }
  void BindViewVehicle(ACarlaWheeledVehicle *Vehicle);
  ACarlaWheeledVehicle *GetViewVehicle() const { return ViewVehicle; }
  ACarlaWheeledVehicle *GetSelectedVehicle() const { return SelectedVehicle.Get(); }
  AActor *GetSelectedSignal() const { return SelectedSignal.Get(); }
  FTransform GetReplayReleaseTransform() const;

  /// 每次键盘离散动作实际生效后广播，供研究采集记录事件。
  FDrivingViewActionDelegate OnAction;

  ACarlaWheeledVehicle *GetEgo() const
  {
    return Ego;
  }

  const FDrivingViewState &GetState() const
  {
    return State;
  }

  const TArray<FDrivingViewMirror> &GetMirrors() const
  {
    return Mirrors;
  }

  const TMap<FString, FKey> &GetKeyMap() const
  {
    return KeyMap;
  }

  const FDrivingViewLayout &GetLayout() const
  {
    return Layout;
  }

  const FDrivingViewCamera &GetFrontCamera() const
  {
    return Front;
  }

  const FDrivingViewCamera &GetRearTopCamera() const
  {
    return RearTop;
  }

  const FDrivingViewCamera &GetRearLeftCamera() const
  {
    return RearLeft;
  }

  const FDrivingViewCamera &GetRearRightCamera() const
  {
    return RearRight;
  }

protected:

  void OnPressed(const FString &ActionName);
  void SampleKeyboard(float DeltaSeconds);
  void ApplyControl();
  void BuildMirrors();
  void ClearMirrors();
  void ApplyLayoutToMirrors();
  void ApplyMirrorTransforms();

  bool IsDown(const TCHAR *ActionName) const;

  UPROPERTY()
  TObjectPtr<ACarlaWheeledVehicle> Ego = nullptr;
  /// 相机跟随对象与实验主车独立，切换观察目标保持研究数据归属。
  UPROPERTY()
  TObjectPtr<ACarlaWheeledVehicle> ViewVehicle = nullptr;

  UPROPERTY()
  TObjectPtr<UCameraComponent> MainCamera = nullptr;

  UPROPERTY()
  TObjectPtr<class UDrivingViewStateComponent> StateComponent = nullptr;

  UPROPERTY()
  TArray<TObjectPtr<USceneCaptureComponent2D>> MirrorCaptures;

  UPROPERTY()
  TArray<TObjectPtr<UTextureRenderTarget2D>> MirrorTargets;

  TArray<FDrivingViewMirror> Mirrors;

  TMap<FString, FKey> KeyMap;
  TSet<FString> PreviousDown;
  FDrivingViewBox Box;
  FDrivingViewCamera Front;
  FDrivingViewCamera RearTop;
  FDrivingViewCamera RearLeft;
  FDrivingViewCamera RearRight;
  FDrivingViewLayout Layout;
  FDrivingViewState State;

  bool bAutopilot = false;
  FString ViewMode = TEXT("cockpit");
  bool bCameraInitialized = false;
  bool bChaseInitialized = false;
  FVector ChaseLocation = FVector::ZeroVector;
  FRotator ChaseRotation = FRotator::ZeroRotator;
  float ChaseDistanceMeters = 7.5f;
  float ChaseYawOffset = 0.0f;
  float ChasePitchOffset = 0.0f;
  bool bSelectionMouseDown = false;
  TWeakObjectPtr<ACarlaWheeledVehicle> SelectedVehicle;
  TWeakObjectPtr<AActor> SelectedSignal;
  bool bExternalControl = false;
  bool bInputMappingsAdded = false;
  bool bReverse = false;
  bool bHandBrake = false;
  bool bManualGearShift = false;
  int32 Gear = 0;
  float Throttle = 0.0f;
  float Steer = 0.0f;
  float Brake = 0.0f;
};
