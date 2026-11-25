#include "DriscaApiSubsystem.h"
#include "DriscaApiInternals.h"
#include "DriscaApiRoadData.h"
#include "DriscaApiTrafficLights.h"

#include "DriscaApiServer.h"
#include "DriscaBoost.h"
#include "DrivingViewPawn.h"
#include "DrivingViewSubsystem.h"

#include "Carla.h"
#include "Carla/Actor/ActorBlueprintFunctionLibrary.h"
#include "Carla/Actor/ActorDefinition.h"
#include "Carla/Actor/ActorDescription.h"
#include "Carla/Actor/ActorInfo.h"
#include "Carla/Actor/ActorRegistry.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEngine.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaGameModeBase.h"
#include "Carla/Game/CarlaStatics.h"
#include "Carla/Sensor/GnssSensor.h"
#include "Carla/Sensor/InertialMeasurementUnit.h"
#include "Carla/Util/BoundingBox.h"
#include "Carla/Vehicle/CarlaWheeledVehicle.h"
#include "Carla/Vehicle/VehicleControl.h"
#include "Carla/Vehicle/VehicleLightState.h"
#include "Carla/Weather/Weather.h"

#include <util/ue-header-guard-begin.h>
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "DrawDebugHelpers.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include <util/ue-header-guard-end.h>

#include <util/disable-ue4-macros.h>
#include "carla/geom/Location.h"
#include "carla/road/Map.h"
#include "carla/road/element/LaneMarking.h"
#include "carla/road/element/Waypoint.h"
#include "carla/rpc/WeatherParameters.h"
#include <util/enable-ue4-macros.h>

namespace
{
  bool SerializeJson(const TSharedPtr<FJsonObject> &Object, FString &OutText)
  {
    TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&OutText);
    return FJsonSerializer::Serialize(Object.ToSharedRef(), Writer);
  }

  TSharedPtr<FJsonObject> EmptyObject()
  {
    return MakeShared<FJsonObject>();
  }

  struct FWeatherPreset
  {
    const TCHAR *Name;
    carla::rpc::WeatherParameters Value;
  };

  const TArray<FWeatherPreset> &GetWeatherPresets()
  {
    static const TArray<FWeatherPreset> Presets = {
        {TEXT("Default"), carla::rpc::WeatherParameters::Default},
        {TEXT("ClearNoon"), carla::rpc::WeatherParameters::ClearNoon},
        {TEXT("CloudyNoon"), carla::rpc::WeatherParameters::CloudyNoon},
        {TEXT("WetNoon"), carla::rpc::WeatherParameters::WetNoon},
        {TEXT("WetCloudyNoon"), carla::rpc::WeatherParameters::WetCloudyNoon},
        {TEXT("MidRainyNoon"), carla::rpc::WeatherParameters::MidRainyNoon},
        {TEXT("HardRainNoon"), carla::rpc::WeatherParameters::HardRainNoon},
        {TEXT("SoftRainNoon"), carla::rpc::WeatherParameters::SoftRainNoon},
        {TEXT("ClearSunset"), carla::rpc::WeatherParameters::ClearSunset},
        {TEXT("CloudySunset"), carla::rpc::WeatherParameters::CloudySunset},
        {TEXT("WetSunset"), carla::rpc::WeatherParameters::WetSunset},
        {TEXT("WetCloudySunset"), carla::rpc::WeatherParameters::WetCloudySunset},
        {TEXT("MidRainSunset"), carla::rpc::WeatherParameters::MidRainSunset},
        {TEXT("HardRainSunset"), carla::rpc::WeatherParameters::HardRainSunset},
        {TEXT("SoftRainSunset"), carla::rpc::WeatherParameters::SoftRainSunset},
        {TEXT("ClearNight"), carla::rpc::WeatherParameters::ClearNight},
        {TEXT("CloudyNight"), carla::rpc::WeatherParameters::CloudyNight},
        {TEXT("WetNight"), carla::rpc::WeatherParameters::WetNight},
        {TEXT("WetCloudyNight"), carla::rpc::WeatherParameters::WetCloudyNight},
        {TEXT("SoftRainNight"), carla::rpc::WeatherParameters::SoftRainNight},
        {TEXT("MidRainyNight"), carla::rpc::WeatherParameters::MidRainyNight},
        {TEXT("HardRainNight"), carla::rpc::WeatherParameters::HardRainNight},
        {TEXT("DustStorm"), carla::rpc::WeatherParameters::DustStorm}};
    return Presets;
  }


}

using namespace DriscaApiInternal;

bool UDriscaApiSubsystem::ShouldCreateSubsystem(UObject *Outer) const
{
  return Super::ShouldCreateSubsystem(Outer);
}

void UDriscaApiSubsystem::Initialize(FSubsystemCollectionBase &Collection)
{
  Super::Initialize(Collection);

  ServerInstance = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphens);
  WorldId = 1;
  bWorldReady = false;
  CurrentWorld.Reset();

  FWorldDelegates::OnWorldPostActorTick.AddUObject(
      this, &UDriscaApiSubsystem::OnWorldPostActorTick);
  FWorldDelegates::OnWorldPreActorTick.AddUObject(
      this, &UDriscaApiSubsystem::OnWorldPreActorTick);

  int32 Port = DriscaApi::DefaultPort;
  FParse::Value(FCommandLine::Get(), TEXT("DriscaDrivingPort="), Port);
  if (Port <= 0 || Port > 65535)
  {
    Port = DriscaApi::DefaultPort;
  }

  Server = new FDriscaApiServer();
  RoadData = new FDriscaRoadData();
  TrafficLights = new FDriscaTrafficLights();
  Server->OnMessage = [this](int64 ConnectionId, const FString &Message)
  {
    OnClientMessage(ConnectionId, Message);
  };
  Server->OnClosed = [this](int64 ConnectionId)
  {
    OnClientClosed(ConnectionId);
  };

  FString Error;
  if (!Server->Start(Port, Error))
  {
    UE_LOG(LogCarla, Error, TEXT("DriscaApi: %s"), *Error);
  }
}

void UDriscaApiSubsystem::Deinitialize()
{
  FWorldDelegates::OnWorldPostActorTick.RemoveAll(this);
  FWorldDelegates::OnWorldPreActorTick.RemoveAll(this);
  StopReplayView();

  AbortSession();
  ClearEnvironment(-1, false);
  if (Server != nullptr)
  {
    Server->Stop();
    delete Server;
    Server = nullptr;
  }
  delete RoadData;
  RoadData = nullptr;
  delete TrafficLights;
  TrafficLights = nullptr;
  Super::Deinitialize();
}

UDriscaApiSubsystem::~UDriscaApiSubsystem() = default;

bool UDriscaApiSubsystem::ApplyScreenMessagePolicy(
    const TSharedPtr<FJsonObject> &Params, FString &OutError)
{
  bool bSuppress = false;
  if (Params->HasField(TEXT("suppress_screen_messages")) &&
      !Params->TryGetBoolField(TEXT("suppress_screen_messages"), bSuppress))
  {
    OutError = TEXT("suppress_screen_messages 必须是布尔值");
    return false;
  }
  IConsoleVariable *Variable = IConsoleManager::Get().FindConsoleVariable(
      TEXT("r.Shadow.Virtual.AllowScreenOverflowMessages"));
  if (!Variable)
  {
    OutError = TEXT("VSM 屏幕消息配置不可用");
    return false;
  }
  const int32 Value = bSuppress ? 0 : 1;
  Variable->Set(Value, ECVF_SetByCode);
  if (Variable->GetInt() != Value)
  {
    OutError = TEXT("VSM 屏幕消息配置被更高优先级设置覆盖");
    return false;
  }
  return true;
}

void UDriscaApiSubsystem::PositionInitialFreeCamera(UCarlaEpisode *Episode)
{
  APlayerController *PC = CurrentWorld.IsValid() ? CurrentWorld->GetFirstPlayerController() : nullptr;
  APawn *Spectator = Episode->GetSpectatorPawn();
  if (!PC || !Spectator || PC->GetViewTarget() != Spectator) return;
  const FVector Current = Spectator->GetActorLocation();
  // 只修正原点附近的贴地初始视角；保留地图已设置的正常观察位置。
  if (Current.SizeSquared2D() > FMath::Square(1000.0) || FMath::Abs(Current.Z) > 300.0) return;
  for (const FTransform &Spawn : Episode->GetRecommendedSpawnPoints())
  {
    if (Spawn.ContainsNaN()) continue;
    const FVector Location = Spawn.GetLocation() + FVector(0, 0, 1800);
    const FRotator Rotation(-20, Spawn.Rotator().Yaw, 0);
    Spectator->SetActorLocationAndRotation(Location, Rotation, false, nullptr, ETeleportType::TeleportPhysics);
    PC->SetControlRotation(Rotation);
    UE_LOG(LogCarla, Log, TEXT("地图初始自由相机已移动至出生点上方 18 米：%s"), *Location.ToString());
    return;
  }
}

void UDriscaApiSubsystem::OnWorldPreActorTick(
    UWorld *World, ELevelTick TickType, float DeltaSeconds)
{
  if (!IsValid(World) || !World->IsGameWorld() || TickType != LEVELTICK_All ||
      !bWorldReady || CurrentWorld.Get() != World ||
      !GetGameInstance() || GetGameInstance()->GetWorld() != World || bFatalPending) return;
  // CARLA 已在 WorldTickStart 更新帧号；此处尚未运行车辆和物理 Tick。
  TGuardValue<bool> BeforePhysics(bBeforePhysics, true);
  if (Server) Server->Poll();
}

void UDriscaApiSubsystem::OnWorldPostActorTick(
    UWorld *World, ELevelTick TickType, float DeltaSeconds)
{
  if (!IsValid(World) || !World->IsGameWorld())
  {
    return;
  }
  if (GetGameInstance() == nullptr || GetGameInstance()->GetWorld() != World)
  {
    return;
  }

  ++PostTickSerial;

  if (bFatalPending)
  {
    HandleFatal();
    return;
  }

  if (Server != nullptr)
  {
    Server->Poll();
  }

  if (bFatalPending)
  {
    HandleFatal();
    return;
  }

  if (CurrentWorld.Get() != World)
  {
    HandleWorldSwitch(World);
  }

  UCarlaEpisode *Episode = GetEpisode();
  if (!bWorldReady)
  {
    if (Episode == nullptr)
    {
      return;
    }
    PositionInitialFreeCamera(Episode);
    bWorldReady = true;
  }

  TickEnvironment();
  TickReplayView();
  for (int32 Index = ActorHighlights.Num() - 1; Index >= 0; --Index)
  {
    const FActorHighlight &Highlight = ActorHighlights[Index];
    AActor *Actor = Highlight.Actor.Get();
    if (!Actor || World->GetTimeSeconds() >= Highlight.EndTime)
    { ActorHighlights.RemoveAtSwap(Index); continue; }
    FVector Center, Extent;
    Actor->GetActorBounds(true, Center, Extent);
    DrawDebugBox(World, Center, Extent + FVector(8), FColor::Yellow, false, -1, 0, 3);
    if (!Highlight.Label.IsEmpty())
      DrawDebugString(World, Center + FVector(0, 0, Extent.Z + 70), Highlight.Label,
          nullptr, FColor::Yellow, 0, true);
    for (int32 Point = 1; Point < Highlight.Points.Num(); ++Point)
      DrawDebugLine(World, Highlight.Points[Point - 1], Highlight.Points[Point],
          FColor::Cyan, false, -1, 0, 16.0f);
  }

  SampleFrame(DeltaSeconds);

  if (bFatalPending)
  {
    HandleFatal();
    return;
  }

  CompletePendingExchange();

  if (PendingMapLoad.bValid && PendingMapLoad.bWorldSwitched && bWorldReady &&
      Episode != nullptr)
  {
    const int64 ConnectionId = PendingMapLoad.ConnectionId;
    const int32 RequestId = PendingMapLoad.RequestId;
    const FString RequestedMap = PendingMapLoad.MapName;
    const bool bMapMatches =
        Episode->GetMapName().Equals(RequestedMap, ESearchCase::IgnoreCase);
    // 整个 pending 状态复位，避免残留字段影响下一次加载。
    PendingMapLoad = DriscaApi::FPendingMapLoad();

    if (bMapMatches)
    {
      TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
      Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
      Result->SetStringField(TEXT("current_map"), GetCurrentMapName());
      SendResult(ConnectionId, RequestId, Result);
    }
    else
    {
      SendError(ConnectionId, RequestId, CodeNotFound,
          FString::Printf(TEXT("地图 %s 加载失败，当前为 %s"),
              *RequestedMap, *GetCurrentMapName()));
    }

    if (DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId))
    {
      Connection->bInFlight = false;
    }
  }

  // 末尾再推进一次非阻塞 I/O：执行本帧响应已排队的写完成回调，使 exchange
  // 的二进制快照在同一物理帧内开始发送，而不必等到下一帧的 Poll。末尾读入
  // 的请求仍以当前 PostTickSerial 受理，保留下一次物理更新后采样。
  if (Server != nullptr && !bFatalPending)
  {
    Server->Poll();
  }
}

void UDriscaApiSubsystem::HandleWorldSwitch(UWorld *World)
{
  // 旧世界正在销毁，不能在其中停止视图或销毁 Actor。会话对象随世界一起消失，
  // 这里只清理本子系统持有的引用和簿记状态。
  EnvironmentRegions.Empty();
  bReplayViewOwned = false;
  ActorHighlights.Empty();
  const bool bInitialWorld = !bWorldAttached;
  bWorldAttached = true;
  ActionDelegateHandle.Reset();
  Imu.Reset();
  Gnss.Reset();
  EgoVehicle.Reset();
  Session = DriscaApi::FSessionState();
  PendingExchange = DriscaApi::FPendingExchange();
  EventQueue.Empty();
  bTakeoverThisFrame = false;
  ResearchTickCount = 0;
  for (TPair<int64, DriscaApi::FConnectionState> &Pair : Connections)
  {
    Pair.Value.bControl = false;
    Pair.Value.SessionId.Empty();
    Pair.Value.CreatedActors.Empty();
  }

  CurrentWorld = World;
  VehicleTracks.Empty();
  LastLightStates.Empty();
  bWorldReady = false;
  ActiveWeatherPreset = TEXT("Custom");
  bHasSample = false;
  // 旧世界的录像对象随世界销毁，归属状态一并清理。
  OwnedRecorder.Reset();
  RecorderPath.Empty();
  if (RoadData != nullptr)
  {
    RoadData->Invalidate();
  }
  if (TrafficLights != nullptr)
  {
    TrafficLights->Invalidate();
  }

  if (bInitialWorld)
  {
    // 首个世界沿用 Initialize 设置的 world_id=1。
  }
  else if (PendingMapLoad.bValid && !PendingMapLoad.bWorldSwitched)
  {
    // 本次切换由 scene.load_map 发起，world_id 使用受理时约定的新值。
    WorldId = PendingMapLoad.NewWorldId;
    PendingMapLoad.bWorldSwitched = true;
  }
  else
  {
    // 没有待完成的地图请求，或请求的切换已完成又发生外部切换：严格递增。
    ++WorldId;
  }
}

void UDriscaApiSubsystem::ResetWorldState()
{
  AbortSession();
  VehicleTracks.Empty();
  LastLightStates.Empty();
  bHasSample = false;
}

void UDriscaApiSubsystem::AbortSession()
{
  ClearEnvironment(-1, true);
  StopResearch();

  if (UDrivingViewSubsystem *View = GetViewSubsystem())
  {
    FString Error;
    View->StopView(Error);
  }

  // 先停止本次 API 启动的录像，再销毁车辆，避免收尾事件落进正在写入的文件。
  StopOwnedRecorder();

  if (UCarlaEpisode *Episode = GetEpisode())
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

  for (TPair<int64, DriscaApi::FConnectionState> &Pair : Connections)
  {
    Pair.Value.bControl = false;
    Pair.Value.SessionId.Empty();
    Pair.Value.CreatedActors.Empty();
  }

  Session = DriscaApi::FSessionState();
  PendingExchange.bValid = false;
  EventQueue.Empty();
  VehicleTracks.Empty();
  LastLightStates.Empty();
  bTakeoverThisFrame = false;
}

// =============================================================================
// -- 连接与请求 ---------------------------------------------------------------
// =============================================================================

void UDriscaApiSubsystem::OnClientMessage(
    int64 ConnectionId, const FString &Message)
{
  DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);
  if (Connection == nullptr)
  {
    Connection = &Connections.Add(ConnectionId, DriscaApi::FConnectionState());
  }

  TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);
  TSharedPtr<FJsonObject> Request;
  if (!FJsonSerializer::Deserialize(Reader, Request) || !Request.IsValid())
  {
    SendError(ConnectionId, 0, CodeInvalidRequest, TEXT("消息不是有效的 JSON 对象"));
    return;
  }

  HandleRequest(ConnectionId, Request, *Connection);
}

void UDriscaApiSubsystem::OnClientClosed(int64 ConnectionId)
{
  DriscaApi::FConnectionState *Connection = Connections.Find(ConnectionId);
  if (Connection == nullptr)
  {
    return;
  }

  ClearEnvironment(ConnectionId, false);
  const bool bWasControl = Connection->bControl;
  const TArray<uint32> CreatedActors = Connection->CreatedActors;
  Connections.Remove(ConnectionId);

  if (bWasControl)
  {
    UE_LOG(LogCarla, Warning,
        TEXT("DriscaApi: control connection %lld closed, aborting experiment"), ConnectionId);
    AbortSession();
    return;
  }

  if (!Session.bActive)
  {
    if (UCarlaEpisode *Episode = GetEpisode())
    {
      for (uint32 Id : CreatedActors)
      {
        Episode->DestroyActor(Id);
      }
    }
  }
}

void UDriscaApiSubsystem::HandleRequest(
    int64 ConnectionId,
    const TSharedPtr<FJsonObject> &Request,
    DriscaApi::FConnectionState &Connection)
{
  double IdNumber = 0.0;
  if (!Request->TryGetNumberField(TEXT("id"), IdNumber))
  {
    SendError(ConnectionId, 0, CodeInvalidRequest, TEXT("缺少请求 id"));
    return;
  }
  const int32 RequestId = static_cast<int32>(IdNumber);

  FString Method;
  if (!Request->TryGetStringField(TEXT("method"), Method))
  {
    SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("缺少 method"));
    return;
  }

  TSharedPtr<FJsonObject> Params;
  const TSharedPtr<FJsonObject> *ParamsObject = nullptr;
  if (Request->TryGetObjectField(TEXT("params"), ParamsObject) && ParamsObject != nullptr)
  {
    Params = *ParamsObject;
  }
  else
  {
    Params = MakeShared<FJsonObject>();
  }

  if (Method == TEXT("hello"))
  {
    HandleHello(ConnectionId, RequestId, Params, Connection);
    return;
  }

  if (!Connection.bHello)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState, TEXT("首条请求必须是 hello"));
    return;
  }

  if (Connection.bInFlight)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState,
        TEXT("前一个请求尚未完成，每连接只允许一个在途请求"));
    return;
  }

  if (Method == TEXT("scene.road_graph") ||
      Method == TEXT("scene.road_junctions") ||
      Method == TEXT("scene.road_signals"))
  {
    Connection.bInFlight = true;
    HandleRoadGraph(ConnectionId, RequestId, Method, Params);
    Connection.bInFlight = false;
    return;
  }

  if (Method == TEXT("exchange") || Method == TEXT("batch"))
  {
    HandleBatch(ConnectionId, RequestId, Params, Connection, Method == TEXT("exchange"));
    return;
  }

  if (Method == TEXT("scene.load_map"))
  {
    FString Code;
    FString Message;
    if (!RequireWorld(Params, Code, Message))
    {
      SendError(ConnectionId, RequestId, Code, Message);
      return;
    }
    if (Session.bActive)
    {
      SendError(ConnectionId, RequestId, CodeInvalidState,
          TEXT("实验进行中不能切换地图"));
      return;
    }
    if (PendingMapLoad.bValid)
    {
      SendError(ConnectionId, RequestId, CodeInvalidState,
          TEXT("地图正在加载"));
      return;
    }

    FString MapName;
    if (!Params->TryGetStringField(TEXT("map_name"), MapName) || MapName.IsEmpty())
    {
      SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("缺少 map_name"));
      return;
    }

    UCarlaEpisode *Episode = GetEpisode();
    if (Episode == nullptr)
    {
      SendError(ConnectionId, RequestId, CodeInvalidState, TEXT("当前没有可用的世界"));
      return;
    }

    // 从干净的 pending 状态开始，避免上一次加载的 bWorldSwitched 等字段残留。
    PendingMapLoad = DriscaApi::FPendingMapLoad();
    PendingMapLoad.bValid = true;
    FString ScreenMessageError;
    if (!ApplyScreenMessagePolicy(Params, ScreenMessageError))
    {
      PendingMapLoad = DriscaApi::FPendingMapLoad();
      SendError(ConnectionId, RequestId, CodeInvalidRequest, ScreenMessageError);
      return;
    }
    PendingMapLoad.ConnectionId = ConnectionId;
    PendingMapLoad.RequestId = RequestId;
    PendingMapLoad.MapName = MapName;
    PendingMapLoad.NewWorldId = WorldId + 1;

    if (!Episode->LoadNewEpisode(MapName, true))
    {
      PendingMapLoad = DriscaApi::FPendingMapLoad();
      SendError(ConnectionId, RequestId, CodeNotFound,
          FString::Printf(TEXT("地图 %s 不存在"), *MapName));
      return;
    }

    Connection.bInFlight = true;
    return;
  }

  // 其余请求要求已有可用世界，只有 server.status 例外。
  if (Method != TEXT("server.status"))
  {
    FString Code;
    FString Message;
    if (!RequireWorld(Params, Code, Message))
    {
      SendError(ConnectionId, RequestId, Code, Message);
      return;
    }
  }

  FString SessionId;
  Params->TryGetStringField(TEXT("session_id"), SessionId);

  DriscaApi::FOperationResult Result;
  bool bFormatError = false;
  Connection.bInFlight = true;
  ExecuteOperation(
      ConnectionId, SessionId, RequestId, 0, Method, Params, Result, bFormatError);

  if (bFatalPending)
  {
    Connection.bInFlight = false;
    SendError(ConnectionId, RequestId, FatalCode, FatalMessage);
    return;
  }

  if (bFormatError)
  {
    Connection.bInFlight = false;
    SendError(ConnectionId, RequestId, CodeInvalidRequest, Result.ErrorMessage);
    return;
  }
  if (Result.Status != DriscaApi::EOperationStatus::Applied)
  {
    Connection.bInFlight = false;
    SendError(ConnectionId, RequestId,
        Result.ErrorCode.IsEmpty() ? CodeOperationFailed : Result.ErrorCode,
        Result.ErrorMessage);
    return;
  }

  Connection.bInFlight = false;
  SendResult(ConnectionId, RequestId,
      Result.Result.IsValid() ? Result.Result : MakeShared<FJsonObject>());
}

void UDriscaApiSubsystem::HandleHello(
    int64 ConnectionId,
    int32 RequestId,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FConnectionState &Connection)
{
  if (Connection.bHello)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState, TEXT("hello 已经完成"));
    return;
  }

  double Version = 0.0;
  if (!Params->TryGetNumberField(TEXT("protocol_version"), Version))
  {
    SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("缺少 protocol_version"));
    return;
  }
  if (static_cast<int32>(Version) != DriscaApi::ProtocolVersion)
  {
    SendError(ConnectionId, RequestId, CodeVersionMismatch,
        FString::Printf(TEXT("只支持协议版本 %d"), DriscaApi::ProtocolVersion));
    return;
  }

  FString Client;
  Params->TryGetStringField(TEXT("client"), Client);

  Connection.bHello = true;
  Connection.Client = Client;

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("protocol_version"), DriscaApi::ProtocolVersion);
  Result->SetStringField(TEXT("server_instance"), ServerInstance);
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetStringField(TEXT("map_name"), GetCurrentMapName());
  Result->SetNumberField(TEXT("max_message_bytes"), DriscaApi::MaxMessageBytes);
  Result->SetNumberField(TEXT("snapshot_header_bytes"), DriscaApi::SnapshotHeaderBytes);
  Result->SetNumberField(TEXT("vehicle_record_bytes"), DriscaApi::VehicleRecordBytes);
  Result->SetNumberField(TEXT("research_record_bytes"), DriscaApi::ResearchRecordBytes);
  SendResult(ConnectionId, RequestId, Result);
}

void UDriscaApiSubsystem::HandleBatch(
    int64 ConnectionId,
    int32 RequestId,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FConnectionState &Connection,
    bool bExchange)
{
  DriscaApi::FOperationResult Ignored;
  bool bFormatError = false;

  FString Code;
  FString Message;
  if (!RequireWorld(Params, Code, Message))
  {
    SendError(ConnectionId, RequestId, Code, Message);
    return;
  }

  FString SessionId;
  Params->TryGetStringField(TEXT("session_id"), SessionId);
  if (!SessionId.IsEmpty() && Session.bActive && Session.SessionId != SessionId)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState,
        TEXT("session_id 与当前实验不一致"));
    return;
  }

  if (bExchange)
  {
    if (!Connection.bControl || !Session.bActive ||
        Session.ControlConnection != ConnectionId)
    {
      SendError(ConnectionId, RequestId, CodeInvalidState,
          TEXT("exchange 只能由当前实验的控制连接发送"));
      return;
    }
  }

  const TArray<TSharedPtr<FJsonValue>> *Operations = nullptr;
  if (!Params->TryGetArrayField(TEXT("operations"), Operations) || Operations == nullptr)
  {
    SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("缺少 operations 数组"));
    return;
  }
  if (bExchange && PendingExchange.bValid)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState,
        TEXT("另一个 exchange 尚未完成"));
    return;
  }
  if (Operations->Num() > DriscaApi::MaxOperationsPerRequest)
  {
    SendError(ConnectionId, RequestId, CodeInvalidRequest,
        FString::Printf(TEXT("单次请求最多 %d 条操作"),
            DriscaApi::MaxOperationsPerRequest));
    return;
  }

  struct FQueuedOperation
  {
    FString Method;
    TSharedPtr<FJsonObject> Params;
  };
  TArray<FQueuedOperation> Queue;
  Queue.Reserve(Operations->Num());
  for (const TSharedPtr<FJsonValue> &Value : *Operations)
  {
    if (!Value.IsValid() || Value->Type != EJson::Object)
    {
      SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("operations 的每一项必须是对象"));
      return;
    }
    const TSharedPtr<FJsonObject> &Operation = Value->AsObject();
    FString Method;
    if (!Operation->TryGetStringField(TEXT("method"), Method) || Method.IsEmpty())
    {
      SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("操作缺少 method"));
      return;
    }
    TSharedPtr<FJsonObject> OperationParams = MakeShared<FJsonObject>();
    const TSharedPtr<FJsonObject> *ParamsObject = nullptr;
    if (Operation->TryGetObjectField(TEXT("params"), ParamsObject) && ParamsObject != nullptr)
    {
      OperationParams = *ParamsObject;
    }
    Queue.Add({Method, OperationParams});
  }

  TArray<DriscaApi::FOperationResult> Results;
  Results.Reserve(Queue.Num());
  bool bExecutionFailed = false;
  FString FailureCode;
  FString FailureMessage;

  Connection.bInFlight = true;
  for (int32 Index = 0; Index < Queue.Num(); ++Index)
  {
    DriscaApi::FOperationResult Result;
    Result.Index = Index;
    if (bExecutionFailed)
    {
      Result.Status = DriscaApi::EOperationStatus::Skipped;
      Results.Add(Result);
      continue;
    }

    const bool bApplied = ExecuteOperation(
        ConnectionId, SessionId, RequestId, Index,
        Queue[Index].Method, Queue[Index].Params, Result, bFormatError);
    if (bFormatError)
    {
      Connection.bInFlight = false;
      SendError(ConnectionId, RequestId, CodeInvalidRequest, Result.ErrorMessage);
      return;
    }
    Results.Add(Result);
    if (bFatalPending)
    {
      bExecutionFailed = true;
      FailureCode = FatalCode;
      FailureMessage = FatalMessage;
    }
    else if (Result.Status == DriscaApi::EOperationStatus::Skipped)
    {
      // 过期的控制请求按 skipped 处理，不终止批次。
    }
    else if (!bApplied)
    {
      bExecutionFailed = true;
      FailureCode = Result.ErrorCode;
      FailureMessage = Result.ErrorMessage;
    }
  }

  auto ResultsJson = [&Results]()
  {
    TArray<TSharedPtr<FJsonValue>> Array;
    Array.Reserve(Results.Num());
    for (const DriscaApi::FOperationResult &Result : Results)
    {
      TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
      Item->SetNumberField(TEXT("index"), Result.Index);
      switch (Result.Status)
      {
        case DriscaApi::EOperationStatus::Applied:
          Item->SetStringField(TEXT("status"), TEXT("applied"));
          Item->SetNumberField(TEXT("applied_frame_no"),
              static_cast<double>(Result.AppliedFrameNo));
          if (Result.SampledFrameNo != 0)
          {
            Item->SetNumberField(TEXT("sampled_frame_no"),
                static_cast<double>(Result.SampledFrameNo));
          }
          Item->SetObjectField(TEXT("result"),
              Result.Result.IsValid() ? Result.Result : MakeShared<FJsonObject>());
          break;
        case DriscaApi::EOperationStatus::Failed:
        {
          Item->SetStringField(TEXT("status"), TEXT("failed"));
          TSharedPtr<FJsonObject> Error = DriscaApi::MakeError(
              Result.ErrorCode.IsEmpty() ? CodeOperationFailed : Result.ErrorCode,
              Result.ErrorMessage);
          Item->SetObjectField(TEXT("error"), Error);
          break;
        }
        default:
          Item->SetStringField(TEXT("status"), TEXT("skipped"));
          if (!Result.ErrorCode.IsEmpty())
          {
            Item->SetObjectField(TEXT("error"), DriscaApi::MakeError(
                Result.ErrorCode, Result.ErrorMessage));
          }
          break;
      }
      Array.Add(MakeShared<FJsonValueObject>(Item));
    }
    return Array;
  };

  if (bExecutionFailed)
  {
    Connection.bInFlight = false;
    TSharedPtr<FJsonObject> Extra = MakeShared<FJsonObject>();
    Extra->SetArrayField(TEXT("results"), ResultsJson());
    SendError(ConnectionId, RequestId,
        FailureCode.IsEmpty() ? CodeOperationFailed : FailureCode,
        FailureMessage, Extra);
    return;
  }

  if (!bExchange)
  {
    Connection.bInFlight = false;
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
    Result->SetArrayField(TEXT("results"), ResultsJson());
    Result->SetBoolField(TEXT("snapshot"), false);
    SendResult(ConnectionId, RequestId, Result);
    return;
  }

  if (Session.bActive && !SessionId.IsEmpty() && SessionId != Session.SessionId)
  {
    Connection.bInFlight = false;
    SendError(ConnectionId, RequestId, CodeInvalidState,
        TEXT("session_id 与当前实验不一致"));
    return;
  }

  PendingExchange.bValid = true;
  PendingExchange.ConnectionId = ConnectionId;
  PendingExchange.RequestId = RequestId;
  PendingExchange.SessionId = SessionId;
  PendingExchange.Results = MoveTemp(Results);
  PendingExchange.AppliedFrameNo = CurrentFrameNo();
  PendingExchange.ScheduledPostTick = PostTickSerial;
  PendingExchange.bBeforePhysics = bBeforePhysics;
  PendingExchange.AcceptedTimeSeconds = FPlatformTime::Seconds();
}

bool UDriscaApiSubsystem::HandleRoadGraph(
    int64 ConnectionId,
    int32 RequestId,
    const FString &Method,
    const TSharedPtr<FJsonObject> &Params)
{
  FString Code;
  FString Message;
  if (!RequireWorld(Params, Code, Message))
  {
    SendError(ConnectionId, RequestId, Code, Message);
    return false;
  }
  if (Session.bActive)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState,
        TEXT("静态交通数据只能在地图准备空闲期构建"));
    return false;
  }

  UCarlaEpisode *Episode = GetEpisode();
  ACarlaGameModeBase *GameMode = GetGameMode();
  if (Episode == nullptr || GameMode == nullptr)
  {
    SendError(ConnectionId, RequestId, CodeInvalidState, TEXT("当前没有可用的世界"));
    return false;
  }

  const FString MapName = GetCurrentMapName();

  if (Method == TEXT("scene.road_graph"))
  {
    double Step = 2.0;
    if (Params->HasField(TEXT("sampling_step")))
    {
      if (!Params->TryGetNumberField(TEXT("sampling_step"), Step) ||
          Step < 0.5 || Step > 20.0)
      {
        SendError(ConnectionId, RequestId, CodeInvalidRequest,
            TEXT("sampling_step 必须在 0.5 到 20.0 米之间"));
        return false;
      }
    }

    double CursorValue = 0.0;
    Params->TryGetNumberField(TEXT("cursor"), CursorValue);
    if (CursorValue < 0.0)
    {
      SendError(ConnectionId, RequestId, CodeInvalidRequest, TEXT("cursor 不能为负"));
      return false;
    }
    const int32 Cursor = static_cast<int32>(CursorValue);

    double MaxLanesValue = 200.0;
    Params->TryGetNumberField(TEXT("max_lanes"), MaxLanesValue);
    if (MaxLanesValue < 1.0)
    {
      SendError(ConnectionId, RequestId, CodeInvalidRequest,
          TEXT("max_lanes 必须是正数"));
      return false;
    }
    const int32 MaxLanes = FMath::Clamp(
        static_cast<int32>(MaxLanesValue), 1, 500);

    if (RoadData == nullptr)
    {
      SendError(ConnectionId, RequestId, CodeOperationFailed,
          TEXT("道路数据模块不可用"));
      return false;
    }
    if (!RoadData->IsBuilt(WorldId, Step))
    {
      FString BuildError;
      if (!RoadData->Build(*GameMode, WorldId, Step, BuildError))
      {
        SendError(ConnectionId, RequestId, CodeOperationFailed, BuildError);
        return false;
      }
    }

    TSharedPtr<FJsonObject> Result;
    FString PageError;
    if (!RoadData->SerializePage(
            WorldId, MapName, Cursor, MaxLanes, Result, PageError))
    {
      const bool bOverflow = PageError.Contains(TEXT("预算"));
      SendError(ConnectionId, RequestId,
          bOverflow ? TEXT("overflow") : CodeOperationFailed, PageError);
      return false;
    }
    Result->SetNumberField(TEXT("build_ms"), RoadData->GetBuildMilliseconds());
    SendResult(ConnectionId, RequestId, Result);
    return true;
  }

  if (Method == TEXT("scene.road_junctions"))
  {
    if (RoadData == nullptr)
    {
      SendError(ConnectionId, RequestId, CodeOperationFailed,
          TEXT("道路数据模块不可用"));
      return false;
    }
    if (!RoadData->IsWorldBuilt(WorldId))
    {
      FString BuildError;
      if (!RoadData->Build(*GameMode, WorldId, 2.0, BuildError))
      {
        SendError(ConnectionId, RequestId, CodeOperationFailed, BuildError);
        return false;
      }
    }
    TSharedPtr<FJsonObject> Result;
    FString Error;
    if (!RoadData->SerializeJunctions(WorldId, MapName, Result, Error))
    {
      SendError(ConnectionId, RequestId, CodeOperationFailed, Error);
      return false;
    }
    Result->SetNumberField(TEXT("build_ms"), RoadData->GetBuildMilliseconds());
    SendResult(ConnectionId, RequestId, Result);
    return true;
  }

  if (Method == TEXT("scene.road_signals"))
  {
    if (TrafficLights == nullptr)
    {
      SendError(ConnectionId, RequestId, CodeOperationFailed,
          TEXT("信号数据模块不可用"));
      return false;
    }
    if (!TrafficLights->IsBuilt(WorldId))
    {
      FString BuildError;
      if (!TrafficLights->Build(*GameMode, *Episode, WorldId, BuildError))
      {
        SendError(ConnectionId, RequestId, CodeOperationFailed, BuildError);
        return false;
      }
    }
    TSharedPtr<FJsonObject> Result;
    FString Error;
    if (!TrafficLights->SerializeSignals(WorldId, MapName, Result, Error))
    {
      SendError(ConnectionId, RequestId, CodeOperationFailed, Error);
      return false;
    }
    SendResult(ConnectionId, RequestId, Result);
    return true;
  }

  SendError(ConnectionId, RequestId, CodeUnsupported, TEXT("未知交通数据请求"));
  return false;
}

void UDriscaApiSubsystem::CompletePendingExchange()
{
  if (!PendingExchange.bValid || !bWorldReady)
  {
    return;
  }
  // 本帧刚受理的命令要等下一次物理更新，避免快照出现“新控制量 + 旧运动状态”。
  if (PendingExchange.ScheduledPostTick == PostTickSerial)
  {
    return;
  }

  if (!Session.bActive || Session.ControlConnection != PendingExchange.ConnectionId)
  {
    SendError(PendingExchange.ConnectionId, PendingExchange.RequestId, CodeInvalidState,
        TEXT("实验已结束，exchange 不再交付"));
    PendingExchange = DriscaApi::FPendingExchange();
    return;
  }

  const double BuildStart = FPlatformTime::Seconds();
  const DriscaApi::FSnapshot Snapshot = BuildSnapshot(PendingExchange.RequestId);
  FString InvalidReason;
  if (!ValidateSnapshot(Snapshot, InvalidReason))
  {
    RequestFatal(CodeOperationFailed,
        FString::Printf(TEXT("快照包含非法数值：%s"), *InvalidReason));
    return;
  }

  DriscaApi::FPendingExchange Exchange = MoveTemp(PendingExchange);
  PendingExchange = DriscaApi::FPendingExchange();

  TArray<TSharedPtr<FJsonValue>> ResultsJson;
  ResultsJson.Reserve(Exchange.Results.Num());
  for (const DriscaApi::FOperationResult &Result : Exchange.Results)
  {
    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetNumberField(TEXT("index"), Result.Index);
    if (Result.Status == DriscaApi::EOperationStatus::Applied)
    {
      Item->SetStringField(TEXT("status"), TEXT("applied"));
      Item->SetNumberField(TEXT("applied_frame_no"),
          static_cast<double>(Result.AppliedFrameNo));
      Item->SetObjectField(TEXT("result"),
          Result.Result.IsValid() ? Result.Result : MakeShared<FJsonObject>());
    }
    else
    {
      Item->SetStringField(TEXT("status"), TEXT("skipped"));
      if (!Result.ErrorCode.IsEmpty())
      {
        Item->SetObjectField(TEXT("error"), DriscaApi::MakeError(
            Result.ErrorCode, Result.ErrorMessage));
      }
    }
    ResultsJson.Add(MakeShared<FJsonValueObject>(Item));
  }

  TArray<TSharedPtr<FJsonValue>> EventsJson = TakeEventsJson();
  bTakeoverThisFrame = false;

  TArray<TSharedPtr<FJsonValue>> TrafficLightJson;
  TArray<TSharedPtr<FJsonValue>> TrafficControllerJson;
  if (CurrentWorld.IsValid() && TrafficLights != nullptr)
  {
    TrafficLights->BuildRuntime(
        *CurrentWorld.Get(), TrafficLightJson, TrafficControllerJson);
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetNumberField(TEXT("frame_no"), static_cast<double>(Snapshot.FrameNo));
  Result->SetArrayField(TEXT("results"), ResultsJson);
  Result->SetArrayField(TEXT("events"), EventsJson);
  const UDrivingViewSubsystem *SelectionView = GetViewSubsystem();
  const ADrivingViewPawn *SelectionPawn = SelectionView ? SelectionView->GetActiveViewPawn() : nullptr;
  ACarlaWheeledVehicle *SelectedVehicle = SelectionPawn ? SelectionPawn->GetSelectedVehicle() : nullptr;
  const FCarlaActor *SelectedActor = SelectedVehicle && GetEpisode() ? GetEpisode()->FindCarlaActor(SelectedVehicle) : nullptr;
  if (SelectedActor) Result->SetNumberField(TEXT("selected_actor_id"), SelectedActor->GetActorId());
  else Result->SetField(TEXT("selected_actor_id"), MakeShared<FJsonValueNull>());
  AActor *SelectedSignal = SelectionPawn ? SelectionPawn->GetSelectedSignal() : nullptr;
  const FCarlaActor *SignalActor = SelectedSignal && GetEpisode() ? GetEpisode()->FindCarlaActor(SelectedSignal) : nullptr;
  if (SignalActor) Result->SetNumberField(TEXT("selected_signal_actor_id"), SignalActor->GetActorId());
  else Result->SetField(TEXT("selected_signal_actor_id"), MakeShared<FJsonValueNull>());
  Result->SetArrayField(TEXT("traffic_lights"), TrafficLightJson);
  Result->SetArrayField(TEXT("traffic_controllers"), TrafficControllerJson);
  Result->SetArrayField(TEXT("control_state"), BuildControlStateJson());
  Result->SetBoolField(TEXT("snapshot"), true);
  SendResult(Exchange.ConnectionId, Exchange.RequestId, Result);

  const TArray<uint8> Bytes = EncodeSnapshot(Snapshot);
  if (Server != nullptr)
  {
    Server->SendBinary(Exchange.ConnectionId, Bytes);
  }
  UE_LOG(LogCarla, Verbose, TEXT("DriscaApi exchange id=%d phase=%s accepted_frame=%llu sampled_frame=%llu wait_ms=%.3f response_cpu_ms=%.3f binary_bytes=%d"),
      Exchange.RequestId, Exchange.bBeforePhysics ? TEXT("pre") : TEXT("post"),
      Exchange.AppliedFrameNo, Snapshot.FrameNo,
      (BuildStart - Exchange.AcceptedTimeSeconds) * 1000.0,
      (FPlatformTime::Seconds() - BuildStart) * 1000.0, Bytes.Num());

  if (DriscaApi::FConnectionState *Connection = Connections.Find(Exchange.ConnectionId))
  {
    Connection->bInFlight = false;
  }
}

void UDriscaApiSubsystem::SendJson(
    int64 ConnectionId, const TSharedPtr<FJsonObject> &Message)
{
  FString Text;
  if (!SerializeJson(Message, Text))
  {
    UE_LOG(LogCarla, Error, TEXT("DriscaApi: cannot serialize response"));
    return;
  }
  if (Server != nullptr)
  {
    Server->SendText(ConnectionId, Text);
  }
}

void UDriscaApiSubsystem::SendResult(
    int64 ConnectionId, int32 RequestId, const TSharedPtr<FJsonObject> &Result)
{
  TSharedPtr<FJsonObject> Response = MakeShared<FJsonObject>();
  Response->SetNumberField(TEXT("id"), RequestId);
  Response->SetBoolField(TEXT("ok"), true);
  Response->SetObjectField(TEXT("result"),
      Result.IsValid() ? Result : MakeShared<FJsonObject>());
  SendJson(ConnectionId, Response);
}

void UDriscaApiSubsystem::SendError(
    int64 ConnectionId,
    int32 RequestId,
    const FString &Code,
    const FString &Message,
    const TSharedPtr<FJsonObject> &Extra)
{
  TSharedPtr<FJsonObject> Error = DriscaApi::MakeError(Code, Message);
  if (Extra.IsValid())
  {
    for (const TPair<FString, TSharedPtr<FJsonValue>> &Pair : Extra->Values)
    {
      Error->SetField(Pair.Key, Pair.Value);
    }
  }

  TSharedPtr<FJsonObject> Response = MakeShared<FJsonObject>();
  Response->SetNumberField(TEXT("id"), RequestId);
  Response->SetBoolField(TEXT("ok"), false);
  Response->SetObjectField(TEXT("error"), Error);
  SendJson(ConnectionId, Response);
}

void UDriscaApiSubsystem::RequestFatal(const FString &Code, const FString &Message)
{
  if (bFatalPending)
  {
    return;
  }
  bFatalPending = true;
  FatalCode = Code;
  FatalMessage = Message;
  UE_LOG(LogCarla, Error,
      TEXT("DriscaApi: fatal experiment error [%s] %s"), *Code, *Message);
}

void UDriscaApiSubsystem::HandleFatal()
{
  bFatalPending = false;
  const FString Code = FatalCode;
  const FString Message = FatalMessage;
  FatalCode.Empty();
  FatalMessage.Empty();

  if (PendingExchange.bValid)
  {
    SendError(PendingExchange.ConnectionId, PendingExchange.RequestId, Code, Message);
    PendingExchange = DriscaApi::FPendingExchange();
  }

  const int64 ControlConnection = Session.ControlConnection;
  AbortSession();

  if (ControlConnection >= 0 && Server != nullptr)
  {
    Server->CloseAfterFlush(ControlConnection, 1011, Message);
  }
}

// =============================================================================
// -- 操作分派 -----------------------------------------------------------------
// =============================================================================

bool UDriscaApiSubsystem::ExecuteOperation(
    int64 ConnectionId,
    const FString &SessionId,
    int32 RequestId,
    int32 OperationIndex,
    const FString &Method,
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult,
    bool &bOutFormatError)
{
  OutResult.Index = OperationIndex;
  OutResult.Status = DriscaApi::EOperationStatus::Failed;

  bool bHandled = false;
  bool bSuccess = false;

  if (Method == TEXT("server.status"))
  {
    bSuccess = ExecuteServerStatus(Params, OutResult);
    bHandled = true;
  }
  else if (Method == TEXT("scene.catalog"))
  {
    bSuccess = ExecuteSceneCatalog(Params, OutResult);
    bHandled = true;
  }
  else if (Method == TEXT("scene.get_weather") || Method == TEXT("scene.set_weather"))
  {
    OutResult.ErrorCode = CodeUnsupported;
    OutResult.ErrorMessage = TEXT("天气接口已替换为 environment.get/apply/update");
    bHandled = true;
  }
  else if (Method == TEXT("scene.set_world"))
  {
    bSuccess = ExecuteSceneSetWorld(Params, OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method == TEXT("scene.clear_actors"))
  {
    bSuccess = ExecuteClearActors(OutResult);
    bHandled = true;
  }
  else if (Method.StartsWith(TEXT("environment.")))
  {
    bSuccess = ExecuteEnvironment(Method, ConnectionId, RequestId, OperationIndex, Params, OutResult);
    bHandled = true;
  }
  else if (Method == TEXT("debug.highlight_path"))
  {
    bHandled = true;
    double Id = 0, Duration = 0.4;
    const TArray<TSharedPtr<FJsonValue>> *Points = nullptr;
    bool bValid = Params->TryGetNumberField(TEXT("actor_id"), Id) && FMath::IsFinite(Id) &&
        Id > 0 && Id <= MAX_uint32 && FMath::FloorToDouble(Id) == Id &&
        (!Params->HasField(TEXT("duration_s")) || Params->TryGetNumberField(TEXT("duration_s"), Duration)) &&
        FMath::IsFinite(Duration) && Duration > 0 &&
        Params->TryGetArrayField(TEXT("points"), Points) && Points && Points->Num() >= 2;
    FActorHighlight Highlight;
    if (bValid)
      for (const auto &Point : *Points)
      {
        if (!Point.IsValid() || Point->Type != EJson::Array || Point->AsArray().Num() != 3)
        { bValid = false; break; }
        const auto &Coordinates = Point->AsArray();
        for (const auto &Coordinate : Coordinates)
          if (!Coordinate.IsValid() || Coordinate->Type != EJson::Number ||
              !FMath::IsFinite(Coordinate->AsNumber()) || !FMath::IsFinite(Coordinate->AsNumber() * 100.0))
          { bValid = false; break; }
        if (!bValid) break;
        Highlight.Points.Add(FVector(Coordinates[0]->AsNumber(), Coordinates[1]->AsNumber(), Coordinates[2]->AsNumber()) * 100.0);
      }
    if (!bValid)
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("轨迹需要至少两个有限数值三维点及有效车辆编号、正时长"); }
    else
    {
      FCarlaActor *Actor = GetEpisode() ? GetEpisode()->FindCarlaActor(static_cast<uint32>(Id)) : nullptr;
      if (!Actor || !Cast<ACarlaWheeledVehicle>(Actor->GetActor()))
      { OutResult.ErrorCode = CodeNotFound; OutResult.ErrorMessage = TEXT("目标车辆不存在"); }
      else
      {
        Highlight.Actor = Actor->GetActor();
        Highlight.EndTime = CurrentWorld->GetTimeSeconds() + Duration;
        // 同一车辆的新预测替换旧轨迹，避免高频更新在持续时间内累积多份折线。
        ActorHighlights.RemoveAll([&Highlight](const FActorHighlight &Existing)
        { return Existing.Actor == Highlight.Actor && !Existing.Points.IsEmpty(); });
        ActorHighlights.Add(MoveTemp(Highlight));
        OutResult.Result = MakeShared<FJsonObject>();
        OutResult.Result->SetNumberField(TEXT("actor_id"), Id);
        OutResult.Result->SetNumberField(TEXT("duration_s"), Duration);
        bSuccess = true;
      }
    }
  }
  else if (Method == TEXT("debug.highlight_actor"))
  {
    bHandled = true;
    double Id = 0, Duration = 5;
    FString Label;
    const bool bValid = Params->TryGetNumberField(TEXT("actor_id"), Id) && FMath::IsFinite(Id) &&
        Id > 0 && Id <= MAX_uint32 && FMath::FloorToDouble(Id) == Id &&
        (!Params->HasField(TEXT("duration_s")) || Params->TryGetNumberField(TEXT("duration_s"), Duration)) &&
        FMath::IsFinite(Duration) && Duration > 0 &&
        (!Params->HasField(TEXT("label")) || Params->TryGetStringField(TEXT("label"), Label));
    if (!bValid)
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("高亮参数无效"); }
    else
    {
      FCarlaActor *Actor = GetEpisode() ? GetEpisode()->FindCarlaActor(static_cast<uint32>(Id)) : nullptr;
      if (!Actor || !Cast<ACarlaWheeledVehicle>(Actor->GetActor()))
      { OutResult.ErrorCode = CodeNotFound; OutResult.ErrorMessage = TEXT("目标车辆不存在"); }
      else
      {
        FActorHighlight Highlight;
        Highlight.Actor = Actor->GetActor();
        Highlight.Label = FString::Printf(TEXT("%s [%u]"), *Label, static_cast<uint32>(Id));
        Highlight.EndTime = CurrentWorld->GetTimeSeconds() + Duration;
        ActorHighlights.Add(MoveTemp(Highlight));
        OutResult.Result = MakeShared<FJsonObject>();
        OutResult.Result->SetNumberField(TEXT("actor_id"), Id);
        OutResult.Result->SetNumberField(TEXT("duration_s"), Duration);
        bSuccess = true;
      }
    }
  }
  else if (Method.StartsWith(TEXT("vehicle.")))
  {
    bSuccess = ExecuteVehicle(
        Method, ConnectionId, RequestId, OperationIndex, SessionId, Params,
        OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method.StartsWith(TEXT("driving_view.")))
  {
    bSuccess = ExecuteDrivingView(
        Method, ConnectionId, RequestId, OperationIndex, SessionId, Params,
        OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method.StartsWith(TEXT("traffic_")))
  {
    bSuccess = ExecuteTrafficOperation(
        Method, ConnectionId, RequestId, OperationIndex, Params,
        OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method == TEXT("scene.road_graph") ||
           Method == TEXT("scene.road_junctions") ||
           Method == TEXT("scene.road_signals"))
  {
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("道路目录必须作为独立请求发送，不能放进批次");
    return false;
  }
  else if (Method == TEXT("road.query"))
  {
    bSuccess = ExecuteRoadQuery(Params, OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method.StartsWith(TEXT("recorder.")))
  {
    bSuccess = ExecuteRecorder(Method, Params, OutResult, bOutFormatError);
    bHandled = true;
  }
  else if (Method == TEXT("experiment.stop"))
  {
    bSuccess = ExecuteExperimentStop(
        ConnectionId, SessionId, OutResult, bOutFormatError);
    bHandled = true;
  }

  if (!bHandled)
  {
    OutResult.ErrorCode = CodeUnsupported;
    OutResult.ErrorMessage = FString::Printf(TEXT("未知方法 %s"), *Method);
    return false;
  }

  if (bSuccess)
  {
    if (bBeforePhysics && OutResult.SampledFrameNo != 0)
      OutResult.SampledFrameNo = LastSampleFrameNo;
    if (OutResult.Status != DriscaApi::EOperationStatus::Skipped)
    {
      OutResult.Status = DriscaApi::EOperationStatus::Applied;
      if (OutResult.AppliedFrameNo == 0)
      {
        // 物理前受理的命令作用于本帧，物理后受理的命令作用于下一帧。
        OutResult.AppliedFrameNo = OutResult.SampledFrameNo != 0
            ? OutResult.SampledFrameNo : CurrentFrameNo() + (bBeforePhysics ? 0 : 1);
      }
    }
    return true;
  }

  OutResult.Status = DriscaApi::EOperationStatus::Failed;
  if (OutResult.ErrorCode.IsEmpty())
  {
    OutResult.ErrorCode = CodeOperationFailed;
  }
  return false;
}

bool UDriscaApiSubsystem::ExecuteServerStatus(
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult)
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetStringField(TEXT("server_instance"), ServerInstance);
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetStringField(TEXT("map_name"), GetCurrentMapName());
  Result->SetBoolField(TEXT("experiment_active"), Session.bActive);
  Result->SetStringField(TEXT("session_id"), Session.SessionId);
  Result->SetBoolField(TEXT("driving_view_active"),
      GetViewSubsystem() != nullptr && GetViewSubsystem()->IsActive());
  Result->SetStringField(TEXT("error"), FString());
  OutResult.Result = Result;
  OutResult.SampledFrameNo = CurrentFrameNo();
  return true;
}

bool UDriscaApiSubsystem::ExecuteSceneCatalog(
    const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult)
{
  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("当前没有可用的世界");
    return false;
  }

  TArray<TSharedPtr<FJsonValue>> Maps;
  for (const FString &Map : UCarlaStatics::GetAllMapNames())
  {
    Maps.Add(MakeShared<FJsonValueString>(Map));
  }

  TArray<TSharedPtr<FJsonValue>> Blueprints;
  for (const FActorDefinition &Definition : GetDefinitions(*Episode))
  {
    if (!Definition.Id.StartsWith(TEXT("vehicle.")))
    {
      continue;
    }
    TSharedPtr<FJsonObject> Blueprint = MakeShared<FJsonObject>();
    Blueprint->SetStringField(TEXT("id"), Definition.Id);
    Blueprint->SetStringField(TEXT("tags"), Definition.Tags);
    Blueprints.Add(MakeShared<FJsonValueObject>(Blueprint));
  }

  TArray<TSharedPtr<FJsonValue>> SpawnPoints;
  for (const FTransform &Transform : Episode->GetRecommendedSpawnPoints())
  {
    SpawnPoints.Add(MakeShared<FJsonValueObject>(TransformToJson(Transform)));
  }

  TArray<TSharedPtr<FJsonValue>> Presets;
  for (const FWeatherPreset &Preset : GetWeatherPresets())
  {
    // Default 的旧值是 -1 哨兵；新预设必须是可直接应用的完整状态。
    const auto State = FCString::Strcmp(Preset.Name, TEXT("Default")) == 0
        ? DriscaApi::FEnvironmentGlobalState()
        : DriscaApi::FEnvironmentGlobalState::FromAuthoredWeather(static_cast<FWeatherParameters>(Preset.Value));
    auto Value = State.ToJson();
    Value->SetStringField(TEXT("preset_name"), Preset.Name);
    Presets.Add(MakeShared<FJsonValueObject>(Value));
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetArrayField(TEXT("maps"), Maps);
  Result->SetStringField(TEXT("current_map"), GetCurrentMapName());
  Result->SetArrayField(TEXT("vehicle_blueprints"), Blueprints);
  Result->SetArrayField(TEXT("spawn_points"), SpawnPoints);
  Result->SetArrayField(TEXT("weather_presets"), Presets);
  OutResult.Result = Result;
  OutResult.SampledFrameNo = CurrentFrameNo();
  return true;
}

bool UDriscaApiSubsystem::ExecuteSceneSetWorld(
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

  double SimulationFps = 0.0;
  if (!Params->TryGetNumberField(TEXT("simulation_fps"), SimulationFps) || SimulationFps <= 0.0)
  {
    bOutFormatError = true;
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("simulation_fps 必须是正数");
    return false;
  }

  FEpisodeSettings Settings = Episode->GetSettings();
  Settings.bSynchronousMode = false;
  // 异步可变步长：FixedDeltaSeconds 必须保持未设置。赋 0 会让
  // CarlaEngine 打开 FApp benchmarking 并把固定步长设为 0，世界 delta
  // 退化为固定小值（约 0.0005），仿真时间与墙钟脱节。
  Settings.FixedDeltaSeconds.Reset();
  Settings.bSubstepping = true;
  Settings.MaxSubstepDeltaTime = 1.0 / SimulationFps;
  // Chaos 用 min(帧 delta, MaxSubsteps * MaxSubstepDeltaTime) 截断物理推进。
  // 子步数必须覆盖低帧率下的整帧时间，否则物理时钟慢于仿真时钟。
  // 按最长 0.2 秒世界帧计算：60 Hz 时需要 12 个子步。
  constexpr double MaxFrameDeltaSeconds = 0.2;
  Settings.MaxSubsteps = FMath::Max(
      1, FMath::CeilToInt(SimulationFps * MaxFrameDeltaSeconds));
  Episode->ApplySettings(Settings);

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("simulation_fps"), 1.0 / Settings.MaxSubstepDeltaTime);
  Result->SetBoolField(TEXT("synchronous_mode"), false);
  Result->SetBoolField(TEXT("substepping"), true);
  Result->SetNumberField(TEXT("max_substep_delta_time"), Settings.MaxSubstepDeltaTime);
  Result->SetNumberField(TEXT("max_substeps"), Settings.MaxSubsteps);
  OutResult.Result = Result;
  return true;
}

bool UDriscaApiSubsystem::ExecuteClearActors(DriscaApi::FOperationResult &OutResult)
{
  if (Session.bActive)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("实验进行中不能清理场景");
    return false;
  }

  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("当前没有可用的世界");
    return false;
  }

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
  VehicleTracks.Empty();
  LastLightStates.Empty();

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("destroyed"), ToDestroy.Num());
  OutResult.Result = Result;
  return true;
}

