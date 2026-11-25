#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "DrivingViewStateComponent.generated.h"

class ADrivingViewPawn;

/// 在物理推进之后汇总驾驶状态。
///
/// 输入在 Pawn 的 PrePhysics tick 中采集并写入车辆，位姿与速度要等物理完成后才有意义，
/// 因此状态由这个组件在 TG_PostPhysics 读取，帧号对应这一帧刚结束的世界帧。
UCLASS(ClassGroup = (Carla), meta = (BlueprintSpawnableComponent))
class UDrivingViewStateComponent : public UActorComponent
{
  GENERATED_BODY()

public:

  UDrivingViewStateComponent();

  virtual void BeginPlay() override;
  virtual void TickComponent(
      float DeltaTime,
      ELevelTick TickType,
      FActorComponentTickFunction *ThisTickFunction) override;

private:

  UPROPERTY()
  TObjectPtr<ADrivingViewPawn> ViewPawn = nullptr;
};
