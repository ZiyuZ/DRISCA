#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/// DRISCA 原生 API 的协议常量与运行时数据结构。
namespace DriscaApi
{
  constexpr int32 ProtocolVersion = 1;
  constexpr int32 DefaultPort = 7910;
  constexpr int32 MaxMessageBytes = 8 * 1024 * 1024;
  constexpr int32 MaxOperationsPerRequest = 256;
  constexpr int32 MaxEventQueue = 4096;
  constexpr int32 SnapshotHeaderBytes = 48;
  constexpr int32 VehicleRecordBytes = 96;
  constexpr int32 ResearchRecordBytes = 128;

  enum class EOperationStatus : uint8
  {
    Applied,
    Failed,
    Skipped
  };

  struct FOperationResult
  {
    int32 Index = 0;
    EOperationStatus Status = EOperationStatus::Skipped;
    uint64 AppliedFrameNo = 0;
    uint64 SampledFrameNo = 0;
    TSharedPtr<FJsonObject> Result;
    FString ErrorCode;
    FString ErrorMessage;
  };

  struct FEvent
  {
    uint64 EventId = 0;
    uint64 WorldId = 0;
    FString SessionId;
    uint64 FrameNo = 0;
    int64 SimulationTimeUs = 0;
    int64 WallTimeUs = 0;
    FString Name;
    FString Source;
    TOptional<int32> RequestId;
    TOptional<int32> OperationIndex;
    TSharedPtr<FJsonObject> Payload;
  };

  struct FVehicleSample
  {
    uint32 ActorId = 0;
    uint32 Flags = 0;
    FVector Location = FVector::ZeroVector;
    FRotator Rotation = FRotator::ZeroRotator;
    FVector Velocity = FVector::ZeroVector;
    FVector AngularVelocity = FVector::ZeroVector;
    FVector Acceleration = FVector::ZeroVector;
    float Throttle = 0.0f;
    float Steer = 0.0f;
    float Brake = 0.0f;
    int32 Gear = 0;
    float SpeedLimitMps = 0.0f;
    int32 RoadId = 0;
    int32 LaneId = 0;
  };

  struct FResearchSample
  {
    uint32 ActorId = 0;
    uint32 ValidityFlags = 0;
    float InputThrottle = 0.0f;
    float InputSteer = 0.0f;
    float InputBrake = 0.0f;
    uint32 InputFlags = 0;
    int32 InputGear = 0;
    uint64 ImuFrameNo = 0;
    int64 ImuSimulationTimeUs = 0;
    uint64 GnssFrameNo = 0;
    int64 GnssSimulationTimeUs = 0;
    FVector Accelerometer = FVector::ZeroVector;
    FVector Gyroscope = FVector::ZeroVector;
    float Compass = 0.0f;
    float Longitude = 0.0f;
    float Latitude = 0.0f;
    float Altitude = 0.0f;
    FVector RoadDirection = FVector::ZeroVector;
    float LaneWidth = 0.0f;
    float LaneOffset = 0.0f;
    uint32 LaneType = 0;
    float CollisionIntensity = 0.0f;
  };

  struct FSnapshot
  {
    uint32 RequestId = 0;
    uint64 WorldId = 0;
    uint64 FrameNo = 0;
    int64 SimulationTimeUs = 0;
    int64 WallTimeUs = 0;
    float DeltaSeconds = 0.0f;
    TArray<FVehicleSample> Vehicles;
    bool bHasResearch = false;
    FResearchSample Research;
  };

  struct FConnectionState
  {
    bool bHello = false;
    FString Client;
    bool bControl = false;
    FString SessionId;
    bool bInFlight = false;
    TArray<uint32> CreatedActors;
  };

  struct FSessionState
  {
    bool bActive = false;
    FString SessionId;
    int64 ControlConnection = -1;
    uint32 EgoActorId = 0;
    TArray<uint32> OwnedActors;

    bool bImuValid = false;
    uint64 ImuFrameNo = 0;
    int64 ImuSimulationTimeUs = 0;
    FVector Accelerometer = FVector::ZeroVector;
    FVector Gyroscope = FVector::ZeroVector;
    float Compass = 0.0f;

    bool bGnssValid = false;
    uint64 GnssFrameNo = 0;
    int64 GnssSimulationTimeUs = 0;
    float Longitude = 0.0f;
    float Latitude = 0.0f;
    float Altitude = 0.0f;

    float CollisionIntensity = 0.0f;
    bool bHasPreviousCorners = false;
    FVector PreviousCorners[4];

    bool bResearchReady = false;
  };

  struct FVehicleTrack
  {
    FString Source = TEXT("external_unassigned");
    FString Controller = TEXT("unassigned");
    uint64 ControlRevision = 1;
    bool bControlled = false;
    FVector LastVelocity = FVector::ZeroVector;
    bool bHasLastVelocity = false;
    FVector Acceleration = FVector::ZeroVector;
  };

  struct FPendingExchange
  {
    bool bValid = false;
    int64 ConnectionId = -1;
    int32 RequestId = 0;
    FString SessionId;
    TArray<FOperationResult> Results;
    uint64 AppliedFrameNo = 0;
    uint64 ScheduledPostTick = 0;
    bool bBeforePhysics = false;
    double AcceptedTimeSeconds = 0;
  };

  struct FPendingMapLoad
  {
    bool bValid = false;
    bool bWorldSwitched = false;
    int64 ConnectionId = -1;
    int32 RequestId = 0;
    FString MapName;
    uint64 NewWorldId = 0;
  };

  inline int64 ToMicroseconds(double Seconds)
  {
    return static_cast<int64>(FMath::RoundToDouble(Seconds * 1.0e6));
  }

  inline int64 WallTimeMicroseconds()
  {
    const FDateTime Now = FDateTime::UtcNow();
    const FTimespan SinceEpoch = Now - FDateTime(1970, 1, 1);
    return SinceEpoch.GetTicks() / ETimespan::TicksPerMicrosecond;
  }

  inline TSharedPtr<FJsonObject> MakeError(const FString &Code, const FString &Message)
  {
    TSharedPtr<FJsonObject> Error = MakeShared<FJsonObject>();
    Error->SetStringField(TEXT("code"), Code);
    Error->SetStringField(TEXT("message"), Message);
    return Error;
  }
}
