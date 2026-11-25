"""管理端桌面与服务入口。"""

import ctypes
import socket
import threading
import time
from contextlib import ExitStack
from ctypes import wintypes
from typing import TYPE_CHECKING, Any, cast

from drisca.core.config import initialize_configs, load_machine_config
from drisca.core.paths import PROJECT_ROOT
from drisca.launcher.cli import execute, parser
from drisca.launcher.dev import frontend_dev_server

if TYPE_CHECKING:
    import uvicorn


_GWL_WNDPROC = -4
_GWL_STYLE = -16
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WM_NCCALCSIZE = 0x0083
_WM_NCLBUTTONDOWN = 0x00A1
_SWP_FRAMECHANGED = 0x0020
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
)

_RESIZE_HIT_TEST: dict[str, int] = {
    'left': 10,  # HTLEFT
    'right': 11,  # HTRIGHT
    'top': 12,  # HTTOP
    'top-left': 13,  # HTTOPLEFT
    'top-right': 14,  # HTTOPRIGHT
    'bottom': 15,  # HTBOTTOM
    'bottom-left': 16,  # HTBOTTOMLEFT
    'bottom-right': 17,  # HTBOTTOMRIGHT
}


def _user32() -> Any:
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    return user32


class WindowBridge:
    def __init__(self, server: uvicorn.Server) -> None:
        self._server = server
        self._window: Any = None
        self._maximized = False
        self._closing = False
        self._hwnd: int | None = None
        self._orig_wndproc: int | None = None
        self._wndproc: Any = None

    def _on_shown(self) -> None:
        """为无边框 WinForms 窗口启用原生 WS_THICKFRAME 缩放并消除非客户区白边。"""
        assert self._window is not None
        native = getattr(self._window, 'native', None)
        if native is None:
            return
        user32 = _user32()
        hwnd = int(native.Handle.ToInt64())
        style = int(user32.GetWindowLongPtrW(hwnd, _GWL_STYLE))
        style |= _WS_THICKFRAME | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
        user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style)

        def wndproc(h: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == _WM_NCCALCSIZE and wparam == 1:
                return 0
            assert self._orig_wndproc is not None
            return int(user32.CallWindowProcW(self._orig_wndproc, h, msg, wparam, lparam))

        callback = _WNDPROC(wndproc)
        proc_ptr = ctypes.cast(callback, ctypes.c_void_p).value
        assert proc_ptr is not None
        self._hwnd = hwnd
        self._wndproc = callback
        self._orig_wndproc = int(user32.SetWindowLongPtrW(hwnd, _GWL_WNDPROC, proc_ptr))
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
        )

    def _restore_wndproc(self) -> None:
        if self._hwnd is not None and self._orig_wndproc is not None:
            try:
                _user32().SetWindowLongPtrW(self._hwnd, _GWL_WNDPROC, self._orig_wndproc)
            except Exception:
                pass
            self._orig_wndproc = None

    def start_resize(self, edge: str) -> None:
        """由前端八方向边缘热区触发原生 Win32 窗口拖拽缩放（必须调度到 WinForms UI 线程）。"""
        hit = _RESIZE_HIT_TEST.get(edge)
        if hit is None or self._hwnd is None or self._maximized or self._window is None:
            return
        native = getattr(self._window, 'native', None)
        if native is None:
            return
        from System import Action  # ty: ignore[import-not-found]

        hwnd = self._hwnd

        def _invoke() -> None:
            user32 = _user32()
            user32.ReleaseCapture()
            user32.PostMessageW(hwnd, _WM_NCLBUTTONDOWN, hit, 0)

        native.BeginInvoke(Action(_invoke))

    def minimize_window(self) -> None:
        assert self._window is not None
        self._window.minimize()

    def toggle_maximize(self) -> None:
        assert self._window is not None
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized

    def close_window(self) -> None:
        assert self._window is not None
        if self._closing:
            return
        self._closing = True
        self._restore_wndproc()
        self._server.should_exit = True
        self._window.destroy()

    def _on_closing(self) -> bool:
        self._restore_wndproc()
        self._server.should_exit = True
        self._closing = True
        return True


def main() -> None:
    args = parser().parse_args()
    initialize_configs()
    if args.command:
        raise SystemExit(execute(args))
    import uvicorn
    import webview

    from drisca.launcher.server import create_app

    class LauncherServer(uvicorn.Server):
        async def shutdown(self, sockets=None) -> None:
            runtime = cast(Any, self.config.app).state.runtime
            await runtime.shutdown()
            await super().shutdown(sockets=sockets)

    config = load_machine_config()
    app = create_app()
    server = LauncherServer(
        uvicorn.Config(
            app,
            host=config.service.launcher_host,
            port=config.service.launcher_port,
            log_level='info',
            timeout_graceful_shutdown=2,
        )
    )
    if args.web:
        server.run()
        return
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((config.service.launcher_host, config.service.launcher_port))
    listener.listen(2048)
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError('管理端服务启动失败')
        time.sleep(0.05)
    resources = ExitStack()
    try:
        url = (
            resources.enter_context(frontend_dev_server(config.service.launcher_port))
            if args.dev
            else f'http://127.0.0.1:{config.service.launcher_port}'
        )
        bridge = WindowBridge(server)
        bridge._window = webview.create_window(
            'DRISCA',
            url,
            js_api=bridge,
            frameless=True,
            easy_drag=False,
            width=1200,
            height=780,
            min_size=(840, 560),
        )
        assert bridge._window is not None
        bridge._window.events.shown += bridge._on_shown
        bridge._window.events.closing += bridge._on_closing
        webview.start(
            gui='edgechromium', debug=config.service.debug, icon=str(PROJECT_ROOT / 'docs/assets/icon.ico')
        )
    finally:
        server.should_exit = True
        resources.close()
        thread.join()
        listener.close()


if __name__ == '__main__':
    main()
