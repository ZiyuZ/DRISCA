#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class UCarlaEpisode;
class ACarlaGameModeBase;

/// 静态道路图：按世界构建一次，供 Python 本地建图与规划。
class FDriscaRoadData
{
public:

  bool Build(
      ACarlaGameModeBase &GameMode,
      uint64 WorldId,
      double SamplingStep,
      FString &OutError);

  bool IsBuilt(uint64 WorldId, double SamplingStep) const;
  bool IsWorldBuilt(uint64 WorldId) const
  {
    return CachedWorldId == WorldId;
  }
  void Invalidate();

  int32 GetLaneCount() const
  {
    return Lanes.Num();
  }

  double GetBuildMilliseconds() const
  {
    return BuildMilliseconds;
  }

  bool SerializePage(
      uint64 WorldId,
      const FString &MapName,
      int32 Start,
      int32 MaxLanes,
      TSharedPtr<FJsonObject> &OutResult,
      FString &OutError);

  bool SerializeJunctions(
      uint64 WorldId,
      const FString &MapName,
      TSharedPtr<FJsonObject> &OutResult,
      FString &OutError);

private:

  struct FMarkSide
  {
    FString Type;
    FString Color;
    float Width = 0.0f;
  };

  struct FMarkSegment
  {
    double SStart = 0.0;
    double SEnd = 0.0;
    int32 LaneChange = 0;
    bool bLeftAllowed = false;
    bool bRightAllowed = false;
    FMarkSide LeftMark;
    FMarkSide RightMark;
  };

  struct FLaneSample
  {
    double S = 0.0;
    double RoadS = 0.0;
    FVector Location = FVector::ZeroVector;
    FVector Direction = FVector::ZeroVector;
    float Width = 0.0f;
  };

  struct FLaneNode
  {
    FString Id;
    int32 RoadId = 0;
    int32 SectionId = 0;
    int32 LaneId = 0;
    int32 TypeValue = 0;
    FString TypeName;
    double Length = 0.0;
    double SectionStartS = 0.0;
    double SectionEndS = 0.0;
    bool bPositiveDirection = true;
    bool bJunction = false;
    int32 JunctionId = 0;
    TArray<FString> Successors;
    TArray<FString> Predecessors;
    FString LeftLane;
    FString RightLane;
    bool bLeftSameDirection = false;
    bool bRightSameDirection = false;
    int32 LaneChange = 0;
    bool bLeftAllowed = false;
    bool bRightAllowed = false;
    TArray<FMarkSegment> MarkSegments;
    TArray<FLaneSample> Centerline;
  };

  TArray<FLaneNode> Lanes;
  TArray<TSharedPtr<FJsonValue>> Junctions;
  uint64 CachedWorldId = 0;
  double CachedStep = 0.0;
  double BuildMilliseconds = 0.0;
};
