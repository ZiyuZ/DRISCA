#include "DriscaApiSubsystem.h"
#include "DriscaApiInternals.h"

#include "DriscaApiServer.h"
#include "DriscaApiTrafficLights.h"
#include "DrivingViewPawn.h"
#include "DrivingViewSubsystem.h"

#include "Carla.h"
#include "Carla/Actor/ActorDefinition.h"
#include "Carla/Actor/ActorDescription.h"
#include "Carla/Actor/ActorInfo.h"
#include "Carla/Actor/ActorRegistry.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEngine.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaGameModeBase.h"
#include "Carla/Game/CarlaStatics.h"
#include "Carla/Recorder/CarlaRecorder.h"
#include "Carla/Util/BoundingBox.h"
#include "Carla/Vehicle/CarlaWheeledVehicle.h"
#include "Carla/Vehicle/VehicleControl.h"
#include "Carla/Vehicle/VehicleInputPriority.h"
#include "Carla/Vehicle/VehicleLightState.h"

#include <util/ue-header-guard-begin.h>
#include "Components/PrimitiveComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include <util/ue-header-guard-end.h>

#include <util/disable-ue4-macros.h>
#include "carla/geom/Location.h"
#include "carla/road/Lane.h"
#include "carla/road/Map.h"
#include "carla/road/element/Waypoint.h"
#include "carla/rpc/VehicleLightState.h"
#include <util/enable-ue4-macros.h>

using namespace DriscaApiInternal;

void UDriscaApiSubsystem::StopReplayView()
{
  if (!bReplayViewOwned) return;
  if (UDrivingViewSubsystem *View = GetViewSubsystem())
  {
    FString Error;
    if (UCarlaEpisode *Episode = GetEpisode()) View->PrepareReplayFreeView(Episode->GetSpectatorPawn());
    View->StopView(Error);
  }
  bReplayViewOwned = false;
}

void UDriscaApiSubsystem::TickReplayView()
{
  if (!bReplayViewOwned) return;
  UCarlaEpisode *Episode = GetEpisode();
  if (!Episode || !Episode->GetRecorder() || !Episode->GetRecorder()->GetReplayer()->IsEnabled())
    StopReplayView();
}

bool UDriscaApiSubsystem::UpdateReplayView(
    const TSharedPtr<FJsonObject> &Params, DriscaApi::FOperationResult &OutResult)
{
  UDrivingViewSubsystem *View = GetViewSubsystem();
  UCarlaEpisode *Episode = GetEpisode();
  if (!View || !Episode || (View->IsActive() && !bReplayViewOwned))
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("当前视角不属于录像回放");
    return false;
  }
  FString Mode = View->IsActive() ? View->GetPawn()->GetViewMode() : TEXT("cockpit");
  if (Params->HasField(TEXT("view_mode")) && (!Params->TryGetStringField(TEXT("view_mode"), Mode) ||
      (Mode != TEXT("free") && Mode != TEXT("cockpit") && Mode != TEXT("chase"))))
  {
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("view_mode 必须是 free、cockpit 或 chase");
    return false;
  }
  uint32 CurrentId = 0;
  FString IdSpace = TEXT("auto");
  if (Params->HasField(TEXT("actor_id_space")) &&
      (!Params->TryGetStringField(TEXT("actor_id_space"), IdSpace) ||
       (IdSpace != TEXT("auto") && IdSpace != TEXT("recorded") && IdSpace != TEXT("current"))))
  {
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("actor_id_space 必须是 auto、recorded 或 current");
    return false;
  }
  double RequestedId = 0;
  if (Params->HasField(TEXT("ego_actor_id")))
  {
    if (!Params->TryGetNumberField(TEXT("ego_actor_id"), RequestedId) || !FMath::IsFinite(RequestedId) ||
        RequestedId < 0 || RequestedId > MAX_uint32 || FMath::FloorToDouble(RequestedId) != RequestedId)
    {
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("ego_actor_id 必须是非负整数");
      return false;
    }
    if (RequestedId > 0)
    {
      const uint32 Id = static_cast<uint32>(RequestedId);
      const uint32 Mapped = Episode->GetRecorder()->GetReplayer()->ResolveActorId(Id, false);
      FCarlaActor *Current = Episode->FindCarlaActor(Id);
      FCarlaActor *Recorded = Mapped ? Episode->FindCarlaActor(Mapped) : nullptr;
      const bool bCurrentVehicle = Current && Cast<ACarlaWheeledVehicle>(Current->GetActor());
      const bool bRecordedVehicle = Recorded && Cast<ACarlaWheeledVehicle>(Recorded->GetActor());
      if (IdSpace == TEXT("auto") && bCurrentVehicle && bRecordedVehicle && Id != Mapped)
      {
        OutResult.ErrorCode = CodeInvalidRequest;
        OutResult.ErrorMessage = TEXT("录像与当前编号指向不同车辆，请指定 actor_id_space=recorded 或 current");
        return false;
      }
      CurrentId = IdSpace == TEXT("current") ? Id :
          (IdSpace == TEXT("recorded") || bRecordedVehicle ? Mapped : Id);
      if (CurrentId == 0)
      {
        OutResult.ErrorCode = CodeNotFound;
        OutResult.ErrorMessage = TEXT("录像中尚未出现指定车辆");
        return false;
      }
    }
  }
  if (CurrentId == 0 && Mode != TEXT("free"))
  {
    FCarlaActor *Bound = View->IsActive() && View->GetPawn()->GetViewVehicle() ?
        Episode->FindCarlaActor(View->GetPawn()->GetViewVehicle()) : nullptr;
    CurrentId = Bound ? Bound->GetActorId() : Episode->GetRecorder()->GetReplayer()->ResolveActorId(ReplayFollowActorId);
  }
  if (CurrentId != 0 || Mode != TEXT("free"))
  {
    FCarlaActor *Actor = Episode->FindCarlaActor(CurrentId);
    if (!Actor || !Cast<ACarlaWheeledVehicle>(Actor->GetActor()))
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = TEXT("指定回放车辆尚未出现或已经销毁，请传入有效录像或当前车辆编号");
      return false;
    }
  }
  // 先以无主车 free 视角创建执行器，再绑定观察目标，避免输入、传感器与回放竞争。
  const bool bCreated = !View->IsActive();
  FString Error;
  if (bCreated)
  {
    auto Start = MakeShared<FJsonObject>();
    Start->SetStringField(TEXT("view_mode"), TEXT("free"));
    Start->SetNumberField(TEXT("ego_actor_id"), 0);
    Start->SetStringField(TEXT("mode"), TEXT("manual"));
    if (!View->StartView(Start, Error))
    {
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = Error;
      return false;
    }
    View->GetPawn()->SetExternalControl(true);
    if (APlayerController *PC = GetWorld()->GetFirstPlayerController())
    {
      FVector Location;
      FRotator Rotation;
      PC->GetPlayerViewPoint(Location, Rotation);
      View->GetPawn()->SetActorLocationAndRotation(Location, Rotation);
    }
    // 回放默认使用标准驾驶安装点和三镜布局，update 仍可覆盖 cameras/layout。
    const FDrivingViewCamera Front{0.5f, -0.35f, 0.8f, 5.8f, 0, 0, 120};
    const FDrivingViewCamera RearTop{0.34f, 0, 0.7f, 5.8f, 180, 0, 100};
    const FDrivingViewCamera RearLeft{0.4f, -0.93f, 0.5f, 5.8f, 180, 0, 100};
    const FDrivingViewCamera RearRight{0.4f, 0.93f, 0.5f, 5.8f, 180, 0, 100};
    FDrivingViewLayout Layout;
    Layout.BorderWidth = 0;
    Layout.RearTop.ScreenPosition = FVector2D(0.5, 0.1);
    Layout.RearLeft.ScreenPosition = FVector2D(0.12, 0.9);
    Layout.RearRight.ScreenPosition = FVector2D(0.88, 0.9);
    View->GetPawn()->UpdateConfig(Front, RearTop, RearLeft, RearRight, Layout);
    bReplayViewOwned = true;
  }
  Params->SetStringField(TEXT("view_mode"), Mode);
  if (CurrentId != 0) Params->SetNumberField(TEXT("ego_actor_id"), CurrentId);
  else Params->RemoveField(TEXT("ego_actor_id"));
  if (Mode == TEXT("free")) View->PrepareReplayFreeView(Episode->GetSpectatorPawn());
  if (!View->UpdateView(Params, Error))
  {
    if (bCreated) StopReplayView();
    OutResult.ErrorCode = CodeOperationFailed;
    OutResult.ErrorMessage = Error;
    return false;
  }
  Episode->GetRecorder()->GetReplayer()->ClearFollowCamera();
  TSharedPtr<FJsonObject> Config = MakeShared<FJsonObject>();
  View->GetViewConfig(Config, Error);
  OutResult.Result = Config;
  OutResult.Result->SetBoolField(TEXT("updated"), true);
  return true;
}

UCarlaEpisode *UDriscaApiSubsystem::GetEpisode() const
{
  UWorld *World = CurrentWorld.Get();
  return World != nullptr ? UCarlaStatics::GetCurrentEpisode(World) : nullptr;
}

ACarlaGameModeBase *UDriscaApiSubsystem::GetGameMode() const
{
  UWorld *World = CurrentWorld.Get();
  return World != nullptr ? UCarlaStatics::GetGameMode(World) : nullptr;
}

UDrivingViewSubsystem *UDriscaApiSubsystem::GetViewSubsystem() const
{
  UWorld *World = CurrentWorld.Get();
  return World != nullptr ? World->GetSubsystem<UDrivingViewSubsystem>() : nullptr;
}

FString UDriscaApiSubsystem::GetCurrentMapName() const
{
  const UCarlaEpisode *Episode = GetEpisode();
  return Episode != nullptr ? Episode->GetMapName() : FString();
}

int64 UDriscaApiSubsystem::SimulationTimeUs() const
{
  // 与原生 IMU/GNSS 的采样时钟一致：使用本世界的 TimeSeconds，
  // 而不是跨地图保持的 Episode 累计时间。协议定义为“自本次世界开始”。
  const UWorld *World = CurrentWorld.Get();
  return World != nullptr ? DriscaApi::ToMicroseconds(World->GetTimeSeconds()) : 0;
}

uint64 UDriscaApiSubsystem::CurrentFrameNo() const
{
  return static_cast<uint64>(FCarlaEngine::GetFrameCounter());
}

FString UDriscaApiSubsystem::GetConnectionSource(int64 ConnectionId) const
{
  const DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);
  if (Connection == nullptr)
  {
    return TEXT("system");
  }
  if (Connection->Client.Contains(TEXT("worker")))
  {
    return TEXT("model");
  }
  if (Connection->Client.Contains(TEXT("launcher")))
  {
    return TEXT("launcher");
  }
  return TEXT("system");
}

TArray<TSharedPtr<FJsonValue>> UDriscaApiSubsystem::BuildControlStateJson() const
{
  TArray<TPair<uint32, TSharedPtr<FJsonObject>>> Entries;
  Entries.Reserve(VehicleTracks.Num());
  for (const TPair<uint32, DriscaApi::FVehicleTrack> &Pair : VehicleTracks)
  {
    if (!Pair.Value.bControlled)
    {
      continue;
    }
    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetNumberField(TEXT("actor_id"), Pair.Key);
    Item->SetStringField(TEXT("mode"),
        Pair.Value.Source == TEXT("manual") ? TEXT("manual") : TEXT("external"));
    Item->SetStringField(TEXT("controller"), Pair.Value.Controller);
    Item->SetNumberField(TEXT("revision"),
        static_cast<double>(Pair.Value.ControlRevision));
    Entries.Add(TPair<uint32, TSharedPtr<FJsonObject>>(Pair.Key, Item));
  }
  Entries.Sort([](const TPair<uint32, TSharedPtr<FJsonObject>> &Left,
                  const TPair<uint32, TSharedPtr<FJsonObject>> &Right)
  {
    return Left.Key < Right.Key;
  });

  TArray<TSharedPtr<FJsonValue>> Result;
  Result.Reserve(Entries.Num());
  for (const TPair<uint32, TSharedPtr<FJsonObject>> &Entry : Entries)
  {
    Result.Add(MakeShared<FJsonValueObject>(Entry.Value));
  }
  return Result;
}

bool UDriscaApiSubsystem::RequireWorld(
    const TSharedPtr<FJsonObject> &Params,
    FString &OutCode,
    FString &OutMessage) const
{
  double RequestedWorld = 0.0;
  if (!Params->TryGetNumberField(TEXT("world_id"), RequestedWorld))
  {
    OutCode = CodeInvalidRequest;
    OutMessage = TEXT("缺少 world_id");
    return false;
  }
  if (static_cast<uint64>(RequestedWorld) != WorldId)
  {
    OutCode = CodeWorldChanged;
    OutMessage = FString::Printf(TEXT("world_id 已变为 %llu"),
        static_cast<unsigned long long>(WorldId));
    return false;
  }
  if (GetEpisode() == nullptr)
  {
    OutCode = CodeInvalidState;
    OutMessage = TEXT("当前没有可用的世界");
    return false;
  }
  return true;
}

bool UDriscaApiSubsystem::RequireSession(
    const FString &SessionId,
    FString &OutCode,
    FString &OutMessage) const
{
  if (!Session.bActive)
  {
    OutCode = CodeInvalidState;
    OutMessage = TEXT("当前没有进行中的实验");
    return false;
  }
  if (!SessionId.IsEmpty() && SessionId != Session.SessionId)
  {
    OutCode = CodeInvalidState;
    OutMessage = TEXT("session_id 与当前实验不一致");
    return false;
  }
  return true;
}

bool UDriscaApiSubsystem::ExecuteVehicle(
    const FString &Method,
    int64 ConnectionId,
    int32 RequestId,
    int32 OperationIndex,
    const FString &SessionId,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("当前没有可用的世界");
    return false;
  }

  DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);

  if (Method == TEXT("vehicle.spawn"))
  {
    if (Session.bActive && (Connection == nullptr || !Connection->bControl))
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("实验进行中只有控制连接可以创建车辆");
      return false;
    }

    double InitialSpeedMps = 0.0;
    if (Params->HasField(TEXT("initial_speed_mps")) &&
        (!Params->TryGetNumberField(TEXT("initial_speed_mps"), InitialSpeedMps) ||
         !FMath::IsFinite(InitialSpeedMps) || InitialSpeedMps < 0.0))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("initial_speed_mps 必须是有限非负数，单位为 m/s");
      return false;
    }

    FString Blueprint;
    if (!Params->TryGetStringField(TEXT("blueprint"), Blueprint) || Blueprint.IsEmpty())
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 blueprint");
      return false;
    }

    const TSharedPtr<FJsonObject> *TransformObject = nullptr;
    if (!Params->TryGetObjectField(TEXT("transform"), TransformObject) ||
        TransformObject == nullptr)
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 transform");
      return false;
    }
    FTransform Transform;
    if (!ReadTransform(*TransformObject, Transform))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("transform 格式错误");
      return false;
    }

    FString Mode = TEXT("external");
    Params->TryGetStringField(TEXT("mode"), Mode);
    if (Mode == TEXT("autopilot"))
    {
      OutResult.ErrorCode = CodeUnsupported;
      OutResult.ErrorMessage = TEXT(
          "autopilot 依赖 CARLA Traffic Manager，原生 API 尚未接入");
      return false;
    }
    if (Mode != TEXT("manual") && Mode != TEXT("external"))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("mode 必须是 manual、external 或 autopilot");
      return false;
    }

    const FActorDefinition *Definition = FindDefinition(*Episode, Blueprint);
    if (Definition == nullptr)
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = FString::Printf(TEXT("蓝图 %s 不存在"), *Blueprint);
      return false;
    }

    TMap<FString, FString> Overrides;
    FString RoleName;
    if (Params->TryGetStringField(TEXT("role_name"), RoleName) && !RoleName.IsEmpty())
    {
      Overrides.Add(TEXT("role_name"), RoleName);
    }
    const TSharedPtr<FJsonObject> *Attributes = nullptr;
    if (Params->TryGetObjectField(TEXT("attributes"), Attributes) && Attributes != nullptr)
    {
      for (const TPair<FString, TSharedPtr<FJsonValue>> &Pair : (*Attributes)->Values)
      {
        if (!Pair.Value.IsValid())
        {
          continue;
        }
        switch (Pair.Value->Type)
        {
          case EJson::String:
            Overrides.Add(Pair.Key, Pair.Value->AsString());
            break;
          case EJson::Boolean:
            Overrides.Add(Pair.Key, Pair.Value->AsBool() ? TEXT("true") : TEXT("false"));
            break;
          case EJson::Number:
            Overrides.Add(Pair.Key, FString::SanitizeFloat(Pair.Value->AsNumber()));
            break;
          default:
            break;
        }
      }
    }

    const TPair<EActorSpawnResultStatus, FCarlaActor *> SpawnResult =
        Episode->SpawnActorWithInfo(Transform, MakeDescription(*Definition, Overrides));
    if (SpawnResult.Key != EActorSpawnResultStatus::Success ||
        SpawnResult.Value == nullptr)
    {
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = FString::Printf(
          TEXT("车辆创建失败：%s"), *FActorSpawnResult::StatusToString(SpawnResult.Key));
      return false;
    }

    if (InitialSpeedMps > 0.01)
    {
      if (ACarlaWheeledVehicle *Vehicle = Cast<ACarlaWheeledVehicle>(SpawnResult.Value->GetActor()))
      {
        if (UPrimitiveComponent *Root = Cast<UPrimitiveComponent>(Vehicle->GetRootComponent()))
        {
          // 接口使用米每秒，物理线速度使用厘米每秒。
          const FVector Forward = Vehicle->GetActorForwardVector();
          Root->SetPhysicsLinearVelocity(Forward * static_cast<float>(InitialSpeedMps * 100.0), false);
        }
      }
    }

    const uint32 ActorId = SpawnResult.Value->GetActorId();
    DriscaApi::FVehicleTrack &Track = VehicleTracks.FindOrAdd(ActorId);
    Track.Source = Mode == TEXT("manual") ? TEXT("manual") : TEXT("external");
    Track.Controller = Mode == TEXT("manual") ? TEXT("human") : TEXT("python");
    Track.bControlled = true;
    Track.bHasLastVelocity = false;

    if (Session.bActive)
    {
      Session.OwnedActors.AddUnique(ActorId);
    }
    else if (Connection != nullptr)
    {
      Connection->CreatedActors.AddUnique(ActorId);
    }

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("actor_id"), ActorId);
    Result->SetObjectField(TEXT("describe"), DescribeActor(*SpawnResult.Value));
    OutResult.Result = Result;
    return true;
  }

  const bool bNeedsActorIds =
      Method == TEXT("vehicle.describe") || Method == TEXT("vehicle.destroy");
  const TArray<TSharedPtr<FJsonValue>> *ActorIds = nullptr;
  if (bNeedsActorIds &&
      (!Params->TryGetArrayField(TEXT("actor_ids"), ActorIds) || ActorIds == nullptr))
  {
    bOutFormatError = true;
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("缺少 actor_ids");
    return false;
  }

  if (Method == TEXT("vehicle.describe"))
  {
    TArray<TSharedPtr<FJsonValue>> Descriptions;
    for (const TSharedPtr<FJsonValue> &Value : *ActorIds)
    {
      if (!Value.IsValid() || Value->Type != EJson::Number)
      {
        bOutFormatError = true;
        OutResult.ErrorCode = CodeInvalidRequest;
        OutResult.ErrorMessage = TEXT("actor_ids 必须是整数数组");
        return false;
      }
      FCarlaActor *Actor = Episode->FindCarlaActor(
          static_cast<uint32>(Value->AsNumber()));
      if (Actor == nullptr)
      {
        OutResult.ErrorCode = CodeNotFound;
        OutResult.ErrorMessage = TEXT("车辆不存在");
        return false;
      }
      Descriptions.Add(MakeShared<FJsonValueObject>(DescribeActor(*Actor)));
    }
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetArrayField(TEXT("vehicles"), Descriptions);
    OutResult.Result = Result;
    OutResult.SampledFrameNo = CurrentFrameNo();
    return true;
  }

  if (Method == TEXT("vehicle.destroy"))
  {
    TArray<TSharedPtr<FJsonValue>> Destroyed;
    for (const TSharedPtr<FJsonValue> &Value : *ActorIds)
    {
      const uint32 ActorId = static_cast<uint32>(Value->AsNumber());
      if (ActorId == Session.EgoActorId)
      {
        OutResult.ErrorCode = CodeInvalidState;
        OutResult.ErrorMessage = TEXT("不能销毁当前实验主车");
        return false;
      }
      FCarlaActor *Actor = Episode->FindCarlaActor(ActorId);
      if (Actor == nullptr)
      {
        OutResult.ErrorCode = CodeNotFound;
        OutResult.ErrorMessage = TEXT("车辆不存在");
        return false;
      }
      if (!Episode->DestroyActor(ActorId))
      {
        OutResult.ErrorCode = CodeOperationFailed;
        OutResult.ErrorMessage = TEXT("车辆销毁失败");
        return false;
      }
      Session.OwnedActors.Remove(ActorId);
      if (Connection != nullptr)
      {
        Connection->CreatedActors.Remove(ActorId);
      }
      VehicleTracks.Remove(ActorId);
      LastLightStates.Remove(ActorId);
      Destroyed.Add(MakeShared<FJsonValueNumber>(ActorId));
    }
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetArrayField(TEXT("destroyed"), Destroyed);
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("vehicle.set_mode"))
  {
    double ActorNumber = 0.0;
    if (!Params->TryGetNumberField(TEXT("actor_id"), ActorNumber))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 actor_id");
      return false;
    }
    const uint32 ActorId = static_cast<uint32>(ActorNumber);

    FString Mode;
    if (!Params->TryGetStringField(TEXT("mode"), Mode))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 mode");
      return false;
    }
    if (Mode == TEXT("autopilot"))
    {
      OutResult.ErrorCode = CodeUnsupported;
      OutResult.ErrorMessage = TEXT(
          "autopilot 依赖 CARLA Traffic Manager，原生 API 尚未接入");
      return false;
    }
    if (Mode != TEXT("manual") && Mode != TEXT("external"))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("mode 必须是 manual、external 或 autopilot");
      return false;
    }

    FCarlaActor *Actor = Episode->FindCarlaActor(ActorId);
    if (Actor == nullptr)
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = TEXT("车辆不存在");
      return false;
    }

    FString Controller;
    if (!Params->TryGetStringField(TEXT("controller"), Controller) ||
        Controller.IsEmpty())
    {
      Controller = Mode == TEXT("external") ? TEXT("python") : TEXT("human");
    }
    if (Controller != TEXT("python") && Controller != TEXT("human"))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("controller 必须是 python 或 human");
      return false;
    }
    if ((Mode == TEXT("manual")) != (Controller == TEXT("human")))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("manual 只能配 human，external 只能配 python");
      return false;
    }

    DriscaApi::FVehicleTrack &Track = VehicleTracks.FindOrAdd(ActorId);
    double ExpectedRevision = 0.0;
    const bool bHasExpected = Params->TryGetNumberField(
        TEXT("expected_control_revision"), ExpectedRevision);
    if (Session.bActive && !bHasExpected)
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("活动实验中必须提供 expected_control_revision");
      return false;
    }
    if (bHasExpected &&
        static_cast<uint64>(ExpectedRevision) != Track.ControlRevision)
    {
      OutResult.Status = DriscaApi::EOperationStatus::Skipped;
      OutResult.ErrorCode = TEXT("control_superseded");
      OutResult.ErrorMessage = TEXT("该车控制权已变化，请刷新模式后重新决策");
      return true;
    }

    const FString PreviousMode =
        Track.Source == TEXT("manual") ? TEXT("manual") : TEXT("external");
    const FString PreviousController = Track.Controller;
    Track.Source = Mode;
    Track.Controller = Controller;
    Track.bControlled = true;

    UDrivingViewSubsystem *View = GetViewSubsystem();
    ADrivingViewPawn *Pawn = View != nullptr ? View->GetPawn() : nullptr;
    if (Pawn != nullptr && Pawn->GetEgo() == Actor->GetActor())
    {
      Pawn->SetExternalControl(Mode == TEXT("external"));
    }

    const bool bChanged =
        PreviousMode != Mode || PreviousController != Controller;
    if (bChanged)
    {
      ++Track.ControlRevision;
      TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
      Payload->SetNumberField(TEXT("actor_id"), ActorId);
      Payload->SetStringField(TEXT("previous_mode"), PreviousMode);
      Payload->SetStringField(TEXT("mode"), Mode);
      Payload->SetStringField(TEXT("controller"), Controller);
      Payload->SetNumberField(TEXT("revision"),
          static_cast<double>(Track.ControlRevision));
      EmitEvent(TEXT("control_mode_changed"), GetConnectionSource(ConnectionId),
          Payload, RequestId, OperationIndex);
    }

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("actor_id"), ActorId);
    Result->SetStringField(TEXT("mode"), Mode);
    Result->SetStringField(TEXT("controller"), Controller);
    Result->SetNumberField(TEXT("revision"),
        static_cast<double>(Track.ControlRevision));
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("vehicle.apply_control"))
  {
    double ActorNumber = 0.0;
    if (!Params->TryGetNumberField(TEXT("actor_id"), ActorNumber))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 actor_id");
      return false;
    }
    const uint32 ActorId = static_cast<uint32>(ActorNumber);

    DriscaApi::FVehicleTrack *Track = VehicleTracks.Find(ActorId);
    if (Track == nullptr)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("车辆不在本会话的控制记录中");
      return false;
    }

    double ExpectedRevision = 0.0;
    const bool bHasExpected = Params->TryGetNumberField(
        TEXT("expected_control_revision"), ExpectedRevision);
    if (Session.bActive && !bHasExpected)
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("活动实验中必须提供 expected_control_revision");
      return false;
    }
    if (bHasExpected &&
        static_cast<uint64>(ExpectedRevision) != Track->ControlRevision)
    {
      OutResult.Status = DriscaApi::EOperationStatus::Skipped;
      OutResult.ErrorCode = TEXT("control_superseded");
      OutResult.ErrorMessage = TEXT("该车控制权已变化，请刷新模式后重新决策");
      return true;
    }
    if (!Track->bControlled)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("车辆未纳入本会话的控制记录");
      return false;
    }
    if (Track->Source != TEXT("external"))
    {
      if (Track->Controller == TEXT("human"))
      {
        OutResult.Status = DriscaApi::EOperationStatus::Skipped;
        OutResult.ErrorCode = TEXT("control_superseded");
        OutResult.ErrorMessage = TEXT("驾驶人已接管，外部控制被忽略");
        return true;
      }
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("只有 external 来源车辆接受外部连续控制");
      return false;
    }

    FCarlaActor *Actor = Episode->FindCarlaActor(ActorId);
    ACarlaWheeledVehicle *Vehicle = Actor != nullptr
        ? Cast<ACarlaWheeledVehicle>(Actor->GetActor())
        : nullptr;
    if (Vehicle == nullptr)
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = TEXT("车辆不存在");
      return false;
    }

    double Throttle = 0.0;
    double Steer = 0.0;
    double Brake = 0.0;
    double Gear = 0.0;
    bool bReverse = false;
    bool bHandBrake = false;
    bool bManualGearShift = false;
    if (!Params->TryGetNumberField(TEXT("throttle"), Throttle) ||
        !Params->TryGetNumberField(TEXT("steer"), Steer) ||
        !Params->TryGetNumberField(TEXT("brake"), Brake))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 throttle、steer 或 brake");
      return false;
    }
    Params->TryGetBoolField(TEXT("reverse"), bReverse);
    Params->TryGetBoolField(TEXT("hand_brake"), bHandBrake);
    Params->TryGetBoolField(TEXT("manual_gear_shift"), bManualGearShift);
    Params->TryGetNumberField(TEXT("gear"), Gear);

    FVehicleControl Control;
    Control.Throttle = FMath::Clamp(static_cast<float>(Throttle), 0.0f, 1.0f);
    Control.Steer = FMath::Clamp(static_cast<float>(Steer), -1.0f, 1.0f);
    Control.Brake = FMath::Clamp(static_cast<float>(Brake), 0.0f, 1.0f);
    Control.bReverse = bReverse;
    Control.bHandBrake = bHandBrake;
    Control.bManualGearShift = bManualGearShift;
    Control.Gear = static_cast<int32>(Gear);
    Vehicle->ApplyVehicleControl(Control, EVehicleInputPriority::Client);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("actor_id"), ActorId);
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("vehicle.set_lights"))
  {
    double ActorNumber = 0.0;
    if (!Params->TryGetNumberField(TEXT("actor_id"), ActorNumber) ||
        !Params->HasField(TEXT("light_state")))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 actor_id 或 light_state");
      return false;
    }
    const uint32 ActorId = static_cast<uint32>(ActorNumber);
    double LightState = 0.0;
    if (!Params->TryGetNumberField(TEXT("light_state"), LightState))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("light_state 必须是整数掩码");
      return false;
    }
    const uint32 NewState = static_cast<uint32>(LightState);

    FCarlaActor *Actor = Episode->FindCarlaActor(ActorId);
    ACarlaWheeledVehicle *Vehicle = Actor != nullptr
        ? Cast<ACarlaWheeledVehicle>(Actor->GetActor())
        : nullptr;
    if (Vehicle == nullptr)
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = TEXT("车辆不存在");
      return false;
    }

    const uint32 OldState = LastLightStates.FindRef(ActorId);
    const carla::rpc::VehicleLightState RpcLights(NewState);
    Vehicle->SetVehicleLightState(static_cast<FVehicleLightState>(RpcLights));
    LastLightStates.Add(ActorId, NewState);

    for (uint32 Bit = 1u; Bit <= 0x400u; Bit <<= 1)
    {
      const bool bWas = (OldState & Bit) != 0u;
      const bool bNow = (NewState & Bit) != 0u;
      if (bWas == bNow)
      {
        continue;
      }
      if (const TCHAR *Name = LightName(Bit))
      {
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetStringField(TEXT("light"), Name);
        Payload->SetBoolField(TEXT("enabled"), bNow);
        EmitEvent(TEXT("toggle_light"), TEXT("launcher"), Payload,
            RequestId, OperationIndex);
      }
    }

    const uint32 Actual = carla::rpc::VehicleLightState(
        Vehicle->GetVehicleLightState()).GetLightStateAsValue();
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("actor_id"), ActorId);
    Result->SetNumberField(TEXT("light_state"), Actual);
    OutResult.Result = Result;
    return true;
  }

  OutResult.ErrorCode = CodeUnsupported;
  OutResult.ErrorMessage = FString::Printf(TEXT("未知车辆方法 %s"), *Method);
  return false;
}

bool UDriscaApiSubsystem::ExecuteDrivingView(
    const FString &Method,
    int64 ConnectionId,
    int32 RequestId,
    int32 OperationIndex,
    const FString &SessionId,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  UDrivingViewSubsystem *View = GetViewSubsystem();
  DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);

  if (Method == TEXT("driving_view.start"))
  {
    if (GetEpisode() && GetEpisode()->GetRecorder() && GetEpisode()->GetRecorder()->GetReplayer()->IsEnabled())
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("回放期间请用 driving_view.update 调整观察视角");
      return false;
    }
    FString NewSessionId;
    if (!Params->TryGetStringField(TEXT("session_id"), NewSessionId) ||
        NewSessionId.IsEmpty())
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 session_id");
      return false;
    }
    if (Session.bActive)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("已有进行中的实验");
      return false;
    }
    if (Connection == nullptr)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("连接状态不可用");
      return false;
    }

    FString Mode = TEXT("manual");
    Params->TryGetStringField(TEXT("mode"), Mode);
    if (Mode == TEXT("autopilot"))
    {
      OutResult.ErrorCode = CodeUnsupported;
      OutResult.ErrorMessage = TEXT(
          "autopilot 已取消；请用 mode=external 交给 Python 模型");
      return false;
    }
    if (Mode != TEXT("manual") && Mode != TEXT("external"))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("mode 必须是 manual 或 external");
      return false;
    }

    FString ViewMode = TEXT("cockpit");
    if (Params->HasField(TEXT("view_mode")) && (!Params->TryGetStringField(TEXT("view_mode"), ViewMode) ||
        (ViewMode != TEXT("free") && ViewMode != TEXT("cockpit") && ViewMode != TEXT("chase"))))
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("view_mode 无效"); return false; }
    double EgoNumber = 0.0;
    if (Params->HasField(TEXT("ego_actor_id")) &&
        (!Params->TryGetNumberField(TEXT("ego_actor_id"), EgoNumber) || !FMath::IsFinite(EgoNumber) ||
         EgoNumber < 0 || EgoNumber > MAX_uint32 || FMath::FloorToDouble(EgoNumber) != EgoNumber))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 ego_actor_id");
      return false;
    }
    uint32 EgoId = static_cast<uint32>(EgoNumber);
    if (ViewMode == TEXT("chase") && EgoId == 0)
    {
      TArray<uint32> Ids;
      VehicleTracks.GetKeys(Ids);
      Ids.Sort();
      for (uint32 Id : Ids) if (VehicleTracks[Id].bControlled) { EgoId = Id; break; }
    }

    if (View == nullptr)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("驾驶视图子系统不可用");
      return false;
    }

    UCarlaEpisode *Episode = GetEpisode();
    FCarlaActor *EgoActor = Episode != nullptr ? Episode->FindCarlaActor(EgoId) : nullptr;
    if (EgoActor == nullptr && (EgoId != 0 || ViewMode != TEXT("free")))
    {
      OutResult.ErrorCode = CodeNotFound;
      OutResult.ErrorMessage = TEXT("主车不存在");
      return false;
    }
    const FActorInfo *EgoInfo = EgoActor ? EgoActor->GetActorInfo() : nullptr;

    TSharedPtr<FJsonObject> ViewParams = MakeShared<FJsonObject>();
    ViewParams->SetNumberField(TEXT("ego_actor_id"), EgoId);
    ViewParams->SetStringField(TEXT("mode"), TEXT("manual"));
    ViewParams->SetStringField(TEXT("view_mode"), ViewMode);
    for (const TCHAR *Field : {TEXT("cameras"), TEXT("layout"), TEXT("keyboard")})
    {
      const TSharedPtr<FJsonObject> *Object = nullptr;
      if (Params->TryGetObjectField(Field, Object) && Object != nullptr)
      {
        ViewParams->SetObjectField(Field, *Object);
      }
    }
    if (EgoInfo != nullptr && !Params->HasField(TEXT("box")))
    {
      TSharedPtr<FJsonObject> Location = MakeShared<FJsonObject>();
      Location->SetNumberField(TEXT("x"), EgoInfo->BoundingBox.Origin.X * 0.01f);
      Location->SetNumberField(TEXT("y"), EgoInfo->BoundingBox.Origin.Y * 0.01f);
      Location->SetNumberField(TEXT("z"), EgoInfo->BoundingBox.Origin.Z * 0.01f);
      TSharedPtr<FJsonObject> Extent = MakeShared<FJsonObject>();
      Extent->SetNumberField(TEXT("x"), EgoInfo->BoundingBox.Extent.X * 0.01f);
      Extent->SetNumberField(TEXT("y"), EgoInfo->BoundingBox.Extent.Y * 0.01f);
      Extent->SetNumberField(TEXT("z"), EgoInfo->BoundingBox.Extent.Z * 0.01f);
      TSharedPtr<FJsonObject> Rotation = MakeShared<FJsonObject>();
      Rotation->SetNumberField(TEXT("pitch"), EgoInfo->BoundingBox.Rotation.Pitch);
      Rotation->SetNumberField(TEXT("yaw"), EgoInfo->BoundingBox.Rotation.Yaw);
      Rotation->SetNumberField(TEXT("roll"), EgoInfo->BoundingBox.Rotation.Roll);
      TSharedPtr<FJsonObject> Box = MakeShared<FJsonObject>();
      Box->SetObjectField(TEXT("location"), Location);
      Box->SetObjectField(TEXT("extent"), Extent);
      Box->SetObjectField(TEXT("rotation"), Rotation);
      ViewParams->SetObjectField(TEXT("box"), Box);
    }

    FString Error;
    if (!ApplyScreenMessagePolicy(Params, Error))
    {
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = Error;
      return false;
    }
    if (!View->StartView(ViewParams, Error))
    {
      OutResult.ErrorCode = Error.Contains(TEXT("already active"))
          ? CodeInvalidState : CodeOperationFailed;
      OutResult.ErrorMessage = Error;
      return false;
    }

    Session = DriscaApi::FSessionState();
    Session.bActive = true;
    Session.SessionId = NewSessionId;
    Session.ControlConnection = ConnectionId;
    Session.EgoActorId = EgoId;
    for (auto &Pair : EnvironmentRegions)
      if (Pair.Value.OwnerConnection == ConnectionId) Pair.Value.bSessionOwned = true;
    Session.OwnedActors = MoveTemp(Connection->CreatedActors);
    Connection->CreatedActors.Reset();
    Connection->bControl = true;
    Connection->SessionId = NewSessionId;

    bDynamicSpeedLimit = false;
    DefaultSpeedLimitMps = 33.33f;
    Params->TryGetBoolField(TEXT("dynamic_speed_limit"), bDynamicSpeedLimit);
    double DefaultLimit = 0.0;
    if (Params->TryGetNumberField(TEXT("default_speed_limit_mps"), DefaultLimit))
    {
      DefaultSpeedLimitMps = static_cast<float>(DefaultLimit);
    }

    ADrivingViewPawn *Pawn = View->GetPawn();
    if (Pawn == nullptr)
    {
      View->StopView(Error);
      Session = DriscaApi::FSessionState();
      Connection->bControl = false;
      Connection->SessionId.Empty();
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = TEXT("驾驶视图创建后未取得视图实例");
      return false;
    }
    ActionDelegateHandle = Pawn->OnAction.AddLambda(
        [this, Pawn](const FString &Action)
        {
          OnDrivingAction(Pawn, Action);
        });

    EgoVehicle = EgoActor ? Cast<ACarlaWheeledVehicle>(EgoActor->GetActor()) : nullptr;
    if (EgoId != 0)
    {
    DriscaApi::FVehicleTrack &EgoTrack = VehicleTracks.FindOrAdd(EgoId);
    const bool bFollowingExisting = ViewMode == TEXT("chase") && EgoNumber == 0;
    if (!bFollowingExisting)
    {
    EgoTrack.Source = Mode == TEXT("external") ? TEXT("external") : TEXT("manual");
    EgoTrack.Controller = Mode == TEXT("external") ? TEXT("python") : TEXT("human");
    EgoTrack.ControlRevision = 1;
    EgoTrack.bControlled = true;
    }
    Pawn->SetExternalControl(bFollowingExisting || Mode == TEXT("external"));
    if (!SpawnResearchSensors(Error))
    {
      Pawn->OnAction.Remove(ActionDelegateHandle);
      View->StopView(Error);
      Session = DriscaApi::FSessionState();
      Connection->bControl = false;
      Connection->SessionId.Empty();
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = Error;
      return false;
    }
    AttachCollisionHook();
    }
    else Pawn->SetExternalControl(true);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("active"), true);
    Result->SetBoolField(TEXT("ready"), true);
    Result->SetStringField(TEXT("session_id"), NewSessionId);
    Result->SetNumberField(TEXT("ego_actor_id"), EgoId);
    Result->SetStringField(TEXT("view_mode"), ViewMode);
    Result->SetArrayField(TEXT("control_state"), BuildControlStateJson());
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("driving_view.update"))
  {
    if (!Session.bActive && GetEpisode() && GetEpisode()->GetRecorder() &&
        GetEpisode()->GetRecorder()->GetReplayer()->IsEnabled())
      return UpdateReplayView(Params, OutResult);
    if (Connection == nullptr || !Connection->bControl)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("只有控制连接可以调整驾驶视图");
      return false;
    }
    if (View == nullptr || !View->IsActive())
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("驾驶视图未激活");
      return false;
    }

    FString Error;
    if (View->GetPawn()->GetViewVehicle() == nullptr && Params->HasField(TEXT("view_mode")) && !Params->HasField(TEXT("ego_actor_id")))
    {
      TArray<uint32> Ids;
      VehicleTracks.GetKeys(Ids);
      Ids.Sort();
      for (uint32 Id : Ids)
        if (VehicleTracks[Id].bControlled) { Params->SetNumberField(TEXT("ego_actor_id"), Id); break; }
    }
    if (!View->UpdateView(Params, Error))
    {
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = Error;
      return false;
    }

    TSharedPtr<FJsonObject> Config = MakeShared<FJsonObject>();
    if (View->GetViewConfig(Config, Error))
    {
      const TSharedPtr<FJsonObject> *Cameras = nullptr;
      if (Params->TryGetObjectField(TEXT("cameras"), Cameras) && Cameras != nullptr &&
          Config->HasField(TEXT("cameras")))
      {
        const TSharedPtr<FJsonObject> Applied = Config->GetObjectField(TEXT("cameras"));
        for (const TCHAR *Name : {TEXT("front"), TEXT("rear_top"),
                 TEXT("rear_left"), TEXT("rear_right")})
        {
          if ((*Cameras)->HasField(Name) && Applied->HasField(Name))
          {
            TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
            Payload->SetStringField(TEXT("camera_name"), Name);
            Payload->SetObjectField(TEXT("mount"), Applied->GetObjectField(Name));
            EmitEvent(TEXT("update_camera"), TEXT("launcher"), Payload,
                RequestId, OperationIndex);
          }
        }
      }
      if (Params->HasField(TEXT("layout")) && Config->HasField(TEXT("layout")))
      {
        EmitEvent(TEXT("update_layout"), TEXT("launcher"),
            Config->GetObjectField(TEXT("layout")), RequestId, OperationIndex);
      }
      if (Params->HasField(TEXT("view_mode")))
      {
        auto Payload = MakeShared<FJsonObject>();
        Payload->SetStringField(TEXT("view_mode"), Config->GetStringField(TEXT("view_mode")));
        EmitEvent(TEXT("update_view_mode"), GetConnectionSource(ConnectionId), Payload, RequestId, OperationIndex);
      }
      if (Params->HasField(TEXT("ego_actor_id")))
      {
        auto Payload = MakeShared<FJsonObject>();
        Payload->SetNumberField(TEXT("ego_actor_id"), Config->GetNumberField(TEXT("ego_actor_id")));
        EmitEvent(TEXT("update_view_target"), GetConnectionSource(ConnectionId), Payload, RequestId, OperationIndex);
      }
    }

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("updated"), true);
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("driving_view.get_config"))
  {
    if (View == nullptr || !View->IsActive())
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("驾驶视图未激活");
      return false;
    }
    TSharedPtr<FJsonObject> Config = MakeShared<FJsonObject>();
    FString Error;
    if (!View->GetViewConfig(Config, Error))
    {
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = Error;
      return false;
    }
    Config->SetNumberField(TEXT("ego_actor_id"), Session.EgoActorId);
    Config->SetStringField(TEXT("session_id"), Session.SessionId);
    Config->SetBoolField(TEXT("dynamic_speed_limit"), bDynamicSpeedLimit);
    Config->SetNumberField(TEXT("default_speed_limit_mps"), DefaultSpeedLimitMps);
    OutResult.Result = Config;
    OutResult.SampledFrameNo = CurrentFrameNo();
    return true;
  }

  if (Method == TEXT("driving_view.stop"))
  {
    if (Connection == nullptr || !Connection->bControl)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("只有控制连接可以停止驾驶视图");
      return false;
    }

    StopResearch();
    if (View != nullptr)
    {
      FString Error;
      View->StopView(Error);
    }

    TArray<TSharedPtr<FJsonValue>> Events = TakeEventsJson();
    Connection->bControl = false;
    Connection->SessionId.Empty();
    Session.bActive = false;
    Session.ControlConnection = -1;
    Session.OwnedActors.Empty();
    bTakeoverThisFrame = false;

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("active"), false);
    Result->SetArrayField(TEXT("events"), Events);
    OutResult.Result = Result;
    return true;
  }

  OutResult.ErrorCode = CodeUnsupported;
  OutResult.ErrorMessage = FString::Printf(TEXT("未知驾驶视图方法 %s"), *Method);
  return false;
}

bool UDriscaApiSubsystem::ExecuteTrafficOperation(
    const FString &Method,
    int64 ConnectionId,
    int32 RequestId,
    int32 OperationIndex,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  if (TrafficLights == nullptr || !CurrentWorld.IsValid())
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("信号数据模块不可用");
    return false;
  }

  FTrafficOperationResult Operation;
  if (!TrafficLights->ApplyOperation(
          Method, Params, *CurrentWorld.Get(), Operation))
  {
    OutResult.ErrorCode = Operation.ErrorCode.IsEmpty()
        ? CodeOperationFailed : Operation.ErrorCode;
    OutResult.ErrorMessage = Operation.ErrorMessage;
    if (OutResult.ErrorCode == CodeInvalidRequest)
    {
      bOutFormatError = true;
    }
    return false;
  }

  OutResult.Result = Operation.Result;
  if (!Operation.EventName.IsEmpty())
  {
    EmitEvent(Operation.EventName, GetConnectionSource(ConnectionId),
        Operation.EventPayload, RequestId, OperationIndex);
  }
  return true;
}

bool UDriscaApiSubsystem::ExecuteRoadQuery(
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  ACarlaGameModeBase *GameMode = GetGameMode();
  if (GameMode == nullptr || !GameMode->GetMap().has_value())
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("道路地图不可用");
    return false;
  }
  const carla::road::Map &Map = *GameMode->GetMap();

  const TArray<TSharedPtr<FJsonValue>> *Locations = nullptr;
  if (!Params->TryGetArrayField(TEXT("locations"), Locations) || Locations == nullptr)
  {
    bOutFormatError = true;
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("缺少 locations");
    return false;
  }

  TArray<TSharedPtr<FJsonValue>> Results;
  for (const TSharedPtr<FJsonValue> &Value : *Locations)
  {
    FVector Location;
    if (!ReadVector(Value, Location))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("locations 的每一项必须是 [x,y,z]");
      return false;
    }

    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    const carla::geom::Location QueryLocation(Location * 100.0);
    const std::optional<carla::road::element::Waypoint> Waypoint =
        Map.GetWaypoint(QueryLocation);
    if (!Waypoint.has_value())
    {
      Item->SetBoolField(TEXT("valid"), false);
      Results.Add(MakeShared<FJsonValueObject>(Item));
      continue;
    }

    const carla::geom::Transform Transform = Map.ComputeTransform(*Waypoint);
    const carla::geom::Location Center = Transform.location;
    const carla::geom::Vector3D Forward = Transform.rotation.GetForwardVector();
    const double LaneOffset =
        Forward.x * (QueryLocation.y - Center.y) -
        Forward.y * (QueryLocation.x - Center.x);

    Item->SetBoolField(TEXT("valid"), true);
    Item->SetNumberField(TEXT("road_id"), static_cast<int32>(Waypoint->road_id));
    Item->SetNumberField(TEXT("lane_id"), static_cast<int32>(Waypoint->lane_id));
    Item->SetNumberField(TEXT("lane_width"), Map.GetLaneWidth(*Waypoint));
    const carla::road::Lane::LaneType LaneType = Map.GetLaneType(*Waypoint);
    Item->SetNumberField(TEXT("lane_type"), static_cast<uint32>(LaneType));
    Item->SetNumberField(TEXT("lane_offset"), LaneOffset);
    Item->SetArrayField(TEXT("road_direction"), {
        MakeShared<FJsonValueNumber>(Forward.x),
        MakeShared<FJsonValueNumber>(Forward.y),
        MakeShared<FJsonValueNumber>(Forward.z)});
    Results.Add(MakeShared<FJsonValueObject>(Item));
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetArrayField(TEXT("roads"), Results);
  OutResult.Result = Result;
  OutResult.SampledFrameNo = CurrentFrameNo();
  return true;
}

void UDriscaApiSubsystem::StopOwnedRecorder()
{
  ACarlaRecorder *Recorder = OwnedRecorder.Get();
  if (IsValid(Recorder) && Recorder->IsEnabled())
  {
    Recorder->Stop();
  }
  // 录制对象可能随旧世界销毁，这里只清引用和路径，不访问已销毁对象。
  OwnedRecorder.Reset();
  RecorderPath.Empty();
}

bool UDriscaApiSubsystem::ExecuteRecorder(
    const FString &Method,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("当前没有可用的世界");
    return false;
  }
  ACarlaRecorder *Recorder = Episode->GetRecorder();
  if (Recorder == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("录像组件不可用");
    return false;
  }

  if (Method == TEXT("recorder.start"))
  {
    FString Path;
    if (!Params->TryGetStringField(TEXT("absolute_path"), Path) || Path.IsEmpty())
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 absolute_path");
      return false;
    }
    // 原生 Start 会先停止当前录像。已有录像不属于本服务时拒绝启动，
    // 避免把外部录像截断并据为己有。
    if (Recorder->IsEnabled() &&
        (RecorderPath.IsEmpty() || OwnedRecorder.Get() != Recorder))
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("已有非本服务启动的录像在运行");
      return false;
    }
    const std::string Actual = Episode->StartRecorder(
        std::string(TCHAR_TO_UTF8(*Path)), false, true);
    RecorderPath = UTF8_TO_TCHAR(Actual.c_str());
    if (RecorderPath.IsEmpty())
    {
      OwnedRecorder.Reset();
    }
    else
    {
      OwnedRecorder = Recorder;
    }
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("path"), RecorderPath);
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("recorder.stop"))
  {
    if (RecorderPath.IsEmpty())
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("当前没有由本服务启动的录像");
      return false;
    }
    const FString StoppedPath = RecorderPath;
    StopOwnedRecorder();
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("path"), StoppedPath);
    Result->SetBoolField(TEXT("stopped"), true);
    OutResult.Result = Result;
    return true;
  }

  if (Method == TEXT("recorder.info"))
  {
    FString Path;
    if (!Params->TryGetStringField(TEXT("absolute_path"), Path) || Path.IsEmpty())
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 absolute_path");
      return false;
    }
    bool bShowAll = false;
    Params->TryGetBoolField(TEXT("show_all"), bShowAll);
    const std::string Info = Recorder->ShowFileInfo(
        std::string(TCHAR_TO_UTF8(*Path)), bShowAll);
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("info"), UTF8_TO_TCHAR(Info.c_str()));
    OutResult.Result = Result;
    OutResult.SampledFrameNo = CurrentFrameNo();
    return true;
  }

  if (Method == TEXT("recorder.stop_replay"))
  {
    StopReplayView();
    ReplayFollowActorId = 0;
    Recorder->GetReplayer()->ClearFollowCamera();
    // 原生 Stop 在未启用回放时也是空操作；停用后不再逐帧移动跟随相机。
    Recorder->GetReplayer()->Stop(false);
    OutResult.Result = MakeShared<FJsonObject>();
    OutResult.Result->SetBoolField(TEXT("stopped"), true);
    return true;
  }

  if (Method == TEXT("recorder.replay"))
  {
    if (Session.bActive)
    {
      OutResult.ErrorCode = CodeInvalidState;
      OutResult.ErrorMessage = TEXT("实验进行中不能回放");
      return false;
    }
    FString Path;
    if (!Params->TryGetStringField(TEXT("absolute_path"), Path) || Path.IsEmpty())
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("缺少 absolute_path");
      return false;
    }
    double StartTime = 0.0;
    double Duration = 0.0;
    double FollowActor = 0.0;
    double TimeFactor = 1.0;
    bool bIgnoreHero = false;
    Params->TryGetNumberField(TEXT("start_time"), StartTime);
    Params->TryGetNumberField(TEXT("duration"), Duration);
    if (Params->HasField(TEXT("follow_actor_id")) &&
        (!Params->TryGetNumberField(TEXT("follow_actor_id"), FollowActor) ||
         !FMath::IsFinite(FollowActor) || FollowActor < 0 || FollowActor > MAX_uint32 ||
         FMath::FloorToDouble(FollowActor) != FollowActor))
    {
      bOutFormatError = true;
      OutResult.ErrorCode = CodeInvalidRequest;
      OutResult.ErrorMessage = TEXT("follow_actor_id 必须是非负整数车辆编号");
      return false;
    }
    Params->TryGetNumberField(TEXT("time_factor"), TimeFactor);
    Params->TryGetBoolField(TEXT("ignore_hero"), bIgnoreHero);

    Recorder->SetReplayerTimeFactor(TimeFactor);
    Recorder->SetReplayerIgnoreHero(bIgnoreHero);
    StopReplayView();
    // 使用录像中的车辆编号，Replayer 将其映射至重放世界的编号后移动 spectator。
    // 0 保持自由观察；驾驶会话已由上方检查限制为空闲，避免与驾驶相机竞争。
    const std::string Info = Recorder->ReplayFile(
        std::string(TCHAR_TO_UTF8(*Path)),
        StartTime,
        Duration,
        static_cast<uint32>(FollowActor),
        FTransform::Identity,
        false,
        false,
        std::string());
    ReplayFollowActorId = static_cast<uint32>(FollowActor);
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("info"), UTF8_TO_TCHAR(Info.c_str()));
    OutResult.Result = Result;
    return true;
  }

  OutResult.ErrorCode = CodeUnsupported;
  OutResult.ErrorMessage = FString::Printf(TEXT("未知录像方法 %s"), *Method);
  return false;
}

bool UDriscaApiSubsystem::ExecuteExperimentStop(
    int64 ConnectionId,
    const FString &SessionId,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);
  if (Connection == nullptr || !Connection->bControl || !Session.bActive)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("只有控制连接可以结束实验");
    return false;
  }
  if (!SessionId.IsEmpty() && SessionId != Session.SessionId)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("session_id 与当前实验不一致");
    return false;
  }
  const FString StoppedSessionId = Session.SessionId;

  StopResearch();
  if (UDrivingViewSubsystem *View = GetViewSubsystem())
  {
    FString Error;
    View->StopView(Error);
  }

  ClearEnvironment(-1, true);

  // 与 AbortSession 一致：只结束本服务启动的录像，先于车辆销毁。
  StopOwnedRecorder();

  UCarlaEpisode *Episode = GetEpisode();
  if (Episode != nullptr)
  {
    TArray<uint32> ToDestroy;
    for (const TPair<uint32, TSharedPtr<FCarlaActor>> &Pair : Episode->GetActorRegistry())
    {
      FCarlaActor *Actor = Pair.Value.Get();
      if (Actor == nullptr)
      {
        continue;
      }
      const FCarlaActor::ActorType Type = Actor->GetActorType();
      if (Type == FCarlaActor::ActorType::Vehicle ||
          Type == FCarlaActor::ActorType::Walker)
      {
        ToDestroy.Add(Pair.Key);
      }
    }
    for (uint32 Id : ToDestroy)
    {
      Episode->DestroyActor(Id);
    }
  }

  TArray<TSharedPtr<FJsonValue>> Events = TakeEventsJson();

  Connection->bControl = false;
  Connection->SessionId.Empty();
  Connection->CreatedActors.Empty();
  Session = DriscaApi::FSessionState();
  PendingExchange.bValid = false;
  VehicleTracks.Empty();
  LastLightStates.Empty();
  bTakeoverThisFrame = false;

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetStringField(TEXT("session_id"), StoppedSessionId);
  Result->SetBoolField(TEXT("stopped"), true);
  Result->SetBoolField(TEXT("cleanup"), true);
  Result->SetArrayField(TEXT("events"), Events);
  OutResult.Result = Result;
  return true;
}

