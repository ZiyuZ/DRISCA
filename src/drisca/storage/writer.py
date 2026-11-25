"""逐帧主车与背景交通流数据的后台批量写入。"""

import queue
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import astuple, fields
from pathlib import Path

from .models import SCHEMA_VERSION, FrameRow, TrafficRow


class BatchDataWriter:
    def __init__(self, db_path: Path, batch_size: int = 500, flush_interval: float = 0.5) -> None:
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: queue.Queue[FrameRow | TrafficRow | None] = queue.Queue(maxsize=50000)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.error: BaseException | None = None

    def start(self) -> None:
        self.thread.start()

    def enqueue(self, row: FrameRow) -> None:
        if self.error is not None:
            raise RuntimeError('数据写入线程失败') from self.error
        self.queue.put_nowait(row)

    def enqueue_traffic(self, rows: list[TrafficRow]) -> None:
        if not rows:
            return
        if self.error is not None:
            raise RuntimeError('数据写入线程失败') from self.error
        for row in rows:
            self.queue.put_nowait(row)

    def close(self) -> None:
        if self.thread.is_alive():
            self.queue.put(None, timeout=5.0)
        self.thread.join()
        if self.error is not None:
            raise RuntimeError('数据写入线程失败') from self.error

    def _run(self) -> None:
        try:
            self._write()
        except BaseException as exc:
            self.error = exc

    def _write(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute('PRAGMA busy_timeout=5000')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version != SCHEMA_VERSION:
                raise RuntimeError('数据库结构版本不匹配；请删除测试库或运行一次性迁移脚本。')
            connection.execute('PRAGMA synchronous=NORMAL')
            data_sql = f'INSERT INTO data VALUES ({", ".join("?" for _ in fields(FrameRow))})'
            traffic_sql = f'INSERT INTO traffic VALUES ({", ".join("?" for _ in fields(TrafficRow))})'
            data_rows: list[FrameRow] = []
            traffic_rows: list[TrafficRow] = []
            deadline = time.monotonic() + self.flush_interval
            done = False
            while not done:
                try:
                    item = self.queue.get(timeout=max(0, deadline - time.monotonic()))
                    if item is None:
                        done = True
                    elif isinstance(item, FrameRow):
                        data_rows.append(item)
                    else:
                        traffic_rows.append(item)
                except queue.Empty:
                    pass
                pending = len(data_rows) + len(traffic_rows)
                if pending and (done or pending >= self.batch_size or time.monotonic() >= deadline):
                    connection.execute('BEGIN IMMEDIATE')
                    if data_rows:
                        connection.executemany(data_sql, (astuple(row) for row in data_rows))
                        data_rows.clear()
                    if traffic_rows:
                        connection.executemany(traffic_sql, (astuple(row) for row in traffic_rows))
                        traffic_rows.clear()
                    connection.commit()
                    deadline = time.monotonic() + self.flush_interval
                elif not pending and time.monotonic() >= deadline:
                    deadline = time.monotonic() + self.flush_interval
