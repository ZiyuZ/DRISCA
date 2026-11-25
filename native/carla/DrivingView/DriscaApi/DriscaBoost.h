#pragma once

// Boost 头文件与 UE 宏冲突（例如 mp11 用 check 作标识符），因此统一在
// CARLA 提供的宏屏蔽区间内引入，再恢复 UE 宏。需要新的 Boost 能力时在
// 这个文件里补充，其他源文件不要直接包含 Boost 头文件。
#include "CoreMinimal.h"

#include <util/disable-ue4-macros.h>
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/core/flat_buffer.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>
#include <util/enable-ue4-macros.h>
