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

SCHEMA_VERSION = 8
RECOVERED_SESSION_STATUS = "interrupted"

# Переписка вне записи (общий чат) хранится под этим ключом: NULL в
# session_id пришлось бы всюду сравнивать через IS, а ключ остаётся внешним
# ключом только для настоящих сессий.
GENERAL_CHAT_ID = ""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _unicode_fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().replace("ё", "е")


def _looks_like_timestamp_label(label: str) -> bool:
    """Метка вида 0:12 / 12.3 - не имя говорящего при backfill."""

    text = str(label or "").strip()
    if not text:
        return True
    if ":" in text:
        parts = text.split(":")
        return len(parts) in (2, 3) and all(part.replace(".", "", 1).isdigit() for part in parts)
    try:
        float(text.replace(",", "."))
    except ValueError:
        return False
    return True


def _split_speaker_prefix(text: str) -> tuple[str, str]:
    """Вернуть (speaker, body) если текст начинается с ``[Имя]``."""

    body = str(text or "")
    if not body.startswith("[") or "]" not in body:
        return "", body
    label, rest = body[1:].split("]", 1)
    label = label.strip()
    if not label or _looks_like_timestamp_label(label):
        return "", body
    return label, rest.strip()


def _validate_segment(segment: dict[str, Any]) -> tuple[float, float, str, str, str]:
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
    words = segment.get("words", [])
    if not isinstance(words, list):
        words = []
    safe_words = []
    for word in words:
        if not isinstance(word, dict):
            continue
        try:
            word_text = str(word.get("text", "")).strip()
            word_start = float(word.get("start", start))
            word_end = float(word.get("end", word_start))
        except (TypeError, ValueError):
            continue
        if word_text and math.isfinite(word_start) and math.isfinite(word_end):
            safe_words.append({"text": word_text, "start": max(0.0, word_start), "end": max(word_start, word_end)})
    speaker = str(segment.get("speaker") or "").strip()
    if speaker:
        # Отдельное поле важнее префикса в тексте: не дублируем [Имя].
        _prefixed, plain = _split_speaker_prefix(text)
        if _prefixed:
            text = plain
    else:
        speaker, text = _split_speaker_prefix(text)
    return start, end, text, json.dumps(safe_words, ensure_ascii=False), speaker


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
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    "database schema is newer than this version of DotAudio"
                )

            migrations = (
                self._create_initial_schema,
                self._add_word_timestamps,
                self._add_history_indexes,
                self._add_assistant_tables,
                self._add_session_pin,
                self._add_transcript_embeddings,
                self._add_recovery_and_events,
                self._add_segment_speaker,
            )
            for target_version in range(version + 1, SCHEMA_VERSION + 1):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    migrations[target_version - 1](connection)
                    connection.execute(f"PRAGMA user_version = {target_version}")
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()

            # A process cannot safely resume capture or inference after it has exited.
            # Keep already persisted text, but make the interrupted state visible in history.
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET status = ?, finished_at = COALESCE(finished_at, ?)
                    WHERE status = 'active'
                    """,
                    (RECOVERED_SESSION_STATUS, _utc_now()),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _create_initial_schema(connection: sqlite3.Connection) -> None:
        statements = (
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
                )
            """,
            """

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    text TEXT NOT NULL,
                    original_text TEXT NOT NULL
                )
            """,
            """

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """,
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _add_word_timestamps(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(segments)")}
        if "words_json" not in columns:
            connection.execute(
                "ALTER TABLE segments ADD COLUMN words_json TEXT NOT NULL DEFAULT '[]'"
            )

    @staticmethod
    def _add_history_indexes(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_segments_session_order "
            "ON segments(session_id, start, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_sessions_history_order "
            "ON sessions(created_at DESC, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_sessions_status ON sessions(status)"
        )

    @staticmethod
    def _add_assistant_tables(connection: sqlite3.Connection) -> None:
        """Переписка с ассистентом и выжимки частей записи.

        Внешнего ключа на ``sessions`` здесь нет: у общего чата записи нет
        вовсе, и он живёт под пустым ключом. Выжимки хранят хеш текста части,
        поэтому правка расшифровки не оставляет устаревшее описание.
        """

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                meta_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_chat_session_order "
            "ON chat_messages(session_id, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_digests (
                session_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                summary TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, chunk_index)
            )
            """
        )

    @staticmethod
    def _add_session_pin(connection: sqlite3.Connection) -> None:
        """Закреплённые записи поднимаются в списках ассистента и истории."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        if "pinned" not in columns:
            connection.execute(
                "ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_sessions_pinned_order "
            "ON sessions(pinned DESC, created_at DESC, id DESC)"
        )

    @staticmethod
    def _add_transcript_embeddings(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_embeddings (
                session_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY (session_id, chunk_index)
            )
            """
        )

    @staticmethod
    def _add_recovery_and_events(connection: sqlite3.Connection) -> None:
        """Путь к аудио хвосту и журнал совпадений эфира с клипами."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        if "audio_path" not in columns:
            connection.execute(
                "ALTER TABLE sessions ADD COLUMN audio_path TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS keyword_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                keyword TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                clip_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_keyword_events_created "
            "ON keyword_events(created_at DESC, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_keyword_events_session "
            "ON keyword_events(session_id, start)"
        )

    @staticmethod
    def _add_segment_speaker(connection: sqlite3.Connection) -> None:
        """Отдельная колонка говорящего; старый префикс ``[Имя]`` в text снимаем."""

        columns = {row[1] for row in connection.execute("PRAGMA table_info(segments)")}
        if "speaker" not in columns:
            connection.execute(
                "ALTER TABLE segments ADD COLUMN speaker TEXT NOT NULL DEFAULT ''"
            )
        rows = connection.execute(
            "SELECT id, text, speaker FROM segments WHERE IFNULL(speaker, '') = ''"
        ).fetchall()
        for row in rows:
            speaker, body = _split_speaker_prefix(str(row["text"] or ""))
            if not speaker:
                continue
            connection.execute(
                "UPDATE segments SET speaker = ?, text = ? WHERE id = ?",
                (speaker, body, int(row["id"])),
            )

    def create_session(
        self,
        title: str,
        mode: str,
        source: str,
        model: str,
        audio_path: str = "",
    ) -> str:
        session_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, title, mode, source, model, created_at, audio_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    mode,
                    source,
                    model,
                    _utc_now(),
                    str(audio_path or ""),
                ),
            )
        return session_id

    def set_session_audio_path(self, session_id: str, path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET audio_path = ? WHERE id = ?",
                (str(path or ""), session_id),
            )

    def append_segments(
        self,
        session_id: str,
        segments: Iterable[dict[str, Any]],
    ) -> list[int]:
        rows = [_validate_segment(segment) for segment in segments]
        if not rows:
            return []
        identifiers: list[int] = []
        with self._connect() as connection:
            for start, end, text, words, speaker in rows:
                cursor = connection.execute(
                    """
                    INSERT INTO segments (
                        session_id, start, end, text, original_text, words_json, speaker
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, start, end, text, text, words, speaker),
                )
                identifiers.append(int(cursor.lastrowid))
        return identifiers

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None
            segments = connection.execute(
                """
                SELECT id, start, end, text, words_json, speaker
                FROM segments
                WHERE session_id = ?
                ORDER BY start ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        result = dict(session)
        result["segments"] = []
        for segment in segments:
            item = dict(segment)
            raw_words = item.pop("words_json", "[]")
            try:
                words = json.loads(raw_words)
            except (TypeError, ValueError):
                words = []
            if isinstance(words, list) and words:
                item["words"] = words
            item["speaker"] = str(item.get("speaker") or "")
            result["segments"].append(item)
        return result

    def list_sessions(
        self,
        query: str = "",
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return history newest first, optionally selecting one page.

        Omitting ``limit`` and ``offset`` preserves the original all-history API.
        """
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer or None")

        folded_query = _unicode_fold(query.strip())
        where = ""
        params: list[str | int] = []
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
            params = [pattern, pattern, pattern, pattern, pattern]
        pagination = ""
        if limit is not None:
            pagination = "LIMIT ? OFFSET ?"
            params.extend((limit, offset))
        elif offset:
            pagination = "LIMIT -1 OFFSET ?"
            params.append(offset)
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
                    s.status,
                    COALESCE(s.audio_path, '') AS audio_path,
                    COALESCE(s.pinned, 0) AS pinned,
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
                        AS segment_count,
                    (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id)
                        AS chat_count
                FROM sessions s
                {where}
                ORDER BY COALESCE(s.pinned, 0) DESC, s.created_at DESC, s.id DESC
                {pagination}
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def search_sessions(
        self,
        query: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        semantic: bool = False,
    ) -> list[dict[str, Any]]:
        """Поиск по истории; при ``semantic`` - LIKE + выжимки + эмбеддинги."""

        if not semantic or not str(query or "").strip():
            return self.list_sessions(query, limit=limit, offset=offset)

        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer or None")

        folded = _unicode_fold(str(query).strip())
        tokens = [token for token in folded.split() if token]
        lexical_rows = self.list_sessions(query)
        by_id: dict[str, dict[str, Any]] = {
            str(row["id"]): dict(row) for row in lexical_rows
        }
        scores: dict[str, float] = {sid: 1.0 for sid in by_id}
        kinds: dict[str, set[str]] = {sid: {"lexical"} for sid in by_id}

        with self._connect() as connection:
            digests = connection.execute(
                "SELECT session_id, summary, keywords FROM transcript_digests"
            ).fetchall()
            embeddings = connection.execute(
                "SELECT session_id, vector_json FROM transcript_embeddings"
            ).fetchall()

        for row in digests:
            try:
                keywords = json.loads(row["keywords"] or "[]")
            except (TypeError, ValueError):
                keywords = []
            if not isinstance(keywords, list):
                keywords = []
            haystack = _unicode_fold(
                f"{row['summary'] or ''} {' '.join(str(item) for item in keywords)}"
            )
            hits = sum(1 for token in tokens if token in haystack)
            if hits <= 0:
                continue
            sid = str(row["session_id"])
            scores[sid] = scores.get(sid, 0.0) + float(hits)
            kinds.setdefault(sid, set()).add("semantic")

        from dotaudio.assistant import cosine, embed_text

        query_vector = embed_text(str(query))
        embed_best: dict[str, float] = {}
        for row in embeddings:
            try:
                vector = json.loads(row["vector_json"] or "[]")
            except (TypeError, ValueError):
                vector = []
            if not isinstance(vector, list) or not vector:
                continue
            try:
                numeric = [float(value) for value in vector]
            except (TypeError, ValueError):
                continue
            score = float(cosine(query_vector, numeric))
            if score <= 0:
                continue
            sid = str(row["session_id"])
            embed_best[sid] = max(embed_best.get(sid, 0.0), score)
        for sid, score in embed_best.items():
            scores[sid] = scores.get(sid, 0.0) + score
            kinds.setdefault(sid, set()).add("semantic")

        missing = [sid for sid in scores if sid not in by_id]
        if missing:
            catalog = {str(row["id"]): dict(row) for row in self.list_sessions()}
            for sid in missing:
                row = catalog.get(sid)
                if row is None:
                    scores.pop(sid, None)
                    kinds.pop(sid, None)
                    continue
                by_id[sid] = row

        results: list[dict[str, Any]] = []
        for sid, score in scores.items():
            row = by_id.get(sid)
            if row is None:
                continue
            item = dict(row)
            kind_set = kinds.get(sid, set())
            if "lexical" in kind_set and "semantic" in kind_set:
                item["match_kind"] = "both"
            elif "semantic" in kind_set:
                item["match_kind"] = "semantic"
            else:
                item["match_kind"] = "lexical"
            item["match_score"] = float(score)
            results.append(item)
        results.sort(
            key=lambda item: (
                -float(item.get("match_score", 0.0)),
                -int(item.get("pinned", 0) or 0),
                str(item.get("created_at", "")),
            )
        )
        if offset:
            results = results[offset:]
        if limit is not None:
            results = results[:limit]
        return results

    def save_keyword_event(
        self,
        session_id: str,
        *,
        start: float,
        end: float,
        keyword: str,
        text: str,
        source: str = "",
        clip_path: str = "",
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO keyword_events (
                    session_id, start, end, keyword, text, source, clip_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    float(start),
                    float(end),
                    str(keyword),
                    str(text),
                    str(source or ""),
                    str(clip_path or ""),
                    _utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_keyword_events(
        self,
        *,
        limit: int = 200,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            if session_id:
                rows = connection.execute(
                    """
                    SELECT * FROM keyword_events
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM keyword_events
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_recoverable_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.mode,
                    s.source,
                    s.model,
                    s.created_at,
                    s.status,
                    COALESCE(s.audio_path, '') AS audio_path,
                    (SELECT COUNT(*) FROM segments WHERE session_id = s.id)
                        AS segment_count
                FROM sessions s
                WHERE s.status = ?
                  AND (
                    COALESCE(s.audio_path, '') != ''
                    OR EXISTS (SELECT 1 FROM segments g WHERE g.session_id = s.id)
                  )
                ORDER BY s.created_at DESC, s.id DESC
                """,
                (RECOVERED_SESSION_STATUS,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_chat_messages(self, session_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE session_id = ?",
                (session_id or GENERAL_CHAT_ID,),
            ).fetchone()
        return int(row["n"] if row is not None else 0)

    def update_segment(
        self,
        session_id: str,
        segment_id: int,
        text: str,
        speaker: str | None = None,
    ) -> None:
        if not isinstance(text, str):
            raise ValueError("segment text must be a string")
        with self._connect() as connection:
            if speaker is None:
                connection.execute(
                    """
                    UPDATE segments
                    SET text = ?, original_text = COALESCE(original_text, text)
                    WHERE id = ? AND session_id = ?
                    """,
                    (text, segment_id, session_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE segments
                    SET text = ?,
                        speaker = ?,
                        original_text = COALESCE(original_text, text)
                    WHERE id = ? AND session_id = ?
                    """,
                    (text, str(speaker).strip(), segment_id, session_id),
                )

    def extend_segment(
        self,
        session_id: str,
        segment_id: int,
        end: float,
        text: str,
    ) -> None:
        """Grow a live phrase with the next fragment of the same sentence.

        This is recognition, not a user edit: the joined text is what the
        recogniser produced for the sentence, so ``original_text`` follows it
        and a later edit still has the recognised sentence to fall back to.
        """

        if not isinstance(text, str):
            raise ValueError("segment text must be a string")
        end = float(end)
        if not math.isfinite(end) or end < 0:
            raise ValueError("segment timestamps must be finite")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE segments
                SET end = MAX(end, ?), text = ?, original_text = ?
                WHERE id = ? AND session_id = ?
                """,
                (end, text, text, segment_id, session_id),
            )

    def update_segment_edit(
        self,
        session_id: str,
        segment_id: int,
        segment: dict[str, Any],
    ) -> None:
        """Persist an edited row: timings, text and word timings together.

        A karaoke edit can change the phrase window and per-word timings in one
        action.  Rewriting all three from a single validated row keeps the
        segment always consistent instead of applying partial updates that can
        break monotonicity in between calls.
        """
        start, end, text, words, speaker = _validate_segment(segment)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE segments
                SET start = ?, end = ?, text = ?, words_json = ?, speaker = ?
                WHERE id = ? AND session_id = ?
                """,
                (start, end, text, words, speaker, segment_id, session_id),
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

    def rename_session(self, session_id: str, title: str) -> str:
        """Переименовать сессию. Возвращает нормализованный заголовок."""

        cleaned = " ".join(str(title or "").strip().split())
        if not cleaned:
            raise ValueError("title must be non-empty")
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (cleaned, session_id),
            )
        return cleaned

    def set_pinned(self, session_id: str, pinned: bool) -> bool:
        """Закрепить или открепить сессию. Возвращает новое состояние."""

        value = 1 if pinned else 0
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET pinned = ? WHERE id = ?",
                (value, session_id),
            )
        return bool(value)

    def delete_session(self, session_id: str) -> bool:
        """Удалить запись целиком: сегменты, чат, выжимки и саму сессию."""

        sid = str(session_id or "")
        if not sid:
            return False
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
            if exists is None:
                return False
            connection.execute("DELETE FROM segments WHERE session_id = ?", (sid,))
            connection.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
            connection.execute(
                "DELETE FROM transcript_digests WHERE session_id = ?", (sid,)
            )
            connection.execute(
                "DELETE FROM transcript_embeddings WHERE session_id = ?", (sid,)
            )
            connection.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        return True

    def append_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        model: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Сохранить реплику переписки с ассистентом."""

        if role not in ("user", "assistant", "system"):
            raise ValueError("chat role must be user, assistant or system")
        if not isinstance(content, str):
            raise ValueError("chat content must be a string")
        payload = json.dumps(meta or {}, ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, created_at, model, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id or GENERAL_CHAT_ID, role, content, _utc_now(), model, payload),
            )
        return int(cursor.lastrowid)

    def list_chat_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Переписка по записи в порядке разговора; ``limit`` - последние реплики."""

        with self._connect() as connection:
            if limit is None:
                rows = connection.execute(
                    """
                    SELECT id, role, content, created_at, model, meta_json
                    FROM chat_messages WHERE session_id = ? ORDER BY id ASC
                    """,
                    (session_id or GENERAL_CHAT_ID,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, role, content, created_at, model, meta_json FROM (
                        SELECT id, role, content, created_at, model, meta_json
                        FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (session_id or GENERAL_CHAT_ID, limit),
                ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("meta_json", "{}")
            try:
                meta = json.loads(raw)
            except (TypeError, ValueError):
                meta = {}
            item["meta"] = meta if isinstance(meta, dict) else {}
            messages.append(item)
        return messages

    def clear_chat_messages(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM chat_messages WHERE session_id = ?",
                (session_id or GENERAL_CHAT_ID,),
            )

    def save_digest(
        self,
        session_id: str,
        chunk_index: int,
        content_hash: str,
        start: float,
        end: float,
        summary: str,
        keywords: Iterable[str] = (),
        model: str = "",
    ) -> None:
        """Запомнить выжимку части записи, заменив прежнюю для этой части."""

        payload = json.dumps(list(keywords), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcript_digests (
                    session_id, chunk_index, content_hash, start, end,
                    summary, keywords, model, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, chunk_index) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    start = excluded.start,
                    end = excluded.end,
                    summary = excluded.summary,
                    keywords = excluded.keywords,
                    model = excluded.model,
                    created_at = excluded.created_at
                """,
                (
                    session_id,
                    int(chunk_index),
                    content_hash,
                    float(start),
                    float(end),
                    summary,
                    payload,
                    model,
                    _utc_now(),
                ),
            )

    def list_digests(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_index, content_hash, start, end, summary, keywords, model
                FROM transcript_digests WHERE session_id = ? ORDER BY chunk_index ASC
                """,
                (session_id,),
            ).fetchall()
        digests: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                keywords = json.loads(item.pop("keywords", "[]"))
            except (TypeError, ValueError):
                keywords = []
            item["keywords"] = keywords if isinstance(keywords, list) else []
            digests.append(item)
        return digests

    def clear_digests(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM transcript_digests WHERE session_id = ?", (session_id,)
            )

    def save_embedding(
        self,
        session_id: str,
        chunk_index: int,
        content_hash: str,
        model: str,
        vector: Iterable[float],
    ) -> None:
        """Запомнить вектор части записи, заменив прежний для этой части."""

        payload = json.dumps(list(vector), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcript_embeddings (
                    session_id, chunk_index, content_hash, model, vector_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, chunk_index) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    model = excluded.model,
                    vector_json = excluded.vector_json
                """,
                (
                    session_id,
                    int(chunk_index),
                    content_hash,
                    model,
                    payload,
                ),
            )

    def list_embeddings(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_index, content_hash, model, vector_json
                FROM transcript_embeddings WHERE session_id = ?
                ORDER BY chunk_index ASC
                """,
                (session_id,),
            ).fetchall()
        embeddings: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("vector_json", "[]")
            try:
                vector = json.loads(raw)
            except (TypeError, ValueError):
                vector = []
            item["vector"] = vector if isinstance(vector, list) else []
            embeddings.append(item)
        return embeddings

    def clear_embeddings(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM transcript_embeddings WHERE session_id = ?",
                (session_id,),
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
