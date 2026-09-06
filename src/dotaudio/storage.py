"""Persistent local storage for DotAudio transcripts."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _unicode_fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().replace("ё", "е")


def _validate_segment(segment: dict[str, Any]) -> tuple[float, float, str]:
    try:
        start = float(segment["start"])
        end = float(segment["end"])
        text = segment["text"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("segment must contain start, end and text") from error

    if not isinstance(text, str):
        raise ValueError("segment text must be a string")
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("segment timestamps must be finite")
    if start < 0 or end < 0 or end < start:
        raise ValueError("segment timestamps are invalid")
    return start, end, text


class Store:
    """A small SQLite store using a new, WAL-enabled connection per call."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._schema_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("unicode_fold", 1, _unicode_fold)
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._schema_lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active'
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    text TEXT NOT NULL,
                    original_text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_segments_session_order
                    ON segments(session_id, start, id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def create_session(
        self,
        title: str,
        mode: str,
        source: str,
        model: str,
    ) -> str:
        session_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, title, mode, source, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, title, mode, source, model, _utc_now()),
            )
        return session_id

    def append_segments(
        self,
        session_id: str,
        segments: Iterable[dict[str, Any]],
    ) -> None:
        rows = [_validate_segment(segment) for segment in segments]
        if not rows:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO segments (session_id, start, end, text, original_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (session_id, start, end, text, text)
                    for start, end, text in rows
                ],
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None
            segments = connection.execute(
                """
                SELECT id, start, end, text
                FROM segments
                WHERE session_id = ?
                ORDER BY start ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        result = dict(session)
        result["segments"] = [dict(segment) for segment in segments]
        return result

    def list_sessions(self, query: str = "") -> list[dict[str, Any]]:
        folded_query = _unicode_fold(query.strip())
        where = ""
        params: tuple[str, ...] = ()
        if folded_query:
            pattern = f"%{folded_query}%"
            where = """
                WHERE unicode_fold(s.title) LIKE ?
                   OR unicode_fold(s.mode) LIKE ?
                   OR unicode_fold(s.source) LIKE ?
                   OR unicode_fold(s.model) LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM segments searched
                       WHERE searched.session_id = s.id
                         AND unicode_fold(searched.text) LIKE ?
                   )
            """
            params = (pattern, pattern, pattern, pattern, pattern)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    s.id,
                    s.title,
                    s.mode,
                    s.source,
                    s.model,
                    s.created_at,
                    COALESCE((
                        SELECT GROUP_CONCAT(ordered.text, char(10))
                        FROM (
                            SELECT text
                            FROM segments
                            WHERE session_id = s.id
                            ORDER BY start ASC, id ASC
                        ) AS ordered
                    ), '') AS text,
                    (SELECT COUNT(*) FROM segments WHERE session_id = s.id)
                        AS segment_count
                FROM sessions s
                {where}
                ORDER BY s.created_at DESC, s.id DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_segment(
        self,
        session_id: str,
        segment_id: int,
        text: str,
    ) -> None:
        if not isinstance(text, str):
            raise ValueError("segment text must be a string")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE segments
                SET text = ?, original_text = COALESCE(original_text, text)
                WHERE id = ? AND session_id = ?
                """,
                (text, segment_id, session_id),
            )

    def finish_session(
        self, session_id: str, status: str = "completed"
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, _utc_now(), session_id),
            )

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", ("app",)
            ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row["value"])
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def save_settings(self, settings: dict[str, Any]) -> None:
        if not isinstance(settings, dict):
            raise ValueError("settings must be a dictionary")
        value = json.dumps(settings, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("app", value),
            )
