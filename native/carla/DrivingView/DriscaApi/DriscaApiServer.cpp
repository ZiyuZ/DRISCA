#include "DriscaApiServer.h"

#include "DriscaApiTypes.h"
#include "DriscaBoost.h"

#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <string>

#include "Carla.h"

namespace
{
  namespace beast = boost::beast;
  namespace http = beast::http;
  namespace websocket = beast::websocket;
  namespace asio = boost::asio;
  using tcp = asio::ip::tcp;

  constexpr int32 MaxOutboxBytes = 8 * 1024 * 1024;

  std::string ToUtf8(const FString &Text)
  {
    FTCHARToUTF8 Converter(*Text);
    return std::string(Converter.Get(), Converter.Length());
  }

  FString FromUtf8(const std::string &Text)
  {
    FUTF8ToTCHAR Converter(Text.data(), Text.size());
    return FString(Converter.Length(), Converter.Get());
  }
}

struct FDriscaWsConnection : std::enable_shared_from_this<FDriscaWsConnection>
{
  explicit FDriscaWsConnection(tcp::socket &&InSocket, int64 InId)
    : Ws(std::move(InSocket)), Id(InId)
  {
  }

  websocket::stream<tcp::socket> Ws;
  beast::flat_buffer Buffer;
  std::deque<std::string> Outbox;
  std::deque<bool> OutboxBinary;
  std::string CurrentWrite;
  bool bWriting = false;
  bool bClosed = false;
  bool bCloseAfterFlush = false;
  int32 CloseCode = 1000;
  std::string CloseReason;
  int64 Id = 0;
  size_t QueuedBytes = 0;
};

class FDriscaApiServerImpl
{
public:

  explicit FDriscaApiServerImpl(FDriscaApiServer &InOwner)
    : Owner(InOwner)
  {
  }

  ~FDriscaApiServerImpl()
  {
    Stop();
  }

  bool Start(int32 Port, FString &OutError)
  {
    beast::error_code Ec;
    tcp::endpoint Endpoint(asio::ip::address_v4::loopback(),
        static_cast<unsigned short>(Port));
    Acceptor.open(Endpoint.protocol(), Ec);
    if (Ec)
    {
      OutError = FString::Printf(
          TEXT("cannot open WebSocket port %d: %hs"), Port, Ec.message().c_str());
      return false;
    }

    Acceptor.set_option(asio::socket_base::reuse_address(true), Ec);
    Acceptor.bind(Endpoint, Ec);
    if (Ec)
    {
      OutError = FString::Printf(
          TEXT("cannot bind WebSocket port %d: %hs"), Port, Ec.message().c_str());
      Acceptor.close(Ec);
      return false;
    }

    Acceptor.listen(asio::socket_base::max_listen_connections, Ec);
    if (Ec)
    {
      OutError = FString::Printf(
          TEXT("cannot listen on WebSocket port %d: %hs"), Port, Ec.message().c_str());
      Acceptor.close(Ec);
      return false;
    }

    DoAccept();
    return true;
  }

  void Stop()
  {
    beast::error_code Ec;
    Acceptor.close(Ec);
    for (auto &Pair : Connections)
    {
      std::shared_ptr<FDriscaWsConnection> Conn = Pair.second;
      Conn->bClosed = true;
      beast::error_code CloseEc;
      Conn->Ws.next_layer().close(CloseEc);
    }
    Connections.clear();
    PendingCloses.Reset();
    Io.stop();
    Io.restart();
  }

  void Poll()
  {
    Io.poll();

    // 关闭通知在回调之外执行，避免持有者在回调里再次操作该连接。
    TArray<int64> Closed;
    Closed.Append(PendingCloses.Array());
    PendingCloses.Reset();
    for (int64 Id : Closed)
    {
      if (Owner.OnClosed)
      {
        Owner.OnClosed(Id);
      }
    }
  }

  void Send(int64 ConnectionId, bool bBinary, std::string Message)
  {
    std::shared_ptr<FDriscaWsConnection> Conn = Find(ConnectionId);
    if (!Conn || Conn->bClosed || Conn->bCloseAfterFlush)
    {
      return;
    }

    if (Conn->QueuedBytes + Message.size() > MaxOutboxBytes)
    {
      UE_LOG(LogCarla, Error,
          TEXT("DriscaApi: connection %lld is not reading, closing"), ConnectionId);
      Fail(Conn);
      return;
    }

    Conn->QueuedBytes += Message.size();
    Conn->Outbox.push_back(std::move(Message));
    Conn->OutboxBinary.push_back(bBinary);
    DoWrite(Conn);
  }

  void Close(int64 ConnectionId, int32 Code, const FString &Reason)
  {
    std::shared_ptr<FDriscaWsConnection> Conn = Find(ConnectionId);
    if (!Conn || Conn->bClosed)
    {
      return;
    }

    Conn->bClosed = true;
    websocket::close_reason ReasonCode(
        static_cast<websocket::close_code>(Code), ToUtf8(Reason));
    std::weak_ptr<FDriscaWsConnection> Weak = Conn;
    Conn->Ws.async_close(ReasonCode, [this, Weak, ConnectionId](
        beast::error_code Ec)
    {
      if (auto Locked = Weak.lock())
      {
        beast::error_code CloseEc;
        Locked->Ws.next_layer().close(CloseEc);
      }
      Connections.erase(ConnectionId);
      PendingCloses.Add(ConnectionId);
    });
  }

  void CloseAfterFlush(int64 ConnectionId, int32 Code, const FString &Reason)
  {
    std::shared_ptr<FDriscaWsConnection> Conn = Find(ConnectionId);
    if (!Conn || Conn->bClosed || Conn->bCloseAfterFlush)
    {
      return;
    }
    Conn->bCloseAfterFlush = true;
    Conn->CloseCode = Code;
    Conn->CloseReason = ToUtf8(Reason);
    DoWrite(Conn);
  }

private:

  std::shared_ptr<FDriscaWsConnection> Find(int64 ConnectionId)
  {
    auto It = Connections.find(ConnectionId);
    return It == Connections.end() ? nullptr : It->second;
  }

  void DoAccept()
  {
    Acceptor.async_accept([this](beast::error_code Ec, tcp::socket Socket)
    {
      if (Ec)
      {
        if (Ec != asio::error::operation_aborted)
        {
          UE_LOG(LogCarla, Warning,
              TEXT("DriscaApi: accept failed: %hs"), Ec.message().c_str());
          DoAccept();
        }
        return;
      }

      // 本机低延迟命令及 JSON/二进制双响应均立即发送，避免 Nagle 等待 ACK。
      Socket.set_option(tcp::no_delay(true), Ec);
      if (Ec)
      {
        UE_LOG(LogCarla, Error, TEXT("DriscaApi: TCP_NODELAY 设置失败：%hs"), Ec.message().c_str());
        DoAccept();
        return;
      }
      auto SocketPtr = std::make_shared<tcp::socket>(std::move(Socket));
      auto BufferPtr = std::make_shared<beast::flat_buffer>();
      auto RequestPtr = std::make_shared<http::request<http::string_body>>();
      http::async_read(*SocketPtr, *BufferPtr, *RequestPtr,
          [this, SocketPtr, BufferPtr, RequestPtr](
              beast::error_code ReadEc, size_t)
      {
        if (ReadEc)
        {
          beast::error_code CloseEc;
          SocketPtr->close(CloseEc);
          DoAccept();
          return;
        }

        const std::string Target = std::string(RequestPtr->target());
        const std::string Path = Target.substr(0, Target.find('?'));
        if (Path != "/drisca/v1")
        {
          auto Response = std::make_shared<http::response<http::string_body>>(
              http::status::not_found, RequestPtr->version());
          Response->set(http::field::content_type, "text/plain");
          Response->body() = "unknown endpoint";
          Response->prepare_payload();
          http::async_write(*SocketPtr, *Response,
              [SocketPtr, Response](beast::error_code, size_t)
          {
            beast::error_code CloseEc;
            SocketPtr->close(CloseEc);
          });
          DoAccept();
          return;
        }

        const int64 Id = NextConnectionId++;
        auto Conn = std::make_shared<FDriscaWsConnection>(std::move(*SocketPtr), Id);
        Conn->Ws.set_option(websocket::stream_base::timeout::suggested(
            beast::role_type::server));
        Conn->Ws.set_option(websocket::stream_base::decorator(
            [](websocket::response_type &Response)
        {
          Response.set(http::field::server, "drisca-native-api/1");
        }));
        Conn->Ws.read_message_max(DriscaApi::MaxMessageBytes);
        // 快照作为单个 WebSocket 帧提交，减少分片引入的异步写完成往返。
        Conn->Ws.auto_fragment(false);

        Conn->Ws.async_accept(*RequestPtr,
            [this, Conn](beast::error_code AcceptEc)
        {
          if (AcceptEc)
          {
            Conn->bClosed = true;
            beast::error_code CloseEc;
            Conn->Ws.next_layer().close(CloseEc);
            PendingCloses.Add(Conn->Id);
            return;
          }

          Connections[Conn->Id] = Conn;
          UE_LOG(LogCarla, Log, TEXT("DriscaApi: client %lld connected"), Conn->Id);
          DoRead(Conn);
        });
      });

      DoAccept();
    });
  }

  void DoRead(const std::shared_ptr<FDriscaWsConnection> &Conn)
  {
    if (Conn->bClosed)
    {
      return;
    }

    Conn->Ws.async_read(Conn->Buffer,
        [this, Conn](beast::error_code Ec, size_t)
    {
      if (Ec)
      {
        Fail(Conn);
        return;
      }

      if (Conn->Ws.got_binary())
      {
        // 客户端发二进制属于协议错误。
        Conn->Buffer.consume(Conn->Buffer.size());
        Owner.SendText(Conn->Id, TEXT(
            "{\"id\":0,\"ok\":false,\"error\":{\"code\":\"invalid_request\","
            "\"message\":\"binary messages are not accepted\"}}"));
        Close(Conn->Id, websocket::close_code::protocol_error,
            TEXT("binary messages are not accepted"));
        return;
      }

      std::string Text = beast::buffers_to_string(Conn->Buffer.data());
      Conn->Buffer.consume(Conn->Buffer.size());

      if (Owner.OnMessage)
      {
        Owner.OnMessage(Conn->Id, FromUtf8(Text));
      }

      DoRead(Conn);
    });
  }

  void DoWrite(const std::shared_ptr<FDriscaWsConnection> &Conn)
  {
    if (Conn->bClosed || Conn->bWriting)
    {
      return;
    }
    if (Conn->Outbox.empty())
    {
      if (Conn->bCloseAfterFlush)
      {
        Close(Conn->Id, Conn->CloseCode, FromUtf8(Conn->CloseReason));
      }
      return;
    }

    Conn->bWriting = true;
    Conn->CurrentWrite = std::move(Conn->Outbox.front());
    Conn->Outbox.pop_front();
    const bool bBinary = Conn->OutboxBinary.front();
    Conn->OutboxBinary.pop_front();
    Conn->QueuedBytes -= Conn->CurrentWrite.size();

    Conn->Ws.binary(bBinary);
    Conn->Ws.async_write(asio::buffer(Conn->CurrentWrite),
        [this, Conn](beast::error_code Ec, size_t)
    {
      Conn->bWriting = false;
      if (Ec)
      {
        Fail(Conn);
        return;
      }
      DoWrite(Conn);
    });
  }

  void Fail(const std::shared_ptr<FDriscaWsConnection> &Conn)
  {
    if (Conn->bClosed)
    {
      return;
    }
    Conn->bClosed = true;
    Conn->Outbox.clear();
    Conn->OutboxBinary.clear();
    Conn->QueuedBytes = 0;
    beast::error_code Ec;
    Conn->Ws.next_layer().close(Ec);
    Connections.erase(Conn->Id);
    PendingCloses.Add(Conn->Id);
  }

  FDriscaApiServer &Owner;
  asio::io_context Io;
  tcp::acceptor Acceptor{Io};
  std::map<int64, std::shared_ptr<FDriscaWsConnection>> Connections;
  TSet<int64> PendingCloses;
  int64 NextConnectionId = 1;
};

FDriscaApiServer::FDriscaApiServer()
  : Impl(MakeUnique<FDriscaApiServerImpl>(*this))
{
}

FDriscaApiServer::~FDriscaApiServer() = default;

bool FDriscaApiServer::Start(int32 Port, FString &OutError)
{
  if (bRunning)
  {
    return true;
  }
  bRunning = Impl->Start(Port, OutError);
  return bRunning;
}

void FDriscaApiServer::Stop()
{
  if (!bRunning)
  {
    return;
  }
  Impl->Stop();
  bRunning = false;
}

void FDriscaApiServer::Poll()
{
  if (bRunning)
  {
    Impl->Poll();
  }
}

void FDriscaApiServer::SendText(int64 ConnectionId, const FString &Message)
{
  if (bRunning)
  {
    Impl->Send(ConnectionId, false, ToUtf8(Message));
  }
}

void FDriscaApiServer::SendBinary(int64 ConnectionId, const TArray<uint8> &Message)
{
  if (bRunning)
  {
    std::string Bytes(reinterpret_cast<const char *>(Message.GetData()), Message.Num());
    Impl->Send(ConnectionId, true, std::move(Bytes));
  }
}

void FDriscaApiServer::Close(int64 ConnectionId, int32 Code, const FString &Reason)
{
  if (bRunning)
  {
    Impl->Close(ConnectionId, Code, Reason);
  }
}

void FDriscaApiServer::CloseAfterFlush(
    int64 ConnectionId, int32 Code, const FString &Reason)
{
  if (bRunning)
  {
    Impl->CloseAfterFlush(ConnectionId, Code, Reason);
  }
}
