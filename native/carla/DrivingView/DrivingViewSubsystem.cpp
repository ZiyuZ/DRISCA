#include "DrivingViewSubsystem.h"

#include "DrivingViewPawn.h"

#include "Carla.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaStatics.h"
#include "Carla/Vehicle/CarlaWheeledVehicle.h"

#include <util/ue-header-guard-begin.h>
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/Parse.h"
#include <util/ue-header-guard-end.h>

void UDrivingViewSubsystem::Deinitialize()
{
  FString Error;
  StopView(Error);
  Super::Deinitialize();
}

bool UDrivingViewSubsystem::StartView(
    const TSharedPtr<FJsonObject> &Params, FString &OutError)
{
  if (IsActive())
  {
    OutError = TEXT("driving view is already active, use update to change it");
    return false;
  }
  return StartViewInternal(Params, OutError);
}

bool UDrivingViewSubsystem::StartViewInternal(
    const TSharedPtr<FJsonObject> &Params, FString &OutError)
{
  FString ViewMode = TEXT("cockpit");
  if (Params->HasField(TEXT("view_mode")) && (!Params->TryGetStringField(TEXT("view_mode"), ViewMode) ||
      (ViewMode != TEXT("free") && ViewMode != TEXT("cockpit") && ViewMode != TEXT("chase"))))
  { OutError = TEXT("view_mode 必须是 free、cockpit 或 chase"); return false; }
  if (ViewMode != TEXT("free") && !Params->HasTypedField<EJson::Number>(TEXT("ego_actor_id")))
  {
    OutError = TEXT("missing ego_actor_id");
    return false;
  }
  const int32 EgoId = Params->HasField(TEXT("ego_actor_id")) ? Params->GetIntegerField(TEXT("ego_actor_id")) : 0;

  FDrivingViewBox Box;
  const TSharedPtr<FJsonObject> *BoxObject = nullptr;
  if (Params->TryGetObjectField(TEXT("box"), BoxObject) && BoxObject != nullptr)
  {
    if (!ParseBox(*BoxObject, Box))
    {
      OutError = TEXT("invalid box");
      return false;
    }
  }

  FDrivingViewCamera Front;
  FDrivingViewCamera RearTop;
  FDrivingViewCamera RearLeft;
  FDrivingViewCamera RearRight;
  const TSharedPtr<FJsonObject> *CamerasObject = nullptr;
  const TSharedPtr<FJsonObject> *FrontObject = nullptr;
  const TSharedPtr<FJsonObject> *RearTopObject = nullptr;
  const TSharedPtr<FJsonObject> *RearLeftObject = nullptr;
  const TSharedPtr<FJsonObject> *RearRightObject = nullptr;
  if (Params->TryGetObjectField(TEXT("cameras"), CamerasObject) && CamerasObject != nullptr)
  {
    if ((*CamerasObject)->TryGetObjectField(TEXT("front"), FrontObject) && FrontObject != nullptr)
    {
      if (!ParseCamera(*FrontObject, Front))
      {
        OutError = TEXT("invalid front camera");
        return false;
      }
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_top"), RearTopObject) && RearTopObject != nullptr)
    {
      ParseCamera(*RearTopObject, RearTop);
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_left"), RearLeftObject) && RearLeftObject != nullptr)
    {
      ParseCamera(*RearLeftObject, RearLeft);
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_right"), RearRightObject) && RearRightObject != nullptr)
    {
      ParseCamera(*RearRightObject, RearRight);
    }
  }

  FDrivingViewLayout Layout;
  const TSharedPtr<FJsonObject> *LayoutObject = nullptr;
  if (Params->TryGetObjectField(TEXT("layout"), LayoutObject) && LayoutObject != nullptr)
  {
    if (!ParseLayout(*LayoutObject, Layout))
    {
      OutError = TEXT("invalid layout");
      return false;
    }
  }

  TMap<FString, FString> Keyboard;
  const TSharedPtr<FJsonObject> *KeyboardObject = nullptr;
  if (Params->TryGetObjectField(TEXT("keyboard"), KeyboardObject) && KeyboardObject != nullptr)
  {
    for (const TPair<FString, TSharedPtr<FJsonValue>> &Pair : (*KeyboardObject)->Values)
    {
      if (Pair.Value.IsValid() && Pair.Value->Type == EJson::String)
      {
        Keyboard.Add(Pair.Key, Pair.Value->AsString());
      }
    }
  }

  FString Mode = TEXT("manual");
  Params->TryGetStringField(TEXT("mode"), Mode);
  if (Mode != TEXT("manual") && Mode != TEXT("autopilot"))
  {
    OutError = TEXT("mode must be manual or autopilot");
    return false;
  }

  UCarlaEpisode *Episode = UCarlaStatics::GetCurrentEpisode(GetWorld());
  if (Episode == nullptr)
  {
    OutError = TEXT("CARLA episode unavailable");
    return false;
  }

  FCarlaActor *CarlaActor = Episode->FindCarlaActor(EgoId);
  if (CarlaActor == nullptr && (EgoId != 0 || ViewMode != TEXT("free")))
  {
    OutError = TEXT("ego actor not found");
    return false;
  }

  ACarlaWheeledVehicle *Ego = CarlaActor ? Cast<ACarlaWheeledVehicle>(CarlaActor->GetActor()) : nullptr;
  if (Ego == nullptr && (EgoId != 0 || ViewMode != TEXT("free")))
  {
    OutError = TEXT("ego actor is not a wheeled vehicle");
    return false;
  }

  APlayerController *PC = UGameplayStatics::GetPlayerController(GetWorld(), 0);
  if (PC == nullptr)
  {
    OutError = TEXT("player controller unavailable");
    return false;
  }

  FActorSpawnParameters SpawnParameters;
  SpawnParameters.SpawnCollisionHandlingOverride =
      ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
  ADrivingViewPawn *Pawn = GetWorld()->SpawnActor<ADrivingViewPawn>(
      ADrivingViewPawn::StaticClass(), Ego ? Ego->GetActorTransform() : FTransform::Identity, SpawnParameters);
  if (Pawn == nullptr)
  {
    OutError = TEXT("cannot spawn driving view pawn");
    return false;
  }

  Pawn->SetViewMode(ViewMode);
  if (!Pawn->Start(
          Ego, Box, Front, RearTop, RearLeft, RearRight, Layout, Keyboard,
          Mode == TEXT("autopilot")))
  {
    Pawn->Destroy();
    OutError = TEXT("driving view start failed");
    return false;
  }

  PreviousPawn = PC->GetPawn();
  PreviousViewTarget = PC->GetViewTarget();
  bPreviousAutoManageCamera = PC->bAutoManageActiveCameraTarget;
  bPreviousShowMouseCursor = PC->bShowMouseCursor;
  PlayerController = PC;
  ActivePawn = Pawn;
  ApplyViewMode(ViewMode, true);
  return true;
}

bool UDrivingViewSubsystem::UpdateView(
    const TSharedPtr<FJsonObject> &Params, FString &OutError)
{
  if (!IsActive())
  {
    OutError = TEXT("driving view is not active");
    return false;
  }

  FString Mode = ActivePawn->GetViewMode();
  if (Params->HasField(TEXT("view_mode")) && (!Params->TryGetStringField(TEXT("view_mode"), Mode) ||
      (Mode != TEXT("free") && Mode != TEXT("cockpit") && Mode != TEXT("chase"))))
  { OutError = TEXT("view_mode 必须是 free、cockpit 或 chase"); return false; }
  if (Params->HasField(TEXT("ego_actor_id")) || (Mode != TEXT("free") && ActivePawn->GetViewVehicle() == nullptr))
  {
    double Id = 0;
    if (!Params->TryGetNumberField(TEXT("ego_actor_id"), Id) || !FMath::IsFinite(Id) ||
        Id <= 0 || Id > MAX_uint32 || FMath::FloorToDouble(Id) != Id)
    { OutError = TEXT("ego_actor_id 必须是有效车辆编号"); return false; }
    UCarlaEpisode *Episode = UCarlaStatics::GetCurrentEpisode(GetWorld());
    FCarlaActor *Actor = Episode ? Episode->FindCarlaActor(static_cast<uint32>(Id)) : nullptr;
    auto *Vehicle = Actor ? Cast<ACarlaWheeledVehicle>(Actor->GetActor()) : nullptr;
    if (!Vehicle) { OutError = TEXT("切换视角需要绑定车辆"); return false; }
    if (ActivePawn->GetViewVehicle() != Vehicle) ActivePawn->BindViewVehicle(Vehicle);
  }

  // 只更新调用方提供的部分，未提供的保持当前值（便于实验时动态调布局）。
  FDrivingViewCamera Front = ActivePawn->GetFrontCamera();
  FDrivingViewCamera RearTop = ActivePawn->GetRearTopCamera();
  FDrivingViewCamera RearLeft = ActivePawn->GetRearLeftCamera();
  FDrivingViewCamera RearRight = ActivePawn->GetRearRightCamera();
  const TSharedPtr<FJsonObject> *CamerasObject = nullptr;
  const TSharedPtr<FJsonObject> *FrontObject = nullptr;
  const TSharedPtr<FJsonObject> *RearTopObject = nullptr;
  const TSharedPtr<FJsonObject> *RearLeftObject = nullptr;
  const TSharedPtr<FJsonObject> *RearRightObject = nullptr;
  if (Params->TryGetObjectField(TEXT("cameras"), CamerasObject) && CamerasObject != nullptr)
  {
    if ((*CamerasObject)->TryGetObjectField(TEXT("front"), FrontObject) && FrontObject != nullptr)
    {
      ParseCamera(*FrontObject, Front);
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_top"), RearTopObject) && RearTopObject != nullptr)
    {
      ParseCamera(*RearTopObject, RearTop);
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_left"), RearLeftObject) && RearLeftObject != nullptr)
    {
      ParseCamera(*RearLeftObject, RearLeft);
    }
    if ((*CamerasObject)->TryGetObjectField(TEXT("rear_right"), RearRightObject) && RearRightObject != nullptr)
    {
      ParseCamera(*RearRightObject, RearRight);
    }
  }

  FDrivingViewLayout Layout = ActivePawn->GetLayout();
  const TSharedPtr<FJsonObject> *LayoutObject = nullptr;
  if (Params->TryGetObjectField(TEXT("layout"), LayoutObject) && LayoutObject != nullptr)
  {
    ParseLayout(*LayoutObject, Layout);
  }

  ActivePawn->UpdateConfig(Front, RearTop, RearLeft, RearRight, Layout);
  if (Mode != ActivePawn->GetViewMode()) ApplyViewMode(Mode, false);
  return true;
}

void UDrivingViewSubsystem::ApplyViewMode(const FString &Mode, bool bInitial)
{
  APlayerController *PC = PlayerController.Get();
  const bool bLeavingFree = ActivePawn->GetViewMode() == TEXT("free") && Mode != TEXT("free");
  if (bLeavingFree && !bInitial)
  {
    PreviousPawn = PC->GetPawn();
    PreviousViewTarget = PC->GetViewTarget();
  }
  ActivePawn->SetViewMode(Mode);
  PC->bShowMouseCursor = Mode == TEXT("free") ? true : bPreviousShowMouseCursor;
  if (Mode == TEXT("free"))
  {
    if (bInitial) return;
    AActor *From = PC->GetViewTarget();
    PC->bAutoManageActiveCameraTarget = false;
    if (PreviousPawn.IsValid()) PC->Possess(PreviousPawn.Get());
    else PC->UnPossess();
    PC->SetViewTarget(From);
    PC->SetViewTargetWithBlend(PreviousViewTarget.IsValid() ? PreviousViewTarget.Get() : PC->GetPawnOrSpectator(), 0.35f);
    PC->bAutoManageActiveCameraTarget = bPreviousAutoManageCamera;
  }
  else
  {
    AActor *From = PC->GetViewTarget();
    PC->bAutoManageActiveCameraTarget = false;
    PC->Possess(ActivePawn);
    PC->SetViewTarget(From);
    PC->SetViewTargetWithBlend(ActivePawn, bInitial ? 0.0f : 0.35f);
    PC->bAutoManageActiveCameraTarget = bPreviousAutoManageCamera;
  }
}

void UDrivingViewSubsystem::PrepareReplayFreeView(APawn *Spectator)
{
  if (!IsActive() || !Spectator || ActivePawn->GetViewMode() == TEXT("free")) return;
  const FTransform View = ActivePawn->GetReplayReleaseTransform();
  Spectator->SetActorLocationAndRotation(View.GetLocation(), View.Rotator(),
      false, nullptr, ETeleportType::TeleportPhysics);
  PreviousPawn = Spectator;
  PreviousViewTarget = Spectator;
  if (APlayerController *PC = PlayerController.Get()) PC->SetControlRotation(View.Rotator());
}

bool UDrivingViewSubsystem::StopView(FString &OutError)
{
  if (ActivePawn == nullptr)
  {
    return true;
  }

  if (IsValid(ActivePawn))
  {
    ActivePawn->Stop();
  }

  if (APlayerController *PC = PlayerController.Get(); PC && ActivePawn->GetViewMode() != TEXT("free"))
  {
    if (APawn *Previous = PreviousPawn.Get())
    {
      PC->Possess(Previous);
    }
    else
    {
      PC->SetViewTarget(PC->GetPawnOrSpectator());
    }
    if (PreviousViewTarget.IsValid()) PC->SetViewTarget(PreviousViewTarget.Get());
  }

  if (IsValid(ActivePawn))
  {
    ActivePawn->Destroy();
  }
  if (APlayerController *PC = PlayerController.Get()) PC->bShowMouseCursor = bPreviousShowMouseCursor;
  ActivePawn = nullptr;
  PreviousPawn.Reset();
  PreviousViewTarget.Reset();
  PlayerController.Reset();
  return true;
}

const FDrivingViewState *UDrivingViewSubsystem::GetState() const
{
  return IsActive() ? &ActivePawn->GetState() : nullptr;
}

TSharedPtr<FJsonObject> UDrivingViewSubsystem::StateToJson(const FDrivingViewState &State) const
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("timestamp"), State.Timestamp);
  Result->SetNumberField(TEXT("wall_time"), State.WallTime);
  Result->SetNumberField(TEXT("frame_no"), static_cast<double>(State.FrameNo));
  Result->SetNumberField(TEXT("delta"), State.Delta);
  Result->SetObjectField(TEXT("input"), InputToJson(State.Input));
  Result->SetObjectField(TEXT("control"), InputToJson(State.Control));
  Result->SetArrayField(TEXT("location"), VectorToJson(State.Location));
  Result->SetArrayField(TEXT("rotation"), RotatorToJson(State.Rotation));
  Result->SetArrayField(TEXT("velocity"), VectorToJson(State.Velocity));
  Result->SetStringField(TEXT("mode"), State.Mode);
  Result->SetBoolField(TEXT("active"), State.bActive);
  Result->SetBoolField(TEXT("ready"), State.bReady);
  Result->SetStringField(TEXT("error"), State.Error);
  return Result;
}

TSharedPtr<FJsonObject> UDrivingViewSubsystem::InputToJson(const FDrivingViewInput &Input) const
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("throttle"), Input.Throttle);
  Result->SetNumberField(TEXT("steer"), Input.Steer);
  Result->SetNumberField(TEXT("brake"), Input.Brake);
  Result->SetBoolField(TEXT("reverse"), Input.bReverse);
  Result->SetBoolField(TEXT("hand_brake"), Input.bHandBrake);
  Result->SetBoolField(TEXT("manual_gear_shift"), Input.bManualGearShift);
  Result->SetNumberField(TEXT("gear"), Input.Gear);
  Result->SetBoolField(TEXT("takeover_requested"), Input.bTakeoverRequested);
  Result->SetBoolField(TEXT("toggle_autopilot_requested"), Input.bToggleAutopilotRequested);
  return Result;
}

TArray<TSharedPtr<FJsonValue>> UDrivingViewSubsystem::VectorToJson(const FVector &Value)
{
  return {
      MakeShared<FJsonValueNumber>(Value.X),
      MakeShared<FJsonValueNumber>(Value.Y),
      MakeShared<FJsonValueNumber>(Value.Z)};
}

TArray<TSharedPtr<FJsonValue>> UDrivingViewSubsystem::RotatorToJson(const FRotator &Value)
{
  return {
      MakeShared<FJsonValueNumber>(Value.Pitch),
      MakeShared<FJsonValueNumber>(Value.Yaw),
      MakeShared<FJsonValueNumber>(Value.Roll)};
}

bool UDrivingViewSubsystem::GetViewConfig(
    TSharedPtr<FJsonObject> &OutResult, FString &OutError) const
{
  if (!IsActive())
  {
    OutError = TEXT("driving view is not active");
    return false;
  }

  const ADrivingViewPawn &View = *ActivePawn;
  const FDrivingViewLayout &Layout = View.GetLayout();

  TSharedPtr<FJsonObject> Cameras = MakeShared<FJsonObject>();
  Cameras->SetObjectField(TEXT("front"), CameraToJson(View.GetFrontCamera()));
  Cameras->SetObjectField(TEXT("rear_top"), CameraToJson(View.GetRearTopCamera()));
  Cameras->SetObjectField(TEXT("rear_left"), CameraToJson(View.GetRearLeftCamera()));
  Cameras->SetObjectField(TEXT("rear_right"), CameraToJson(View.GetRearRightCamera()));

  TSharedPtr<FJsonObject> LayoutJson = MakeShared<FJsonObject>();
  LayoutJson->SetBoolField(TEXT("show_rearview"), Layout.bShowRearview);
  LayoutJson->SetNumberField(TEXT("border_width"), Layout.BorderWidth);
  LayoutJson->SetStringField(TEXT("border_color"), ColorToHex(Layout.BorderColor));
  LayoutJson->SetObjectField(TEXT("rear_top"), ViewportToJson(Layout.RearTop));
  LayoutJson->SetObjectField(TEXT("rear_left"), ViewportToJson(Layout.RearLeft));
  LayoutJson->SetObjectField(TEXT("rear_right"), ViewportToJson(Layout.RearRight));

  TSharedPtr<FJsonObject> Keyboard = MakeShared<FJsonObject>();
  for (const TPair<FString, FKey> &Pair : View.GetKeyMap())
  {
    Keyboard->SetStringField(Pair.Key, Pair.Value.ToString());
  }

  OutResult->SetBoolField(TEXT("active"), true);
  OutResult->SetStringField(TEXT("view_mode"), View.GetViewMode());
  UCarlaEpisode *Episode = UCarlaStatics::GetCurrentEpisode(GetWorld());
  const FCarlaActor *FollowActor = Episode && View.GetViewVehicle() ? Episode->FindCarlaActor(View.GetViewVehicle()) : nullptr;
  OutResult->SetNumberField(TEXT("ego_actor_id"), FollowActor ? FollowActor->GetActorId() : 0);
  OutResult->SetStringField(TEXT("mode"), View.GetState().Mode);
  OutResult->SetObjectField(TEXT("cameras"), Cameras);
  OutResult->SetObjectField(TEXT("layout"), LayoutJson);
  OutResult->SetObjectField(TEXT("keyboard"), Keyboard);
  return true;
}

TSharedPtr<FJsonObject> UDrivingViewSubsystem::CameraToJson(const FDrivingViewCamera &Camera)
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("x"), Camera.X);
  Result->SetNumberField(TEXT("y"), Camera.Y);
  Result->SetNumberField(TEXT("z"), Camera.Z);
  Result->SetNumberField(TEXT("pitch"), Camera.Pitch);
  Result->SetNumberField(TEXT("yaw"), Camera.Yaw);
  Result->SetNumberField(TEXT("roll"), Camera.Roll);
  Result->SetNumberField(TEXT("fov"), Camera.Fov);
  return Result;
}

TSharedPtr<FJsonObject> UDrivingViewSubsystem::ViewportToJson(
    const FDrivingViewViewport &Viewport)
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetArrayField(TEXT("screen_position"), {
      MakeShared<FJsonValueNumber>(Viewport.ScreenPosition.X),
      MakeShared<FJsonValueNumber>(Viewport.ScreenPosition.Y)});
  Result->SetArrayField(TEXT("image_size"), {
      MakeShared<FJsonValueNumber>(Viewport.ImageSize.X),
      MakeShared<FJsonValueNumber>(Viewport.ImageSize.Y)});
  return Result;
}

FString UDrivingViewSubsystem::ColorToHex(const FLinearColor &Color)
{
  const FColor Srgb = Color.ToFColor(true);
  return FString::Printf(TEXT("#%02X%02X%02X"), Srgb.R, Srgb.G, Srgb.B);
}

bool UDrivingViewSubsystem::ParseCamera(
    const TSharedPtr<FJsonObject> &Object, FDrivingViewCamera &OutCamera)
{
  OutCamera.X = Object->GetNumberField(TEXT("x"));
  OutCamera.Y = Object->GetNumberField(TEXT("y"));
  OutCamera.Z = Object->GetNumberField(TEXT("z"));
  OutCamera.Pitch = Object->GetNumberField(TEXT("pitch"));
  OutCamera.Yaw = Object->GetNumberField(TEXT("yaw"));
  OutCamera.Roll = Object->GetNumberField(TEXT("roll"));
  const double Fov = Object->GetNumberField(TEXT("fov"));
  OutCamera.Fov = Fov > 0.0 ? static_cast<float>(Fov) : 90.0f;
  return true;
}

bool UDrivingViewSubsystem::ParseBox(
    const TSharedPtr<FJsonObject> &Object, FDrivingViewBox &OutBox)
{
  const TSharedPtr<FJsonObject> *Location = nullptr;
  const TSharedPtr<FJsonObject> *Extent = nullptr;
  const TSharedPtr<FJsonObject> *Rotation = nullptr;
  if (Object->TryGetObjectField(TEXT("location"), Location) && Location != nullptr)
  {
    OutBox.Location = FVector(
        (*Location)->GetNumberField(TEXT("x")),
        (*Location)->GetNumberField(TEXT("y")),
        (*Location)->GetNumberField(TEXT("z"))) * 100.0f;
  }
  if (Object->TryGetObjectField(TEXT("extent"), Extent) && Extent != nullptr)
  {
    OutBox.Extent = FVector(
        (*Extent)->GetNumberField(TEXT("x")),
        (*Extent)->GetNumberField(TEXT("y")),
        (*Extent)->GetNumberField(TEXT("z"))) * 100.0f;
  }
  if (Object->TryGetObjectField(TEXT("rotation"), Rotation) && Rotation != nullptr)
  {
    OutBox.Rotation = FRotator(
        (*Rotation)->GetNumberField(TEXT("pitch")),
        (*Rotation)->GetNumberField(TEXT("yaw")),
        (*Rotation)->GetNumberField(TEXT("roll")));
  }
  return true;
}

bool UDrivingViewSubsystem::ParseLayout(
    const TSharedPtr<FJsonObject> &Object, FDrivingViewLayout &OutLayout)
{
  bool bShowRearview = OutLayout.bShowRearview;
  if (Object->TryGetBoolField(TEXT("show_rearview"), bShowRearview))
  {
    OutLayout.bShowRearview = bShowRearview;
  }

  double BorderWidth = OutLayout.BorderWidth;
  if (Object->TryGetNumberField(TEXT("border_width"), BorderWidth))
  {
    OutLayout.BorderWidth = FMath::Max(0.0f, static_cast<float>(BorderWidth));
  }
  OutLayout.BorderColor = ParseColor(Object->TryGetField(TEXT("border_color")), OutLayout.BorderColor);

  const TSharedPtr<FJsonObject> *ViewportObject = nullptr;
  if (Object->TryGetObjectField(TEXT("rear_top"), ViewportObject) && ViewportObject != nullptr)
  {
    ParseViewport(*ViewportObject, OutLayout.RearTop);
  }
  if (Object->TryGetObjectField(TEXT("rear_left"), ViewportObject) && ViewportObject != nullptr)
  {
    ParseViewport(*ViewportObject, OutLayout.RearLeft);
  }
  if (Object->TryGetObjectField(TEXT("rear_right"), ViewportObject) && ViewportObject != nullptr)
  {
    ParseViewport(*ViewportObject, OutLayout.RearRight);
  }
  return true;
}

FLinearColor UDrivingViewSubsystem::ParseColor(
    const TSharedPtr<FJsonValue> &Value, const FLinearColor &Default)
{
  if (!Value.IsValid())
  {
    return Default;
  }

  // Accept "#RRGGBB", "#RRGGBBAA" or [r, g, b] / [r, g, b, a] with 0-255 channels.
  if (Value->Type == EJson::String)
  {
    FString Text = Value->AsString().TrimStartAndEnd();
    Text.RemoveFromStart(TEXT("#"));
    if (Text.Len() == 6 || Text.Len() == 8)
    {
      const int32 Red = FParse::HexNumber(*Text.Mid(0, 2));
      const int32 Green = FParse::HexNumber(*Text.Mid(2, 2));
      const int32 Blue = FParse::HexNumber(*Text.Mid(4, 2));
      const int32 Alpha = Text.Len() == 8 ? FParse::HexNumber(*Text.Mid(6, 2)) : 255;
      return FLinearColor(
          FLinearColor::FromSRGBColor(FColor(
              static_cast<uint8>(Red), static_cast<uint8>(Green),
              static_cast<uint8>(Blue), static_cast<uint8>(Alpha))));
    }
    return Default;
  }

  if (Value->Type == EJson::Array)
  {
    const TArray<TSharedPtr<FJsonValue>> &Channels = Value->AsArray();
    if (Channels.Num() >= 3)
    {
      const double Alpha = Channels.Num() >= 4 ? Channels[3]->AsNumber() : 255.0;
      return FLinearColor::FromSRGBColor(FColor(
          static_cast<uint8>(FMath::Clamp(Channels[0]->AsNumber(), 0.0, 255.0)),
          static_cast<uint8>(FMath::Clamp(Channels[1]->AsNumber(), 0.0, 255.0)),
          static_cast<uint8>(FMath::Clamp(Channels[2]->AsNumber(), 0.0, 255.0)),
          static_cast<uint8>(FMath::Clamp(Alpha, 0.0, 255.0))));
    }
  }

  return Default;
}

bool UDrivingViewSubsystem::ParseViewport(
    const TSharedPtr<FJsonObject> &Object, FDrivingViewViewport &OutViewport)
{
  const TArray<TSharedPtr<FJsonValue>> *Position = nullptr;
  if (Object->TryGetArrayField(TEXT("screen_position"), Position) && Position != nullptr &&
      Position->Num() >= 2)
  {
    OutViewport.ScreenPosition = FVector2D(
        static_cast<float>((*Position)[0]->AsNumber()),
        static_cast<float>((*Position)[1]->AsNumber()));
  }

  const TArray<TSharedPtr<FJsonValue>> *Size = nullptr;
  if (Object->TryGetArrayField(TEXT("image_size"), Size) && Size != nullptr && Size->Num() >= 2)
  {
    OutViewport.ImageSize = FIntPoint(
        FMath::RoundToInt((*Size)[0]->AsNumber()),
        FMath::RoundToInt((*Size)[1]->AsNumber()));
  }
  return true;
}
