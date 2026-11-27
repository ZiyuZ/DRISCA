#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Dom/JsonObject.h"
#include "DriscaApiTypes.h"
#include "DriscaApiEnvironment.h"
#include "DriscaApiSubsystem.generated.h"

class FDriscaApiServer;
class FDriscaRoadData;
class FDriscaTrafficLights;
class UCarlaEpisode;
class ACarlaGameModeBase;
class ACarlaRecorder;
class ADrivingViewPawn;
class AInertialMeasurementUnit;
class AGnssSensor;
class ACarlaWheeledVehicle;
class AWeather;
struct FWeatherParameters;

/// DRISCA 原生 API 服务端。
///
/// WebSocket 服务挂在本子系统上，随 GameInstance 存活，跨地图切换保留连接。
/// 网络回调与游戏对象访问都在游戏线程：每帧在 PostActorTick 推进网络，
/// 随后汇总帧快照。
UCLASS()
class CARLA_API UDriscaApiSubsystem : public UGameInstanceSubsystem
{
  GENERATED_BODY()

public:

  virtual bool ShouldCreateSubsystem(UObject *Outer) const override;
  virtual void Initialize(FSubsystemCollectionBase &Collection) override;
  virtual void Deinitialize() override;
  virtual ~UDriscaApiSubsystem();

  /// GameMode 初始化早于首个 PostActorTick，因此显式传入世界。
  void InitializeEnvironment(UWorld *World, const FWeatherParameters &Defaults);


private:

  // -- 世界与连接 ------------------------------------------------------------

  void OnWorldPostActorTick(UWorld *World, ELevelTick TickType, float DeltaSeconds);
  void OnWorldPreActorTick(UWorld *World, ELevelTick TickType, float DeltaSeconds);
  void HandleWorldSwitch(UWorld *World);
  void ResetWorldState();
  void AbortSession();
  void StopOwnedRecorder();

  void OnClientMessage(int64 ConnectionId, const FString &Message);
  void OnClientClosed(int64 ConnectionId);
  void HandleRequest(
      int64 ConnectionId,
      const TSharedPtr<FJsonObject> &Request,
      DriscaApi::FConnectionState &Connection);
  void HandleHello(
      int64 ConnectionId,
      int32 RequestId,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FConnectionState &Connection);
  void HandleBatch(
      int64 ConnectionId,
      int32 RequestId,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FConnectionState &Connection,
      bool bExchange);
  void CompletePendingExchange();

  bool HandleRoadGraph(
      int64 ConnectionId,
      int32 RequestId,
      const FString &Method,
      const TSharedPtr<FJsonObject> &Params);

  void SendJson(int64 ConnectionId, const TSharedPtr<FJsonObject> &Message);
  void SendResult(int64 ConnectionId, int32 RequestId, const TSharedPtr<FJsonObject> &Result);
  void SendError(
      int64 ConnectionId,
      int32 RequestId,
      const FString &Code,
      const FString &Message,
      const TSharedPtr<FJsonObject> &Extra = nullptr);

  /// 记录必须终止当前实验的错误；下一个 PostActorTick 统一收尾。
  void RequestFatal(const FString &Code, const FString &Message);
  void HandleFatal();

  // -- 操作 ------------------------------------------------------------------

  bool ExecuteOperation(
      int64 ConnectionId,
      const FString &SessionId,
      int32 RequestId,
      int32 OperationIndex,
      const FString &Method,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);

  bool ExecuteServerStatus(
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult);
  bool ExecuteSceneCatalog(
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult);
  bool ExecuteSceneSetWorld(
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteClearActors(
      DriscaApi::FOperationResult &OutResult);
  bool ExecuteVehicle(
      const FString &Method,
      int64 ConnectionId,
      int32 RequestId,
      int32 OperationIndex,
      const FString &SessionId,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteDrivingView(
      const FString &Method,
      int64 ConnectionId,
      int32 RequestId,
      int32 OperationIndex,
      const FString &SessionId,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteRoadQuery(
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteRecorder(
      const FString &Method,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteExperimentStop(
      int64 ConnectionId,
      const FString &SessionId,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);
  bool ExecuteTrafficOperation(
      const FString &Method,
      int64 ConnectionId,
      int32 RequestId,
      int32 OperationIndex,
      const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult,
      bool &bOutFormatError);

  // -- 研究采集 --------------------------------------------------------------

  void StopResearch();
  bool SpawnResearchSensors(FString &OutError);
  void UpdateResearch();
  void UpdateLaneInvasion();
  void AttachCollisionHook();
  void DetachCollisionHook();
  void OnDrivingAction(ADrivingViewPawn *Pawn, const FString &Action);

  UFUNCTION()
  void OnEgoHit(
      AActor *SelfActor,
      AActor *OtherActor,
      FVector NormalImpulse,
      const FHitResult &Hit);

  // -- 快照与事件 ------------------------------------------------------------

  void SampleFrame(float DeltaSeconds);
  DriscaApi::FSnapshot BuildSnapshot(uint32 RequestId) const;
  TArray<uint8> EncodeSnapshot(const DriscaApi::FSnapshot &Snapshot) const;
  bool ValidateSnapshot(
      const DriscaApi::FSnapshot &Snapshot, FString &OutReason) const;
  void EmitEvent(
      const FString &Name,
      const FString &Source,
      const TSharedPtr<FJsonObject> &Payload,
      TOptional<int32> RequestId = TOptional<int32>(),
      TOptional<int32> OperationIndex = TOptional<int32>());
  TSharedPtr<FJsonObject> EventToJson(const DriscaApi::FEvent &Event) const;
  TArray<TSharedPtr<FJsonValue>> TakeEventsJson();

  // -- 辅助 ------------------------------------------------------------------

  UCarlaEpisode *GetEpisode() const;
  ACarlaGameModeBase *GetGameMode() const;
  class UDrivingViewSubsystem *GetViewSubsystem() const;
  FString GetCurrentMapName() const;
  int64 SimulationTimeUs() const;
  uint64 CurrentFrameNo() const;
  FString GetConnectionSource(int64 ConnectionId) const;
  bool ApplyScreenMessagePolicy(const TSharedPtr<FJsonObject> &Params, FString &OutError);
  void PositionInitialFreeCamera(UCarlaEpisode *Episode);
  TArray<TSharedPtr<FJsonValue>> BuildControlStateJson() const;

  bool RequireWorld(
      const TSharedPtr<FJsonObject> &Params,
      FString &OutCode,
      FString &OutMessage) const;
  bool RequireSession(
      const FString &SessionId,
      FString &OutCode,
      FString &OutMessage) const;

  bool ExecuteEnvironment(const FString &Method, int64 ConnectionId, int32 RequestId,
      int32 OperationIndex, const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult);
  void TickEnvironment();
  bool ExecuteGlobalEnvironment(const FString &Method, int64 ConnectionId, int32 RequestId,
      int32 OperationIndex, const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult);
  bool RenderGlobalEnvironment(FString &Error);
  void AdvanceGlobalEnvironment(double Now);
  TSharedPtr<FJsonObject> GlobalEnvironmentJson(double Now) const;
  TWeakObjectPtr<UWorld> EnvironmentWorld;
  DriscaApi::FEnvironmentGlobalState GlobalCurrent;
  DriscaApi::FEnvironmentGlobalState GlobalStart;
  DriscaApi::FEnvironmentGlobalState GlobalTarget;
  double GlobalStartTime = 0.0;
  double GlobalDuration = 0.0;
  TOptional<int32> GlobalRequestId;
  TOptional<int32> GlobalOperationIndex;
  FString GlobalSource;
  FString GlobalAction;
  FString EnvironmentError;

  void ClearEnvironment(int64 ConnectionId, bool bSession);
  TMap<uint32, DriscaApi::FEnvironmentRegion> EnvironmentRegions;
  uint32 NextEnvironmentRegionId = 1;

  FDriscaApiServer *Server = nullptr;
  FDriscaRoadData *RoadData = nullptr;
  FDriscaTrafficLights *TrafficLights = nullptr;

  FString ServerInstance;
  uint64 WorldId = 1;
  TWeakObjectPtr<UWorld> CurrentWorld;
  bool bWorldReady = false;
  bool bWorldAttached = false;

  TMap<int64, DriscaApi::FConnectionState> Connections;
  DriscaApi::FSessionState Session;
  DriscaApi::FPendingExchange PendingExchange;
  DriscaApi::FPendingMapLoad PendingMapLoad;

  TMap<uint32, DriscaApi::FVehicleTrack> VehicleTracks;
  struct FActorHighlight
  {
    TWeakObjectPtr<AActor> Actor;
    FString Label;
    TArray<FVector> Points;
    double EndTime = 0;
  };
  TArray<FActorHighlight> ActorHighlights;

  TArray<DriscaApi::FEvent> EventQueue;
  uint64 NextEventId = 1;

  bool bDynamicSpeedLimit = false;
  float DefaultSpeedLimitMps = 33.33f;

  FString RecorderPath;
  TWeakObjectPtr<ACarlaRecorder> OwnedRecorder;
  TMap<uint32, uint32> LastLightStates;
  FDelegateHandle ActionDelegateHandle;
  bool bTakeoverThisFrame = false;
  int32 ResearchTickCount = 0;

  TWeakObjectPtr<AInertialMeasurementUnit> Imu;
  TWeakObjectPtr<AGnssSensor> Gnss;
  TWeakObjectPtr<ACarlaWheeledVehicle> EgoVehicle;

  uint64 LastSampleFrameNo = 0;
  int64 LastSampleSimulationUs = 0;
  float SampleDeltaSeconds = 0.0f;
  bool bHasSample = false;
  uint64 PostTickSerial = 0;
  bool bBeforePhysics = false;
  bool bReplayViewOwned = false;
  uint32 ReplayFollowActorId = 0;
  bool UpdateReplayView(const TSharedPtr<FJsonObject> &Params,
      DriscaApi::FOperationResult &OutResult);
  void StopReplayView();
  void TickReplayView();

  bool bFatalPending = false;
  FString FatalCode;
  FString FatalMessage;
};

