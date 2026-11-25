#include "DriscaApiSubsystem.h"
#include "DriscaApiInternals.h"

#include "DrivingViewPawn.h"
#include "DrivingViewSubsystem.h"

#include "Carla.h"
#include "Carla/Actor/ActorInfo.h"
#include "Carla/Actor/ActorRegistry.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaGameModeBase.h"
#include "Carla/Game/CarlaStatics.h"
#include "Carla/Sensor/GnssSensor.h"
#include "Carla/Sensor/InertialMeasurementUnit.h"
#include "Carla/Util/BoundingBox.h"
#include "Carla/Vehicle/CarlaWheeledVehicle.h"
#include "Carla/Vehicle/VehicleControl.h"
#include "Carla/Vehicle/VehicleInputPriority.h"
#include "Carla/Vehicle/WheeledVehicleAIController.h"

#include <util/ue-header-guard-begin.h>
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include <util/ue-header-guard-end.h>

#include <util/disable-ue4-macros.h>
#include "carla/geom/Location.h"
#include "carla/road/Lane.h"
#include "carla/road/Map.h"
#include "carla/road/element/LaneMarking.h"
#include "carla/road/element/Waypoint.h"
#include <util/enable-ue4-macros.h>

namespace
{
  static_assert(PLATFORM_LITTLE_ENDIAN, "DRISCA snapshot layout requires little endian");

  void PutU32(TArray<uint8> &Bytes, uint32 Value)
  {
    const int32 Offset = Bytes.Num();
    Bytes.AddUninitialized(4);
    FMemory::Memcpy(Bytes.GetData() + Offset, &Value, 4);
  }

  void PutI32(TArray<uint8> &Bytes, int32 Value)
  {
    const int32 Offset = Bytes.Num();
    Bytes.AddUninitialized(4);
    FMemory::Memcpy(Bytes.GetData() + Offset, &Value, 4);
  }

  void PutU64(TArray<uint8> &Bytes, uint64 Value)
  {
    const int32 Offset = Bytes.Num();
    Bytes.AddUninitialized(8);
    FMemory::Memcpy(Bytes.GetData() + Offset, &Value, 8);
  }

  void PutI64(TArray<uint8> &Bytes, int64 Value)
  {
    const int32 Offset = Bytes.Num();
    Bytes.AddUninitialized(8);
    FMemory::Memcpy(Bytes.GetData() + Offset, &Value, 8);
  }

  void PutF32(TArray<uint8> &Bytes, float Value)
  {
    const int32 Offset = Bytes.Num();
    Bytes.AddUninitialized(4);
    FMemory::Memcpy(Bytes.GetData() + Offset, &Value, 4);
  }

  struct FRoadInfo
  {
    bool bValid = false;
    int32 RoadId = 0;
    int32 LaneId = 0;
    float LaneWidth = 0.0f;
    uint32 LaneType = 0;
    float LaneOffset = 0.0f;
    FVector Direction = FVector::ZeroVector;
  };

  FRoadInfo QueryRoad(
      const carla::road::Map &Map,
      const FVector &LocationMeters)
  {
    FRoadInfo Info;
    const carla::geom::Location Location(
        LocationMeters.X, LocationMeters.Y, LocationMeters.Z);
    const std::optional<carla::road::element::Waypoint> Waypoint =
        Map.GetWaypoint(Location);
    if (!Waypoint.has_value())
    {
      return Info;
    }

    const carla::geom::Transform Transform = Map.ComputeTransform(*Waypoint);
    const carla::geom::Vector3D Forward = Transform.rotation.GetForwardVector();
    Info.bValid = true;
    Info.RoadId = static_cast<int32>(Waypoint->road_id);
    Info.LaneId = static_cast<int32>(Waypoint->lane_id);
    Info.LaneWidth = static_cast<float>(Map.GetLaneWidth(*Waypoint));
    Info.LaneType = static_cast<uint32>(Map.GetLaneType(*Waypoint));
    Info.Direction = FVector(Forward.x, Forward.y, Forward.z);
    Info.LaneOffset = static_cast<float>(
        Forward.x * (Location.y - Transform.location.y) -
        Forward.y * (Location.x - Transform.location.x));
    return Info;
  }

  uint32 SourceCode(const FString &Source)
  {
    if (Source == TEXT("manual"))
    {
      return 0u;
    }
    if (Source == TEXT("autopilot"))
    {
      return 1u;
    }
    if (Source == TEXT("external"))
    {
      return 2u;
    }
    return 3u;
  }

  FString LaneMarkingToString(carla::road::element::LaneMarking::Type Type)
  {
    const TCHAR *Name = TEXT("Other");
    switch (Type)
    {
      case carla::road::element::LaneMarking::Type::Broken:
        Name = TEXT("Broken");
        break;
      case carla::road::element::LaneMarking::Type::Solid:
        Name = TEXT("Solid");
        break;
      case carla::road::element::LaneMarking::Type::SolidSolid:
        Name = TEXT("SolidSolid");
        break;
      case carla::road::element::LaneMarking::Type::SolidBroken:
        Name = TEXT("SolidBroken");
        break;
      case carla::road::element::LaneMarking::Type::BrokenSolid:
        Name = TEXT("BrokenSolid");
        break;
      case carla::road::element::LaneMarking::Type::BrokenBroken:
        Name = TEXT("BrokenBroken");
        break;
      case carla::road::element::LaneMarking::Type::BottsDots:
        Name = TEXT("BottsDots");
        break;
      case carla::road::element::LaneMarking::Type::Grass:
        Name = TEXT("Grass");
        break;
      case carla::road::element::LaneMarking::Type::Curb:
        Name = TEXT("Curb");
        break;
      case carla::road::element::LaneMarking::Type::None:
        Name = TEXT("None");
        break;
      default:
        break;
    }
    return FString::Printf(TEXT("LaneMarkingType.%s"), Name);
  }
}

using namespace DriscaApiInternal;

void UDriscaApiSubsystem::SampleFrame(float DeltaSeconds)
{
  SampleDeltaSeconds = DeltaSeconds;
  LastSampleFrameNo = CurrentFrameNo();
  LastSampleSimulationUs = SimulationTimeUs();
  bHasSample = true;
  ++ResearchTickCount;

  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    return;
  }

  TSet<uint32> ExistingVehicles;
  for (const TPair<uint32, TSharedPtr<FCarlaActor>> &Pair : Episode->GetActorRegistry())
  {
    FCarlaActor *CarlaActor = Pair.Value.Get();
    if (CarlaActor == nullptr ||
        CarlaActor->GetActorType() != FCarlaActor::ActorType::Vehicle)
    {
      continue;
    }
    AActor *Actor = CarlaActor->GetActor();
    if (!IsValid(Actor))
    {
      continue;
    }

    ExistingVehicles.Add(Pair.Key);
    DriscaApi::FVehicleTrack &Track = VehicleTracks.FindOrAdd(Pair.Key);
    const FVector Velocity = Actor->GetVelocity() * 0.01;
    if (Track.bHasLastVelocity && DeltaSeconds > 1.0e-4f)
    {
      Track.Acceleration = (Velocity - Track.LastVelocity) / DeltaSeconds;
    }
    Track.LastVelocity = Velocity;
    Track.bHasLastVelocity = true;
  }

  TArray<uint32> RemovedTracks;
  for (const TPair<uint32, DriscaApi::FVehicleTrack> &Pair : VehicleTracks)
  {
    if (!ExistingVehicles.Contains(Pair.Key))
    {
      RemovedTracks.Add(Pair.Key);
    }
  }
  for (uint32 ActorId : RemovedTracks)
  {
    VehicleTracks.Remove(ActorId);
  }

  UpdateResearch();
  UpdateLaneInvasion();
}

DriscaApi::FSnapshot UDriscaApiSubsystem::BuildSnapshot(uint32 RequestId) const
{
  DriscaApi::FSnapshot Snapshot;
  Snapshot.Vehicles.Reserve(VehicleTracks.Num());
  Snapshot.RequestId = RequestId;
  Snapshot.WorldId = WorldId;
  Snapshot.FrameNo = LastSampleFrameNo != 0 ? LastSampleFrameNo : CurrentFrameNo();
  Snapshot.SimulationTimeUs =
      LastSampleSimulationUs != 0 ? LastSampleSimulationUs : SimulationTimeUs();
  Snapshot.WallTimeUs = DriscaApi::WallTimeMicroseconds();
  Snapshot.DeltaSeconds = SampleDeltaSeconds;

  UCarlaEpisode *Episode = GetEpisode();
  const ACarlaGameModeBase *GameMode = GetGameMode();
  const carla::road::Map *Map =
      GameMode != nullptr && GameMode->GetMap().has_value()
          ? &GameMode->GetMap().value() : nullptr;

  if (Episode != nullptr)
  {
    for (const TPair<uint32, TSharedPtr<FCarlaActor>> &Pair : Episode->GetActorRegistry())
    {
      FCarlaActor *CarlaActor = Pair.Value.Get();
      if (CarlaActor == nullptr ||
          CarlaActor->GetActorType() != FCarlaActor::ActorType::Vehicle ||
          !CarlaActor->IsAlive())
      {
        continue;
      }

      ACarlaWheeledVehicle *Vehicle =
          Cast<ACarlaWheeledVehicle>(CarlaActor->GetActor());
      if (Vehicle == nullptr)
      {
        continue;
      }

      DriscaApi::FVehicleSample Sample;
      Sample.ActorId = Pair.Key;

      const FVector Location = Vehicle->GetActorLocation() * 0.01;
      Sample.Location = Location;
      Sample.Rotation = Vehicle->GetActorRotation();
      Sample.Velocity = Vehicle->GetVelocity() * 0.01;
      Sample.AngularVelocity =
          CarlaGetActorAngularVelocityInRadians(*Vehicle) *
          (180.0f / PI);

      const DriscaApi::FVehicleTrack *Track = VehicleTracks.Find(Pair.Key);
      Sample.Acceleration = Track != nullptr ? Track->Acceleration : FVector::ZeroVector;

      const FVehicleControl Control = Vehicle->GetVehicleControl();
      Sample.Throttle = Control.Throttle;
      Sample.Steer = Control.Steer;
      Sample.Brake = Control.Brake;
      Sample.Gear = Control.Gear;

      if (const AWheeledVehicleAIController *Controller =
              Cast<AWheeledVehicleAIController>(Vehicle->GetController()))
      {
        Sample.SpeedLimitMps = Controller->GetSpeedLimit() / 3.6f;
      }

      if (Map != nullptr)
      {
        const FRoadInfo Road = QueryRoad(*Map, Location);
        Sample.Flags |= Road.bValid ? (1u << 4) : 0u;
        if (Road.bValid)
        {
          Sample.RoadId = Road.RoadId;
          Sample.LaneId = Road.LaneId;
        }
      }

      uint32 Flags = 0u;
      if (Control.bReverse)
      {
        Flags |= 1u << 0;
      }
      if (Control.bHandBrake)
      {
        Flags |= 1u << 1;
      }
      if (Control.bManualGearShift)
      {
        Flags |= 1u << 2;
      }
      if (CarlaActor->IsDormant())
      {
        Flags |= 1u << 3;
      }
      Flags |= (Sample.Flags & (1u << 4));
      const FString Source = Track != nullptr ? Track->Source : TEXT("external_unassigned");
      Flags |= (SourceCode(Source) & 0x3u) << 8;
      Sample.Flags = Flags;

      Snapshot.Vehicles.Add(Sample);
    }
  }

  Snapshot.Vehicles.Sort([](
      const DriscaApi::FVehicleSample &Left,
      const DriscaApi::FVehicleSample &Right)
  {
    return Left.ActorId < Right.ActorId;
  });

  if (Session.bActive && Session.EgoActorId != 0)
  {
    const ACarlaWheeledVehicle *Ego = EgoVehicle.Get();
    const UDrivingViewSubsystem *View = GetViewSubsystem();
    const FDrivingViewState *State = View != nullptr ? View->GetState() : nullptr;

    DriscaApi::FResearchSample Research;
    Research.ActorId = Session.EgoActorId;

    uint32 Validity = 0u;
    if (Session.bImuValid)
    {
      Validity |= 1u << 0;
    }
    if (Session.bGnssValid)
    {
      Validity |= 1u << 1;
    }
    if (Session.bResearchReady)
    {
      Validity |= 1u << 4;
    }

    FVector Location = FVector::ZeroVector;
    if (Ego != nullptr)
    {
      Location = Ego->GetActorLocation() * 0.01;
    }

    FRoadInfo Road;
    if (Map != nullptr)
    {
      Road = QueryRoad(*Map, Location);
    }
    if (Road.bValid)
    {
      Validity |= 1u << 2;
    }

    if (State != nullptr && State->bActive)
    {
      Validity |= 1u << 3;
      Research.InputThrottle = State->Input.Throttle;
      Research.InputSteer = State->Input.Steer;
      Research.InputBrake = State->Input.Brake;
      Research.InputGear = State->Input.Gear;
      if (State->Input.bReverse)
      {
        Research.InputFlags |= 1u << 0;
      }
      if (State->Input.bHandBrake)
      {
        Research.InputFlags |= 1u << 1;
      }
      if (State->Input.bManualGearShift)
      {
        Research.InputFlags |= 1u << 2;
      }
      if (bTakeoverThisFrame)
      {
        Research.InputFlags |= 1u << 3;
      }
    }

    Research.ValidityFlags = Validity;
    Research.ImuFrameNo = Session.ImuFrameNo;
    Research.ImuSimulationTimeUs = Session.ImuSimulationTimeUs;
    Research.GnssFrameNo = Session.GnssFrameNo;
    Research.GnssSimulationTimeUs = Session.GnssSimulationTimeUs;
    Research.Accelerometer = Session.Accelerometer;
    Research.Gyroscope = Session.Gyroscope;
    Research.Compass = Session.Compass;
    Research.Longitude = Session.Longitude;
    Research.Latitude = Session.Latitude;
    Research.Altitude = Session.Altitude;
    if (Road.bValid)
    {
      Research.RoadDirection = Road.Direction;
      Research.LaneWidth = Road.LaneWidth;
      Research.LaneOffset = Road.LaneOffset;
      Research.LaneType = Road.LaneType;
    }
    Research.CollisionIntensity = Session.CollisionIntensity;

    Snapshot.bHasResearch = true;
    Snapshot.Research = Research;
  }

  return Snapshot;
}

TArray<uint8> UDriscaApiSubsystem::EncodeSnapshot(
    const DriscaApi::FSnapshot &Snapshot) const
{
  const int32 VehicleCount = Snapshot.Vehicles.Num();
  const int32 ResearchCount = Snapshot.bHasResearch ? 1 : 0;
  const int32 Total = DriscaApi::SnapshotHeaderBytes +
      VehicleCount * DriscaApi::VehicleRecordBytes +
      ResearchCount * DriscaApi::ResearchRecordBytes;

  TArray<uint8> Bytes;
  Bytes.Reserve(Total);

  PutU32(Bytes, Snapshot.RequestId);
  PutU32(Bytes, static_cast<uint32>(VehicleCount));
  PutU64(Bytes, Snapshot.WorldId);
  PutU64(Bytes, Snapshot.FrameNo);
  PutI64(Bytes, Snapshot.SimulationTimeUs);
  PutI64(Bytes, Snapshot.WallTimeUs);
  PutF32(Bytes, Snapshot.DeltaSeconds);
  PutU32(Bytes, static_cast<uint32>(ResearchCount));

  for (const DriscaApi::FVehicleSample &Vehicle : Snapshot.Vehicles)
  {
    PutU32(Bytes, Vehicle.ActorId);
    PutU32(Bytes, Vehicle.Flags);
    PutF32(Bytes, Vehicle.Location.X);
    PutF32(Bytes, Vehicle.Location.Y);
    PutF32(Bytes, Vehicle.Location.Z);
    PutF32(Bytes, Vehicle.Rotation.Pitch);
    PutF32(Bytes, Vehicle.Rotation.Yaw);
    PutF32(Bytes, Vehicle.Rotation.Roll);
    PutF32(Bytes, Vehicle.Velocity.X);
    PutF32(Bytes, Vehicle.Velocity.Y);
    PutF32(Bytes, Vehicle.Velocity.Z);
    PutF32(Bytes, Vehicle.AngularVelocity.X);
    PutF32(Bytes, Vehicle.AngularVelocity.Y);
    PutF32(Bytes, Vehicle.AngularVelocity.Z);
    PutF32(Bytes, Vehicle.Acceleration.X);
    PutF32(Bytes, Vehicle.Acceleration.Y);
    PutF32(Bytes, Vehicle.Acceleration.Z);
    PutF32(Bytes, Vehicle.Throttle);
    PutF32(Bytes, Vehicle.Steer);
    PutF32(Bytes, Vehicle.Brake);
    PutI32(Bytes, Vehicle.Gear);
    PutF32(Bytes, Vehicle.SpeedLimitMps);
    PutI32(Bytes, Vehicle.RoadId);
    PutI32(Bytes, Vehicle.LaneId);
  }

  if (Snapshot.bHasResearch)
  {
    const DriscaApi::FResearchSample &Research = Snapshot.Research;
    PutU32(Bytes, Research.ActorId);
    PutU32(Bytes, Research.ValidityFlags);
    PutF32(Bytes, Research.InputThrottle);
    PutF32(Bytes, Research.InputSteer);
    PutF32(Bytes, Research.InputBrake);
    PutU32(Bytes, Research.InputFlags);
    PutI32(Bytes, Research.InputGear);
    PutU64(Bytes, Research.ImuFrameNo);
    PutI64(Bytes, Research.ImuSimulationTimeUs);
    PutU64(Bytes, Research.GnssFrameNo);
    PutI64(Bytes, Research.GnssSimulationTimeUs);
    PutF32(Bytes, Research.Accelerometer.X);
    PutF32(Bytes, Research.Accelerometer.Y);
    PutF32(Bytes, Research.Accelerometer.Z);
    PutF32(Bytes, Research.Gyroscope.X);
    PutF32(Bytes, Research.Gyroscope.Y);
    PutF32(Bytes, Research.Gyroscope.Z);
    PutF32(Bytes, Research.Compass);
    PutF32(Bytes, Research.Longitude);
    PutF32(Bytes, Research.Latitude);
    PutF32(Bytes, Research.Altitude);
    PutF32(Bytes, Research.RoadDirection.X);
    PutF32(Bytes, Research.RoadDirection.Y);
    PutF32(Bytes, Research.RoadDirection.Z);
    PutF32(Bytes, Research.LaneWidth);
    PutF32(Bytes, Research.LaneOffset);
    PutU32(Bytes, Research.LaneType);
    PutF32(Bytes, Research.CollisionIntensity);
  }

  checkf(Bytes.Num() == Total,
      TEXT("DriscaApi: snapshot size %d does not match %d"), Bytes.Num(), Total);
  return Bytes;
}

bool UDriscaApiSubsystem::ValidateSnapshot(
    const DriscaApi::FSnapshot &Snapshot, FString &OutReason) const
{
  auto CheckFloat = [&OutReason](const TCHAR *Field, double Value)
  {
    if (FMath::IsFinite(Value))
    {
      return true;
    }
    OutReason = Field;
    return false;
  };
  auto CheckVector = [&OutReason](const TCHAR *Field, const FVector &Value)
  {
    if (!FMath::IsFinite(Value.X))
    {
      OutReason = FString::Printf(TEXT("%s.x"), Field);
      return false;
    }
    if (!FMath::IsFinite(Value.Y))
    {
      OutReason = FString::Printf(TEXT("%s.y"), Field);
      return false;
    }
    if (!FMath::IsFinite(Value.Z))
    {
      OutReason = FString::Printf(TEXT("%s.z"), Field);
      return false;
    }
    return true;
  };

  if (!CheckFloat(TEXT("delta_seconds"), Snapshot.DeltaSeconds))
  {
    return false;
  }

  for (const DriscaApi::FVehicleSample &Vehicle : Snapshot.Vehicles)
  {
    if (!CheckVector(TEXT("location"), Vehicle.Location) ||
        !CheckFloat(TEXT("rotation_pitch"), Vehicle.Rotation.Pitch) ||
        !CheckFloat(TEXT("rotation_yaw"), Vehicle.Rotation.Yaw) ||
        !CheckFloat(TEXT("rotation_roll"), Vehicle.Rotation.Roll) ||
        !CheckVector(TEXT("velocity"), Vehicle.Velocity) ||
        !CheckVector(TEXT("angular_velocity"), Vehicle.AngularVelocity) ||
        !CheckVector(TEXT("acceleration"), Vehicle.Acceleration) ||
        !CheckFloat(TEXT("throttle"), Vehicle.Throttle) ||
        !CheckFloat(TEXT("steer"), Vehicle.Steer) ||
        !CheckFloat(TEXT("brake"), Vehicle.Brake) ||
        !CheckFloat(TEXT("speed_limit_mps"), Vehicle.SpeedLimitMps))
    {
      return false;
    }
  }

  if (Snapshot.bHasResearch)
  {
    const DriscaApi::FResearchSample &Research = Snapshot.Research;
    if (!CheckFloat(TEXT("input_throttle"), Research.InputThrottle) ||
        !CheckFloat(TEXT("input_steer"), Research.InputSteer) ||
        !CheckFloat(TEXT("input_brake"), Research.InputBrake) ||
        !CheckVector(TEXT("accelerometer"), Research.Accelerometer) ||
        !CheckVector(TEXT("gyroscope"), Research.Gyroscope) ||
        !CheckFloat(TEXT("compass"), Research.Compass) ||
        !CheckFloat(TEXT("longitude"), Research.Longitude) ||
        !CheckFloat(TEXT("latitude"), Research.Latitude) ||
        !CheckFloat(TEXT("altitude"), Research.Altitude) ||
        !CheckVector(TEXT("road_direction"), Research.RoadDirection) ||
        !CheckFloat(TEXT("lane_width"), Research.LaneWidth) ||
        !CheckFloat(TEXT("lane_offset"), Research.LaneOffset) ||
        !CheckFloat(TEXT("collision_intensity"), Research.CollisionIntensity))
    {
      return false;
    }
  }

  return true;
}

void UDriscaApiSubsystem::EmitEvent(
    const FString &Name,
    const FString &Source,
    const TSharedPtr<FJsonObject> &Payload,
    TOptional<int32> RequestId,
    TOptional<int32> OperationIndex)
{
  if (EventQueue.Num() >= DriscaApi::MaxEventQueue)
  {
    RequestFatal(CodeOperationFailed, TEXT("事件队列已满，实验终止"));
    return;
  }

  DriscaApi::FEvent Event;
  Event.EventId = NextEventId++;
  Event.WorldId = WorldId;
  Event.SessionId = Session.SessionId;
  Event.FrameNo = CurrentFrameNo();
  Event.SimulationTimeUs = SimulationTimeUs();
  Event.WallTimeUs = DriscaApi::WallTimeMicroseconds();
  Event.Name = Name;
  Event.Source = Source;
  Event.RequestId = RequestId;
  Event.OperationIndex = OperationIndex;
  Event.Payload = Payload.IsValid() ? Payload : MakeShared<FJsonObject>();
  EventQueue.Add(Event);
}

TSharedPtr<FJsonObject> UDriscaApiSubsystem::EventToJson(
    const DriscaApi::FEvent &Event) const
{
  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("event_id"), static_cast<double>(Event.EventId));
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(Event.WorldId));
  Result->SetStringField(TEXT("session_id"), Event.SessionId);
  Result->SetNumberField(TEXT("frame_no"), static_cast<double>(Event.FrameNo));
  Result->SetNumberField(TEXT("simulation_time_us"),
      static_cast<double>(Event.SimulationTimeUs));
  Result->SetNumberField(TEXT("wall_time_us"), static_cast<double>(Event.WallTimeUs));
  Result->SetStringField(TEXT("name"), Event.Name);
  Result->SetStringField(TEXT("source"), Event.Source);
  if (Event.RequestId.IsSet())
  {
    Result->SetNumberField(TEXT("request_id"), Event.RequestId.GetValue());
  }
  else
  {
    Result->SetField(TEXT("request_id"), MakeShared<FJsonValueNull>());
  }
  if (Event.OperationIndex.IsSet())
  {
    Result->SetNumberField(TEXT("operation_index"), Event.OperationIndex.GetValue());
  }
  else
  {
    Result->SetField(TEXT("operation_index"), MakeShared<FJsonValueNull>());
  }
  Result->SetObjectField(TEXT("payload"),
      Event.Payload.IsValid() ? Event.Payload : MakeShared<FJsonObject>());
  return Result;
}

TArray<TSharedPtr<FJsonValue>> UDriscaApiSubsystem::TakeEventsJson()
{
  TArray<TSharedPtr<FJsonValue>> Result;
  Result.Reserve(EventQueue.Num());
  for (const DriscaApi::FEvent &Event : EventQueue)
  {
    Result.Add(MakeShared<FJsonValueObject>(EventToJson(Event)));
  }
  EventQueue.Empty();
  return Result;
}

// =============================================================================
// -- 研究采集 -----------------------------------------------------------------
// =============================================================================

bool UDriscaApiSubsystem::SpawnResearchSensors(FString &OutError)
{
  UCarlaEpisode *Episode = GetEpisode();
  if (Episode == nullptr)
  {
    OutError = TEXT("当前没有可用的世界");
    return false;
  }

  Imu.Reset();
  Gnss.Reset();

  struct FSensorRequest
  {
    const TCHAR *Blueprint;
    const TCHAR *RoleName;
  };
  const FSensorRequest Requests[] = {
      {TEXT("sensor.other.imu"), TEXT("drisca_imu")},
      {TEXT("sensor.other.gnss"), TEXT("drisca_gnss")}};

  for (const FSensorRequest &Request : Requests)
  {
    const FActorDefinition *Definition = nullptr;
    for (const FActorDefinition &Candidate : Episode->GetActorDefinitions())
    {
      if (Candidate.Id == Request.Blueprint)
      {
        Definition = &Candidate;
        break;
      }
    }
    if (Definition == nullptr)
    {
      OutError = FString::Printf(TEXT("传感器定义 %s 不存在"), Request.Blueprint);
      return false;
    }

    FActorDescription Description;
    Description.UId = Definition->UId;
    Description.Id = Definition->Id;
    Description.Class = Definition->Class;
    for (const FActorVariation &Variation : Definition->Variations)
    {
      FActorAttribute Attribute;
      Attribute.Id = Variation.Id;
      Attribute.Type = Variation.Type;
      Attribute.Value = Variation.RecommendedValues.Num() > 0
          ? Variation.RecommendedValues[0]
          : FString();
      Description.Variations.Add(Attribute.Id, Attribute);
    }
    FActorAttribute Role;
    Role.Id = TEXT("role_name");
    Role.Type = EActorAttributeType::String;
    Role.Value = Request.RoleName;
    Description.Variations.Add(Role.Id, Role);

    const AActor *Ego = EgoVehicle.Get();
    const FTransform Transform = Ego != nullptr
        ? Ego->GetActorTransform() : FTransform::Identity;
    const TPair<EActorSpawnResultStatus, FCarlaActor *> SpawnResult =
        Episode->SpawnActorWithInfo(Transform, Description);
    if (SpawnResult.Key != EActorSpawnResultStatus::Success ||
        SpawnResult.Value == nullptr)
    {
      OutError = FString::Printf(TEXT("传感器 %s 创建失败"), Request.Blueprint);
      return false;
    }

    AActor *SensorActor = SpawnResult.Value->GetActor();
    Session.OwnedActors.AddUnique(SpawnResult.Value->GetActorId());
    if (Ego != nullptr)
    {
      Episode->AttachActors(SensorActor, const_cast<AActor *>(Ego), EAttachmentType::Rigid);
    }

    if (Request.Blueprint == FString(TEXT("sensor.other.imu")))
    {
      Imu = Cast<AInertialMeasurementUnit>(SensorActor);
    }
    else
    {
      Gnss = Cast<AGnssSensor>(SensorActor);
    }
  }

  if (!Imu.IsValid() || !Gnss.IsValid())
  {
    OutError = TEXT("研究传感器类型不匹配");
    return false;
  }

  ResearchTickCount = 0;
  Session.bImuValid = false;
  Session.bGnssValid = false;
  Session.bResearchReady = false;
  return true;
}

void UDriscaApiSubsystem::StopResearch()
{
  DetachCollisionHook();

  if (UDrivingViewSubsystem *View = GetViewSubsystem())
  {
    if (ADrivingViewPawn *Pawn = View->GetPawn())
    {
      if (ActionDelegateHandle.IsValid())
      {
        Pawn->OnAction.Remove(ActionDelegateHandle);
      }
    }
  }
  ActionDelegateHandle.Reset();

  UCarlaEpisode *Episode = GetEpisode();
  if (Episode != nullptr)
  {
    AActor *Sensors[2] = {Imu.Get(), Gnss.Get()};
    for (AActor *Sensor : Sensors)
    {
      if (Sensor == nullptr)
      {
        continue;
      }
      const FCarlaActor *CarlaActor = Episode->FindCarlaActor(Sensor);
      if (CarlaActor != nullptr)
      {
        Episode->DestroyActor(CarlaActor->GetActorId());
      }
    }
  }

  Imu.Reset();
  Gnss.Reset();
  EgoVehicle.Reset();
  Session.bImuValid = false;
  Session.bGnssValid = false;
  Session.bResearchReady = false;
  ResearchTickCount = 0;
}

void UDriscaApiSubsystem::UpdateResearch()
{
  if (!Session.bActive)
  {
    return;
  }

  if (AInertialMeasurementUnit *ImuSensor = Imu.Get())
  {
    const carla::geom::Vector3D Accelerometer = ImuSensor->GetAccelerometerValue();
    const carla::geom::Vector3D Gyroscope = ImuSensor->GetGyroscopeValue();
    Session.Accelerometer = FVector(Accelerometer.x, Accelerometer.y, Accelerometer.z);
    Session.Gyroscope = FVector(Gyroscope.x, Gyroscope.y, Gyroscope.z);
    Session.Compass = ImuSensor->GetCompassValue();
    Session.ImuFrameNo = ImuSensor->GetSampleFrameNo();
    Session.ImuSimulationTimeUs =
        DriscaApi::ToMicroseconds(ImuSensor->GetSampleSimulationTimeSeconds());
    Session.bImuValid = Session.ImuFrameNo != 0;
  }

  if (AGnssSensor *GnssSensor = Gnss.Get())
  {
    Session.Longitude = static_cast<float>(GnssSensor->GetLongitudeValue());
    Session.Latitude = static_cast<float>(GnssSensor->GetLatitudeValue());
    Session.Altitude = static_cast<float>(GnssSensor->GetAltitudeValue());
    Session.GnssFrameNo = GnssSensor->GetSampleFrameNo();
    Session.GnssSimulationTimeUs =
        DriscaApi::ToMicroseconds(GnssSensor->GetSampleSimulationTimeSeconds());
    Session.bGnssValid = Session.GnssFrameNo != 0;
  }

  if (Session.bImuValid && Session.bGnssValid)
  {
    Session.bResearchReady = true;
  }
}

void UDriscaApiSubsystem::UpdateLaneInvasion()
{
  if (!Session.bActive)
  {
    return;
  }

  ACarlaWheeledVehicle *Ego = EgoVehicle.Get();
  UCarlaEpisode *Episode = GetEpisode();
  ACarlaGameModeBase *GameMode = GetGameMode();
  if (Ego == nullptr || Episode == nullptr || GameMode == nullptr ||
      !GameMode->GetMap().has_value())
  {
    return;
  }

  FCarlaActor *CarlaActor = Episode->FindCarlaActor(Ego);
  const FActorInfo *Info = CarlaActor != nullptr ? CarlaActor->GetActorInfo() : nullptr;
  if (Info == nullptr)
  {
    return;
  }

  const FVector Center =
      Ego->GetActorLocation() * 0.01 + Info->BoundingBox.Origin * 0.01;
  const float Yaw = Ego->GetActorRotation().Yaw;
  const FVector Extent = Info->BoundingBox.Extent * 0.01;

  FVector Corners[4] = {
      Center + RotateYaw(Yaw, FVector(Extent.X, Extent.Y, 0.0f)),
      Center + RotateYaw(Yaw, FVector(-Extent.X, Extent.Y, 0.0f)),
      Center + RotateYaw(Yaw, FVector(Extent.X, -Extent.Y, 0.0f)),
      Center + RotateYaw(Yaw, FVector(-Extent.X, -Extent.Y, 0.0f))};

  if (!Session.bHasPreviousCorners)
  {
    for (int32 Index = 0; Index < 4; ++Index)
    {
      Session.PreviousCorners[Index] = Corners[Index];
    }
    Session.bHasPreviousCorners = true;
    return;
  }

  const carla::road::Map &Map = *GameMode->GetMap();
  std::vector<carla::road::element::LaneMarking> Crossed;
  bool bMoved = false;
  for (int32 Index = 0; Index < 4; ++Index)
  {
    const carla::geom::Location Previous(
        Session.PreviousCorners[Index].X,
        Session.PreviousCorners[Index].Y,
        Session.PreviousCorners[Index].Z);
    const carla::geom::Location Current(
        Corners[Index].X, Corners[Index].Y, Corners[Index].Z);
    if ((Corners[Index] - Session.PreviousCorners[Index]).Size() > 1.0e-3f)
    {
      bMoved = true;
    }
    const std::vector<carla::road::element::LaneMarking> Markings =
        Map.CalculateCrossedLanes(Previous, Current);
    Crossed.insert(Crossed.end(), Markings.begin(), Markings.end());
  }

  if (bMoved && !Crossed.empty())
  {
    TArray<TSharedPtr<FJsonValue>> Markings;
    for (const carla::road::element::LaneMarking &Marking : Crossed)
    {
      Markings.Add(MakeShared<FJsonValueString>(LaneMarkingToString(Marking.type)));
    }
    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetArrayField(TEXT("markings"), Markings);
    EmitEvent(TEXT("lane_invasion"), TEXT("sensor"), Payload);
  }

  for (int32 Index = 0; Index < 4; ++Index)
  {
    Session.PreviousCorners[Index] = Corners[Index];
  }
}

void UDriscaApiSubsystem::AttachCollisionHook()
{
  if (ACarlaWheeledVehicle *Ego = EgoVehicle.Get())
  {
    Ego->OnActorHit.AddDynamic(this, &UDriscaApiSubsystem::OnEgoHit);
  }
}

void UDriscaApiSubsystem::DetachCollisionHook()
{
  if (ACarlaWheeledVehicle *Ego = EgoVehicle.Get())
  {
    Ego->OnActorHit.RemoveDynamic(this, &UDriscaApiSubsystem::OnEgoHit);
  }
}

void UDriscaApiSubsystem::OnEgoHit(
    AActor *SelfActor,
    AActor *OtherActor,
    FVector NormalImpulse,
    const FHitResult &Hit)
{
  if (OtherActor == nullptr)
  {
    return;
  }

  const FVector Impulse = NormalImpulse * 0.01;
  Session.CollisionIntensity = Impulse.Size();

  FString ActorType = TEXT("other");
  uint32 ActorId = 0u;
  if (UCarlaEpisode *Episode = GetEpisode())
  {
    if (const FCarlaActor *CarlaActor = Episode->FindCarlaActor(OtherActor))
    {
      ActorId = CarlaActor->GetActorId();
      switch (CarlaActor->GetActorType())
      {
        case FCarlaActor::ActorType::Vehicle:
          ActorType = TEXT("vehicle");
          break;
        case FCarlaActor::ActorType::Walker:
          ActorType = TEXT("walker");
          break;
        case FCarlaActor::ActorType::TrafficLight:
          ActorType = TEXT("traffic_light");
          break;
        case FCarlaActor::ActorType::TrafficSign:
          ActorType = TEXT("traffic_sign");
          break;
        default:
          break;
      }
    }
  }

  TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
  Payload->SetNumberField(TEXT("actor_id"), ActorId);
  Payload->SetStringField(TEXT("actor_type"), ActorType);
  Payload->SetNumberField(TEXT("impulse_x"), Impulse.X);
  Payload->SetNumberField(TEXT("impulse_y"), Impulse.Y);
  Payload->SetNumberField(TEXT("impulse_z"), Impulse.Z);
  EmitEvent(TEXT("collision"), TEXT("sensor"), Payload);
}

void UDriscaApiSubsystem::OnDrivingAction(
    ADrivingViewPawn *Pawn, const FString &Action)
{
  if (!Session.bActive || Pawn == nullptr)
  {
    return;
  }

  const FDrivingViewState &State = Pawn->GetState();

  if (Action == TEXT("takeover"))
  {
    bTakeoverThisFrame = true;
    DriscaApi::FVehicleTrack *Track =
        VehicleTracks.Find(Session.EgoActorId);
    if (Track == nullptr || Track->Source != TEXT("external"))
    {
      return;
    }
    Pawn->SetExternalControl(false);
    Track->Source = TEXT("manual");
    Track->Controller = TEXT("human");
    ++Track->ControlRevision;
    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetNumberField(TEXT("actor_id"), Session.EgoActorId);
    Payload->SetBoolField(TEXT("enabled"), true);
    Payload->SetNumberField(TEXT("revision"),
        static_cast<double>(Track->ControlRevision));
    EmitEvent(TEXT("toggle_takeover"), TEXT("keyboard"), Payload);
    return;
  }

  if (Action == TEXT("toggle_autopilot"))
  {
    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetStringField(TEXT("action"), TEXT("toggle_automation"));
    EmitEvent(TEXT("driver_request"), TEXT("keyboard"), Payload);
    return;
  }

  auto EmitEnabled = [this](const TCHAR *Name, bool bEnabled)
  {
    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetBoolField(TEXT("enabled"), bEnabled);
    EmitEvent(Name, TEXT("keyboard"), Payload);
  };

  if (Action == TEXT("toggle_reverse"))
  {
    EmitEnabled(TEXT("toggle_reverse"), State.Input.bReverse);
  }
  else if (Action == TEXT("toggle_handbrake"))
  {
    EmitEnabled(TEXT("toggle_handbrake"), State.Input.bHandBrake);
  }
  else if (Action == TEXT("toggle_manual_transmission"))
  {
    EmitEnabled(TEXT("toggle_manual_gear"), State.Input.bManualGearShift);
  }
  else if (Action == TEXT("gear_up") || Action == TEXT("gear_down"))
  {
    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetNumberField(TEXT("gear"), State.Input.Gear);
    EmitEvent(TEXT("change_gear"), TEXT("keyboard"), Payload);
  }
}
