#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class ACarlaGameModeBase;
class UCarlaEpisode;
class UWorld;

struct FTrafficOperationResult
{
  bool bSuccess = false;
  FString ErrorCode;
  FString ErrorMessage;
  TSharedPtr<FJsonObject> Result;
  FString EventName;
  TSharedPtr<FJsonObject> EventPayload;
};

/// 信号静态关联与运行期状态。静态数据按世界构建一次。
class FDriscaTrafficLights
{
public:

  bool Build(
      ACarlaGameModeBase &GameMode,
      UCarlaEpisode &Episode,
      uint64 WorldId,
      FString &OutError);

  bool IsBuilt(uint64 WorldId) const;
  void Invalidate();

  bool SerializeSignals(
      uint64 WorldId,
      const FString &MapName,
      TSharedPtr<FJsonObject> &OutResult,
      FString &OutError);

  void BuildRuntime(
      UWorld &World,
      TArray<TSharedPtr<FJsonValue>> &OutLights,
      TArray<TSharedPtr<FJsonValue>> &OutControllers) const;

  bool ApplyOperation(
      const FString &Method,
      const TSharedPtr<FJsonObject> &Params,
      UWorld &World,
      FTrafficOperationResult &OutResult);

private:

  TArray<TSharedPtr<FJsonValue>> Signals;
  TArray<TSharedPtr<FJsonValue>> Controllers;
  TSharedPtr<FJsonObject> Unmapped;
  uint64 CachedWorldId = 0;
};
