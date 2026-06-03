"""Minimal SQLite persistence for study sessions."""

from __future__ import annotations

import os
import sqlite3


class SessionStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS study_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL,
                    duration_s REAL NOT NULL,
                    bad_posture_count INTEGER NOT NULL,
                    too_close_count INTEGER NOT NULL,
                    camera_view TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_study_sessions_unique
                ON study_sessions (started_at, ended_at, camera_view)
                """
            )

    def save_session(self, session, camera_view: str):
        if not session or session.end_time is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO study_sessions (
                    started_at, ended_at, duration_s,
                    bad_posture_count, too_close_count, camera_view
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(started_at, ended_at, camera_view) DO UPDATE SET
                    duration_s=excluded.duration_s,
                    bad_posture_count=excluded.bad_posture_count,
                    too_close_count=excluded.too_close_count
                """,
                (
                    session.start_time,
                    session.end_time,
                    session.duration,
                    session.bad_posture_count,
                    session.too_close_count,
                    camera_view,
                ),
            )
