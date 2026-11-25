#include "Carla/DrivingView/DriscaApi/DriscaApiEnvironment.h"

#include "Components/LocalFogVolumeComponent.h"
#include "Engine/LocalFogVolume.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Kismet/GameplayStatics.h"
#include "Carla/Weather/Weather.h"
#include "Carla.h"

namespace DriscaApi
{
  FEnvironmentGlobalState FEnvironmentGlobalState::Interpolate(
      const FEnvironmentGlobalState &From, const FEnvironmentGlobalState &To, float Alpha)
  {
    FEnvironmentGlobalState Value;
    float AzimuthDelta = FMath::Fmod(To.SunAzimuthDegrees - From.SunAzimuthDegrees + 360.0f, 360.0f);
    if (AzimuthDelta > 180.0f) AzimuthDelta -= 360.0f;
    Value.SunAzimuthDegrees = FMath::Fmod(From.SunAzimuthDegrees + AzimuthDelta * Alpha + 360.0f, 360.0f);
    Value.SunElevationDegrees = FMath::Lerp(From.SunElevationDegrees, To.SunElevationDegrees, Alpha);
    Value.Cloudiness = FMath::Lerp(From.Cloudiness, To.Cloudiness, Alpha);
    Value.Rain = FMath::Lerp(From.Rain, To.Rain, Alpha);
    Value.Wind = FMath::Lerp(From.Wind, To.Wind, Alpha);
    Value.Wetness = FMath::Lerp(From.Wetness, To.Wetness, Alpha);
    Value.Puddles = FMath::Lerp(From.Puddles, To.Puddles, Alpha);
    Value.Dust = FMath::Lerp(From.Dust, To.Dust, Alpha);
    Value.FogDensity = FMath::Lerp(From.FogDensity, To.FogDensity, Alpha);
    Value.FogDistanceMeters = FMath::Lerp(From.FogDistanceMeters, To.FogDistanceMeters, Alpha);
    Value.FogHeightFalloff = FMath::Lerp(From.FogHeightFalloff, To.FogHeightFalloff, Alpha);
    Value.LightScattering = FMath::Lerp(From.LightScattering, To.LightScattering, Alpha);
    Value.MieScattering = FMath::Lerp(From.MieScattering, To.MieScattering, Alpha);
    Value.RayleighScattering = FMath::Lerp(From.RayleighScattering, To.RayleighScattering, Alpha);
    return Value;
  }

  bool FEnvironmentRegion::Create(UWorld *World, const FEnvironmentRegionState &Initial)
  {
    IConsoleManager &Console = IConsoleManager::Get();
    IConsoleVariable *Support = Console.FindConsoleVariable(TEXT("r.SupportLocalFogVolumes"));
    IConsoleVariable *Enabled = Console.FindConsoleVariable(TEXT("r.LocalFogVolume"));
    IConsoleVariable *Voxelize = Console.FindConsoleVariable(TEXT("r.LocalFogVolume.RenderIntoVolumetricFog"));
    if (!Support || Support->GetInt() == 0 || !Enabled || !Voxelize)
    {
      UE_LOG(LogCarla, Error, TEXT("局部雾渲染支持不可用，请检查 r.SupportLocalFogVolumes"));
      return false;
    }
    // 球雾使用独立解析积分路径，避免质量级别改变体积雾网格及其距离裁剪。
    Enabled->Set(1, ECVF_SetByCode);
    Voxelize->Set(0, ECVF_SetByCode);
    if (IConsoleVariable *StartDist =
            IConsoleManager::Get().FindConsoleVariable(TEXT("r.LocalFogVolume.GlobalStartDistance")))
    {
      if (StartDist->GetFloat() > 10.0f)
        StartDist->Set(10.0f, ECVF_SetByCode);
      UE_LOG(LogCarla, Log, TEXT("局部雾：支持=%d 启用=%d 体积网格注入=%d 起始距离=%.2fcm 优先级=0x%x"),
          Support->GetInt(), Enabled->GetInt(), Voxelize->GetInt(), StartDist->GetFloat(),
          static_cast<uint32>(StartDist->GetFlags() & ECVF_SetByMask));
    }
    if (Enabled->GetInt() != 1 || Voxelize->GetInt() != 0)
    {
      UE_LOG(LogCarla, Error, TEXT("局部雾渲染设置被更高优先级控制台配置覆盖"));
      return false;
    }
    FActorSpawnParameters Params;
    Params.ObjectFlags |= RF_Transient;
    ALocalFogVolume *Volume = World->SpawnActor<ALocalFogVolume>(Params);
    if (Volume == nullptr)
      return false;
    Actor = Volume;
    Current = Start = Target = Initial;
    // UE LocalFogVolume 以覆盖率交集 (1-TR)*(1-TH) 组合径向与高度雾；高度雾为 0 会导致整体不可见。
    // 将高度项设为球内均匀饱和，使球雾外观完全由径向消光控制。
    ULocalFogVolumeComponent *Component = Volume->GetComponent();
    if (!Component->IsRegistered())
    {
      UE_LOG(LogCarla, Error, TEXT("局部雾组件未注册"));
      Volume->Destroy();
      Actor.Reset();
      return false;
    }
    Component->SetHeightFogFalloff(1.0f);
    Component->SetHeightFogOffset(2.0f);
    Component->SetHeightFogExtinction(50.0f);
    Apply();
    UE_LOG(LogCarla, Log, TEXT("局部雾已创建：中心=%s 半径=%.2fm 径向消光=%.3f 可见=%d"),
        *Initial.Center.ToString(), Initial.RadiusMeters, Component->RadialFogExtinction,
        Component->IsVisible());
    return true;
  }

  void FEnvironmentRegion::BeginTransition(
      const FEnvironmentRegionState &NewTarget, double Now, double Seconds)
  {
    Advance(Now);
    Start = Current;
    Target = NewTarget;
    StartTime = Now;
    Duration = Seconds;
    if (Duration == 0.0)
    {
      Current = Target;
      Apply();
    }
  }

  bool FEnvironmentRegion::Advance(double Now)
  {
    if (Duration <= 0.0)
      return false;
    const float Alpha = static_cast<float>(FMath::Clamp((Now - StartTime) / Duration, 0.0, 1.0));
    Current.Center = FMath::Lerp(Start.Center, Target.Center, Alpha);
    Current.RadiusMeters = FMath::Lerp(Start.RadiusMeters, Target.RadiusMeters, Alpha);
    Current.FogDensity = FMath::Lerp(Start.FogDensity, Target.FogDensity, Alpha);
    Apply();
    if (Alpha >= 1.0f)
    {
      Duration = 0.0;
      return true;
    }
    return false;
  }

  void FEnvironmentRegion::Apply() const
  {
    ALocalFogVolume *Volume = Actor.Get();
    check(Volume != nullptr);
    Volume->SetActorLocation(Current.Center * 100.0);
    Volume->SetActorScale3D(FVector(Current.RadiusMeters / 5.0f));
    // UE 径向分布为 1-r²/R²，解析积分还会乘以半径（米）。固定消光会让大球
    // 几乎处处饱和，形成明显轮廓。归一化后，穿过球心的完整光学厚度为
    // density*4（半径至少 2 米时），边缘继续按原生径向积分平滑趋零。
    const float RadialExtinction = Current.FogDensity * 4.0f /
        FMath::Max(Current.RadiusMeters, 2.0f);
    Volume->GetComponent()->SetRadialFogExtinction(RadialExtinction);
  }

  void FEnvironmentRegion::Destroy()
  {
    if (ALocalFogVolume *Volume = Actor.Get())
      Volume->Destroy();
    Actor.Reset();
  }
}

#include "DriscaApiSubsystem.h"
#include "DriscaApiInternals.h"
#include "Dom/JsonValue.h"

namespace
{
  TSharedPtr<FJsonObject> RegionStateJson(const DriscaApi::FEnvironmentRegionState &State)
  {
    TSharedPtr<FJsonObject> Value = MakeShared<FJsonObject>();
    Value->SetArrayField(TEXT("center_m"), DriscaApiInternal::VectorToJson(State.Center));
    Value->SetNumberField(TEXT("radius_m"), State.RadiusMeters);
    TSharedPtr<FJsonObject> Fog = MakeShared<FJsonObject>();
    Fog->SetNumberField(TEXT("density"), State.FogDensity);
    TSharedPtr<FJsonObject> Weather = MakeShared<FJsonObject>();
    Weather->SetObjectField(TEXT("fog"), Fog);
    Value->SetObjectField(TEXT("weather"), Weather);
    return Value;
  }

  TSharedPtr<FJsonObject> RegionJson(const DriscaApi::FEnvironmentRegion &Region, double Now)
  {
    TSharedPtr<FJsonObject> Value = MakeShared<FJsonObject>();
    Value->SetNumberField(TEXT("region_id"), Region.Id);
    Value->SetObjectField(TEXT("current"), RegionStateJson(Region.Current));
    Value->SetObjectField(TEXT("target"), RegionStateJson(Region.Target));
    Value->SetBoolField(TEXT("deleting"), Region.bDeleting);
    Value->SetNumberField(TEXT("remaining_seconds"),
        FMath::Max(0.0, Region.Duration - (Now - Region.StartTime)));
    return Value;
  }
}

void UDriscaApiSubsystem::ClearEnvironment(int64 ConnectionId, bool bSession)
{
  if (bSession && GlobalDuration > 0)
  {
    auto Payload = GlobalEnvironmentJson(EnvironmentWorld.IsValid() ? EnvironmentWorld->GetTimeSeconds() : 0);
    Payload->SetStringField(TEXT("operation"), GlobalAction);
    Payload->SetStringField(TEXT("reason"), TEXT("session_ended"));
    EmitEvent(TEXT("environment_replaced"), GlobalSource, Payload, GlobalRequestId, GlobalOperationIndex);
    GlobalTarget = GlobalStart = GlobalCurrent;
    GlobalDuration = 0;
  }
  for (auto It = EnvironmentRegions.CreateIterator(); It; ++It)
  {
    auto &Region = It.Value();
    if ((bSession && Region.bSessionOwned) ||
        (!bSession && (ConnectionId < 0 || (!Region.bSessionOwned && Region.OwnerConnection == ConnectionId))))
    {
      Region.Destroy();
      It.RemoveCurrent();
    }
  }
}

void UDriscaApiSubsystem::TickEnvironment()
{
  UWorld *World = CurrentWorld.Get();
  if (World == nullptr) return;
  const double Now = World->GetTimeSeconds();
  if (EnvironmentWorld.Get() == World)
  {
    AdvanceGlobalEnvironment(Now);
    if (AWeather *Renderer = Cast<AWeather>(UGameplayStatics::GetActorOfClass(World, AWeather::StaticClass())))
      Renderer->MaintainEnvironment();
  }
  for (auto It = EnvironmentRegions.CreateIterator(); It; ++It)
  {
    auto &Region = It.Value();
    if (Region.Advance(Now))
    {
      auto Payload = RegionJson(Region, Now);
      Payload->SetStringField(TEXT("operation"), Region.Action);
      EmitEvent(TEXT("environment_completed"), Region.Source, Payload,
          Region.RequestId, Region.OperationIndex);
      if (Region.bDeleting)
      {
        Region.Destroy();
        It.RemoveCurrent();
      }
    }
  }
}

bool UDriscaApiSubsystem::ExecuteEnvironment(const FString &Method, int64 ConnectionId,
    int32 RequestId, int32 OperationIndex, const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult)
{
  using namespace DriscaApiInternal;
  UWorld *World = CurrentWorld.Get();
  if (World == nullptr)
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = TEXT("世界尚未就绪");
    return false;
  }
  TickEnvironment();
  const double Now = World->GetTimeSeconds();
  if (Method == TEXT("environment.apply") ||
      ((Method == TEXT("environment.get") || Method == TEXT("environment.update")) &&
          !Params->HasField(TEXT("region_id"))))
    return ExecuteGlobalEnvironment(Method, ConnectionId, RequestId, OperationIndex, Params, OutResult);
  if (Method == TEXT("environment.list"))
  {
    for (const auto &Field : Params->Values)
      if (Field.Key != TEXT("world_id") && Field.Key != TEXT("session_id"))
      { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("列表参数无效"); return false; }
    TArray<uint32> Ids;
    EnvironmentRegions.GetKeys(Ids);
    Ids.Sort();
    TArray<TSharedPtr<FJsonValue>> Items;
    for (uint32 Id : Ids)
      Items.Add(MakeShared<FJsonValueObject>(RegionJson(EnvironmentRegions[Id], Now)));
    OutResult.Result = MakeShared<FJsonObject>();
    OutResult.Result->SetArrayField(TEXT("regions"), Items);
    OutResult.SampledFrameNo = CurrentFrameNo();
    return true;
  }
  const bool bCreate = Method == TEXT("environment.create");
  const bool bGet = Method == TEXT("environment.get");
  const bool bUpdate = Method == TEXT("environment.update");
  const bool bDelete = Method == TEXT("environment.delete");
  if (!bCreate && !bGet && !bUpdate && !bDelete)
  {
    OutResult.ErrorCode = CodeUnsupported;
    OutResult.ErrorMessage = TEXT("环境操作尚未支持");
    return false;
  }
  for (const auto &Field : Params->Values)
  {
    const auto &Key = Field.Key;
    if (Key == TEXT("world_id") || Key == TEXT("session_id") ||
        (Key == TEXT("region_id") && !bCreate) ||
        (Key == TEXT("transition_seconds") && !bGet) ||
        ((Key == TEXT("center_m") || Key == TEXT("radius_m") || Key == TEXT("weather")) && (bCreate || bUpdate)))
      continue;
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("不支持的环境字段");
    return false;
  }
  uint32 Id = 0;
  DriscaApi::FEnvironmentRegion *Region = nullptr;
  if (!bCreate)
  {
    if (bGet && !Params->HasField(TEXT("region_id")))
    { OutResult.ErrorCode = CodeUnsupported; OutResult.ErrorMessage = TEXT("全局环境尚未支持"); return false; }
    double RawId = 0;
    if (!Params->TryGetNumberField(TEXT("region_id"), RawId) || !FMath::IsFinite(RawId) ||
        RawId < 1 || RawId > MAX_uint32 || FMath::FloorToDouble(RawId) != RawId)
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("region_id 无效"); return false; }
    Id = static_cast<uint32>(RawId);
    Region = EnvironmentRegions.Find(Id);
    if (!Region) { OutResult.ErrorCode = CodeNotFound; OutResult.ErrorMessage = TEXT("区域不存在"); return false; }
    if (bGet)
    {
      OutResult.Result = RegionJson(*Region, Now);
      OutResult.SampledFrameNo = CurrentFrameNo();
      return true;
    }
    if (Region->bDeleting)
    { OutResult.ErrorCode = CodeInvalidState; OutResult.ErrorMessage = TEXT("区域正在删除"); return false; }
  }
  double Duration = 0;
  if (Params->HasField(TEXT("transition_seconds")) &&
      (!Params->TryGetNumberField(TEXT("transition_seconds"), Duration) || !FMath::IsFinite(Duration) || Duration < 0))
  { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("渐变时长无效"); return false; }
  DriscaApi::FEnvironmentRegionState Target = bCreate ? DriscaApi::FEnvironmentRegionState() : Region->Target;
  if (!bDelete)
  {
    auto Center = Params->TryGetField(TEXT("center_m"));
    if ((bCreate && !Center.IsValid()) || (Center.IsValid() &&
        (Center->Type != EJson::Array || Center->AsArray().Num() != 3)))
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("center_m 无效"); return false; }
    if (Center.IsValid())
    {
      const auto &Array = Center->AsArray();
      for (const auto &Value : Array)
        if (!Value.IsValid() || Value->Type != EJson::Number || !FMath::IsFinite(Value->AsNumber()))
        { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("center_m 无效"); return false; }
      Target.Center = FVector(Array[0]->AsNumber(), Array[1]->AsNumber(), Array[2]->AsNumber());
    }
    double Radius = Target.RadiusMeters;
    if ((bCreate || Params->HasField(TEXT("radius_m"))) &&
        (!Params->TryGetNumberField(TEXT("radius_m"), Radius) || !FMath::IsFinite(Radius) || Radius <= 0 || Radius > 100000))
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("radius_m 无效"); return false; }
    Target.RadiusMeters = static_cast<float>(Radius);
    const TSharedPtr<FJsonObject> *Weather = nullptr;
    if ((bCreate || Params->HasField(TEXT("weather"))) &&
        (!Params->TryGetObjectField(TEXT("weather"), Weather) || !Weather || !Weather->IsValid() || (*Weather)->Values.Num() == 0))
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("weather 无效"); return false; }
    const TSharedPtr<FJsonObject> *Fog = nullptr;
    if (Weather)
      for (const auto &Field : (*Weather)->Values)
        if (Field.Key != TEXT("fog"))
        { OutResult.ErrorCode = CodeUnsupported; OutResult.ErrorMessage = TEXT("该天气通道尚未支持"); return false; }
    if (Weather && (!(*Weather)->TryGetObjectField(TEXT("fog"), Fog) || !Fog || !Fog->IsValid() || (*Fog)->Values.Num() != 1))
    { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("fog 无效"); return false; }
    if (Fog)
    {
      double Density = 0;
      if (!(*Fog)->TryGetNumberField(TEXT("density"), Density) || !FMath::IsFinite(Density) || Density < 0 || Density > 1)
      { OutResult.ErrorCode = CodeInvalidRequest; OutResult.ErrorMessage = TEXT("雾密度无效"); return false; }
      Target.FogDensity = static_cast<float>(Density);
    }
  }
  else Target.FogDensity = 0;
  if (bCreate)
  {
    if (NextEnvironmentRegionId == 0)
    { OutResult.ErrorCode = CodeOperationFailed; OutResult.ErrorMessage = TEXT("区域编号耗尽"); return false; }
    Id = NextEnvironmentRegionId++;
    DriscaApi::FEnvironmentRegion Entry;
    Entry.Id = Id;
    Entry.OwnerConnection = ConnectionId;
    Entry.bSessionOwned = Session.bActive;
    auto Initial = Target;
    if (Duration > 0) Initial.FogDensity = 0;
    if (!Entry.Create(World, Initial))
    { OutResult.ErrorCode = CodeOperationFailed; OutResult.ErrorMessage = TEXT("创建球雾失败"); return false; }
    Region = &EnvironmentRegions.Add(Id, MoveTemp(Entry));
  }
  else
  {
    Region->Advance(Now);
    if (Region->Duration > 0)
    {
      auto Replaced = RegionJson(*Region, Now);
      Replaced->SetStringField(TEXT("operation"), Region->Action);
      Replaced->SetNumberField(TEXT("new_request_id"), RequestId);
      Replaced->SetNumberField(TEXT("new_operation_index"), OperationIndex);
      Replaced->SetStringField(TEXT("new_operation"), bDelete ? TEXT("delete") : TEXT("update"));
      Replaced->SetObjectField(TEXT("new_target"), RegionStateJson(Target));
      EmitEvent(TEXT("environment_replaced"), Region->Source, Replaced,
          Region->RequestId, Region->OperationIndex);
    }
  }
  auto Previous = RegionStateJson(Region->Current);
  Region->bDeleting = bDelete;
  Region->BeginTransition(Target, Now, Duration);
  Region->RequestId = RequestId;
  Region->OperationIndex = OperationIndex;
  Region->Source = GetConnectionSource(ConnectionId);
  Region->Action = bCreate ? TEXT("create") : (bDelete ? TEXT("delete") : TEXT("update"));
  OutResult.Result = RegionJson(*Region, Now);
  auto Payload = RegionJson(*Region, Now);
  Payload->SetObjectField(TEXT("previous"), Previous);
  Payload->SetNumberField(TEXT("transition_seconds"), Duration);
  Payload->SetStringField(TEXT("operation"), Region->Action);
  EmitEvent(TEXT("environment_applied"), Region->Source, Payload, RequestId, OperationIndex);
  if (bDelete && Duration == 0)
  {
    Region->Destroy();
    EnvironmentRegions.Remove(Id);
  }
  return true;
}


// 全局环境由 API 控制器持有；FWeatherParameters 仅为现有材质执行层的投影。
namespace
{
  TSharedPtr<FJsonObject> GlobalWeatherJson(const DriscaApi::FEnvironmentGlobalState &State)
  {
    auto Value = MakeShared<FJsonObject>();
    auto Sun = MakeShared<FJsonObject>();
    Sun->SetNumberField(TEXT("azimuth_deg"), State.SunAzimuthDegrees);
    Sun->SetNumberField(TEXT("elevation_deg"), State.SunElevationDegrees);
    Value->SetObjectField(TEXT("sun"), Sun);
    Value->SetNumberField(TEXT("cloudiness"), State.Cloudiness);
    Value->SetNumberField(TEXT("wind"), State.Wind);
    Value->SetNumberField(TEXT("dust"), State.Dust);
    auto Precipitation = MakeShared<FJsonObject>();
    Precipitation->SetNumberField(TEXT("rain"), State.Rain);
    Precipitation->SetNumberField(TEXT("snow"), 0);
    Value->SetObjectField(TEXT("precipitation"), Precipitation);
    auto Surface = MakeShared<FJsonObject>();
    Surface->SetNumberField(TEXT("wetness"), State.Wetness);
    Surface->SetNumberField(TEXT("puddles"), State.Puddles);
    Value->SetObjectField(TEXT("surface"), Surface);
    auto Fog = MakeShared<FJsonObject>();
    Fog->SetNumberField(TEXT("density"), State.FogDensity);
    Fog->SetNumberField(TEXT("distance_m"), State.FogDistanceMeters);
    Fog->SetNumberField(TEXT("height_falloff"), State.FogHeightFalloff);
    Value->SetObjectField(TEXT("fog"), Fog);
    auto Scattering = MakeShared<FJsonObject>();
    Scattering->SetNumberField(TEXT("light"), State.LightScattering);
    Scattering->SetNumberField(TEXT("mie"), State.MieScattering);
    Scattering->SetNumberField(TEXT("rayleigh"), State.RayleighScattering);
    Value->SetObjectField(TEXT("scattering"), Scattering);
    return Value;
  }

  bool ParseGlobalWeather(const TSharedPtr<FJsonObject> &Object, bool bComplete,
      DriscaApi::FEnvironmentGlobalState &Target, FString &Error, bool &bUnsupported)
  {
    struct FField
    {
      const TCHAR *Group;
      const TCHAR *Key;
      float DriscaApi::FEnvironmentGlobalState::*Member;
      double Minimum;
      double Maximum;
    };
    static const FField Fields[] = {
      {TEXT("sun"), TEXT("azimuth_deg"), &DriscaApi::FEnvironmentGlobalState::SunAzimuthDegrees, 0, 360},
      {TEXT("sun"), TEXT("elevation_deg"), &DriscaApi::FEnvironmentGlobalState::SunElevationDegrees, -90, 90},
      {nullptr, TEXT("cloudiness"), &DriscaApi::FEnvironmentGlobalState::Cloudiness, 0, 1},
      {nullptr, TEXT("wind"), &DriscaApi::FEnvironmentGlobalState::Wind, 0, 1},
      {nullptr, TEXT("dust"), &DriscaApi::FEnvironmentGlobalState::Dust, 0, 1},
      {TEXT("precipitation"), TEXT("rain"), &DriscaApi::FEnvironmentGlobalState::Rain, 0, 1},
      {TEXT("surface"), TEXT("wetness"), &DriscaApi::FEnvironmentGlobalState::Wetness, 0, 1},
      {TEXT("surface"), TEXT("puddles"), &DriscaApi::FEnvironmentGlobalState::Puddles, 0, 1},
      {TEXT("fog"), TEXT("density"), &DriscaApi::FEnvironmentGlobalState::FogDensity, 0, 100},
      {TEXT("fog"), TEXT("distance_m"), &DriscaApi::FEnvironmentGlobalState::FogDistanceMeters, 0, 1000000},
      {TEXT("fog"), TEXT("height_falloff"), &DriscaApi::FEnvironmentGlobalState::FogHeightFalloff, 0, 10000},
      {TEXT("scattering"), TEXT("light"), &DriscaApi::FEnvironmentGlobalState::LightScattering, 0, 1000},
      {TEXT("scattering"), TEXT("mie"), &DriscaApi::FEnvironmentGlobalState::MieScattering, 0, 1000},
      {TEXT("scattering"), TEXT("rayleigh"), &DriscaApi::FEnvironmentGlobalState::RayleighScattering, 0, 1000}
    };
    if (Object->Values.IsEmpty())
    {
      Error = TEXT("weather 至少需要一个字段");
      return false;
    }
    for (const auto &Pair : Object->Values)
    {
      bool bKnown = false;
      bool bGroup = false;
      for (const FField &Field : Fields)
      {
        if (Pair.Key == (Field.Group ? Field.Group : Field.Key))
        {
          bKnown = true;
          bGroup = Field.Group != nullptr;
          break;
        }
      }
      if (!bKnown)
      {
        Error = FString::Printf(TEXT("未知全局天气字段：%s"), *Pair.Key);
        return false;
      }
      if (bGroup)
      {
        if (Pair.Value->Type != EJson::Object || Pair.Value->AsObject()->Values.IsEmpty())
        {
          Error = FString::Printf(TEXT("%s 必须是非空对象"), *Pair.Key);
          return false;
        }
        for (const auto &Child : Pair.Value->AsObject()->Values)
        {
          bool bKnownChild = Pair.Key == TEXT("precipitation") && Child.Key == TEXT("snow");
          for (const FField &Field : Fields)
            bKnownChild |= Field.Group && Pair.Key == Field.Group && Child.Key == Field.Key;
          if (!bKnownChild)
          {
            Error = FString::Printf(TEXT("未知全局天气字段：%s.%s"), *Pair.Key, *Child.Key);
            return false;
          }
        }
      }
    }
    for (const FField &Field : Fields)
    {
      const TSharedPtr<FJsonObject> *Group = nullptr;
      const FJsonObject *Container = Object.Get();
      if (Field.Group)
      {
        if (!Object->TryGetObjectField(Field.Group, Group))
        {
          if (!bComplete) continue;
          Error = FString::Printf(TEXT("完整天气缺少 %s"), Field.Group);
          return false;
        }
        Container = Group->Get();
      }
      if (!Container->HasField(Field.Key) && !bComplete) continue;
      double Number = 0;
      const auto NumberValue = Container->TryGetField(Field.Key);
      if (!NumberValue.IsValid() || NumberValue->Type != EJson::Number ||
          !Container->TryGetNumberField(Field.Key, Number) || !FMath::IsFinite(Number) ||
          Number < Field.Minimum ||
          (Field.Member != &DriscaApi::FEnvironmentGlobalState::FogDensity && Number > Field.Maximum) ||
          !FMath::IsFinite(static_cast<float>(Number)) ||
          (Field.Member == &DriscaApi::FEnvironmentGlobalState::SunAzimuthDegrees && Number == 360))
      {
        Error = FString::Printf(TEXT("天气字段缺失或超出范围：%s%s%s"),
            Field.Group ? Field.Group : TEXT(""), Field.Group ? TEXT(".") : TEXT(""), Field.Key);
        return false;
      }
      Target.*(Field.Member) = static_cast<float>(Number);
      if (Field.Member == &DriscaApi::FEnvironmentGlobalState::FogDensity && Number > 20)
        UE_LOG(LogCarla, Warning, TEXT("全局雾密度 %.6g 超过 20，仍按请求应用"), Number);
    }
    const TSharedPtr<FJsonObject> *Precipitation = nullptr;
    if (Object->TryGetObjectField(TEXT("precipitation"), Precipitation) &&
        (*Precipitation)->HasField(TEXT("snow")))
    {
      double Snow = 0;
      if (!(*Precipitation)->TryGetNumberField(TEXT("snow"), Snow) || !FMath::IsFinite(Snow) || Snow < 0 || Snow > 1)
      {
        Error = TEXT("snow 必须是 0 至 1 的有限数值");
        return false;
      }
      if (Snow != 0)
      {
        bUnsupported = true;
        Error = TEXT("当前尚未制作雪效资源，snow 只能为 0");
        return false;
      }
    }
    return true;
  }

  FWeatherParameters RenderProjection(const DriscaApi::FEnvironmentGlobalState &State)
  {
    FWeatherParameters Value;
    Value.SunAzimuthAngle = State.SunAzimuthDegrees;
    Value.SunAltitudeAngle = State.SunElevationDegrees;
    Value.Cloudiness = State.Cloudiness * 100.0f;
    Value.Precipitation = State.Rain * 100.0f;
    Value.WindIntensity = State.Wind * 100.0f;
    Value.Wetness = State.Wetness * 100.0f;
    Value.PrecipitationDeposits = State.Puddles * 100.0f;
    Value.DustStorm = State.Dust * 100.0f;
    // 此副本仅供天空曲线与材质输入；实际雾密度另以 UE 原生数值写入。
    Value.FogDensity = State.FogDensity * 100.0f;
    Value.FogDistance = State.FogDistanceMeters;
    Value.FogFalloff = State.FogHeightFalloff;
    Value.ScatteringIntensity = State.LightScattering;
    Value.MieScatteringScale = State.MieScattering;
    Value.RayleighScatteringScale = State.RayleighScattering;
    return Value;
  }
}

void UDriscaApiSubsystem::InitializeEnvironment(UWorld *World, const FWeatherParameters &Defaults)
{
  if (EnvironmentWorld.Get() == World) return;
  EnvironmentWorld = World;
  GlobalCurrent = DriscaApi::FEnvironmentGlobalState::FromAuthoredWeather(Defaults);
  GlobalStart = GlobalTarget = GlobalCurrent;
  GlobalDuration = 0;
  GlobalRequestId.Reset();
  GlobalOperationIndex.Reset();
  GlobalSource.Empty();
  GlobalAction.Empty();
  EnvironmentError.Empty();
  RenderGlobalEnvironment(EnvironmentError);
}

bool UDriscaApiSubsystem::RenderGlobalEnvironment(FString &Error)
{
  UWorld *World = EnvironmentWorld.Get();
  AWeather *Renderer = World ? Cast<AWeather>(UGameplayStatics::GetActorOfClass(World, AWeather::StaticClass())) : nullptr;
  if (!Renderer)
  {
    Error = TEXT("当前地图缺少天气渲染执行器");
    return false;
  }
  return Renderer->RenderEnvironment(RenderProjection(GlobalCurrent), GlobalCurrent.FogDensity, Error);
}

TSharedPtr<FJsonObject> UDriscaApiSubsystem::GlobalEnvironmentJson(double Now) const
{
  auto Value = MakeShared<FJsonObject>();
  Value->SetField(TEXT("region_id"), MakeShared<FJsonValueNull>());
  auto Current = MakeShared<FJsonObject>();
  Current->SetObjectField(TEXT("weather"), GlobalWeatherJson(GlobalCurrent));
  auto Target = MakeShared<FJsonObject>();
  Target->SetObjectField(TEXT("weather"), GlobalWeatherJson(GlobalTarget));
  Value->SetObjectField(TEXT("current"), Current);
  Value->SetObjectField(TEXT("target"), Target);
  Value->SetNumberField(TEXT("remaining_seconds"), FMath::Max(0.0, GlobalDuration - (Now - GlobalStartTime)));
  Value->SetBoolField(TEXT("deleting"), false);
  return Value;
}

void UDriscaApiSubsystem::AdvanceGlobalEnvironment(double Now)
{
  if (GlobalDuration <= 0.0) return;
  const float Alpha = static_cast<float>(FMath::Clamp((Now - GlobalStartTime) / GlobalDuration, 0.0, 1.0));
  GlobalCurrent = DriscaApi::FEnvironmentGlobalState::Interpolate(GlobalStart, GlobalTarget, Alpha);
  if (!RenderGlobalEnvironment(EnvironmentError))
  {
    GlobalDuration = 0;
    RequestFatal(TEXT("operation_failed"), EnvironmentError);
    return;
  }
  if (Alpha >= 1.0f)
  {
    GlobalDuration = 0;
    auto Payload = GlobalEnvironmentJson(Now);
    Payload->SetStringField(TEXT("operation"), GlobalAction);
    EmitEvent(TEXT("environment_completed"), GlobalSource, Payload, GlobalRequestId, GlobalOperationIndex);
  }
}

bool UDriscaApiSubsystem::ExecuteGlobalEnvironment(const FString &Method, int64 ConnectionId,
    int32 RequestId, int32 OperationIndex, const TSharedPtr<FJsonObject> &Params,
    DriscaApi::FOperationResult &OutResult)
{
  using namespace DriscaApiInternal;
  if (EnvironmentWorld.Get() != CurrentWorld.Get() || !EnvironmentError.IsEmpty())
  {
    OutResult.ErrorCode = CodeInvalidState;
    OutResult.ErrorMessage = EnvironmentError.IsEmpty() ? TEXT("全局环境尚未初始化") : EnvironmentError;
    return false;
  }
  const bool bGet = Method == TEXT("environment.get");
  for (const auto &Field : Params->Values)
  {
    if (Field.Key == TEXT("world_id") || Field.Key == TEXT("session_id") ||
        (!bGet && (Field.Key == TEXT("weather") || Field.Key == TEXT("transition_seconds")))) continue;
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("全局环境参数包含未知字段");
    return false;
  }
  const double Now = CurrentWorld->GetTimeSeconds();
  if (bGet)
  {
    OutResult.Result = GlobalEnvironmentJson(Now);
    OutResult.SampledFrameNo = CurrentFrameNo();
    return true;
  }
  const TSharedPtr<FJsonObject> *Weather = nullptr;
  if (!Params->TryGetObjectField(TEXT("weather"), Weather))
  {
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("缺少 weather 对象");
    return false;
  }
  DriscaApi::FEnvironmentGlobalState Target = GlobalTarget;
  FString Error;
  bool bUnsupported = false;
  if (!ParseGlobalWeather(*Weather, Method == TEXT("environment.apply"), Target, Error, bUnsupported))
  {
    OutResult.ErrorCode = bUnsupported ? CodeUnsupported : CodeInvalidRequest;
    OutResult.ErrorMessage = Error;
    return false;
  }
  double Duration = 0;
  if (Params->HasField(TEXT("transition_seconds")) &&
      (!Params->TryGetNumberField(TEXT("transition_seconds"), Duration) || !FMath::IsFinite(Duration) || Duration < 0))
  {
    OutResult.ErrorCode = CodeInvalidRequest;
    OutResult.ErrorMessage = TEXT("transition_seconds 必须是非负有限数值");
    return false;
  }
  if (GlobalDuration > 0)
  {
    auto Replaced = GlobalEnvironmentJson(Now);
    Replaced->SetStringField(TEXT("operation"), GlobalAction);
    Replaced->SetNumberField(TEXT("new_request_id"), RequestId);
    Replaced->SetNumberField(TEXT("new_operation_index"), OperationIndex);
    Replaced->SetStringField(TEXT("new_operation"), Method == TEXT("environment.apply") ? TEXT("apply") : TEXT("update"));
    auto NewTarget = MakeShared<FJsonObject>();
    NewTarget->SetObjectField(TEXT("weather"), GlobalWeatherJson(Target));
    Replaced->SetObjectField(TEXT("new_target"), NewTarget);
    EmitEvent(TEXT("environment_replaced"), GlobalSource, Replaced, GlobalRequestId, GlobalOperationIndex);
  }
  const auto Previous = GlobalEnvironmentJson(Now)->GetObjectField(TEXT("current"));
  GlobalStart = GlobalCurrent;
  GlobalTarget = Target;
  GlobalStartTime = Now;
  GlobalDuration = Duration;
  GlobalRequestId = RequestId;
  GlobalOperationIndex = OperationIndex;
  GlobalSource = GetConnectionSource(ConnectionId);
  GlobalAction = Method == TEXT("environment.apply") ? TEXT("apply") : TEXT("update");
  if (Duration == 0)
  {
    GlobalCurrent = Target;
    if (!RenderGlobalEnvironment(EnvironmentError))
    {
      OutResult.ErrorCode = CodeOperationFailed;
      OutResult.ErrorMessage = EnvironmentError;
      return false;
    }
  }
  auto Payload = GlobalEnvironmentJson(Now);
  Payload->SetStringField(TEXT("operation"), GlobalAction);
  Payload->SetObjectField(TEXT("previous"), Previous);
  Payload->SetNumberField(TEXT("transition_seconds"), Duration);
  EmitEvent(TEXT("environment_applied"), GlobalSource, Payload, RequestId, OperationIndex);
  OutResult.Result = GlobalEnvironmentJson(Now);
  return true;
}


DriscaApi::FEnvironmentGlobalState DriscaApi::FEnvironmentGlobalState::FromAuthoredWeather(
    const FWeatherParameters &Defaults)
{
  FEnvironmentGlobalState Value;
  Value.SunAzimuthDegrees = FMath::Fmod(Defaults.SunAzimuthAngle + 360.0f, 360.0f);
  Value.SunElevationDegrees = Defaults.SunAltitudeAngle;
  Value.Cloudiness = Defaults.Cloudiness / 100.0f;
  Value.Rain = Defaults.Precipitation / 100.0f;
  Value.Wind = Defaults.WindIntensity / 100.0f;
  Value.Wetness = Defaults.Wetness / 100.0f;
  Value.Puddles = Defaults.PrecipitationDeposits / 100.0f;
  Value.Dust = Defaults.DustStorm / 100.0f;
  // 地图默认值只在加载时转换一次；新 API 不使用 CARLA 的密度缩放。
  Value.FogDensity = Defaults.FogDensity * 0.001f;
  Value.FogDistanceMeters = Defaults.FogDistance;
  Value.FogHeightFalloff = Defaults.FogFalloff;
  Value.LightScattering = Defaults.ScatteringIntensity;
  Value.MieScattering = Defaults.MieScatteringScale;
  Value.RayleighScattering = Defaults.RayleighScatteringScale;
  return Value;
}

TSharedPtr<FJsonObject> DriscaApi::FEnvironmentGlobalState::ToJson() const
{
  return GlobalWeatherJson(*this);
}
