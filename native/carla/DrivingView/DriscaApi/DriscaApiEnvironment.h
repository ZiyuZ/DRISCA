#pragma once

#include "CoreMinimal.h"

class ALocalFogVolume;
class UWorld;
class FJsonObject;
struct FWeatherParameters;

namespace DriscaApi
{
  /// 全局环境的目标值；强度为无量纲值，角度使用度，距离使用米。
  struct FEnvironmentGlobalState
  {
    float SunAzimuthDegrees = 0.0f;
    float SunElevationDegrees = 75.0f;
    float Cloudiness = 0.0f;
    float Rain = 0.0f;
    float Wind = 0.0f;
    float Wetness = 0.0f;
    float Puddles = 0.0f;
    float Dust = 0.0f;
    float FogDensity = 0.0f;
    float FogDistanceMeters = 0.0f;
    float FogHeightFalloff = 0.2f;
    float LightScattering = 1.0f;
    float MieScattering = 0.003996f;
    float RayleighScattering = 0.0331f;

    static FEnvironmentGlobalState FromAuthoredWeather(const FWeatherParameters &Defaults);
    TSharedPtr<FJsonObject> ToJson() const;
    static FEnvironmentGlobalState Interpolate(
        const FEnvironmentGlobalState &From, const FEnvironmentGlobalState &To, float Alpha);
  };

  /// 固定世界空间球雾；无量纲密度经半径归一化，保持原生径向软边。
  struct FEnvironmentRegionState
  {
    FVector Center = FVector::ZeroVector;
    float RadiusMeters = 1.0f;
    float FogDensity = 0.0f;
  };

  struct FEnvironmentRegion
  {
    uint32 Id = 0;
    int64 OwnerConnection = -1;
    bool bSessionOwned = false;
    bool bDeleting = false;
    TWeakObjectPtr<ALocalFogVolume> Actor;
    FEnvironmentRegionState Current;
    FEnvironmentRegionState Start;
    FEnvironmentRegionState Target;
    double StartTime = 0.0;
    double Duration = 0.0;
    TOptional<int32> RequestId;
    TOptional<int32> OperationIndex;
    FString Source;
    FString Action;

    bool Create(UWorld *World, const FEnvironmentRegionState &Initial);
    void BeginTransition(const FEnvironmentRegionState &NewTarget, double Now, double Seconds);
    bool Advance(double Now);
    void Destroy();

  private:
    void Apply() const;
  };
}
