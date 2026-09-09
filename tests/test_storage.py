from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dotaudio.storage import GENERAL_CHAT_ID, SCHEMA_VERSION, Store


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        segment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(segments)")
        }
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(sessions)")}
        event_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(keyword_events)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "words_json" in segment_columns
    assert "speaker" in segment_columns
    assert "audio_path" in session_columns
    assert {"ix_sessions_history_order", "ix_sessions_status"} <= indexes
    assert {
        "chat_messages",
        "transcript_digests",
        "transcript_embeddings",
        "keyword_events",
    } <= tables
    assert {
        "ix_keyword_events_created",
        "ix_keyword_events_session",
    } <= event_indexes


def test_keyword_events_are_stored_and_filtered(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    first = store.create_session("Эфир 1", "stream", "http://a", "small")
    second = store.create_session("Эфир 2", "stream", "http://b", "small")

    first_id = store.save_keyword_event(
        first,
        start=1.0,
        end=2.5,
        keyword="бюджет",
        text="говорили про бюджет",
        source="http://a",
        clip_path="clips/a.wav",
    )
    store.save_keyword_event(
        second,
        start=0.0,
        end=1.0,
        keyword="срок",
        text="новый срок",
    )

    events = store.list_keyword_events(session_id=first)
    assert len(events) == 1
    assert events[0]["id"] == first_id
    assert events[0]["keyword"] == "бюджет"
    assert events[0]["clip_path"] == "clips/a.wav"
    assert len(store.list_keyword_events(limit=10)) == 2


def test_list_recoverable_sessions_needs_audio_or_segments(tmp_path: Path) -> None:
    path = tmp_path / "dotaudio.sqlite3"
    store = Store(path)
    with_audio = store.create_session(
        "С аудио", "dictation", "mic", "base", audio_path="rec/a.wav"
    )
    with_segments = store.create_session("С текстом", "dictation", "mic", "base")
    store.append_segments(
        with_segments, [{"start": 0.0, "end": 1.0, "text": "хвост"}]
    )
    empty = store.create_session("Пустая", "dictation", "mic", "base")
    store.set_session_audio_path(empty, "")

    reopened = Store(path)
    recoverable = {item["id"]: item for item in reopened.list_recoverable_sessions()}

    assert with_audio in recoverable
    assert recoverable[with_audio]["audio_path"] == "rec/a.wav"
    assert with_segments in recoverable
    assert recoverable[with_segments]["segment_count"] == 1
    assert empty not in recoverable


def test_semantic_search_matches_digest_keywords(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_id = store.create_session("Совещание", "media", "file.wav", "small")
    store.append_segments(
        session_id,
        [{"start": 0.0, "end": 1.0, "text": "обсудили сроки поставки"}],
    )
    store.save_digest(
        session_id,
        0,
        "hash-a",
        0.0,
        1.0,
        "Разговор про смету и людей",
        ["смета", "люди"],
        "qwen3-4b",
    )

    lexical = store.search_sessions("смета", semantic=False)
    assert lexical == []

    semantic = store.search_sessions("смета", semantic=True)
    assert len(semantic) == 1
    assert semantic[0]["id"] == session_id
    assert semantic[0]["match_kind"] == "semantic"
    assert float(semantic[0]["match_score"]) > 0

    both = store.search_sessions("сроки", semantic=True)
    assert both[0]["id"] == session_id
    assert both[0]["match_kind"] == "lexical"


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


def test_chat_history_belongs_to_a_record_and_to_the_free_chat(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_id = store.create_session("Совещание", "live", "system", "small")

    store.append_chat_message(session_id, "user", "О чём запись?")
    store.append_chat_message(session_id, "assistant", "О смете", "qwen3-4b", {"action": "summary"})
    store.append_chat_message(GENERAL_CHAT_ID, "user", "Просто вопрос")

    talk = store.list_chat_messages(session_id)
    general = store.list_chat_messages(GENERAL_CHAT_ID)

    assert [item["role"] for item in talk] == ["user", "assistant"]
    assert talk[1]["meta"] == {"action": "summary"}
    assert talk[1]["model"] == "qwen3-4b"
    # Общий чат не смешивается с перепиской по записи.
    assert [item["content"] for item in general] == ["Просто вопрос"]

    store.clear_chat_messages(session_id)
    assert store.list_chat_messages(session_id) == []
    assert len(store.list_chat_messages(GENERAL_CHAT_ID)) == 1


def test_chat_history_limit_returns_the_latest_in_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    for number in range(5):
        store.append_chat_message("rec", "user", f"вопрос {number}")

    latest = store.list_chat_messages("rec", limit=2)

    assert [item["content"] for item in latest] == ["вопрос 3", "вопрос 4"]


def test_chat_rejects_an_unknown_role(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")

    with pytest.raises(ValueError):
        store.append_chat_message("rec", "robot", "текст")


def test_rename_session_updates_title(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_id = store.create_session("Старое имя", "transcript", "file.wav", "small")

    cleaned = store.rename_session(session_id, "  Новое   имя  ")

    assert cleaned == "Новое имя"
    assert store.get_session(session_id)["title"] == "Новое имя"
    with pytest.raises(ValueError):
        store.rename_session(session_id, "   ")


def test_pin_and_delete_session(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    first = store.create_session("Первая", "live", "mic", "small")
    second = store.create_session("Вторая", "live", "mic", "small")
    store.append_segments(first, [{"start": 0.0, "end": 1.0, "text": "а"}])
    store.append_segments(second, [{"start": 0.0, "end": 1.0, "text": "б"}])
    store.append_chat_message(first, "user", "вопрос")
    store.save_digest(first, 0, "h", 0.0, 1.0, "выжимка", ["а"], "qwen")
    store.save_embedding(first, 0, "h", "hash256", [0.1, 0.2])

    assert store.set_pinned(first, True) is True
    rows = store.list_sessions()
    assert rows[0]["id"] == first
    assert int(rows[0]["pinned"]) == 1

    assert store.delete_session(first) is True
    assert store.get_session(first) is None
    assert store.list_chat_messages(first) == []
    assert store.list_digests(first) == []
    assert store.list_embeddings(first) == []
    assert store.get_session(second) is not None


def test_digests_are_replaced_per_part_and_keep_the_text_hash(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")

    store.save_digest("rec", 0, "hash-a", 0.0, 60.0, "О смете", ["смета"], "qwen3-4b")
    store.save_digest("rec", 1, "hash-b", 60.0, 120.0, "О сроках", ["сроки"], "qwen3-4b")
    # Правка расшифровки меняет хеш части: описание обновляется, а не дублируется.
    store.save_digest("rec", 0, "hash-c", 0.0, 60.0, "О смете и людях", ["люди"], "qwen3-4b")

    digests = store.list_digests("rec")

    assert [item["chunk_index"] for item in digests] == [0, 1]
    assert digests[0]["content_hash"] == "hash-c"
    assert digests[0]["summary"] == "О смете и людях"
    assert digests[0]["keywords"] == ["люди"]

    store.clear_digests("rec")
    assert store.list_digests("rec") == []


def test_embeddings_are_replaced_per_part_and_survive_reopen(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")

    store.save_embedding("rec", 0, "hash-a", "hash256", [0.1, 0.2, 0.3])
    store.save_embedding("rec", 1, "hash-b", "hash256", [1.0, 0.0])
    store.save_embedding("rec", 0, "hash-c", "hash256", [0.9, 0.8])

    embeddings = store.list_embeddings("rec")

    assert [item["chunk_index"] for item in embeddings] == [0, 1]
    assert embeddings[0]["content_hash"] == "hash-c"
    assert embeddings[0]["model"] == "hash256"
    assert embeddings[0]["vector"] == [0.9, 0.8]

    reopened = Store(tmp_path / "dotaudio.sqlite3")
    assert reopened.list_embeddings("rec") == embeddings

    store.clear_embeddings("rec")
    assert store.list_embeddings("rec") == []


def test_append_segments_stores_speaker_separately(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    session_id = store.create_session("Разговор", "transcript", "a.wav", "small")
    [seg_id] = store.append_segments(
        session_id,
        [{"start": 0.0, "end": 1.0, "text": "привет", "speaker": "Анна"}],
    )
    segment = store.get_session(session_id)["segments"][0]
    assert segment["id"] == seg_id
    assert segment["text"] == "привет"
    assert segment["speaker"] == "Анна"

    store.update_segment(session_id, seg_id, "здравствуй", speaker="Борис")
    updated = store.get_session(session_id)["segments"][0]
    assert updated["text"] == "здравствуй"
    assert updated["speaker"] == "Борис"

    store.update_segment(session_id, seg_id, "только текст")
    text_only = store.get_session(session_id)["segments"][0]
    assert text_only["text"] == "только текст"
    assert text_only["speaker"] == "Борис"


def test_legacy_speaker_prefix_splits_on_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy-speaker.sqlite3"
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
                ('legacy', 'Old', 'transcript', 'old.wav', 'base',
                 '2026-01-01T00:00:00+00:00', NULL, 'completed');
            INSERT INTO segments (session_id, start, end, text, original_text)
                VALUES
                ('legacy', 0, 1, '[Анна] привет', '[Анна] привет'),
                ('legacy', 1, 2, 'без метки', 'без метки'),
                ('legacy', 2, 3, '[0:12] не имя', '[0:12] не имя');
            """
        )

    migrated = Store(path)
    segments = migrated.get_session("legacy")["segments"]
    assert segments[0]["speaker"] == "Анна"
    assert segments[0]["text"] == "привет"
    assert segments[1]["speaker"] == ""
    assert segments[1]["text"] == "без метки"
    assert segments[2]["speaker"] == ""
    assert "[0:12]" in segments[2]["text"]
