"""管理端桌面与服务入口。"""

import socket
import threading
import time
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, cast

from drisca.core.config import initialize_configs, load_machine_config
from drisca.core.paths import PROJECT_ROOT
from drisca.launcher.cli import execute, parser
from drisca.launcher.dev import frontend_dev_server

if TYPE_CHECKING:
    import uvicorn


class WindowBridge:
    def __init__(self, server: uvicorn.Server) -> None:
        self._server = server
        self._window = None
        self._maximized = False
        self._closing = False

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

        self._server.should_exit = True
        self._window.destroy()

    def _on_closing(self) -> bool:
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
            width=1440,
            height=900,
            min_size=(900, 600),
        )
        assert bridge._window is not None
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
