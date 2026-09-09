from __future__ import annotations

from dotaudio.transcript_pro import (
    apply_dictionary,
    confidence_from_logprob,
    diff_transcripts,
    export_with_preset,
    find_replace,
    merge_segments,
    needs_review,
    preset_list,
    quality_stats,
    resolve_export_options,
    split_segment,
)


def test_confidence_and_quality_flags() -> None:
    assert confidence_from_logprob(0.0) == 1.0
    assert 0.3 < confidence_from_logprob(-1.0) < 0.5
    low = {"text": "а", "confidence": 0.4}
    ok = {"text": "полное предложение", "confidence": 0.9}
    assert needs_review(low) is True
    assert needs_review(ok) is False
    stats = quality_stats([low, ok])
    assert stats["total"] == 2
    assert stats["flagged"] == 1


def test_merge_split_and_replace() -> None:
    rows = [
        {"start": 0.0, "end": 1.0, "text": "Раз два", "speaker": "А", "confidence": 0.8},
        {"start": 1.0, "end": 2.0, "text": "три", "speaker": "А", "confidence": 0.7},
    ]
    merged = merge_segments(rows, 0)
    assert len(merged) == 1
    assert merged[0]["text"] == "Раз два три"
    assert merged[0]["end"] == 2.0

    split = split_segment(
        [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "Раз два три четыре",
                "words": [
                    {"text": "Раз", "start": 0.0, "end": 0.4},
                    {"text": "два", "start": 0.4, "end": 0.8},
                    {"text": "три", "start": 1.0, "end": 1.4},
                    {"text": "четыре", "start": 1.4, "end": 2.0},
                ],
            }
        ],
        0,
        0.9,
    )
    assert len(split) == 2
    assert "Раз" in split[0]["text"]
    assert "три" in split[1]["text"]

    replaced, count = find_replace(rows, "три", "ТРИ")
    assert count == 1
    assert replaced[1]["text"] == "ТРИ"


def test_dictionary_and_court_export() -> None:
    text = apply_dictionary(
        "Судья Иванов слушает",
        [{"term": "Иванов И.И.", "misheard": "Иванов"}],
    )
    assert "Иванов И.И." in text
    body, ext, stem = export_with_preset(
        [
            {
                "start": 0,
                "end": 1.5,
                "text": "Слушается дело",
                "speaker": "Судья",
                "confidence": 0.9,
            }
        ],
        "court",
        title="Дело 1",
        source="hearing.wav",
        model="small",
    )
    assert ext == "txt"
    assert "ПРОТОКОЛ" in body
    assert "Судья" in body
    assert stem == "protocol_court"


def test_export_option_overrides() -> None:
    rows = [
        {
            "start": 0,
            "end": 1,
            "text": "фраза",
            "speaker": "А",
            "confidence": 0.42,
            "reviewed": False,
        }
    ]
    defaults = resolve_export_options("protocol")
    assert defaults["include_speakers"] is True
    assert defaults["include_confidence"] is False

    muted = resolve_export_options(
        "protocol",
        {"include_speakers": False, "include_confidence": True},
    )
    assert muted["include_speakers"] is False
    assert muted["include_confidence"] is True

    body, ext, _ = export_with_preset(
        rows,
        "protocol",
        options={"include_confidence": True, "include_review_flags": True},
    )
    assert ext == "txt"
    assert "на проверку" in body

    body_conf, _, _ = export_with_preset(
        [{**rows[0], "reviewed": True, "confidence": 0.91}],
        "protocol",
        options={"include_confidence": True, "include_review_flags": True},
    )
    assert "91%" in body_conf

    presets = preset_list()
    court = next(item for item in presets if item["key"] == "court")
    assert court["include_confidence"] is True
    assert court["include_speakers"] is True


def test_model_diff_picks_winner() -> None:
    a = [{"start": 0, "end": 1, "text": "привет мир", "confidence": 0.6}]
    b = [{"start": 0, "end": 1, "text": "привет мир сегодня", "confidence": 0.9}]
    report = diff_transcripts(a, b, baseline_model="tiny", challenger_model="small")
    assert report["winner"] == "small"
    assert report["changeCount"] >= 1
