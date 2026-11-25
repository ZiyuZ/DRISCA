#pragma once

#include "CoreMinimal.h"

class FDriscaApiServerImpl;

/// 本机 WebSocket 服务：负责消息分帧、文本/二进制收发和连接生命周期。
///
/// 网络推进由持有者每帧调用 Poll，所有回调都在游戏线程执行。
class FDriscaApiServer
{
public:

  FDriscaApiServer();
  ~FDriscaApiServer();

  FDriscaApiServer(const FDriscaApiServer &) = delete;
  FDriscaApiServer &operator=(const FDriscaApiServer &) = delete;

  bool Start(int32 Port, FString &OutError);
  void Stop();
  void Poll();

  void SendText(int64 ConnectionId, const FString &Message);
  void SendBinary(int64 ConnectionId, const TArray<uint8> &Message);
  void Close(int64 ConnectionId, int32 Code, const FString &Reason);
  /// 发送队列清空后再关闭，保证错误响应能先送达。
  void CloseAfterFlush(int64 ConnectionId, int32 Code, const FString &Reason);

  bool IsRunning() const
  {
    return bRunning;
  }

  /// 收到一条完整文本消息。
  TFunction<void(int64 ConnectionId, const FString &Message)> OnMessage;

  /// 连接已断开（对端关闭、读写失败或本地关闭）。
  TFunction<void(int64 ConnectionId)> OnClosed;

private:

  TUniquePtr<FDriscaApiServerImpl> Impl;
  bool bRunning = false;
};
