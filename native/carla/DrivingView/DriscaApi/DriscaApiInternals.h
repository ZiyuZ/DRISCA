#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

#include "Carla/Actor/ActorDefinition.h"
#include "Carla/Actor/ActorDescription.h"
#include "Carla/Actor/ActorInfo.h"
#include "Carla/Actor/CarlaActor.h"
#include "Carla/Game/CarlaEpisode.h"
#include "Carla/Util/BoundingBox.h"

/// DriscaApi 各源文件共用的小工具。
///
/// 模块使用 Unity 构建，同一个翻译单元里会合并多个 .cpp，
/// 因此这些函数统一放在这里，避免匿名命名空间重复定义。
namespace DriscaApiInternal
{
  inline const TCHAR *CodeInvalidRequest = TEXT("invalid_request");
  inline const TCHAR *CodeInvalidState = TEXT("invalid_state");
  inline const TCHAR *CodeNotFound = TEXT("not_found");
  inline const TCHAR *CodeUnsupported = TEXT("unsupported");
  inline const TCHAR *CodeWorldChanged = TEXT("world_changed");
  inline const TCHAR *CodeOperationFailed = TEXT("operation_failed");
  inline const TCHAR *CodeVersionMismatch = TEXT("version_mismatch");

  inline TArray<TSharedPtr<FJsonValue>> VectorToJson(const FVector &Value)
  {
    return {
        MakeShared<FJsonValueNumber>(Value.X),
        MakeShared<FJsonValueNumber>(Value.Y),
        MakeShared<FJsonValueNumber>(Value.Z)};
  }

  inline TArray<TSharedPtr<FJsonValue>> RotatorToJson(const FRotator &Value)
  {
    return {
        MakeShared<FJsonValueNumber>(Value.Pitch),
        MakeShared<FJsonValueNumber>(Value.Yaw),
        MakeShared<FJsonValueNumber>(Value.Roll)};
  }

  inline bool ReadVector(const TSharedPtr<FJsonValue> &Value, FVector &OutVector)
  {
    if (!Value.IsValid() || Value->Type != EJson::Array)
    {
      return false;
    }
    const TArray<TSharedPtr<FJsonValue>> &Array = Value->AsArray();
    if (Array.Num() != 3)
    {
      return false;
    }
    for (const auto &Element : Array)
    {
      if (!Element.IsValid() || Element->Type != EJson::Number ||
          !FMath::IsFinite(Element->AsNumber())) return false;
    }
    OutVector = FVector(
        Array[0]->AsNumber(), Array[1]->AsNumber(), Array[2]->AsNumber());
    return true;
  }

  inline bool ReadRotator(
      const TSharedPtr<FJsonValue> &Value, FRotator &OutRotation)
  {
    FVector Vector;
    if (!ReadVector(Value, Vector))
    {
      return false;
    }
    OutRotation = FRotator(Vector.X, Vector.Y, Vector.Z);
    return true;
  }

  inline bool ReadTransform(
      const TSharedPtr<FJsonObject> &Object, FTransform &OutTransform)
  {
    FVector Location = FVector::ZeroVector;
    FRotator Rotation = FRotator::ZeroRotator;
    const TSharedPtr<FJsonValue> LocationValue = Object->TryGetField(TEXT("location"));
    if (LocationValue.IsValid() && !ReadVector(LocationValue, Location))
    {
      return false;
    }
    const TSharedPtr<FJsonValue> RotationValue = Object->TryGetField(TEXT("rotation"));
    if (RotationValue.IsValid() && !ReadRotator(RotationValue, Rotation))
    {
      return false;
    }
    OutTransform = FTransform(Rotation, Location * 100.0, FVector::OneVector);
    return true;
  }

  inline TSharedPtr<FJsonObject> BoundingBoxToJson(const FBoundingBox &Box)
  {
    TSharedPtr<FJsonObject> Location = MakeShared<FJsonObject>();
    Location->SetNumberField(TEXT("x"), Box.Origin.X * 0.01f);
    Location->SetNumberField(TEXT("y"), Box.Origin.Y * 0.01f);
    Location->SetNumberField(TEXT("z"), Box.Origin.Z * 0.01f);

    TSharedPtr<FJsonObject> Extent = MakeShared<FJsonObject>();
    Extent->SetNumberField(TEXT("x"), Box.Extent.X * 0.01f);
    Extent->SetNumberField(TEXT("y"), Box.Extent.Y * 0.01f);
    Extent->SetNumberField(TEXT("z"), Box.Extent.Z * 0.01f);

    TSharedPtr<FJsonObject> Rotation = MakeShared<FJsonObject>();
    Rotation->SetNumberField(TEXT("pitch"), Box.Rotation.Pitch);
    Rotation->SetNumberField(TEXT("yaw"), Box.Rotation.Yaw);
    Rotation->SetNumberField(TEXT("roll"), Box.Rotation.Roll);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetObjectField(TEXT("location"), Location);
    Result->SetObjectField(TEXT("extent"), Extent);
    Result->SetObjectField(TEXT("rotation"), Rotation);
    return Result;
  }

  inline TSharedPtr<FJsonObject> TransformToJson(const FTransform &Transform)
  {
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetArrayField(TEXT("location"),
        VectorToJson(Transform.GetLocation() * 0.01));
    Result->SetArrayField(TEXT("rotation"), RotatorToJson(Transform.Rotator()));
    return Result;
  }

  inline const TArray<FActorDefinition> &GetDefinitions(UCarlaEpisode &Episode)
  {
    return Episode.GetActorDefinitions();
  }

  inline const FActorDefinition *FindDefinition(
      UCarlaEpisode &Episode, const FString &Id)
  {
    for (const FActorDefinition &Definition : GetDefinitions(Episode))
    {
      if (Definition.Id == Id)
      {
        return &Definition;
      }
    }
    return nullptr;
  }

  inline FActorDescription MakeDescription(
      const FActorDefinition &Definition,
      const TMap<FString, FString> &Overrides)
  {
    FActorDescription Description;
    Description.UId = Definition.UId;
    Description.Id = Definition.Id;
    Description.Class = Definition.Class;

    for (const FActorVariation &Variation : Definition.Variations)
    {
      FActorAttribute Attribute;
      Attribute.Id = Variation.Id;
      Attribute.Type = Variation.Type;
      Attribute.Value = Variation.RecommendedValues.Num() > 0
          ? Variation.RecommendedValues[0]
          : FString();
      Description.Variations.Add(Attribute.Id, Attribute);
    }
    for (const FActorAttribute &Attribute : Definition.Attributes)
    {
      Description.Variations.Add(Attribute.Id, Attribute);
    }
    for (const TPair<FString, FString> &Pair : Overrides)
    {
      FActorAttribute Attribute = Description.Variations.FindRef(Pair.Key);
      Attribute.Id = Pair.Key;
      Attribute.Value = Pair.Value;
      Description.Variations.Add(Pair.Key, Attribute);
    }
    return Description;
  }

  inline TSharedPtr<FJsonObject> DescribeActor(FCarlaActor &Actor)
  {
    AActor *Object = Actor.GetActor();
    const FActorInfo *Info = Actor.GetActorInfo();
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("actor_id"), Actor.GetActorId());
    Result->SetStringField(
        TEXT("blueprint"), Info != nullptr ? Info->Description.Id : FString());
    Result->SetArrayField(TEXT("location"), VectorToJson(
        Object != nullptr ? Object->GetActorLocation() * 0.01 : FVector::ZeroVector));
    Result->SetArrayField(TEXT("rotation"), RotatorToJson(
        Object != nullptr ? Object->GetActorRotation() : FRotator::ZeroRotator));
    if (Info != nullptr)
    {
      Result->SetObjectField(TEXT("bounding_box"),
          BoundingBoxToJson(Info->BoundingBox));

      TSharedPtr<FJsonObject> Attributes = MakeShared<FJsonObject>();
      FString RoleName;
      for (const TPair<FString, FActorAttribute> &Pair : Info->Description.Variations)
      {
        Attributes->SetStringField(Pair.Key, Pair.Value.Value);
        if (Pair.Key == TEXT("role_name"))
        {
          RoleName = Pair.Value.Value;
        }
      }
      Result->SetStringField(TEXT("role_name"), RoleName);
      Result->SetObjectField(TEXT("attributes"), Attributes);
    }
    return Result;
  }

  inline FVector RotateYaw(float YawDegrees, const FVector &Location)
  {
    const float Yaw = FMath::DegreesToRadians(YawDegrees);
    const float Cosine = FMath::Cos(Yaw);
    const float Sine = FMath::Sin(Yaw);
    return FVector(
        Cosine * Location.X - Sine * Location.Y,
        Sine * Location.X + Cosine * Location.Y,
        Location.Z);
  }

  inline const TCHAR *LightName(uint32 Bit)
  {
    switch (Bit)
    {
      case 0x1:
        return TEXT("position");
      case 0x2:
        return TEXT("low_beam");
      case 0x4:
        return TEXT("high_beam");
      case 0x8:
        return TEXT("brake");
      case 0x10:
        return TEXT("right_blinker");
      case 0x20:
        return TEXT("left_blinker");
      case 0x40:
        return TEXT("reverse");
      case 0x80:
        return TEXT("fog");
      case 0x100:
        return TEXT("interior");
      case 0x200:
        return TEXT("special1");
      case 0x400:
        return TEXT("special2");
      default:
        return nullptr;
    }
  }
}
