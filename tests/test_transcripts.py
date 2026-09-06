from __future__ import annotations

import json

import pytest

from dotaudio.transcripts import export_transcript, match_keywords, timestamp

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


def test_unknown_export_format_and_negative_timestamp_fail() -> None:
    with pytest.raises(ValueError):
        export_transcript(SEGMENTS, "md")
    with pytest.raises(ValueError):
        timestamp(-0.001)
