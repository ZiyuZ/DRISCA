#include "DrivingViewStateComponent.h"

#include "DrivingViewPawn.h"

UDrivingViewStateComponent::UDrivingViewStateComponent()
{
  PrimaryComponentTick.bCanEverTick = true;
  PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UDrivingViewStateComponent::BeginPlay()
{
  Super::BeginPlay();
  ViewPawn = Cast<ADrivingViewPawn>(GetOwner());
}

void UDrivingViewStateComponent::TickComponent(
    float DeltaTime,
    ELevelTick TickType,
    FActorComponentTickFunction *ThisTickFunction)
{
  Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
  if (ViewPawn != nullptr)
  {
    ViewPawn->UpdateState(DeltaTime);
  }
}
