from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dotaudio.storage import Store


def test_store_persists_sessions_segments_and_settings(tmp_path: Path) -> None:
    path = tmp_path / "dotaudio.sqlite3"
    store = Store(path)
    session_id = store.create_session(
        title="Вечерний эфир",
        mode="live",
        source="microphone",
        model="small",
    )
    identifiers = store.append_segments(
        session_id,
        [
            {"start": 0, "end": 1.25, "text": "Первый фрагмент"},
            {"start": 1.25, "end": 2.5, "text": "Второй фрагмент"},
        ],
    )
    assert len(identifiers) == 2
    store.save_settings({"model": "small", "language": "ru"})
    store.finish_session(session_id)

    reopened = Store(path)
    session = reopened.get_session(session_id)

    assert session is not None
    assert session["status"] == "completed"
    assert [segment["text"] for segment in session["segments"]] == [
        "Первый фрагмент",
        "Второй фрагмент",
    ]
    assert reopened.get_settings() == {"language": "ru", "model": "small"}

    listed = reopened.list_sessions("второй")
    assert listed[0]["id"] == session_id
    assert listed[0]["segment_count"] == 2
    assert listed[0]["text"] == "Первый фрагмент\nВторой фрагмент"


def test_segment_edits_are_scoped_and_keep_original_text(tmp_path: Path) -> None:
    path = tmp_path / "dotaudio.sqlite3"
    store = Store(path)
    first = store.create_session("First", "live", "mic", "base")
    second = store.create_session("Second", "live", "mic", "base")
    store.append_segments(first, [{"start": 0, "end": 1, "text": "before"}])
    store.append_segments(second, [{"start": 0, "end": 1, "text": "other"}])
    first_segment = store.get_session(first)["segments"][0]

    store.update_segment(first, first_segment["id"], "after")
    store.update_segment(second, first_segment["id"], "must not change")

    assert store.get_session(first)["segments"][0]["text"] == "after"
    assert store.get_session(second)["segments"][0]["text"] == "other"

    with sqlite3.connect(path) as connection:
        original = connection.execute(
            "SELECT original_text FROM segments WHERE id = ?",
            (first_segment["id"],),
        ).fetchone()[0]
    assert original == "before"


@pytest.mark.parametrize(
    "segment",
    [
        {"start": -0.1, "end": 1, "text": "bad"},
        {"start": 2, "end": 1, "text": "bad"},
        {"start": float("inf"), "end": 1, "text": "bad"},
    ],
)
def test_invalid_segment_timestamps_are_rejected(
    tmp_path: Path, segment: dict[str, object]
) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_id = store.create_session("Test", "live", "mic", "base")

    with pytest.raises(ValueError):
        store.append_segments(session_id, [segment])


def test_existing_active_sessions_are_marked_interrupted_on_startup(tmp_path: Path) -> None:
    path = tmp_path / "dotaudio.sqlite3"
    store = Store(path)
    session_id = store.create_session("Interrupted", "dictation", "mic", "base")
    store.append_segments(session_id, [{"start": 0, "end": 1, "text": "saved text"}])

    reopened = Store(path)
    recovered = reopened.get_session(session_id)

    assert recovered is not None
    assert recovered["status"] == "interrupted"
    assert recovered["finished_at"] is not None
    assert recovered["segments"][0]["text"] == "saved text"


def test_versionless_database_is_migrated_without_losing_data(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                mode TEXT NOT NULL,
                source TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                start REAL NOT NULL,
                end REAL NOT NULL,
                text TEXT NOT NULL,
                original_text TEXT NOT NULL
            );
            INSERT INTO sessions VALUES
                ('legacy', 'Old recording', 'media', 'old.wav', 'base',
                 '2026-01-01T00:00:00+00:00', NULL, 'completed');
            INSERT INTO segments (session_id, start, end, text, original_text)
                VALUES ('legacy', 0, 1, 'old text', 'old text');
            """
        )

    migrated = Store(path)

    assert migrated.get_session("legacy")["segments"][0]["text"] == "old text"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in connection.execute("PRAGMA table_info(segments)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(sessions)")}
    assert "words_json" in columns
    assert {"ix_sessions_history_order", "ix_sessions_status"} <= indexes


def test_list_sessions_supports_stable_pagination(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_ids = [
        store.create_session(f"Session {number}", "media", "file", "base")
        for number in range(3)
    ]

    first_page = store.list_sessions(limit=2, offset=0)
    second_page = store.list_sessions(limit=2, offset=2)
    unbounded = store.list_sessions()

    assert [item["id"] for item in first_page + second_page] == [
        item["id"] for item in unbounded
    ]
    assert {item["id"] for item in unbounded} == set(session_ids)


@pytest.mark.parametrize("limit, offset", [(-1, 0), (1, -1), (True, 0), (1, False)])
def test_list_sessions_rejects_invalid_pagination(
    tmp_path: Path, limit: int | bool, offset: int | bool
) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")

    with pytest.raises(ValueError):
        store.list_sessions(limit=limit, offset=offset)
