#pragma once

#include "CoreMinimal.h"

struct FDrivingViewCamera
{
  float X = 0.0f;
  float Y = 0.0f;
  float Z = 0.0f;
  float Pitch = 0.0f;
  float Yaw = 0.0f;
  float Roll = 0.0f;
  float Fov = 90.0f;
};

struct FDrivingViewBox
{
  FVector Location = FVector::ZeroVector;
  FVector Extent = FVector::ZeroVector;
  FRotator Rotation = FRotator::ZeroRotator;
};

struct FDrivingViewViewport
{
  FVector2D ScreenPosition = FVector2D(0.5f, 0.5f);
  FIntPoint ImageSize = FIntPoint(320, 150);
  bool bVisible = true;
};

struct FDrivingViewLayout
{
  bool bShowRearview = true;
  float BorderWidth = 2.0f;
  FLinearColor BorderColor = FLinearColor::Black;
  FDrivingViewViewport RearTop;
  FDrivingViewViewport RearLeft;
  FDrivingViewViewport RearRight;
};

struct FDrivingViewInput
{
  float Throttle = 0.0f;
  float Steer = 0.0f;
  float Brake = 0.0f;
  bool bReverse = false;
  bool bHandBrake = false;
  bool bManualGearShift = false;
  int32 Gear = 0;
  bool bTakeoverRequested = false;
  bool bToggleAutopilotRequested = false;
};

struct FDrivingViewMirror
{
  FVector2D ScreenPosition = FVector2D(0.5f, 0.5f);
  FIntPoint ImageSize = FIntPoint(320, 150);
  bool bVisible = true;
  float BorderWidth = 0.0f;
  FLinearColor BorderColor = FLinearColor::Black;
  class UTextureRenderTarget2D *RenderTarget = nullptr;
  class USceneCaptureComponent2D *Capture = nullptr;
};

struct FDrivingViewState
{
  double Timestamp = 0.0;
  double WallTime = 0.0;
  int64 FrameNo = 0;
  double Delta = 0.0;
  FDrivingViewInput Input;
  FDrivingViewInput Control;
  FVector Location = FVector::ZeroVector;
  FRotator Rotation = FRotator::ZeroRotator;
  FVector Velocity = FVector::ZeroVector;
  FString Mode = TEXT("manual");
  bool bActive = false;
  bool bReady = false;
  FString Error;
};
