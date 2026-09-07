from __future__ import annotations

import json

import pytest

from dotaudio.transcripts import (
    apply_keyword_cooldown,
    export_transcript,
    match_keywords,
    regroup_for_subtitles,
    timestamp,
)

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
        export_transcript(SEGMENTS, "md")
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
