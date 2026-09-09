from __future__ import annotations

from pathlib import Path

from dotaudio.karaoke_edit import (
    apply_word,
    clamp_row,
    rebuild_text,
    sanitize_row,
    set_word_text,
    sync_words_to_text,
)
from dotaudio.storage import Store


def _row(words=None, text="Привет мир", start=0.0, end=4.0):
    return {"start": start, "end": end, "text": text, "words": words or []}


def _words():
    return [
        {"text": "Привет", "start": 0.2, "end": 1.2},
        {"text": "мир", "start": 1.4, "end": 2.6},
        {"text": "!", "start": 2.6, "end": 3.1},
    ]


def test_apply_word_start_is_bounded_by_previous_end() -> None:
    result = apply_word(_row(words=_words()), 2, "start", 20.0)
    assert result["words"][2]["start"] <= result["words"][2]["end"]
    assert result["clamped"] is True


def test_apply_word_end_keeps_order_with_next_word() -> None:
    result = apply_word(_row(words=_words()), 1, "end", 99.0)
    assert result["clamped"] is True
    assert result["words"][1]["end"] <= result["words"][2]["start"]


def test_set_word_text_rebuilds_phrase_text() -> None:
    row = _row(words=_words())
    result = set_word_text(row, 0, "Здравствуй")
    assert result["words"][0]["text"] == "Здравствуй"
    assert result["text"] == "Здравствуй мир !"


def test_sync_words_to_text_keeps_timings_on_rename() -> None:
    row = _row(words=_words(), text="Привет мир !")
    result = sync_words_to_text(row, "Здравствуй мир !")
    assert result["text"] == "Здравствуй мир !"
    assert result["words"][0]["text"] == "Здравствуй"
    assert result["words"][0]["start"] == 0.2
    assert result["words"][0]["end"] == 1.2
    assert len(result["words"]) == 3


def test_sync_words_to_text_without_words_stays_phrase_only() -> None:
    row = _row(words=[], text="старое")
    result = sync_words_to_text(row, "новое без слов")
    assert result["text"] == "новое без слов"
    assert result["words"] == []


def test_sync_words_to_text_replace_redistributes_span() -> None:
    row = _row(
        words=[{"text": "раз", "start": 0.0, "end": 2.0}],
        text="раз",
        start=0.0,
        end=2.0,
    )
    result = sync_words_to_text(row, "раз два")
    assert result["text"] == "раз два"
    assert len(result["words"]) == 2
    assert result["words"][0]["start"] == 0.0
    assert result["words"][-1]["end"] == 2.0


def test_clamp_row_never_drops_out_of_window_words() -> None:
    row = _row(words=_words())
    tight = clamp_row(row, start=0.0, end=3.1)
    assert len(tight["words"]) == 3
    narrowed = clamp_row(row, start=0.2, end=1.0)
    assert len(narrowed["words"]) == 3
    assert narrowed["clamped"] is True


def test_rebuild_text_uses_single_space_and_keeps_punctuation() -> None:
    assert rebuild_text([{"text": "Привет"}, {"text": ","}, {"text": "мир"}]) == "Привет , мир"
    assert rebuild_text([]) == ""
    assert rebuild_text([{"text": "  Речь  "}]) == "Речь"


def test_sanitize_row_preserves_only_valid_words() -> None:
    clean = sanitize_row(_row(words=[{"text": "да", "start": 1, "end": 2},
                                     {"text": ""}, {"text": "н", "start": 2, "end": 3}]))
    assert len(clean["words"]) == 2


def test_store_update_segment_edit_persists_words_and_window(tmp_path: Path) -> None:
    store = Store(tmp_path / "d.sqlite3")
    sid = store.create_session("караоке", "media", "song.mp3", "small")
    [seg_id] = store.append_segments(sid, [_row(text="оригинал")])
    edited = sanitize_row({
        "start": 0.2, "end": 3.1, "text": "Исправлено",
        "words": _words(),
    })
    assert edited is not None
    store.update_segment_edit(sid, seg_id, {**edited, "id": seg_id})
    session = store.get_session(sid)
    seg = session["segments"][0]
    assert seg["start"] == 0.2
    assert seg["end"] == 3.1
    assert seg["text"] == "Исправлено"
    assert len(seg["words"]) == 3
