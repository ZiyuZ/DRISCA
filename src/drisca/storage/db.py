"""SQLite 会话、事件与导出。"""

import csv
import sqlite3
import time
from dataclasses import astuple, fields
from pathlib import Path

from .models import SCHEMA_SQL, SCHEMA_VERSION, EventRow, SessionRow, SessionStatus


class SchemaMismatchError(RuntimeError):
    """数据库结构版本不匹配。"""


class StorageDB:
    def __init__(self, db_path: Path) -> None:
        self.connection = sqlite3.connect(db_path)
        self.connection.execute('PRAGMA busy_timeout=5000')
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        tables = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == 0 and not tables:
            self.connection.executescript(
                f'BEGIN IMMEDIATE;\n{SCHEMA_SQL}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;'
            )
        elif version != SCHEMA_VERSION:
            self.connection.close()
            raise SchemaMismatchError('数据库结构版本不匹配；请删除测试库或运行一次性迁移脚本。')
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=NORMAL')

    def close(self) -> None:
        self.connection.close()

    def create_session(self, row: SessionRow) -> None:
        with self.connection:
            self.connection.execute(
                f'INSERT INTO session VALUES ({",".join("?" for _ in fields(row))})', astuple(row)
            )

    def update_session_ego(self, session_id: str, ego_actor_id: int, ego_type_id: str) -> None:
        with self.connection:
            self.connection.execute(
                'UPDATE session SET ego_actor_id=?, ego_type_id=? WHERE session_id=?',
                (ego_actor_id, ego_type_id, session_id),
            )

    def finish_session(self, session_id: str, status: SessionStatus, finished_at: float) -> None:
        with self.connection:
            self.connection.execute(
                'UPDATE session SET status=?, finished_at=? WHERE session_id=?',
                (status, finished_at, session_id),
            )

    def append_events(self, rows: list[EventRow]) -> None:
        with self.connection:
            self.connection.executemany(
                'INSERT INTO event VALUES (?, ?, ?, ?, ?, ?, ?, ?)', map(astuple, rows)
            )

    def abort_stale_running_sessions(self) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE session SET status='aborted', finished_at=? WHERE status='running'", (time.time(),)
            )
        return cursor.rowcount

    def list_sessions(self, status_filter: SessionStatus | None = None) -> list[SessionRow]:
        if status_filter is None:
            rows = self.connection.execute('SELECT * FROM session ORDER BY started_at DESC')
        else:
            rows = self.connection.execute(
                'SELECT * FROM session WHERE status=? ORDER BY started_at DESC', (status_filter,)
            )
        return [SessionRow(*row[:1], SessionStatus(row[1]), *row[2:]) for row in rows]

    def list_session_events(self, session_id: str) -> list[EventRow]:
        rows = self.connection.execute(
            'SELECT * FROM event WHERE session_id=? ORDER BY timestamp, rowid', (session_id,)
        )
        return [EventRow(*row) for row in rows]

    def count_session_frames(self, session_id: str) -> int:
        return self.connection.execute(
            'SELECT count(*) FROM data WHERE session_id=?', (session_id,)
        ).fetchone()[0]

    def export_sessions(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for table, filename in (('session', 'sessions.csv'), ('data', 'data.csv'), ('event', 'events.csv')):
            cursor = self.connection.execute(f'SELECT * FROM {table}')
            with (output_dir / filename).open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor)
