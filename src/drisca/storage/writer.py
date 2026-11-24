"""逐帧数据的后台批量写入。"""

import queue
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import astuple, fields
from pathlib import Path

from .models import SCHEMA_VERSION, FrameRow


class BatchDataWriter:
    def __init__(self, db_path: Path, batch_size: int = 500, flush_interval: float = 0.5) -> None:
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: queue.Queue[FrameRow | None] = queue.Queue(maxsize=10000)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.error: BaseException | None = None

    def start(self) -> None:
        self.thread.start()

    def enqueue(self, row: FrameRow) -> None:
        if self.error is not None:
            raise RuntimeError('数据写入线程失败') from self.error
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
            sql = f'INSERT INTO data VALUES ({", ".join("?" for _ in fields(FrameRow))})'
            rows: list[FrameRow] = []
            deadline = time.monotonic() + self.flush_interval
            done = False
            while not done:
                try:
                    item = self.queue.get(timeout=max(0, deadline - time.monotonic()))
                    if item is None:
                        done = True
                    else:
                        rows.append(item)
                except queue.Empty:
                    pass
                if rows and (done or len(rows) >= self.batch_size or time.monotonic() >= deadline):
                    connection.execute('BEGIN IMMEDIATE')
                    connection.executemany(sql, (astuple(row) for row in rows))
                    connection.commit()
                    rows.clear()
                    deadline = time.monotonic() + self.flush_interval
                elif not rows and time.monotonic() >= deadline:
                    deadline = time.monotonic() + self.flush_interval
