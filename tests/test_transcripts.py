from __future__ import annotations

import json

import pytest

from dotaudio.transcripts import (
    LIVE_CAPTION_VISIBLE_CHARS,
    LIVE_SENTENCE_GAP_SECONDS,
    LIVE_SENTENCE_MAX_CHARS,
    apply_keyword_cooldown,
    blend_fragments,
    continues_sentence,
    export_transcript,
    format_time,
    join_fragments,
    match_keywords,
    quantise_seconds,
    regroup_for_subtitles,
    sentence_open,
    split_caption_window,
    timestamp,
    window_caption,
)


def test_sentence_stays_open_without_terminal_punctuation_or_after_a_cut() -> None:
    assert sentence_open("в реальном") is True
    assert sentence_open("почти мгновенно,") is True
    assert sentence_open("Привет.") is False
    assert sentence_open("Как дела?») ") is False
    # Точка от окна, обрезанного лимитом, ничего не значит.
    assert sentence_open("почти мгновенно.", cut=True) is True
    assert sentence_open("", cut=True) is False


def test_continuation_follows_case_and_pause() -> None:
    assert continues_sentence("в реальном", False, "времени.", 0.3) is True
    # Строчная буква продолжает даже «законченное» предложение.
    assert continues_sentence("без видеокарты.", False, "даже ночью.", 0.3) is True
    assert continues_sentence("без видеокарты.", False, "Это главная задача.", 0.3) is False
    # Долгая пауза заканчивает мысль, какой бы ни была пунктуация.
    assert continues_sentence("в реальном", False, "времени.", LIVE_SENTENCE_GAP_SECONDS + 0.1) is False
    # Слишком длинное предложение закрывается, чтобы живая строка читалась.
    long_head = "слово " * ((LIVE_SENTENCE_MAX_CHARS // 6) + 2)
    assert continues_sentence(long_head, True, "ещё", 0.1) is False


def test_caption_window_keeps_a_readable_tail() -> None:
    assert window_caption("коротко", 40) == "коротко"
    long = "один два три четыре пять шесть семь восемь девять десять"
    shown = window_caption(long, 28)
    assert shown.endswith("десять")
    assert "один" not in shown
    head, tail = split_caption_window(
        "начало длинной подтверждённой фразы про субтитры в зале",
        "черновик хвоста",
        max_chars=40,
    )
    assert tail == "черновик хвоста"
    assert "начало длинной" not in head
    assert " ".join(part for part in (head, tail) if part).endswith("черновик хвоста")
    assert LIVE_CAPTION_VISIBLE_CHARS <= LIVE_SENTENCE_MAX_CHARS


def test_cut_seam_becomes_a_comma_and_lower_case() -> None:
    assert blend_fragments("почти мгновенно.", True, "Даже на слабом") == ("почти мгновенно,", "даже на слабом")
    assert join_fragments("в реальном", True, "времени.") == "в реальном времени."
    # Вопрос и восклицание декодера не переписываются, имена и аббревиатуры тоже.
    assert blend_fragments("Правда?", True, "Да.") == ("Правда?", "Да.")
    assert blend_fragments("работает.", True, "GPU нужен") == ("работает,", "GPU нужен")
    assert blend_fragments("работает.", True, "Я думаю") == ("работает,", "я думаю")
    # Без обрезки пунктуация - решение декодера.
    assert blend_fragments("мгновенно.", False, "Даже") == ("мгновенно.", "Даже")

SEGMENTS = [
    {"start": 0, "end": 1.25, "text": "Привет, мир"},
    {"start": 59.9996, "end": 61.5, "text": "Вторая строка"},
]


def test_exports_use_expected_timestamp_formats() -> None:
    assert timestamp(59.9996) == "00:01:00,000"
    assert timestamp(3600.001, ".") == "01:00:00.001"

    srt = export_transcript(SEGMENTS, "srt")
    assert "1\n00:00:00,000 --> 00:00:01,250\nПривет, мир" in srt
    assert "2\n00:01:00,000 --> 00:01:01,500\nВторая строка" in srt

    vtt = export_transcript(SEGMENTS, "vtt")
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:01:00.000 --> 00:01:01.500" in vtt
    assert export_transcript(SEGMENTS, "txt") == "Привет, мир\nВторая строка"
    assert json.loads(export_transcript(SEGMENTS, "json")) == SEGMENTS


def test_time_precision_rounds_and_carries_into_minutes() -> None:
    assert format_time(16.084, precision="seconds") == "00:16"
    assert format_time(16.084, precision="tenths") == "00:16.1"
    assert format_time(16.084, precision="hundredths") == "00:16.08"
    assert format_time(16.084, precision="millis") == "00:16.084"
    # Округление вверх переносится в минуты, а не даёт «00:60».
    assert format_time(59.96, precision="tenths") == "01:00.0"
    # Часы: только при нужде, всегда или никогда - минуты продолжают счёт.
    assert format_time(3616.4, precision="seconds") == "01:00:16"
    assert format_time(16.4, precision="seconds", hours="always") == "00:00:16"
    assert format_time(3616.4, precision="seconds", hours="never") == "60:16"
    assert quantise_seconds(16.084, "seconds") == 16.0
    with pytest.raises(ValueError):
        format_time(-0.5)
    with pytest.raises(ValueError):
        format_time(1.0, precision="nanoseconds")


def test_text_export_follows_requested_time_precision() -> None:
    rows = [{"start": 16.084, "end": 20.116, "text": "фраза"}]
    assert export_transcript(
        rows,
        "txt",
        include_timestamps=True,
        time_precision="seconds",
        time_mode="range",
        time_hours="auto",
    ) == "[00:16 - 00:20] фраза"
    # Субтитрам миллисекунды нужны всегда, огрубление только округляет время.
    srt = export_transcript(rows, "srt", time_precision="seconds")
    assert "00:00:16,000 --> 00:00:20,000" in srt


def test_export_filters_timestamps_speakers_and_markdown() -> None:
    rows = [
        {"start": 0, "end": 1.0, "text": "Раз", "speaker": "Анна"},
        {"start": 2, "end": 3.5, "text": "Два", "speaker": "Борис"},
    ]
    plain = export_transcript(rows, "txt", include_timestamps=False, include_speakers=False)
    assert plain == "Раз\nДва"

    stamped = export_transcript(rows, "txt", include_timestamps=True, include_speakers=True)
    assert stamped == (
        "[00:00:00.000] [Анна] Раз\n"
        "[00:00:02.000] [Борис] Два"
    )

    srt = export_transcript(rows, "srt", include_speakers=True)
    assert "[Анна] Раз" in srt
    assert "00:00:00,000 --> 00:00:01,000" in srt

    payload = json.loads(
        export_transcript(rows, "json", include_timestamps=False, include_speakers=True)
    )
    assert payload == [
        {"text": "Раз", "speaker": "Анна"},
        {"text": "Два", "speaker": "Борис"},
    ]

    md = export_transcript(rows, "md", include_timestamps=True, include_speakers=True)
    assert "### Анна" in md
    assert "`00:00:00.000` Раз" in md
    assert "### Борис" in md


def test_keyword_matching_respects_unicode_word_and_phrase_boundaries() -> None:
    text = "Ёлка и новая новость. Новостной выпуск не про елкуx."

    assert match_keywords(
        text,
        ["елка", "новая новость", "новость", "новост", "елку"],
    ) == ["елка", "новая новость", "новость"]


def test_keyword_cooldown_ignores_repeats_until_the_window_elapses() -> None:
    seen: dict[str, float] = {}
    assert apply_keyword_cooldown(["елка"], seen, 0.0, 20.0) == ["елка"]
    assert apply_keyword_cooldown(["елка"], seen, 5.0, 20.0) == []
    assert apply_keyword_cooldown(["елка", "новость"], seen, 21.0, 20.0) == ["елка", "новость"]


def test_unknown_export_format_and_negative_timestamp_fail() -> None:
    with pytest.raises(ValueError):
        export_transcript(SEGMENTS, "docx")
    with pytest.raises(ValueError):
        timestamp(-0.001)


def test_regroup_for_subtitles_splits_on_word_timings_and_prefers_punctuation() -> None:
    segments = [
        {
            "start": 0,
            "end": 4.2,
            "text": "One two. Three four five.",
            "words": [
                {"start": 0, "end": 0.4, "text": "One"},
                {"start": 0.4, "end": 0.8, "text": "two."},
                {"start": 1.0, "end": 1.4, "text": "Three"},
                {"start": 1.4, "end": 1.8, "text": "four"},
                {"start": 1.8, "end": 2.2, "text": "five."},
            ],
        }
    ]

    assert regroup_for_subtitles(segments, max_chars=16, max_duration=6) == [
        {
            "start": 0.0,
            "end": 0.8,
            "text": "One two.",
            "words": [
                {"start": 0.0, "end": 0.4, "text": "One"},
                {"start": 0.4, "end": 0.8, "text": "two."},
            ],
        },
        {
            "start": 1.0,
            "end": 2.2,
            "text": "Three four five.",
            "words": [
                {"start": 1.0, "end": 1.4, "text": "Three"},
                {"start": 1.4, "end": 1.8, "text": "four"},
                {"start": 1.8, "end": 2.2, "text": "five."},
            ],
        },
    ]


def test_regroup_for_subtitles_uses_duration_limit_and_keeps_long_words() -> None:
    segments = [
        {
            "start": 0,
            "end": 4,
            "text": "one two three",
            "words": [
                {"start": 0, "end": 0.2, "text": "one"},
                {"start": 1.8, "end": 2.0, "text": "two"},
                {"start": 3.5, "end": 4.0, "text": "three"},
            ],
        },
        {"start": 5, "end": 5.2, "text": "supercalifragilistic"},
    ]

    assert regroup_for_subtitles(segments, max_chars=10, max_duration=1) == [
        {
            "start": 0.0,
            "end": 0.2,
            "text": "one",
            "words": [{"start": 0.0, "end": 0.2, "text": "one"}],
        },
        {
            "start": 1.8,
            "end": 2.0,
            "text": "two",
            "words": [{"start": 1.8, "end": 2.0, "text": "two"}],
        },
        {
            "start": 3.5,
            "end": 4.0,
            "text": "three",
            "words": [{"start": 3.5, "end": 4.0, "text": "three"}],
        },
        {"start": 5.0, "end": 5.2, "text": "supercalifragilistic"},
    ]


def test_regroup_for_subtitles_preserves_atomic_segments_without_safe_words() -> None:
    segments = [
        {
            "start": 0,
            "end": 3,
            "text": "A source segment that is too long",
            "words": [{"start": 2, "end": 1, "text": "broken"}],
        },
        {"start": 4, "end": 4.5, "text": "Next."},
    ]

    assert regroup_for_subtitles(segments, max_chars=10, max_duration=1) == [
        {"start": 0.0, "end": 3.0, "text": "A source segment that is too long"},
        {"start": 4.0, "end": 4.5, "text": "Next."},
    ]


def test_regroup_for_subtitles_combines_short_legacy_segments() -> None:
    assert regroup_for_subtitles(
        [
            {"start": 0, "end": 0.5, "text": "First"},
            {"start": 0.7, "end": 1.2, "text": "second."},
        ],
        max_chars=20,
        max_duration=2,
    ) == [{"start": 0.0, "end": 1.2, "text": "First second."}]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_chars": 0}, "max_chars"),
        ({"max_chars": True}, "max_chars"),
        ({"max_duration": 0}, "max_duration"),
        ({"max_duration": float("inf")}, "max_duration"),
    ],
)
def test_regroup_for_subtitles_rejects_invalid_limits(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        regroup_for_subtitles([], **kwargs)
