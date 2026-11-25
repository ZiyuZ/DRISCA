#include "DriscaApiTrafficLights.h"

#include "Carla.h"
#include "Carla/Actor/ActorRegistry.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaGameModeBase.h"
#include "Carla/Game/CarlaStatics.h"
#include "Carla/Traffic/TrafficLightBase.h"
#include "Carla/Traffic/TrafficLightComponent.h"
#include "Carla/Traffic/TrafficLightController.h"
#include "Carla/Traffic/TrafficLightGroup.h"
#include "Carla/Traffic/TrafficLightManager.h"

#include <util/ue-header-guard-begin.h>
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include <util/ue-header-guard-end.h>

#include <util/disable-ue4-macros.h>
#include "carla/road/Controller.h"
#include "carla/road/Junction.h"
#include "carla/road/Map.h"
#include "carla/road/Signal.h"
#include "carla/road/element/RoadInfoSignal.h"
#include <util/enable-ue4-macros.h>

namespace
{
  FString SignalStateToString(ETrafficLightState State)
  {
    switch (State)
    {
      case ETrafficLightState::Red:
        return TEXT("red");
      case ETrafficLightState::Yellow:
        return TEXT("yellow");
      case ETrafficLightState::Green:
        return TEXT("green");
      case ETrafficLightState::Off:
      default:
        return TEXT("off");
    }
  }

  bool ParseSignalState(const FString &Text, ETrafficLightState &OutState)
  {
    if (Text == TEXT("red"))
    {
      OutState = ETrafficLightState::Red;
      return true;
    }
    if (Text == TEXT("yellow"))
    {
      OutState = ETrafficLightState::Yellow;
      return true;
    }
    if (Text == TEXT("green"))
    {
      OutState = ETrafficLightState::Green;
      return true;
    }
    if (Text == TEXT("off"))
    {
      OutState = ETrafficLightState::Off;
      return true;
    }
    return false;
  }

  FString OrientationToString(carla::road::SignalOrientation Orientation)
  {
    switch (Orientation)
    {
      case carla::road::SignalOrientation::Positive:
        return TEXT("positive");
      case carla::road::SignalOrientation::Negative:
        return TEXT("negative");
      default:
        return TEXT("both");
    }
  }

  FString SignalIdToString(const carla::road::SignId &Id)
  {
    return FString(UTF8_TO_TCHAR(Id.c_str()));
  }

  FString ControllerIdToString(const carla::road::ContId &Id)
  {
    return FString(UTF8_TO_TCHAR(Id.c_str()));
  }

  TArray<TSharedPtr<FJsonValue>> ControllerIdsToJson(
      const std::set<carla::road::ContId> &Ids)
  {
    TArray<TSharedPtr<FJsonValue>> Values;
    for (const carla::road::ContId &Id : Ids)
    {
      Values.Add(MakeShared<FJsonValueString>(ControllerIdToString(Id)));
    }
    return Values;
  }

  TArray<TSharedPtr<FJsonValue>> JunctionIdsToJson(
      const std::set<carla::road::JuncId> &Ids)
  {
    TArray<TSharedPtr<FJsonValue>> Values;
    for (const carla::road::JuncId Id : Ids)
    {
      Values.Add(MakeShared<FJsonValueNumber>(Id));
    }
    return Values;
  }

  TSharedPtr<FJsonObject> TransformToJson(const carla::geom::Transform &Transform)
  {
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetArrayField(TEXT("location"), {
        MakeShared<FJsonValueNumber>(Transform.location.x),
        MakeShared<FJsonValueNumber>(Transform.location.y),
        MakeShared<FJsonValueNumber>(Transform.location.z)});
    Result->SetArrayField(TEXT("rotation"), {
        MakeShared<FJsonValueNumber>(Transform.rotation.pitch),
        MakeShared<FJsonValueNumber>(Transform.rotation.yaw),
        MakeShared<FJsonValueNumber>(Transform.rotation.roll)});
    return Result;
  }

  TSharedPtr<FJsonObject> UeTransformToJson(const FTransform &Transform)
  {
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    const FVector Location = Transform.GetLocation() * 0.01;
    Result->SetArrayField(TEXT("location"), {
        MakeShared<FJsonValueNumber>(Location.X),
        MakeShared<FJsonValueNumber>(Location.Y),
        MakeShared<FJsonValueNumber>(Location.Z)});
    const FRotator Rotation = Transform.Rotator();
    Result->SetArrayField(TEXT("rotation"), {
        MakeShared<FJsonValueNumber>(Rotation.Pitch),
        MakeShared<FJsonValueNumber>(Rotation.Yaw),
        MakeShared<FJsonValueNumber>(Rotation.Roll)});
    return Result;
  }

  void SetNumberOrNull(
      const TSharedPtr<FJsonObject> &Object,
      const TCHAR *Key,
      bool bValid,
      double Value)
  {
    if (bValid)
    {
      Object->SetNumberField(Key, Value);
    }
    else
    {
      Object->SetField(Key, MakeShared<FJsonValueNull>());
    }
  }

  void SetStringOrNull(
      const TSharedPtr<FJsonObject> &Object,
      const TCHAR *Key,
      bool bValid,
      const FString &Value)
  {
    if (bValid)
    {
      Object->SetStringField(Key, Value);
    }
    else
    {
      Object->SetField(Key, MakeShared<FJsonValueNull>());
    }
  }

  ATrafficLightBase *ResolveLight(UWorld &World, int32 ActorId)
  {
    UCarlaEpisode *Episode = UCarlaStatics::GetCurrentEpisode(&World);
    if (Episode == nullptr)
    {
      return nullptr;
    }
    FCarlaActor *CarlaActor = Episode->FindCarlaActor(
        static_cast<uint32>(ActorId));
    return CarlaActor != nullptr
        ? Cast<ATrafficLightBase>(CarlaActor->GetActor())
        : nullptr;
  }

  TArray<TSharedPtr<FJsonValue>> GroupControllerIds(
      ATrafficLightGroup &Group)
  {
    TArray<TSharedPtr<FJsonValue>> Values;
    for (UTrafficLightController *Controller : Group.GetControllers())
    {
      if (Controller != nullptr)
      {
        Values.Add(MakeShared<FJsonValueString>(Controller->GetControllerId()));
      }
    }
    return Values;
  }
}

void FDriscaTrafficLights::Invalidate()
{
  Signals.Reset();
  Controllers.Reset();
  Unmapped = nullptr;
  CachedWorldId = 0;
}

bool FDriscaTrafficLights::IsBuilt(uint64 WorldId) const
{
  return CachedWorldId == WorldId;
}

bool FDriscaTrafficLights::Build(
    ACarlaGameModeBase &GameMode,
    UCarlaEpisode &Episode,
    uint64 WorldId,
    FString &OutError)
{
  if (!GameMode.GetMap().has_value())
  {
    OutError = TEXT("道路地图不可用");
    return false;
  }

  const carla::road::Map &Map = *GameMode.GetMap();
  const carla::road::MapData &Data = Map.GetData();

  TMap<FString, uint32> SignalActors;
  TMap<FString, UTrafficLightComponent *> SignalComponents;
  TArray<TSharedPtr<FJsonValue>> LightsWithoutSignal;

  for (const TPair<uint32, TSharedPtr<FCarlaActor>> &Pair :
      Episode.GetActorRegistry())
  {
    FCarlaActor *CarlaActor = Pair.Value.Get();
    if (CarlaActor == nullptr ||
        CarlaActor->GetActorType() != FCarlaActor::ActorType::TrafficLight)
    {
      continue;
    }
    ATrafficLightBase *Light = Cast<ATrafficLightBase>(CarlaActor->GetActor());
    if (Light == nullptr)
    {
      continue;
    }
    UTrafficLightComponent *Component = Light->GetTrafficLightComponent();
    if (Component == nullptr)
    {
      continue;
    }
    const FString SignId = Component->GetSignId();
    if (SignId.IsEmpty())
    {
      LightsWithoutSignal.Add(MakeShared<FJsonValueNumber>(Pair.Key));
      continue;
    }
    SignalActors.Add(SignId, Pair.Key);
    SignalComponents.Add(SignId, Component);
  }

  TMap<FString, TArray<const carla::road::element::RoadInfoSignal *>> References;
  for (const carla::road::element::RoadInfoSignal *Reference :
      Map.GetAllSignalReferences())
  {
    References.FindOrAdd(SignalIdToString(Reference->GetSignalId())).Add(Reference);
  }

  TArray<TSharedPtr<FJsonValue>> WithoutController;
  TArray<TSharedPtr<FJsonValue>> WithoutValidity;
  TArray<TSharedPtr<FJsonValue>> WithoutActor;
  TArray<TSharedPtr<FJsonValue>> WithoutTriggerZones;
  TArray<TSharedPtr<FJsonValue>> RuntimeFallback;

  TArray<carla::road::SignId> SignalIds;
  for (const auto &Pair : Data.GetSignals())
  {
    SignalIds.Add(Pair.first);
  }
  SignalIds.Sort();

  Signals.Reset();
  Signals.Reserve(SignalIds.Num());
  for (const carla::road::SignId &SignalId : SignalIds)
  {
    const carla::road::Signal &Signal = *Data.GetSignals().at(SignalId);
    const FString IdText = SignalIdToString(SignalId);

    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetStringField(TEXT("signal_id"), IdText);
    Item->SetNumberField(TEXT("road_id"), Signal.GetRoadId());
    Item->SetNumberField(TEXT("s"), Signal.GetS());
    Item->SetNumberField(TEXT("t"), Signal.GetT());
    Item->SetStringField(TEXT("orientation"),
        OrientationToString(Signal.GetOrientation()));
    Item->SetBoolField(TEXT("dynamic"), Signal.GetDynamic());
    Item->SetStringField(TEXT("type"),
        FString(UTF8_TO_TCHAR(Signal.GetType().c_str())));
    Item->SetStringField(TEXT("subtype"),
        FString(UTF8_TO_TCHAR(Signal.GetSubtype().c_str())));
    Item->SetObjectField(TEXT("transform"), TransformToJson(Signal.GetTransform()));

    const std::set<carla::road::ContId> ControllerIds = Signal.GetControllers();
    Item->SetArrayField(TEXT("controller_ids"), ControllerIdsToJson(ControllerIds));

    std::set<carla::road::JuncId> JunctionIds;
    for (const carla::road::ContId &ControllerId : ControllerIds)
    {
      const auto ControllerIt = Data.GetControllers().find(ControllerId);
      if (ControllerIt != Data.GetControllers().end())
      {
        for (const carla::road::JuncId JunctionId : ControllerIt->second->GetJunctions())
        {
          JunctionIds.insert(JunctionId);
        }
      }
    }
    Item->SetArrayField(TEXT("junction_ids"), JunctionIdsToJson(JunctionIds));

    const uint32 *ActorId = SignalActors.Find(IdText);
    if (ActorId != nullptr)
    {
      Item->SetNumberField(TEXT("actor_id"), *ActorId);
    }
    else
    {
      Item->SetField(TEXT("actor_id"), MakeShared<FJsonValueNull>());
    }

    UTrafficLightComponent *RuntimeComponent = nullptr;
    if (UTrafficLightComponent *const *FoundComponent =
        SignalComponents.Find(IdText))
    {
      RuntimeComponent = *FoundComponent;
    }
    UTrafficLightController *RuntimeController = RuntimeComponent != nullptr
        ? RuntimeComponent->GetController() : nullptr;
    ATrafficLightGroup *RuntimeGroup = RuntimeComponent != nullptr
        ? RuntimeComponent->GetGroup() : nullptr;
    SetStringOrNull(Item, TEXT("runtime_controller_id"), RuntimeController != nullptr,
        RuntimeController != nullptr ? RuntimeController->GetControllerId() : FString());
    SetNumberOrNull(Item, TEXT("runtime_group_id"), RuntimeGroup != nullptr,
        RuntimeGroup != nullptr ? RuntimeGroup->GetJunctionId() : 0.0);

    bool bRuntimeMatchesOpenDrive = false;
    if (RuntimeController != nullptr)
    {
      const std::string RuntimeId =
          std::string(TCHAR_TO_UTF8(*RuntimeController->GetControllerId()));
      bRuntimeMatchesOpenDrive = ControllerIds.count(RuntimeId) > 0;
    }
    Item->SetStringField(TEXT("association"),
        ActorId == nullptr ? TEXT("none") :
        (bRuntimeMatchesOpenDrive ? TEXT("opendrive") : TEXT("fallback")));
    if (ActorId != nullptr && !bRuntimeMatchesOpenDrive)
    {
      RuntimeFallback.Add(MakeShared<FJsonValueString>(IdText));
    }

    TArray<TSharedPtr<FJsonValue>> ReferenceJson;
    bool bHasValidity = false;
    const TArray<const carla::road::element::RoadInfoSignal *> *SignalReferences =
        References.Find(IdText);
    if (SignalReferences != nullptr)
    {
      for (const carla::road::element::RoadInfoSignal *Reference : *SignalReferences)
      {
        TSharedPtr<FJsonObject> ReferenceItem = MakeShared<FJsonObject>();
        ReferenceItem->SetNumberField(TEXT("road_id"), Reference->GetRoadId());
        ReferenceItem->SetNumberField(TEXT("s"), Reference->GetS());
        ReferenceItem->SetNumberField(TEXT("t"), Reference->GetT());
        TArray<TSharedPtr<FJsonValue>> Validities;
        for (const carla::road::LaneValidity &Validity : Reference->GetValidities())
        {
          TSharedPtr<FJsonObject> ValidityItem = MakeShared<FJsonObject>();
          ValidityItem->SetNumberField(TEXT("from_lane"), Validity._from_lane);
          ValidityItem->SetNumberField(TEXT("to_lane"), Validity._to_lane);
          Validities.Add(MakeShared<FJsonValueObject>(ValidityItem));
          bHasValidity = true;
        }
        ReferenceItem->SetArrayField(TEXT("validities"), Validities);
        ReferenceJson.Add(MakeShared<FJsonValueObject>(ReferenceItem));
      }
    }
    Item->SetArrayField(TEXT("references"), ReferenceJson);

    TArray<TSharedPtr<FJsonValue>> TriggerZones;
    if (UTrafficLightComponent *const *Component =
        SignalComponents.Find(IdText))
    {
      for (const FTrafficLightTriggerZone &Zone : (*Component)->GetTriggerZones())
      {
        TSharedPtr<FJsonObject> ZoneItem = MakeShared<FJsonObject>();
        ZoneItem->SetNumberField(TEXT("road_id"), Zone.RoadId);
        ZoneItem->SetNumberField(TEXT("section_id"), Zone.SectionId);
        ZoneItem->SetNumberField(TEXT("lane_id"), Zone.LaneId);
        ZoneItem->SetNumberField(TEXT("s"), Zone.S);
        ZoneItem->SetObjectField(TEXT("transform"), UeTransformToJson(Zone.Transform));
        ZoneItem->SetArrayField(TEXT("extent"), {
            MakeShared<FJsonValueNumber>(Zone.Extent.X),
            MakeShared<FJsonValueNumber>(Zone.Extent.Y),
            MakeShared<FJsonValueNumber>(Zone.Extent.Z)});
        ZoneItem->SetStringField(TEXT("source"),
            TEXT("UTrafficLightComponent::InitializeSign"));
        TriggerZones.Add(MakeShared<FJsonValueObject>(ZoneItem));
      }
    }
    Item->SetArrayField(TEXT("trigger_zones"), TriggerZones);
    Item->SetBoolField(TEXT("has_trigger_zones"), TriggerZones.Num() > 0);
    Item->SetStringField(TEXT("trigger_zone_source"),
        TriggerZones.Num() > 0
            ? TEXT("UTrafficLightComponent::InitializeSign")
            : TEXT("none"));
    if (TriggerZones.Num() == 0)
    {
      WithoutTriggerZones.Add(MakeShared<FJsonValueString>(IdText));
    }

    const bool bUnmapped = ControllerIds.empty() || !bHasValidity || ActorId == nullptr;
    Item->SetBoolField(TEXT("unmapped"), bUnmapped);
    if (ControllerIds.empty())
    {
      WithoutController.Add(MakeShared<FJsonValueString>(IdText));
    }
    if (!bHasValidity)
    {
      WithoutValidity.Add(MakeShared<FJsonValueString>(IdText));
    }
    if (ActorId == nullptr)
    {
      WithoutActor.Add(MakeShared<FJsonValueString>(IdText));
    }

    Signals.Add(MakeShared<FJsonValueObject>(Item));
  }

  TArray<TSharedPtr<FJsonValue>> WithoutSignals;
  TArray<TSharedPtr<FJsonValue>> WithoutJunction;
  TArray<carla::road::ContId> ControllerIds;
  for (const auto &Pair : Data.GetControllers())
  {
    ControllerIds.Add(Pair.first);
  }
  ControllerIds.Sort();

  Controllers.Reset();
  Controllers.Reserve(ControllerIds.Num());
  for (const carla::road::ContId &ControllerId : ControllerIds)
  {
    const carla::road::Controller &Controller =
        *Data.GetControllers().at(ControllerId);
    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetStringField(TEXT("controller_id"), ControllerIdToString(ControllerId));
    Item->SetStringField(TEXT("name"),
        FString(UTF8_TO_TCHAR(Controller.GetName().c_str())));
    Item->SetNumberField(TEXT("sequence"), Controller.GetSequence());
    TArray<TSharedPtr<FJsonValue>> SignalValues;
    for (const carla::road::SignId &SignalId : Controller.GetSignals())
    {
      SignalValues.Add(MakeShared<FJsonValueString>(SignalIdToString(SignalId)));
    }
    Item->SetArrayField(TEXT("signals"), SignalValues);
    Item->SetArrayField(TEXT("junctions"),
        JunctionIdsToJson(Controller.GetJunctions()));

    if (Controller.GetSignals().empty())
    {
      WithoutSignals.Add(MakeShared<FJsonValueString>(
          ControllerIdToString(ControllerId)));
    }
    if (Controller.GetJunctions().empty())
    {
      WithoutJunction.Add(MakeShared<FJsonValueString>(
          ControllerIdToString(ControllerId)));
    }
    Controllers.Add(MakeShared<FJsonValueObject>(Item));
  }

  Unmapped = MakeShared<FJsonObject>();
  Unmapped->SetArrayField(TEXT("signals_without_controller"), WithoutController);
  Unmapped->SetArrayField(TEXT("signals_without_validity"), WithoutValidity);
  Unmapped->SetArrayField(TEXT("signals_without_actor"), WithoutActor);
  Unmapped->SetArrayField(TEXT("signals_without_trigger_zones"), WithoutTriggerZones);
  Unmapped->SetArrayField(TEXT("signals_with_runtime_fallback"), RuntimeFallback);
  Unmapped->SetArrayField(TEXT("controllers_without_signals"), WithoutSignals);
  Unmapped->SetArrayField(TEXT("controllers_without_junction"), WithoutJunction);
  Unmapped->SetArrayField(TEXT("lights_without_signal"), LightsWithoutSignal);

  CachedWorldId = WorldId;

  UE_LOG(LogCarla, Log,
      TEXT("DriscaApi: traffic signals built for world %llu, %d signals, %d controllers"),
      static_cast<unsigned long long>(WorldId), Signals.Num(), Controllers.Num());
  return true;
}

bool FDriscaTrafficLights::SerializeSignals(
    uint64 WorldId,
    const FString &MapName,
    TSharedPtr<FJsonObject> &OutResult,
    FString &OutError)
{
  if (CachedWorldId != WorldId || !Unmapped.IsValid())
  {
    OutResult = nullptr;
    OutError = TEXT("信号数据未构建");
    return false;
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetStringField(TEXT("map_name"), MapName);
  Result->SetArrayField(TEXT("signals"), Signals);
  Result->SetArrayField(TEXT("controllers"), Controllers);
  Result->SetObjectField(TEXT("unmapped"), Unmapped);
  OutResult = Result;
  return true;
}

void FDriscaTrafficLights::BuildRuntime(
    UWorld &World,
    TArray<TSharedPtr<FJsonValue>> &OutLights,
    TArray<TSharedPtr<FJsonValue>> &OutControllers) const
{
  OutLights.Reset();
  OutControllers.Reset();

  UCarlaEpisode *Episode = UCarlaStatics::GetCurrentEpisode(&World);
  if (Episode == nullptr)
  {
    return;
  }

  struct FLightEntry
  {
    uint32 ActorId = 0;
    TSharedPtr<FJsonObject> Json;
  };
  TArray<FLightEntry> LightEntries;

  for (const TPair<uint32, TSharedPtr<FCarlaActor>> &Pair :
      Episode->GetActorRegistry())
  {
    FCarlaActor *CarlaActor = Pair.Value.Get();
    if (CarlaActor == nullptr ||
        CarlaActor->GetActorType() != FCarlaActor::ActorType::TrafficLight)
    {
      continue;
    }
    ATrafficLightBase *Light = Cast<ATrafficLightBase>(CarlaActor->GetActor());
    if (Light == nullptr)
    {
      continue;
    }
    UTrafficLightComponent *Component = Light->GetTrafficLightComponent();
    UTrafficLightController *Controller =
        Component != nullptr ? Component->GetController() : nullptr;
    ATrafficLightGroup *Group =
        Component != nullptr ? Component->GetGroup() : nullptr;

    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetNumberField(TEXT("actor_id"), Pair.Key);
    SetStringOrNull(Item, TEXT("signal_id"), Component != nullptr,
        Component != nullptr ? Component->GetSignId() : FString());
    SetStringOrNull(Item, TEXT("controller_id"), Controller != nullptr,
        Controller != nullptr ? Controller->GetControllerId() : FString());
    if (Group != nullptr)
    {
      Item->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
    }
    else
    {
      Item->SetField(TEXT("group_id"), MakeShared<FJsonValueNull>());
    }
    Item->SetStringField(TEXT("state"),
        SignalStateToString(Light->GetTrafficLightState()));
    Item->SetBoolField(TEXT("frozen"), Light->GetTimeIsFrozen());

    FLightEntry Entry;
    Entry.ActorId = Pair.Key;
    Entry.Json = Item;
    LightEntries.Add(Entry);
  }

  LightEntries.Sort([](const FLightEntry &Left, const FLightEntry &Right)
  {
    return Left.ActorId < Right.ActorId;
  });
  for (const FLightEntry &Entry : LightEntries)
  {
    OutLights.Add(MakeShared<FJsonValueObject>(Entry.Json));
  }

  struct FControllerEntry
  {
    FString ControllerId;
    TSharedPtr<FJsonObject> Json;
  };
  TArray<FControllerEntry> ControllerEntries;

  for (TActorIterator<ATrafficLightGroup> It(&World); It; ++It)
  {
    ATrafficLightGroup *Group = *It;
    if (Group == nullptr)
    {
      continue;
    }
    const int32 ActiveIndex = Group->GetCurrentControllerIndex();
    const int32 ControllerCount = Group->GetControllerCount();
    for (int32 Index = 0; Index < Group->GetControllers().Num(); ++Index)
    {
      UTrafficLightController *Controller = Group->GetControllers()[Index];
      if (Controller == nullptr)
      {
        continue;
      }

      TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
      Item->SetStringField(TEXT("controller_id"), Controller->GetControllerId());
      Item->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
      const bool bActive = Index == ActiveIndex && ControllerCount > 0;
      Item->SetBoolField(TEXT("active"), bActive);
      Item->SetBoolField(TEXT("frozen"), Group->IsFrozen());

      const int32 StateCount = Controller->GetStateCount();
      const int32 StateIndex = Controller->GetCurrentStateIndex();
      const bool bHasState = StateCount > 0 && bActive;
      SetStringOrNull(Item, TEXT("state"), bHasState,
          bHasState ? SignalStateToString(Controller->GetCurrentLightState()) : FString());
      SetNumberOrNull(Item, TEXT("elapsed"), bHasState,
          bHasState ? Controller->GetElapsedTime() : 0.0);
      SetNumberOrNull(Item, TEXT("stage_time"), bHasState,
          bHasState ? Controller->GetCurrentState().Time : 0.0);
      SetNumberOrNull(Item, TEXT("remaining"), bHasState,
          bHasState ? FMath::Max(0.0f,
              Controller->GetCurrentState().Time - Controller->GetElapsedTime()) : 0.0);
      SetNumberOrNull(Item, TEXT("stage_index"), bHasState,
          bHasState ? StateIndex : 0.0);
      SetNumberOrNull(Item, TEXT("stage_count"), StateCount > 0,
          StateCount > 0 ? StateCount : 0.0);
      Item->SetNumberField(TEXT("green_time"), Controller->GetGreenTime());
      Item->SetNumberField(TEXT("yellow_time"), Controller->GetYellowTime());
      Item->SetNumberField(TEXT("red_time"), Controller->GetRedTime());

      FControllerEntry Entry;
      Entry.ControllerId = Controller->GetControllerId();
      Entry.Json = Item;
      ControllerEntries.Add(Entry);
    }
  }

  ControllerEntries.Sort([](
      const FControllerEntry &Left, const FControllerEntry &Right)
  {
    return Left.ControllerId < Right.ControllerId;
  });
  for (const FControllerEntry &Entry : ControllerEntries)
  {
    OutControllers.Add(MakeShared<FJsonValueObject>(Entry.Json));
  }
}

bool FDriscaTrafficLights::ApplyOperation(
    const FString &Method,
    const TSharedPtr<FJsonObject> &Params,
    UWorld &World,
    FTrafficOperationResult &OutResult)
{
  if (Method == TEXT("traffic_light.freeze_all"))
  {
    ACarlaGameModeBase *GameMode = UCarlaStatics::GetGameMode(&World);
    if (GameMode == nullptr || GameMode->GetTrafficLightManager() == nullptr)
    {
      OutResult.ErrorCode = TEXT("invalid_state");
      OutResult.ErrorMessage = TEXT("交通灯管理器不可用");
      return false;
    }
    bool bFrozen = false;
    if (!Params->TryGetBoolField(TEXT("frozen"), bFrozen))
    {
      OutResult.ErrorCode = TEXT("invalid_request");
      OutResult.ErrorMessage = TEXT("缺少 frozen");
      return false;
    }
    ATrafficLightManager *Manager = GameMode->GetTrafficLightManager();
    const bool bPrevious = Manager->GetFrozen();
    TArray<TSharedPtr<FJsonValue>> GroupIds;
    TArray<TSharedPtr<FJsonValue>> ControllerIds;
    for (TActorIterator<ATrafficLightGroup> It(&World); It; ++It)
    {
      ATrafficLightGroup *Group = *It;
      if (Group == nullptr)
      {
        continue;
      }
      GroupIds.Add(MakeShared<FJsonValueNumber>(Group->GetJunctionId()));
      for (UTrafficLightController *Controller : Group->GetControllers())
      {
        if (Controller != nullptr)
        {
          ControllerIds.Add(MakeShared<FJsonValueString>(
              Controller->GetControllerId()));
        }
      }
    }
    Manager->SetFrozen(bFrozen);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("scope"), TEXT("all"));
    Result->SetArrayField(TEXT("group_ids"), GroupIds);
    Result->SetArrayField(TEXT("controller_ids"), ControllerIds);
    Result->SetBoolField(TEXT("previous"), bPrevious);
    Result->SetBoolField(TEXT("frozen"), bFrozen);

    OutResult.bSuccess = true;
    OutResult.Result = Result;
    OutResult.EventName = TEXT("traffic_light_all_frozen");
    OutResult.EventPayload = Result;
    return true;
  }

  double ActorNumber = 0.0;
  if (!Params->TryGetNumberField(TEXT("actor_id"), ActorNumber))
  {
    OutResult.ErrorCode = TEXT("invalid_request");
    OutResult.ErrorMessage = TEXT("缺少 actor_id");
    return false;
  }
  ATrafficLightBase *Light = ResolveLight(World, static_cast<int32>(ActorNumber));
  if (Light == nullptr)
  {
    OutResult.ErrorCode = TEXT("not_found");
    OutResult.ErrorMessage = TEXT("信号灯 actor 不存在");
    return false;
  }
  UTrafficLightComponent *Component = Light->GetTrafficLightComponent();
  UTrafficLightController *Controller =
      Component != nullptr ? Component->GetController() : nullptr;
  ATrafficLightGroup *Group =
      Component != nullptr ? Component->GetGroup() : nullptr;

  if (Method == TEXT("traffic_light.set_state"))
  {
    if (Component == nullptr)
    {
      OutResult.ErrorCode = TEXT("invalid_state");
      OutResult.ErrorMessage = TEXT("信号灯缺少组件");
      return false;
    }
    FString StateText;
    ETrafficLightState NewState = ETrafficLightState::Off;
    if (!Params->TryGetStringField(TEXT("state"), StateText) ||
        !ParseSignalState(StateText, NewState))
    {
      OutResult.ErrorCode = TEXT("invalid_request");
      OutResult.ErrorMessage = TEXT("state 必须是 red、yellow、green 或 off");
      return false;
    }

    const ETrafficLightState Previous = Light->GetTrafficLightState();
    Light->SetTrafficLightState(NewState);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("scope"), TEXT("light"));
    Result->SetNumberField(TEXT("actor_id"), ActorNumber);
    Result->SetStringField(TEXT("signal_id"), Component->GetSignId());
    SetStringOrNull(Result, TEXT("controller_id"), Controller != nullptr,
        Controller != nullptr ? Controller->GetControllerId() : FString());
    if (Group != nullptr)
    {
      Result->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
    }
    else
    {
      Result->SetField(TEXT("group_id"), MakeShared<FJsonValueNull>());
    }
    Result->SetStringField(TEXT("previous_state"),
        SignalStateToString(Previous));
    Result->SetStringField(TEXT("state"), SignalStateToString(NewState));

    OutResult.bSuccess = true;
    OutResult.Result = Result;
    OutResult.EventName = TEXT("traffic_light_state_changed");
    OutResult.EventPayload = Result;
    return true;
  }

  if (Method == TEXT("traffic_controller.set_timing"))
  {
    if (Controller == nullptr)
    {
      OutResult.ErrorCode = TEXT("invalid_state");
      OutResult.ErrorMessage = TEXT("信号灯没有关联控制器");
      return false;
    }

    double Green = 0.0;
    double Yellow = 0.0;
    double Red = 0.0;
    const bool bHasGreen = Params->TryGetNumberField(TEXT("green"), Green);
    const bool bHasYellow = Params->TryGetNumberField(TEXT("yellow"), Yellow);
    const bool bHasRed = Params->TryGetNumberField(TEXT("red"), Red);
    if (!bHasGreen && !bHasYellow && !bHasRed)
    {
      OutResult.ErrorCode = TEXT("invalid_request");
      OutResult.ErrorMessage = TEXT("至少提供 green、yellow、red 中的一个");
      return false;
    }

    const float PreviousGreen = Controller->GetGreenTime();
    const float PreviousYellow = Controller->GetYellowTime();
    const float PreviousRed = Controller->GetRedTime();
    if (bHasGreen)
    {
      Controller->SetGreenTime(static_cast<float>(Green));
    }
    if (bHasYellow)
    {
      Controller->SetYellowTime(static_cast<float>(Yellow));
    }
    if (bHasRed)
    {
      Controller->SetRedTime(static_cast<float>(Red));
    }

    TSharedPtr<FJsonObject> Previous = MakeShared<FJsonObject>();
    Previous->SetNumberField(TEXT("green"), PreviousGreen);
    Previous->SetNumberField(TEXT("yellow"), PreviousYellow);
    Previous->SetNumberField(TEXT("red"), PreviousRed);
    TSharedPtr<FJsonObject> Current = MakeShared<FJsonObject>();
    Current->SetNumberField(TEXT("green"), Controller->GetGreenTime());
    Current->SetNumberField(TEXT("yellow"), Controller->GetYellowTime());
    Current->SetNumberField(TEXT("red"), Controller->GetRedTime());

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("scope"), TEXT("controller"));
    Result->SetStringField(TEXT("controller_id"), Controller->GetControllerId());
    if (Group != nullptr)
    {
      Result->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
    }
    else
    {
      Result->SetField(TEXT("group_id"), MakeShared<FJsonValueNull>());
    }
    Result->SetObjectField(TEXT("previous"), Previous);
    Result->SetObjectField(TEXT("current"), Current);

    OutResult.bSuccess = true;
    OutResult.Result = Result;
    OutResult.EventName = TEXT("traffic_controller_timing_changed");
    OutResult.EventPayload = Result;
    return true;
  }

  if (Method == TEXT("traffic_light_group.freeze"))
  {
    if (Group == nullptr)
    {
      OutResult.ErrorCode = TEXT("invalid_state");
      OutResult.ErrorMessage = TEXT("信号灯没有关联路口组");
      return false;
    }
    bool bFrozen = false;
    if (!Params->TryGetBoolField(TEXT("frozen"), bFrozen))
    {
      OutResult.ErrorCode = TEXT("invalid_request");
      OutResult.ErrorMessage = TEXT("缺少 frozen");
      return false;
    }
    const bool bPrevious = Group->IsFrozen();
    Group->SetFrozenGroup(bFrozen);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("scope"), TEXT("group"));
    Result->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
    Result->SetNumberField(TEXT("junction_id"), Group->GetJunctionId());
    Result->SetArrayField(TEXT("controller_ids"), GroupControllerIds(*Group));
    Result->SetBoolField(TEXT("previous"), bPrevious);
    Result->SetBoolField(TEXT("frozen"), bFrozen);

    OutResult.bSuccess = true;
    OutResult.Result = Result;
    OutResult.EventName = TEXT("traffic_light_group_frozen");
    OutResult.EventPayload = Result;
    return true;
  }

  if (Method == TEXT("traffic_light_group.reset"))
  {
    if (Group == nullptr)
    {
      OutResult.ErrorCode = TEXT("invalid_state");
      OutResult.ErrorMessage = TEXT("信号灯没有关联路口组");
      return false;
    }
    const bool bPreviousFrozen = Group->IsFrozen();
    Group->ResetGroup();

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetStringField(TEXT("scope"), TEXT("group"));
    Result->SetNumberField(TEXT("group_id"), Group->GetJunctionId());
    Result->SetNumberField(TEXT("junction_id"), Group->GetJunctionId());
    Result->SetArrayField(TEXT("controller_ids"), GroupControllerIds(*Group));
    Result->SetBoolField(TEXT("previous_frozen"), bPreviousFrozen);
    Result->SetBoolField(TEXT("frozen"), Group->IsFrozen());

    OutResult.bSuccess = true;
    OutResult.Result = Result;
    OutResult.EventName = TEXT("traffic_light_group_reset");
    OutResult.EventPayload = Result;
    return true;
  }

  OutResult.ErrorCode = TEXT("unsupported");
  OutResult.ErrorMessage = FString::Printf(TEXT("未知信号操作 %s"), *Method);
  return false;
}
