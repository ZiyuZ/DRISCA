#include "DriscaApiRoadData.h"

#include "Carla.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Game/CarlaGameModeBase.h"

#include <util/ue-header-guard-begin.h>
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/PlatformTime.h"
#include "Math/UnrealMathUtility.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include <util/ue-header-guard-end.h>

#include <util/disable-ue4-macros.h>
#include "carla/road/Junction.h"
#include "carla/road/Lane.h"
#include "carla/road/LaneSection.h"
#include "carla/road/Map.h"
#include "carla/road/Road.h"
#include "carla/road/element/LaneMarking.h"
#include "carla/road/element/RoadInfoLaneWidth.h"
#include "carla/road/element/RoadInfoMarkRecord.h"
#include <util/enable-ue4-macros.h>

#include <algorithm>
#include <set>

namespace
{
  constexpr int32 PageByteBudget = 6 * 1024 * 1024;
  constexpr int32 MessageByteLimit = 7 * 1024 * 1024;

  FString LaneChangeToString(int32 Value)
  {
    switch (Value)
    {
      case 1:
        return TEXT("right");
      case 2:
        return TEXT("left");
      case 3:
        return TEXT("both");
      default:
        return TEXT("none");
    }
  }

  FString LaneTypeToString(carla::road::Lane::LaneType Type)
  {
    switch (Type)
    {
      case carla::road::Lane::LaneType::Driving:
        return TEXT("driving");
      case carla::road::Lane::LaneType::Shoulder:
        return TEXT("shoulder");
      case carla::road::Lane::LaneType::Parking:
        return TEXT("parking");
      case carla::road::Lane::LaneType::Sidewalk:
        return TEXT("sidewalk");
      case carla::road::Lane::LaneType::Biking:
        return TEXT("biking");
      case carla::road::Lane::LaneType::Median:
        return TEXT("median");
      case carla::road::Lane::LaneType::Special1:
        return TEXT("special1");
      case carla::road::Lane::LaneType::Special2:
        return TEXT("special2");
      case carla::road::Lane::LaneType::Special3:
        return TEXT("special3");
      case carla::road::Lane::LaneType::RoadWorks:
        return TEXT("road_works");
      case carla::road::Lane::LaneType::Tram:
        return TEXT("tram");
      case carla::road::Lane::LaneType::Rail:
        return TEXT("rail");
      case carla::road::Lane::LaneType::Entry:
        return TEXT("entry");
      case carla::road::Lane::LaneType::Exit:
        return TEXT("exit");
      case carla::road::Lane::LaneType::OffRamp:
        return TEXT("off_ramp");
      case carla::road::Lane::LaneType::OnRamp:
        return TEXT("on_ramp");
      default:
        return TEXT("none");
    }
  }

  FString MarkType(const carla::road::element::RoadInfoMarkRecord *Record)
  {
    if (Record == nullptr)
    {
      return FString(TEXT("none"));
    }
    return FString(UTF8_TO_TCHAR(Record->GetType().c_str()));
  }

  FString MarkColor(const carla::road::element::RoadInfoMarkRecord *Record)
  {
    if (Record == nullptr)
    {
      return FString();
    }
    return FString(UTF8_TO_TCHAR(Record->GetColor().c_str()));
  }

  float MarkWidth(const carla::road::element::RoadInfoMarkRecord *Record)
  {
    return Record != nullptr ? static_cast<float>(Record->GetWidth()) : 0.0f;
  }

  void SwapLeftRight(int32 &Value)
  {
    if (Value == 1)
    {
      Value = 2;
    }
    else if (Value == 2)
    {
      Value = 1;
    }
  }

  struct FResolvedLaneChange
  {
    int32 Value = 0;
    bool bLeft = false;
    bool bRight = false;
    FString LeftType = TEXT("none");
    FString LeftColor;
    float LeftWidth = 0.0f;
    FString RightType = TEXT("none");
    FString RightColor;
    float RightWidth = 0.0f;
  };

  /// 复刻 carla::client::Waypoint::GetLaneChange 的规则。
  FResolvedLaneChange ResolveLaneChange(
      const carla::road::Map &Map,
      const carla::road::element::Waypoint &Waypoint)
  {
    FResolvedLaneChange Result;
    const carla::road::Lane &Lane = Map.GetLane(Waypoint);
    const carla::road::Road *Road = Lane.GetRoad();
    if (Road == nullptr)
    {
      return Result;
    }

    const auto Marks = Map.GetMarkRecord(Waypoint);
    const carla::road::element::RoadInfoMarkRecord *RightInfo =
        Road->IsRHT() ? Marks.first : Marks.second;
    const carla::road::element::RoadInfoMarkRecord *LeftInfo =
        Road->IsRHT() ? Marks.second : Marks.first;

    int32 RightValue = RightInfo != nullptr
        ? static_cast<int32>(RightInfo->GetLaneChange()) : 3;
    int32 LeftValue = LeftInfo != nullptr
        ? static_cast<int32>(LeftInfo->GetLaneChange()) : 3;

    const bool bPositive = Lane.IsPositiveDirection();
    if (!bPositive)
    {
      SwapLeftRight(RightValue);
    }
    if (((!bPositive) ? Waypoint.lane_id - 1 : Waypoint.lane_id + 1) < 0)
    {
      SwapLeftRight(LeftValue);
    }

    Result.bRight = (RightValue & 1) != 0;
    Result.bLeft = (LeftValue & 2) != 0;
    Result.Value = (Result.bRight ? 1 : 0) | (Result.bLeft ? 2 : 0);
    Result.LeftType = MarkType(LeftInfo);
    Result.LeftColor = MarkColor(LeftInfo);
    Result.LeftWidth = MarkWidth(LeftInfo);
    Result.RightType = MarkType(RightInfo);
    Result.RightColor = MarkColor(RightInfo);
    Result.RightWidth = MarkWidth(RightInfo);
    return Result;
  }

  TArray<double> CollectChangePoints(
      const carla::road::Lane &Lane,
      const carla::road::Lane *InnerLane,
      double Start,
      double End)
  {
    TArray<double> Points;
    Points.Add(Start);
    Points.Add(End);
    for (const carla::road::element::RoadInfoMarkRecord *Info :
        Lane.GetInfos<carla::road::element::RoadInfoMarkRecord>())
    {
      Points.Add(Info->GetDistance());
    }
    if (InnerLane != nullptr)
    {
      for (const carla::road::element::RoadInfoMarkRecord *Info :
          InnerLane->GetInfos<carla::road::element::RoadInfoMarkRecord>())
      {
        Points.Add(Info->GetDistance());
      }
    }
    for (const carla::road::element::RoadInfoLaneWidth *Info :
        Lane.GetInfos<carla::road::element::RoadInfoLaneWidth>())
    {
      Points.Add(Info->GetDistance());
    }
    for (double &Point : Points)
    {
      Point = FMath::Clamp(Point, Start, End);
    }
    Points.Sort();
    TArray<double> Unique;
    for (double Point : Points)
    {
      if (Unique.Num() == 0 || Point - Unique.Last() > 1.0e-4)
      {
        Unique.Add(Point);
      }
    }
    return Unique;
  }
}

void FDriscaRoadData::Invalidate()
{
  Lanes.Reset();
  Junctions.Reset();
  CachedWorldId = 0;
  CachedStep = 0.0;
  BuildMilliseconds = 0.0;
}

bool FDriscaRoadData::IsBuilt(uint64 WorldId, double SamplingStep) const
{
  return CachedWorldId == WorldId && FMath::IsNearlyEqual(CachedStep, SamplingStep);
}

bool FDriscaRoadData::Build(
    ACarlaGameModeBase &GameMode,
    uint64 WorldId,
    double SamplingStep,
    FString &OutError)
{
  if (!GameMode.GetMap().has_value())
  {
    OutError = TEXT("道路地图不可用");
    return false;
  }

  const double StartTime = FPlatformTime::Seconds();
  const carla::road::Map &Map = *GameMode.GetMap();
  const carla::road::MapData &Data = Map.GetData();
  const auto &Roads = Data.GetRoads();

  TArray<carla::road::RoadId> RoadIds;
  RoadIds.Reserve(Roads.size());
  for (const auto &Pair : Roads)
  {
    RoadIds.Add(Pair.first);
  }
  RoadIds.Sort();

  Lanes.Reset();
  TArray<const carla::road::Lane *> LanePtrs;
  TMap<const carla::road::Lane *, int32> LaneIndices;

  for (const carla::road::RoadId RoadId : RoadIds)
  {
    const carla::road::Road &Road = Roads.at(RoadId);
    for (const carla::road::LaneSection &Section : Road.GetLaneSections())
    {
      const double SectionStart =
          FMath::Clamp(Section.GetDistance(), 0.0, Road.GetLength());
      const double SectionEnd =
          FMath::Clamp(Section.GetDistance() + Section.GetLength(),
              0.0, Road.GetLength());
      for (const auto &LanePair : Section.GetLanes())
      {
        const carla::road::LaneId LaneId = LanePair.first;
        if (LaneId == 0)
        {
          continue;
        }
        const carla::road::Lane &Lane = LanePair.second;

        FLaneNode Node;
        Node.RoadId = static_cast<int32>(RoadId);
        Node.SectionId = static_cast<int32>(Section.GetId());
        Node.LaneId = static_cast<int32>(LaneId);
        Node.Id = FString::Printf(TEXT("%d:%d:%d"),
            Node.RoadId, Node.SectionId, Node.LaneId);
        Node.TypeValue = static_cast<int32>(Lane.GetType());
        Node.TypeName = LaneTypeToString(Lane.GetType());
        Node.Length = FMath::Max(0.0, SectionEnd - SectionStart);
        Node.SectionStartS = SectionStart;
        Node.SectionEndS = SectionEnd;
        Node.bPositiveDirection = Lane.IsPositiveDirection();
        Node.bJunction = Road.IsJunction();
        Node.JunctionId = static_cast<int32>(Road.GetJunctionId());

        LanePtrs.Add(&Lane);
        LaneIndices.Add(&Lane, Lanes.Num());
        Lanes.Add(MoveTemp(Node));
      }
    }
  }

  for (int32 Index = 0; Index < Lanes.Num(); ++Index)
  {
    FLaneNode &Node = Lanes[Index];
    const carla::road::Lane &Lane = *LanePtrs[Index];

    for (const carla::road::Lane *Next : Lane.GetNextLanes())
    {
      if (const int32 *NextIndex = LaneIndices.Find(Next))
      {
        Node.Successors.Add(Lanes[*NextIndex].Id);
      }
    }
    for (const carla::road::Lane *Previous : Lane.GetPreviousLanes())
    {
      if (const int32 *PreviousIndex = LaneIndices.Find(Previous))
      {
        Node.Predecessors.Add(Lanes[*PreviousIndex].Id);
      }
    }

    const double MidS = FMath::Clamp(
        Node.SectionStartS + Node.Length * 0.5,
        Node.SectionStartS + 1.0e-4,
        Node.SectionEndS - 1.0e-4);
    const std::optional<carla::road::element::Waypoint> MidWaypoint =
        Map.GetWaypoint(Node.RoadId, Node.LaneId, MidS);
    if (!MidWaypoint.has_value())
    {
      continue;
    }

    if (const std::optional<carla::road::element::Waypoint> Left =
        Map.GetLeft(*MidWaypoint))
    {
      const carla::road::Lane *LeftLane = &Map.GetLane(*Left);
      if (const int32 *LeftIndex = LaneIndices.Find(LeftLane))
      {
        Node.LeftLane = Lanes[*LeftIndex].Id;
        Node.bLeftSameDirection =
            LeftLane->IsPositiveDirection() == Node.bPositiveDirection;
      }
    }
    if (const std::optional<carla::road::element::Waypoint> Right =
        Map.GetRight(*MidWaypoint))
    {
      const carla::road::Lane *RightLane = &Map.GetLane(*Right);
      if (const int32 *RightIndex = LaneIndices.Find(RightLane))
      {
        Node.RightLane = Lanes[*RightIndex].Id;
        Node.bRightSameDirection =
            RightLane->IsPositiveDirection() == Node.bPositiveDirection;
      }
    }

    const carla::road::Lane *InnerLane = nullptr;
    {
      const carla::road::LaneId InnerId =
          Node.LaneId < 0 ? Node.LaneId + 1 : Node.LaneId - 1;
      const carla::road::LaneSection *Section = Lane.GetLaneSection();
      if (Section != nullptr)
      {
        InnerLane = Section->GetLane(InnerId);
      }
    }

    TArray<double> ChangePoints = CollectChangePoints(
        Lane, InnerLane, Node.SectionStartS, Node.SectionEndS);
    for (int32 PointIndex = 0; PointIndex + 1 < ChangePoints.Num(); ++PointIndex)
    {
      const double SegmentStart = ChangePoints[PointIndex];
      const double SegmentEnd = ChangePoints[PointIndex + 1];
      if (SegmentEnd - SegmentStart <= 1.0e-4)
      {
        continue;
      }
      const double SampleS = (SegmentStart + SegmentEnd) * 0.5;
      const std::optional<carla::road::element::Waypoint> Waypoint =
          Map.GetWaypoint(Node.RoadId, Node.LaneId, SampleS);
      if (!Waypoint.has_value())
      {
        continue;
      }

      const FResolvedLaneChange Resolved = ResolveLaneChange(Map, *Waypoint);
      const bool bLeftAllowed =
          Resolved.bLeft && Node.bLeftSameDirection && !Node.LeftLane.IsEmpty();
      const bool bRightAllowed =
          Resolved.bRight && Node.bRightSameDirection && !Node.RightLane.IsEmpty();

      FMarkSegment Segment;
      Segment.SStart = Node.bPositiveDirection
          ? SegmentStart - Node.SectionStartS
          : Node.SectionEndS - SegmentEnd;
      Segment.SEnd = Node.bPositiveDirection
          ? SegmentEnd - Node.SectionStartS
          : Node.SectionEndS - SegmentStart;
      Segment.LaneChange = (bRightAllowed ? 1 : 0) | (bLeftAllowed ? 2 : 0);
      Segment.bLeftAllowed = bLeftAllowed;
      Segment.bRightAllowed = bRightAllowed;
      Segment.LeftMark.Type = Resolved.LeftType;
      Segment.LeftMark.Color = Resolved.LeftColor;
      Segment.LeftMark.Width = Resolved.LeftWidth;
      Segment.RightMark.Type = Resolved.RightType;
      Segment.RightMark.Color = Resolved.RightColor;
      Segment.RightMark.Width = Resolved.RightWidth;
      Node.MarkSegments.Add(Segment);
    }

    if (Node.MarkSegments.Num() > 0)
    {
      const FMarkSegment &Middle = Node.MarkSegments[Node.MarkSegments.Num() / 2];
      Node.LaneChange = Middle.LaneChange;
      Node.bLeftAllowed = Middle.bLeftAllowed;
      Node.bRightAllowed = Middle.bRightAllowed;
    }

    TArray<double> SampleRoadS;
    const double Epsilon = 1.0e-4;
    const double Start = Node.SectionStartS + Epsilon;
    const double End = Node.SectionEndS - Epsilon;
    if (End >= Start)
    {
      SampleRoadS.Add(Start);
      SampleRoadS.Add(End);
      for (double S = Start + SamplingStep; S < End; S += SamplingStep)
      {
        SampleRoadS.Add(S);
      }
      for (double Point : ChangePoints)
      {
        SampleRoadS.Add(FMath::Clamp(Point, Start, End));
      }
    }
    SampleRoadS.Sort();

    TArray<double> UniqueRoadS;
    for (double S : SampleRoadS)
    {
      if (UniqueRoadS.Num() == 0 || S - UniqueRoadS.Last() > 1.0e-3)
      {
        UniqueRoadS.Add(S);
      }
    }

    for (double RoadS : UniqueRoadS)
    {
      const std::optional<carla::road::element::Waypoint> Waypoint =
          Map.GetWaypoint(Node.RoadId, Node.LaneId, RoadS);
      if (!Waypoint.has_value())
      {
        continue;
      }
      const carla::geom::Transform Transform = Map.ComputeTransform(*Waypoint);
      const carla::geom::Vector3D Forward = Transform.rotation.GetForwardVector();
      FLaneSample Sample;
      Sample.RoadS = RoadS;
      Sample.S = Node.bPositiveDirection
          ? RoadS - Node.SectionStartS
          : Node.SectionEndS - RoadS;
      Sample.Location = FVector(Transform.location.x, Transform.location.y, Transform.location.z);
      Sample.Direction = FVector(Forward.x, Forward.y, Forward.z);
      Sample.Width = static_cast<float>(Map.GetLaneWidth(*Waypoint));
      Node.Centerline.Add(Sample);
    }
    Node.Centerline.Sort([](const FLaneSample &Left, const FLaneSample &Right)
    {
      return Left.S < Right.S;
    });
  }

  Junctions.Reset();
  TArray<carla::road::JuncId> JunctionIds;
  for (const auto &Pair : Data.GetJunctions())
  {
    JunctionIds.Add(Pair.first);
  }
  JunctionIds.Sort();
  for (const carla::road::JuncId JunctionId : JunctionIds)
  {
    const carla::road::Junction &Junction =
        Data.GetJunctions().at(JunctionId);
    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetNumberField(TEXT("junction_id"), JunctionId);
    Item->SetStringField(TEXT("name"), FString());

    const carla::geom::BoundingBox Box = Junction.GetBoundingBox();
    TSharedPtr<FJsonObject> BoxJson = MakeShared<FJsonObject>();
    BoxJson->SetArrayField(TEXT("location"), {
        MakeShared<FJsonValueNumber>(Box.location.x),
        MakeShared<FJsonValueNumber>(Box.location.y),
        MakeShared<FJsonValueNumber>(Box.location.z)});
    BoxJson->SetArrayField(TEXT("rotation"), {
        MakeShared<FJsonValueNumber>(Box.rotation.pitch),
        MakeShared<FJsonValueNumber>(Box.rotation.yaw),
        MakeShared<FJsonValueNumber>(Box.rotation.roll)});
    BoxJson->SetArrayField(TEXT("extent"), {
        MakeShared<FJsonValueNumber>(Box.extent.x),
        MakeShared<FJsonValueNumber>(Box.extent.y),
        MakeShared<FJsonValueNumber>(Box.extent.z)});
    Item->SetObjectField(TEXT("bounding_box"), BoxJson);

    TArray<TSharedPtr<FJsonValue>> Controllers;
    for (const carla::road::ContId &ControllerId : Junction.GetControllers())
    {
      Controllers.Add(MakeShared<FJsonValueString>(
          UTF8_TO_TCHAR(ControllerId.c_str())));
    }
    Item->SetArrayField(TEXT("controllers"), Controllers);

    auto Connections = Junction.GetConnections();
    TArray<carla::road::ConId> ConnectionIds;
    for (const auto &Pair : Connections)
    {
      ConnectionIds.Add(Pair.first);
    }
    ConnectionIds.Sort();
    TArray<TSharedPtr<FJsonValue>> ConnectionArray;
    for (const carla::road::ConId ConnectionId : ConnectionIds)
    {
      const carla::road::Junction::Connection &Connection =
          Connections.at(ConnectionId);
      TSharedPtr<FJsonObject> ConnectionJson = MakeShared<FJsonObject>();
      ConnectionJson->SetNumberField(TEXT("connection_id"), Connection.id);
      ConnectionJson->SetNumberField(TEXT("incoming_road"), Connection.incoming_road);
      ConnectionJson->SetNumberField(TEXT("connecting_road"), Connection.connecting_road);
      TArray<TSharedPtr<FJsonValue>> Links;
      for (const carla::road::Junction::LaneLink &Link : Connection.lane_links)
      {
        TSharedPtr<FJsonObject> LinkJson = MakeShared<FJsonObject>();
        LinkJson->SetNumberField(TEXT("from_lane"), Link.from);
        LinkJson->SetNumberField(TEXT("to_lane"), Link.to);
        Links.Add(MakeShared<FJsonValueObject>(LinkJson));
      }
      ConnectionJson->SetArrayField(TEXT("lane_links"), Links);
      ConnectionArray.Add(MakeShared<FJsonValueObject>(ConnectionJson));
    }
    Item->SetArrayField(TEXT("connections"), ConnectionArray);

    TSharedPtr<FJsonObject> Conflicts = MakeShared<FJsonObject>();
    for (const auto &RoadPair : Data.GetRoads())
    {
      const carla::road::RoadId RoadId = RoadPair.first;
      if (!Junction.RoadHasConflicts(RoadId))
      {
        continue;
      }
      TArray<TSharedPtr<FJsonValue>> ConflictValues;
      for (const carla::road::RoadId Conflict : Junction.GetConflictsOfRoad(RoadId))
      {
        ConflictValues.Add(MakeShared<FJsonValueNumber>(Conflict));
      }
      Conflicts->SetArrayField(FString::FromInt(RoadId), ConflictValues);
    }
    Item->SetObjectField(TEXT("conflicting_roads"), Conflicts);
    Junctions.Add(MakeShared<FJsonValueObject>(Item));
  }

  CachedWorldId = WorldId;
  CachedStep = SamplingStep;
  BuildMilliseconds = (FPlatformTime::Seconds() - StartTime) * 1000.0;

  UE_LOG(LogCarla, Log,
      TEXT("DriscaApi: road graph built for world %llu, %d lanes, step %.2f m, %.1f ms"),
      static_cast<unsigned long long>(CachedWorldId), Lanes.Num(), SamplingStep,
      BuildMilliseconds);
  return true;
}

bool FDriscaRoadData::SerializePage(
    uint64 WorldId,
    const FString &MapName,
    int32 Start,
    int32 MaxLanes,
    TSharedPtr<FJsonObject> &OutResult,
    FString &OutError)
{
  if (Start < 0 || Start > Lanes.Num())
  {
    OutError = TEXT("cursor 超出车道范围");
    return false;
  }
  if (MaxLanes <= 0)
  {
    OutError = TEXT("max_lanes 必须是正数");
    return false;
  }

  const int32 Limit = FMath::Min(MaxLanes, 500);
  TArray<TSharedPtr<FJsonValue>> LaneArray;
  int32 Next = Start;
  int32 EstimatedBytes = 1024;

  while (Next < Lanes.Num() && LaneArray.Num() < Limit)
  {
    const FLaneNode &Lane = Lanes[Next];
    const int32 LaneEstimate = 900 + Lane.MarkSegments.Num() * 320 +
        Lane.Centerline.Num() * 160;
    if (LaneArray.Num() == 0 && LaneEstimate > PageByteBudget)
    {
      OutError = FString::Printf(
          TEXT("车道 %s 的中心线超过单条消息预算"), *Lane.Id);
      return false;
    }
    if (EstimatedBytes + LaneEstimate > PageByteBudget)
    {
      break;
    }
    EstimatedBytes += LaneEstimate;

    TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
    Item->SetStringField(TEXT("id"), Lane.Id);
    Item->SetNumberField(TEXT("road_id"), Lane.RoadId);
    Item->SetNumberField(TEXT("section_id"), Lane.SectionId);
    Item->SetNumberField(TEXT("lane_id"), Lane.LaneId);
    Item->SetStringField(TEXT("type"), Lane.TypeName);
    Item->SetNumberField(TEXT("type_value"), Lane.TypeValue);
    Item->SetNumberField(TEXT("length"), Lane.Length);
    Item->SetNumberField(TEXT("section_start_s"), Lane.SectionStartS);
    Item->SetBoolField(TEXT("is_junction"), Lane.bJunction);
    Item->SetBoolField(TEXT("is_positive_direction"), Lane.bPositiveDirection);
    if (Lane.bJunction)
    {
      Item->SetNumberField(TEXT("junction_id"), Lane.JunctionId);
    }
    else
    {
      Item->SetField(TEXT("junction_id"), MakeShared<FJsonValueNull>());
    }

    auto ToValues = [](const TArray<FString> &Entries)
    {
      TArray<TSharedPtr<FJsonValue>> Values;
      Values.Reserve(Entries.Num());
      for (const FString &Entry : Entries)
      {
        Values.Add(MakeShared<FJsonValueString>(Entry));
      }
      return Values;
    };
    Item->SetArrayField(TEXT("successors"), ToValues(Lane.Successors));
    Item->SetArrayField(TEXT("predecessors"), ToValues(Lane.Predecessors));
    if (Lane.LeftLane.IsEmpty())
    {
      Item->SetField(TEXT("left_lane"), MakeShared<FJsonValueNull>());
    }
    else
    {
      Item->SetStringField(TEXT("left_lane"), Lane.LeftLane);
    }
    if (Lane.RightLane.IsEmpty())
    {
      Item->SetField(TEXT("right_lane"), MakeShared<FJsonValueNull>());
    }
    else
    {
      Item->SetStringField(TEXT("right_lane"), Lane.RightLane);
    }
    Item->SetBoolField(TEXT("left_same_direction"), Lane.bLeftSameDirection);
    Item->SetBoolField(TEXT("right_same_direction"), Lane.bRightSameDirection);
    Item->SetBoolField(TEXT("left_allowed"), Lane.bLeftAllowed);
    Item->SetBoolField(TEXT("right_allowed"), Lane.bRightAllowed);
    Item->SetStringField(TEXT("lane_change"), LaneChangeToString(Lane.LaneChange));

    TArray<TSharedPtr<FJsonValue>> Segments;
    Segments.Reserve(Lane.MarkSegments.Num());
    for (const FMarkSegment &Segment : Lane.MarkSegments)
    {
      TSharedPtr<FJsonObject> ItemSegment = MakeShared<FJsonObject>();
      ItemSegment->SetNumberField(TEXT("s_start"), Segment.SStart);
      ItemSegment->SetNumberField(TEXT("s_end"), Segment.SEnd);
      ItemSegment->SetStringField(TEXT("lane_change"),
          LaneChangeToString(Segment.LaneChange));
      ItemSegment->SetBoolField(TEXT("left_allowed"), Segment.bLeftAllowed);
      ItemSegment->SetBoolField(TEXT("right_allowed"), Segment.bRightAllowed);

      auto MarkJson = [](const FMarkSide &Side)
      {
        TSharedPtr<FJsonObject> Mark = MakeShared<FJsonObject>();
        Mark->SetStringField(TEXT("type"), Side.Type);
        Mark->SetStringField(TEXT("color"), Side.Color);
        Mark->SetNumberField(TEXT("width"), Side.Width);
        return Mark;
      };
      ItemSegment->SetObjectField(TEXT("left_marking"), MarkJson(Segment.LeftMark));
      ItemSegment->SetObjectField(TEXT("right_marking"), MarkJson(Segment.RightMark));
      Segments.Add(MakeShared<FJsonValueObject>(ItemSegment));
    }
    Item->SetArrayField(TEXT("marking_segments"), Segments);

    TArray<TSharedPtr<FJsonValue>> Centerline;
    Centerline.Reserve(Lane.Centerline.Num());
    for (const FLaneSample &Sample : Lane.Centerline)
    {
      TSharedPtr<FJsonObject> ItemSample = MakeShared<FJsonObject>();
      ItemSample->SetNumberField(TEXT("s"), Sample.S);
      ItemSample->SetNumberField(TEXT("road_s"), Sample.RoadS);
      ItemSample->SetNumberField(TEXT("x"), Sample.Location.X);
      ItemSample->SetNumberField(TEXT("y"), Sample.Location.Y);
      ItemSample->SetNumberField(TEXT("z"), Sample.Location.Z);
      ItemSample->SetArrayField(TEXT("dir"), {
          MakeShared<FJsonValueNumber>(Sample.Direction.X),
          MakeShared<FJsonValueNumber>(Sample.Direction.Y),
          MakeShared<FJsonValueNumber>(Sample.Direction.Z)});
      ItemSample->SetNumberField(TEXT("width"), Sample.Width);
      Centerline.Add(MakeShared<FJsonValueObject>(ItemSample));
    }
    Item->SetArrayField(TEXT("centerline"), Centerline);

    LaneArray.Add(MakeShared<FJsonValueObject>(Item));
    ++Next;
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetStringField(TEXT("map_name"), MapName);
  Result->SetNumberField(TEXT("sampling_step"), CachedStep);
  Result->SetNumberField(TEXT("lane_count"), Lanes.Num());
  Result->SetNumberField(TEXT("cursor"), Next);
  Result->SetBoolField(TEXT("done"), Next >= Lanes.Num());
  Result->SetArrayField(TEXT("lanes"), LaneArray);

  // 预选之后再核对完整 JSON 的实际 UTF-8 字节数，超预算时缩页。
  while (true)
  {
    Result->SetArrayField(TEXT("lanes"), LaneArray);
    Result->SetNumberField(TEXT("cursor"), Next);
    Result->SetBoolField(TEXT("done"), Next >= Lanes.Num());

    FString Text;
    TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Result.ToSharedRef(), Writer))
    {
      OutError = TEXT("道路页序列化失败");
      return false;
    }
    const FTCHARToUTF8 Converter(*Text);
    if (Converter.Length() <= PageByteBudget)
    {
      OutResult = Result;
      return true;
    }

    if (LaneArray.Num() <= 1)
    {
      const FString LaneId = Next > 0 ? Lanes[Next - 1].Id : FString();
      OutError = FString::Printf(
          TEXT("车道 %s 的完整 JSON 超过单条消息预算"), *LaneId);
      return false;
    }

    LaneArray.Pop();
    --Next;
  }
}

bool FDriscaRoadData::SerializeJunctions(
    uint64 WorldId,
    const FString &MapName,
    TSharedPtr<FJsonObject> &OutResult,
    FString &OutError)
{
  if (CachedWorldId != WorldId)
  {
    OutResult = nullptr;
    OutError = TEXT("道路数据未构建");
    return false;
  }

  TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
  Result->SetNumberField(TEXT("world_id"), static_cast<double>(WorldId));
  Result->SetStringField(TEXT("map_name"), MapName);
  Result->SetArrayField(TEXT("junctions"), Junctions);
  OutResult = Result;
  return true;
}
