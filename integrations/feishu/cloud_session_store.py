# -*- coding: utf-8 -*-
"""飞书 logical session_id ↔ Agent Engine cloud session_id 映射（SQLite）。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional


class CloudSessionStore:
    """云端 create_session 只接受 user_id；飞书群/私聊键需本地映射到 cloud id。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cloud_session_map (
                    logical_session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    cloud_session_id TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def get_cloud_session_id(self, logical_session_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cloud_session_id FROM cloud_session_map WHERE logical_session_id = ?",
                (logical_session_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["cloud_session_id"])

    def put(
        self, *, logical_session_id: str, user_id: str, cloud_session_id: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cloud_session_map
                    (logical_session_id, user_id, cloud_session_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(logical_session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    cloud_session_id = excluded.cloud_session_id,
                    updated_at = excluded.updated_at
                """,
                (logical_session_id, user_id, cloud_session_id, time.time()),
            )

    def delete(self, logical_session_id: str) -> Optional[str]:
        cloud_id = self.get_cloud_session_id(logical_session_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM cloud_session_map WHERE logical_session_id = ?",
                (logical_session_id,),
            )
        return cloud_id
