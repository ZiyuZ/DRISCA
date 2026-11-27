#include "DrivingViewPawn.h"

#include "Carla.h"
#include "Carla/Game/CarlaEngine.h"
#include "Carla/Vehicle/CarlaWheeledVehicle.h"
#include "Carla/Vehicle/VehicleControl.h"
#include "Carla/Vehicle/VehicleInputPriority.h"
#include "Carla/Traffic/TrafficLightBase.h"
#include "Carla/Traffic/TrafficLightComponent.h"
#include "DrivingViewStateComponent.h"

#include <util/ue-header-guard-begin.h>
#include "Camera/CameraComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/MeshComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/HitResult.h"
#include "GameFramework/InputSettings.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerInput.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/DateTime.h"
#include "PixelFormat.h"
#include <util/ue-header-guard-end.h>

ADrivingViewPawn::ADrivingViewPawn()
{
  // 输入在物理之前写入车辆，状态由 StateComponent 在物理之后读取。
  PrimaryActorTick.bCanEverTick = true;
  PrimaryActorTick.TickGroup = TG_PrePhysics;

  RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("DrivingViewRoot"));

  MainCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("DrivingViewCamera"));
  MainCamera->SetupAttachment(RootComponent);
  MainCamera->bUsePawnControlRotation = false;
  MainCamera->bConstrainAspectRatio = false;
  MainCamera->SetFieldOfView(90.0f);

  StateComponent = CreateDefaultSubobject<UDrivingViewStateComponent>(TEXT("DrivingViewState"));
}

bool ADrivingViewPawn::Start(
    ACarlaWheeledVehicle *InEgo,
    const FDrivingViewBox &InBox,
    const FDrivingViewCamera &InFront,
    const FDrivingViewCamera &InRearTop,
    const FDrivingViewCamera &InRearLeft,
    const FDrivingViewCamera &InRearRight,
    const FDrivingViewLayout &InLayout,
    const TMap<FString, FString> &InKeyboard,
    bool bInAutopilot)
{
  Ego = InEgo;
  ViewVehicle = InEgo;
  Box = InBox;
  Front = InFront;
  RearTop = InRearTop;
  RearLeft = InRearLeft;
  RearRight = InRearRight;
  Layout = InLayout;
  bAutopilot = bInAutopilot;
  KeyMap.Empty();
  PreviousDown.Empty();

  for (const TPair<FString, FString> &Pair : InKeyboard)
  {
    if (!Pair.Value.IsEmpty())
    {
      KeyMap.Add(Pair.Key, FKey(FName(*Pair.Value)));
    }
  }

  if (UInputSettings *InputSettings = UInputSettings::GetInputSettings())
  {
    for (const TPair<FString, FKey> &Pair : KeyMap)
    {
      InputSettings->AddActionMapping(FInputActionKeyMapping(FName(*Pair.Key), Pair.Value), false);
    }
    InputSettings->ForceRebuildKeymaps();
    bInputMappingsAdded = true;
  }

  if (Ego == nullptr)
  {
    if (ViewMode == TEXT("free"))
    {
      UpdateConfig(InFront, InRearTop, InRearLeft, InRearRight, InLayout);
      State.bActive = State.bReady = true;
      return true;
    }
    State.bActive = false;
    State.bReady = false;
    State.Error = TEXT("ego vehicle not found");
    return false;
  }

  SetActorLocationAndRotation(Ego->GetActorLocation(), Ego->GetActorRotation());
  AttachToActor(Ego, FAttachmentTransformRules::KeepWorldTransform);
  Ego->AddTickPrerequisiteActor(this);

  const FVehicleControl Actual = Ego->GetVehicleControl();
  Gear = Actual.Gear;
  bReverse = Actual.bReverse;
  bHandBrake = Actual.bHandBrake;
  bManualGearShift = Actual.bManualGearShift;

  UpdateConfig(InFront, InRearTop, InRearLeft, InRearRight, InLayout);
  SetMode(bInAutopilot);

  State.bActive = true;
  State.bReady = true;
  State.Error.Empty();
  return true;
}

void ADrivingViewPawn::UpdateConfig(
    const FDrivingViewCamera &InFront,
    const FDrivingViewCamera &InRearTop,
    const FDrivingViewCamera &InRearLeft,
    const FDrivingViewCamera &InRearRight,
    const FDrivingViewLayout &InLayout)
{
  Front = InFront;
  RearTop = InRearTop;
  RearLeft = InRearLeft;
  RearRight = InRearRight;
  Layout = InLayout;

  if (MainCamera != nullptr && !bCameraInitialized)
  {
    const FVector Offset = Box.Rotation.RotateVector(
        FVector(Box.Extent.X * Front.X, Box.Extent.Y * Front.Y, Box.Extent.Z * Front.Z));
    if (ViewMode == TEXT("chase") && ViewVehicle)
    {
      const float Yaw = ViewVehicle->GetActorRotation().Yaw;
      ChaseLocation = ViewVehicle->GetActorLocation() +
          FRotator(0, Yaw, 0).RotateVector(FVector(-750, 0, 320));
      ChaseRotation = FRotator(-12, Yaw, 0);
      bChaseInitialized = true;
      MainCamera->SetWorldLocationAndRotation(ChaseLocation, ChaseRotation);
    }
    else
    {
      MainCamera->SetRelativeLocationAndRotation(
          Box.Location + Offset,
          FRotator(Front.Pitch, Front.Yaw, Front.Roll));
    }
    MainCamera->SetFieldOfView(Front.Fov);
    bCameraInitialized = true;
  }

  // 位置/边框/可见性可以直接生效，只有数量或分辨率变化才重建 RenderTarget。
  bool bReuseMirrors = ViewMode == TEXT("cockpit") && Layout.bShowRearview && Mirrors.Num() == 3;
  const FDrivingViewViewport *Viewports[3] = {
      &Layout.RearTop, &Layout.RearLeft, &Layout.RearRight};
  for (int32 Index = 0; bReuseMirrors && Index < 3; ++Index)
  {
    bReuseMirrors =
        Viewports[Index]->ImageSize.X == Mirrors[Index].ImageSize.X &&
        Viewports[Index]->ImageSize.Y == Mirrors[Index].ImageSize.Y;
  }

  if (bReuseMirrors)
  {
    ApplyLayoutToMirrors();
  }
  else
  {
    BuildMirrors();
  }
}

void ADrivingViewPawn::ApplyLayoutToMirrors()
{
  const FDrivingViewViewport *Viewports[3] = {
      &Layout.RearTop, &Layout.RearLeft, &Layout.RearRight};
  for (int32 Index = 0; Index < Mirrors.Num() && Index < 3; ++Index)
  {
    Mirrors[Index].ScreenPosition = Viewports[Index]->ScreenPosition;
    Mirrors[Index].bVisible = Viewports[Index]->bVisible;
    if (USceneCaptureComponent2D *Capture = Mirrors[Index].Capture)
    {
      Capture->bCaptureEveryFrame = Mirrors[Index].bVisible;
      Capture->SetComponentTickEnabled(Mirrors[Index].bVisible);
    }
    Mirrors[Index].BorderWidth = Layout.BorderWidth;
    Mirrors[Index].BorderColor = Layout.BorderColor;
  }
  ApplyMirrorTransforms();
}

void ADrivingViewPawn::BuildMirrors()
{
  ClearMirrors();
  if (ViewMode != TEXT("cockpit") || ViewVehicle == nullptr || !Layout.bShowRearview || RootComponent == nullptr)
  {
    return;
  }

  const FDrivingViewCamera *Cameras[3] = {&RearTop, &RearLeft, &RearRight};
  const FDrivingViewViewport *Viewports[3] = {
      &Layout.RearTop, &Layout.RearLeft, &Layout.RearRight};

  for (int32 Index = 0; Index < 3; ++Index)
  {
    const int32 Width = FMath::Max(32, Viewports[Index]->ImageSize.X);
    const int32 Height = FMath::Max(24, Viewports[Index]->ImageSize.Y);

    UTextureRenderTarget2D *Target = NewObject<UTextureRenderTarget2D>(this);
    Target->RenderTargetFormat = RTF_RGBA8;
    Target->ClearColor = FLinearColor::Black;
    Target->bAutoGenerateMips = false;
    Target->InitCustomFormat(Width, Height, PF_B8G8R8A8, false);
    Target->SRGB = true;
    Target->UpdateResourceImmediate(true);

    USceneCaptureComponent2D *Capture = NewObject<USceneCaptureComponent2D>(this);
    Capture->SetupAttachment(RootComponent);
    Capture->RegisterComponent();
    Capture->FOVAngle = Cameras[Index]->Fov;
    Capture->TextureTarget = Target;
    Capture->CaptureSource = ESceneCaptureSource::SCS_FinalToneCurveHDR;
    Capture->bCaptureEveryFrame = Viewports[Index]->bVisible;
    Capture->SetComponentTickEnabled(Viewports[Index]->bVisible);
    Capture->bCaptureOnMovement = false;
    Capture->bAlwaysPersistRenderingState = true;
    Capture->SetRelativeLocationAndRotation(
        Box.Location + Box.Rotation.RotateVector(FVector(
            Box.Extent.X * Cameras[Index]->X,
            Box.Extent.Y * Cameras[Index]->Y,
            Box.Extent.Z * Cameras[Index]->Z)),
        FRotator(Cameras[Index]->Pitch, Cameras[Index]->Yaw, Cameras[Index]->Roll));

    FDrivingViewMirror Mirror;
    Mirror.ScreenPosition = Viewports[Index]->ScreenPosition;
    Mirror.ImageSize = FIntPoint(Width, Height);
    Mirror.bVisible = Viewports[Index]->bVisible;
    Mirror.BorderWidth = Layout.BorderWidth;
    Mirror.BorderColor = Layout.BorderColor;
    Mirror.RenderTarget = Target;
    Mirror.Capture = Capture;

    Mirrors.Add(Mirror);
    MirrorCaptures.Add(Capture);
    MirrorTargets.Add(Target);
  }
}

void ADrivingViewPawn::ClearMirrors()
{
  for (const TObjectPtr<USceneCaptureComponent2D> &Capture : MirrorCaptures)
  {
    if (IsValid(Capture))
    {
      Capture->Deactivate();
      Capture->DestroyComponent();
    }
  }
  for (const TObjectPtr<UTextureRenderTarget2D> &Target : MirrorTargets)
  {
    if (IsValid(Target))
    {
      Target->ReleaseResource();
    }
  }
  MirrorCaptures.Empty();
  MirrorTargets.Empty();
  Mirrors.Empty();
}

void ADrivingViewPawn::ApplyMirrorTransforms()
{
  const FDrivingViewCamera *Cameras[3] = {&RearTop, &RearLeft, &RearRight};
  for (int32 Index = 0; Index < Mirrors.Num() && Index < 3; ++Index)
  {
    if (Mirrors[Index].Capture == nullptr)
    {
      continue;
    }
    Mirrors[Index].Capture->SetRelativeLocationAndRotation(
        Box.Location + Box.Rotation.RotateVector(FVector(
            Box.Extent.X * Cameras[Index]->X,
            Box.Extent.Y * Cameras[Index]->Y,
            Box.Extent.Z * Cameras[Index]->Z)),
        FRotator(Cameras[Index]->Pitch, Cameras[Index]->Yaw, Cameras[Index]->Roll));
    Mirrors[Index].Capture->FOVAngle = Cameras[Index]->Fov;
  }
}

void ADrivingViewPawn::SetMode(bool bEnableAutopilot)
{
  // 车辆是否由 Traffic Manager 驱动由 Python 决定（vehicle.set_autopilot），
  // 这里只记录模式、屏蔽手动控制，避免两个地方同时切换控制权。
  bAutopilot = bEnableAutopilot;

  if (!bEnableAutopilot && Ego != nullptr)
  {
    const FVehicleControl Actual = Ego->GetVehicleControl();
    Gear = Actual.Gear;
    bReverse = Actual.bReverse;
    bHandBrake = Actual.bHandBrake;
    bManualGearShift = Actual.bManualGearShift;
  }

  State.Mode = bAutopilot ? TEXT("autopilot") : TEXT("manual");
  State.Input.bTakeoverRequested = false;
  State.Input.bToggleAutopilotRequested = false;
}

void ADrivingViewPawn::SetExternalControl(bool bExternal)
{
  // 外部模型接管连续控制时，键盘输入继续采样，但不写入车辆。
  bExternalControl = bExternal;
  bAutopilot = false;
  State.Mode = bExternal ? TEXT("external") : TEXT("manual");
  if (!bExternal && Ego != nullptr)
  {
    const FVehicleControl Actual = Ego->GetVehicleControl();
    Gear = Actual.Gear;
    bReverse = Actual.bReverse;
    bHandBrake = Actual.bHandBrake;
    bManualGearShift = Actual.bManualGearShift;
  }
}

void ADrivingViewPawn::Stop()
{
  if (Ego != nullptr && !bAutopilot && !bExternalControl && ViewMode != TEXT("free"))
  {
    Brake = 1.0f;
    Throttle = 0.0f;
    ApplyControl();
  }
  if (bInputMappingsAdded)
  {
    if (UInputSettings *InputSettings = UInputSettings::GetInputSettings())
    {
      for (const TPair<FString, FKey> &Pair : KeyMap)
      {
        InputSettings->RemoveActionMapping(FInputActionKeyMapping(FName(*Pair.Key), Pair.Value), false);
      }
      InputSettings->ForceRebuildKeymaps();
    }
    bInputMappingsAdded = false;
  }
  ClearMirrors();
  State.bActive = false;
  State.bReady = false;
}

void ADrivingViewPawn::Tick(float DeltaSeconds)
{
  Super::Tick(DeltaSeconds);
  APlayerController *PC = UGameplayStatics::GetPlayerController(GetWorld(), 0);
  const bool bLeftDown = PC && PC->IsInputKeyDown(EKeys::LeftMouseButton);
  if (ViewMode == TEXT("free") && bLeftDown && !bSelectionMouseDown)
  {
    FHitResult Hit;
    SelectedVehicle.Reset();
    SelectedSignal.Reset();
    if (PC->GetHitResultUnderCursor(ECC_Visibility, true, Hit))
    {
      SelectedVehicle = Cast<ACarlaWheeledVehicle>(Hit.GetActor());
      if (!SelectedVehicle.IsValid())
      {
        // 灯头可能是附着的子 Actor，沿附着关系定位拥有信号组件的交通灯。
        for (AActor *Candidate = Hit.GetActor(); Candidate; Candidate = Candidate->GetAttachParentActor())
        {
          if (Cast<ATrafficLightBase>(Candidate) || Candidate->FindComponentByClass<UTrafficLightComponent>())
          {
            SelectedSignal = Candidate;
            break;
          }
        }
      }
    }
  }
  bSelectionMouseDown = bLeftDown;
  if (AActor *Signal = SelectedSignal.Get())
  {
    // 仅围住可见灯具网格，避免把车道触发盒也算进选中框。
    FBox Bounds(ForceInit);
    TInlineComponentArray<UMeshComponent *> Meshes(Signal);
    for (UMeshComponent *Mesh : Meshes)
      if (Mesh->IsRegistered() && Mesh->IsVisible()) Bounds += Mesh->Bounds.GetBox();
    if (!Bounds.IsValid)
    {
      FVector Center, Extent;
      Signal->GetActorBounds(true, Center, Extent);
      Bounds = FBox::BuildAABB(Center, Extent);
    }
    DrawDebugBox(GetWorld(), Bounds.GetCenter(), Bounds.GetExtent().ComponentMax(FVector(20)) + FVector(15),
        FColor::Magenta, false, -1, 0, 5.0f);
  }
  if (!IsValid(ViewVehicle))
  {
    return;
  }

  if (ViewMode == TEXT("chase"))
  {
    if (PC)
    {
      if (PC->WasInputKeyJustPressed(EKeys::MouseScrollUp)) ChaseDistanceMeters -= 1.0f;
      if (PC->WasInputKeyJustPressed(EKeys::MouseScrollDown)) ChaseDistanceMeters += 1.0f;
      ChaseDistanceMeters = FMath::Clamp(ChaseDistanceMeters, 4.0f, 18.0f);
      if (PC->IsInputKeyDown(EKeys::RightMouseButton))
      {
        float MouseX = 0, MouseY = 0;
        PC->GetInputMouseDelta(MouseX, MouseY);
        ChaseYawOffset = FMath::UnwindDegrees(ChaseYawOffset + MouseX * 0.7f);
        ChasePitchOffset = FMath::Clamp(ChasePitchOffset - MouseY * 0.7f, -53.0f, 47.0f);
      }
      else
      {
        ChaseYawOffset = FMath::FInterpTo(ChaseYawOffset, 0.0f, DeltaSeconds, 3.0f);
        ChasePitchOffset = FMath::FInterpTo(ChasePitchOffset, 0.0f, DeltaSeconds, 3.0f);
      }
    }
    // 在世界空间阻尼跟随，仅使用车身水平朝向，隔离路面造成的俯仰与侧倾。
    const float Yaw = ViewVehicle->GetActorRotation().Yaw;
    if (!bChaseInitialized)
    {
      ChaseLocation = MainCamera->GetComponentLocation();
      ChaseRotation = MainCamera->GetComponentRotation();
      bChaseInitialized = true;
    }
    const FRotator OrbitRotation(-12 + ChasePitchOffset, Yaw + ChaseYawOffset, 0);
    // 绕车顶附近的观察支点旋转；默认距离和俯角仍对应约 3.2 米高度。
    const float PivotHeight = 320.0f - 750.0f * FMath::Sin(FMath::DegreesToRadians(12.0f));
    const FVector TargetLocation = ViewVehicle->GetActorLocation() + FVector(0, 0, PivotHeight) +
        OrbitRotation.RotateVector(FVector(-ChaseDistanceMeters * 100.0f, 0, 0));
    ChaseRotation = FMath::RInterpTo(ChaseRotation,
        OrbitRotation, DeltaSeconds, 4.0f);
    ChaseRotation.Roll = 0;
    ChaseLocation = FMath::VInterpTo(ChaseLocation, TargetLocation, DeltaSeconds, 4.0f);
    MainCamera->SetWorldLocationAndRotation(ChaseLocation, ChaseRotation);
  }
  else
  {
    const FVector CameraLocation = Box.Location + Box.Rotation.RotateVector(
        FVector(Box.Extent.X * Front.X, Box.Extent.Y * Front.Y, Box.Extent.Z * Front.Z));
    MainCamera->SetRelativeLocationAndRotation(
        FMath::VInterpTo(MainCamera->GetRelativeLocation(), CameraLocation, DeltaSeconds, 6.0f),
        FMath::RInterpTo(MainCamera->GetRelativeRotation(), FRotator(Front.Pitch, Front.Yaw, Front.Roll), DeltaSeconds, 6.0f));
  }
  MainCamera->SetFieldOfView(Front.Fov);
  if (ViewMode == TEXT("free") || !IsValid(Ego)) return;

  // 物理推进之前：采集键盘（external 模式也保留人工输入），再按来源决定是否施加。
  SampleKeyboard(DeltaSeconds);
  ApplyControl();
}

void ADrivingViewPawn::SetViewMode(const FString &InMode)
{
  if (InMode != ViewMode) bChaseInitialized = false;
  const FTransform CameraTransform = MainCamera->GetComponentTransform();
  MainCamera->SetAbsolute(InMode == TEXT("chase"), InMode == TEXT("chase"), false);
  MainCamera->SetWorldTransform(CameraTransform);
  ViewMode = InMode;
  if (ViewMode == TEXT("cockpit")) BuildMirrors();
  else ClearMirrors();
}

FTransform ADrivingViewPawn::GetReplayReleaseTransform() const
{
  if (ViewMode == TEXT("chase")) return MainCamera->GetComponentTransform();
  if (IsValid(ViewVehicle))
  {
    const float Yaw = ViewVehicle->GetActorRotation().Yaw;
    return FTransform(FRotator(-12, Yaw, 0), ViewVehicle->GetActorLocation() +
        FRotator(0, Yaw, 0).RotateVector(FVector(-750, 0, 320)));
  }
  // 目标已在回放末帧销毁时，仍从最后相机位置抬高后交还自由观察。
  return FTransform(FRotator(-12, MainCamera->GetComponentRotation().Yaw, 0),
      MainCamera->GetComponentLocation() + FVector(0, 0, 320));
}

void ADrivingViewPawn::BindViewVehicle(ACarlaWheeledVehicle *Vehicle)
{
  const FTransform CameraTransform = MainCamera->GetComponentTransform();
  ViewVehicle = Vehicle;
  Box.Location = Vehicle->GetVehicleBoundingBoxTransform().GetLocation();
  Box.Rotation = Vehicle->GetVehicleBoundingBoxTransform().Rotator();
  Box.Extent = Vehicle->GetVehicleBoundingBoxExtent();
  AttachToActor(Vehicle, FAttachmentTransformRules::KeepWorldTransform);
  SetActorLocationAndRotation(Vehicle->GetActorLocation(), Vehicle->GetActorRotation());
  // 保留换车瞬间的世界位姿，后续 Tick 从此位置插值到新目标。
  MainCamera->SetWorldTransform(CameraTransform);
  if (ViewMode == TEXT("cockpit")) BuildMirrors();
}

void ADrivingViewPawn::SampleKeyboard(float DeltaSeconds)
{
  const APlayerController *PC = Cast<APlayerController>(GetController());
  if (PC != nullptr)
  {
    for (const TPair<FString, FKey> &Pair : KeyMap)
    {
      const bool bDown = PC->IsInputKeyDown(Pair.Value);
      const bool bWasDown = PreviousDown.Contains(Pair.Key);
      if (bDown && !bWasDown)
      {
        OnPressed(Pair.Key);
      }
      if (bDown)
      {
        PreviousDown.Add(Pair.Key);
      }
      else
      {
        PreviousDown.Remove(Pair.Key);
      }
    }
  }
  else
  {
    PreviousDown.Empty();
  }

  const float TargetSteer =
      static_cast<float>(IsDown(TEXT("drive_right"))) -
      static_cast<float>(IsDown(TEXT("drive_left")));
  const float SteerChange = (TargetSteer != 0.0f ? 0.7f : 1.4f) * DeltaSeconds;
  Steer = FMath::Clamp(Steer + FMath::Clamp(TargetSteer - Steer, -SteerChange, SteerChange), -1.0f, 1.0f);
  Throttle = IsDown(TEXT("drive_forward"))
      ? FMath::Min(1.0f, Throttle + 1.5f * DeltaSeconds)
      : 0.0f;
  Brake = IsDown(TEXT("drive_backward"))
      ? FMath::Min(1.0f, Brake + 4.0f * DeltaSeconds)
      : 0.0f;
}

bool ADrivingViewPawn::IsDown(const TCHAR *ActionName) const
{
  const APlayerController *PC = Cast<APlayerController>(GetController());
  const FKey *Key = KeyMap.Find(FString(ActionName));
  return PC != nullptr && Key != nullptr && PC->IsInputKeyDown(*Key);
}

void ADrivingViewPawn::OnPressed(const FString &ActionName)
{
  if (bAutopilot && (ActionName == TEXT("toggle_reverse") ||
                     ActionName == TEXT("toggle_handbrake") ||
                     ActionName == TEXT("toggle_manual_transmission") ||
                     ActionName == TEXT("gear_up") ||
                     ActionName == TEXT("gear_down")))
  {
    return;
  }

  if (ActionName == TEXT("toggle_autopilot"))
  {
    State.Input.bToggleAutopilotRequested = true;
  }
  else if (ActionName == TEXT("takeover"))
  {
    State.Input.bTakeoverRequested = true;
  }
  else if (ActionName == TEXT("toggle_reverse"))
  {
    bReverse = !bReverse;
    Gear = bReverse ? -1 : 1;
  }
  else if (ActionName == TEXT("toggle_handbrake"))
  {
    bHandBrake = !bHandBrake;
  }
  else if (ActionName == TEXT("toggle_manual_transmission"))
  {
    bManualGearShift = !bManualGearShift;
    if (bManualGearShift && Ego != nullptr)
    {
      const FVehicleControl Actual = Ego->GetVehicleControl();
      Gear = Actual.Gear;
      bReverse = Actual.bReverse;
    }
  }
  else if (ActionName == TEXT("gear_up") && bManualGearShift)
  {
    Gear = FMath::Max(-1, Gear + 1);
    bReverse = Gear < 0;
  }
  else if (ActionName == TEXT("gear_down") && bManualGearShift)
  {
    Gear = FMath::Max(-1, Gear - 1);
    bReverse = Gear < 0;
  }

  // 离散事件同步读取本次切换后的输入，连续状态仍在物理后采样。
  State.Input.bReverse = bReverse;
  State.Input.bHandBrake = bHandBrake;
  State.Input.bManualGearShift = bManualGearShift;
  State.Input.Gear = Gear;
  OnAction.Broadcast(ActionName);
}

void ADrivingViewPawn::ApplyControl()
{
  if (Ego == nullptr || bAutopilot || bExternalControl)
  {
    return;
  }

  FVehicleControl Control;
  Control.Throttle = Throttle;
  Control.Steer = Steer;
  Control.Brake = Brake;
  Control.bReverse = bReverse;
  Control.bHandBrake = bHandBrake;
  Control.bManualGearShift = bManualGearShift;
  Control.Gear = Gear;
  Ego->ApplyVehicleControl(Control, EVehicleInputPriority::User);
}

void ADrivingViewPawn::UpdateState(float DeltaSeconds)
{
  // 在 TG_PostPhysics 调用：帧号是刚刚完成物理的最新世界帧，
  // 位姿/速度与该帧一致；timestamp 是同一时刻的 Unreal 世界时间，wall_time 是 UTC 墙钟。
  State.Timestamp = GetWorld() != nullptr ? GetWorld()->GetTimeSeconds() : 0.0;
  const FDateTime Now = FDateTime::UtcNow();
  State.WallTime =
      static_cast<double>(Now.ToUnixTimestamp()) + static_cast<double>(Now.GetMillisecond()) / 1000.0;
  State.FrameNo = static_cast<int64>(FCarlaEngine::GetFrameCounter());
  State.Delta = DeltaSeconds;

  State.Input.Throttle = Throttle;
  State.Input.Steer = Steer;
  State.Input.Brake = Brake;
  State.Input.bReverse = bReverse;
  State.Input.bHandBrake = bHandBrake;
  State.Input.bManualGearShift = bManualGearShift;
  State.Input.Gear = Gear;

  if (Ego != nullptr)
  {
    const FVehicleControl Actual = Ego->GetVehicleControl();
    State.Control.Throttle = Actual.Throttle;
    State.Control.Steer = Actual.Steer;
    State.Control.Brake = Actual.Brake;
    State.Control.bReverse = Actual.bReverse;
    State.Control.bHandBrake = Actual.bHandBrake;
    State.Control.bManualGearShift = Actual.bManualGearShift;
    State.Control.Gear = Actual.Gear;
    State.Location = Ego->GetActorLocation() / 100.0f;
    State.Rotation = Ego->GetActorRotation();
    State.Velocity = Ego->GetVelocity() / 100.0f;
    State.bActive = true;
    State.bReady = true;
  }
  else
  {
    State.Control = State.Input;
    State.bActive = ViewMode == TEXT("free") || IsValid(ViewVehicle);
    State.bReady = State.bActive;
  }

  State.Mode = bAutopilot ? TEXT("autopilot") : (bExternalControl ? TEXT("external") : TEXT("manual"));
}

void ADrivingViewPawn::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
  if (bInputMappingsAdded)
  {
    if (UInputSettings *InputSettings = UInputSettings::GetInputSettings())
    {
      for (const TPair<FString, FKey> &Pair : KeyMap)
      {
        InputSettings->RemoveActionMapping(FInputActionKeyMapping(FName(*Pair.Key), Pair.Value), false);
      }
      InputSettings->ForceRebuildKeymaps();
    }
    bInputMappingsAdded = false;
  }
  ClearMirrors();
  State.bActive = false;
  State.bReady = false;
  Ego = nullptr;
  ViewVehicle = nullptr;
  Super::EndPlay(EndPlayReason);
}
