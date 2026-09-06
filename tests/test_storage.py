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
