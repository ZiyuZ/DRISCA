"""模拟器与管理端之间的 WebSocket 通道。"""

import asyncio
import queue
import threading
from typing import Any

from loguru import logger
from websockets.asyncio.client import connect

from drisca.core.protocol import (
    LauncherCommand,
    LogEvent,
    LogLevel,
    TelemetrySnapshotEvent,
    WorkerEvent,
    WorkerRole,
    dump_worker_event,
    parse_launcher_command,
)


class WorkerWSClient:
    def __init__(self, ws_url: str, role: WorkerRole = WorkerRole.SIMULATOR) -> None:
        self.ws_url = ws_url
        self.role = role
        self.events: queue.Queue[WorkerEvent] = queue.Queue(maxsize=1024)
        self.commands: queue.Queue[LauncherCommand] = queue.Queue(maxsize=256)
        self.telemetry: TelemetrySnapshotEvent | None = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name='worker-websocket', daemon=True)
        self.sink_id: int | None = None

    def start(self) -> None:
        self.thread.start()
        self.ready.wait()
        self._check()
        logger.remove()
        self.sink_id = logger.add(self._log, catch=False)

    def _log(self, message: Any) -> None:
        record = message.record
        self.send_event(
            LogEvent(
                role=self.role,
                timestamp=record['time'].timestamp(),
                level=LogLevel(record['level'].name),
                message=record['message'],
                command_id=record['extra'].get('command_id'),
            )
        )

    def _check(self) -> None:
        if self.error is not None:
            raise RuntimeError('管理端通信失败') from self.error

    def publish_telemetry(self, snapshot: TelemetrySnapshotEvent) -> None:
        self._check()
        with self.lock:
            self.telemetry = snapshot

    def send_event(self, event: WorkerEvent) -> None:
        self._check()
        self.events.put_nowait(event)

    def poll_commands(self) -> list[LauncherCommand]:
        self._check()
        commands = []
        while True:
            try:
                commands.append(self.commands.get_nowait())
            except queue.Empty:
                return commands

    def close(self) -> None:
        if self.sink_id is not None:
            logger.remove(self.sink_id)
        self.stopping.set()
        self.thread.join()
        self._check()

    def _run(self) -> None:
        try:
            asyncio.run(self._communicate())
        except BaseException as exc:
            self.error = exc
        finally:
            self.ready.set()

    async def _communicate(self) -> None:
        async with connect(self.ws_url, open_timeout=5, close_timeout=5) as socket:
            self.ready.set()
            while not self.stopping.is_set() or not self.events.empty():
                while not self.events.empty():
                    await socket.send(dump_worker_event(self.events.get_nowait()))
                with self.lock:
                    snapshot, self.telemetry = self.telemetry, None
                if snapshot is not None:
                    await socket.send(dump_worker_event(snapshot))
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=0.01)
                except TimeoutError:
                    continue
                self.commands.put_nowait(parse_launcher_command(raw))
