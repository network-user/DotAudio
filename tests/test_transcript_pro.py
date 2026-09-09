from __future__ import annotations

import pytest

from dotaudio.transcript_pro import (
    apply_dictionary,
    confidence_from_logprob,
    diff_transcripts,
    export_format_list,
    export_option_choices,
    export_rows,
    export_with_preset,
    find_replace,
    merge_segments,
    needs_review,
    normalise_export_options,
    preset_list,
    quality_stats,
    render_export,
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


def test_render_export_honours_save_filters() -> None:
    rows = [
        {
            "start": 0.0,
            "end": 1.2,
            "text": "Привет",
            "speaker": "Анна",
            "role": 1,
            "confidence": 0.91,
            "reviewed": True,
        },
        {
            "start": 2.0,
            "end": 3.5,
            "text": "хм",
            "speaker": "Борис",
            "role": 2,
            "confidence": 0.31,
            "reviewed": False,
        },
    ]
    plain, fmt = render_export(
        rows,
        {
            "format": "txt",
            "include_timestamps": False,
            "include_speakers": False,
            "include_confidence": False,
        },
    )
    assert fmt == "txt"
    assert plain == "Привет\nхм"

    rich, _ = render_export(
        rows,
        {
            "format": "txt",
            "include_timestamps": True,
            "include_speakers": True,
            "include_confidence": True,
        },
    )
    assert "[Анна] Привет" in rich
    assert "91%" in rich
    assert "[Борис]" in rich

    flagged, _ = render_export(
        rows,
        {"format": "txt", "only_flagged": True, "include_speakers": True},
    )
    assert "хм" in flagged
    assert "Привет" not in flagged

    one, _ = render_export(
        rows,
        {"format": "txt", "speaker_key": 1, "include_speakers": True},
    )
    assert "Анна" in one
    assert "Борис" not in one

    headed, _ = render_export(
        rows,
        {
            "format": "txt",
            "include_header": True,
            "include_phrase_numbers": True,
            "include_speakers": True,
            "title": "встреча.wav",
        },
    )
    assert headed.startswith("Расшифровка")
    assert "1." in headed
    assert "встреча.wav" in headed

    payload, ext = render_export(
        rows,
        {
            "format": "json",
            "include_timestamps": False,
            "include_speakers": True,
            "include_confidence": True,
        },
    )
    assert ext == "json"
    assert '"confidence"' in payload
    assert '"start"' not in payload


LINE_ROWS = [
    {
        "start": 16.084,
        "end": 20.116,
        "text": "потихонечку сокращается.",
        "speaker": "Диктор 2",
        "role": 2,
        "confidence": 0.93,
    },
    {
        "start": 20.5,
        "end": 24.0,
        "text": "а вот и ответ.",
        "speaker": "Диктор 2",
        "role": 2,
        "confidence": 0.88,
    },
]


def test_line_format_writes_time_speaker_and_text_in_one_row() -> None:
    body, ext = render_export(
        LINE_ROWS,
        {
            "format": "line",
            "include_timestamps": True,
            "include_speakers": True,
            "time_precision": "millis",
        },
    )
    assert ext == "txt"
    assert body.splitlines()[0] == "00:16.084 - 00:20.116 [Диктор 2] потихонечку сокращается."

    # Секундная точность - то, чего просили вместо миллисекунд по умолчанию.
    rough, _ = render_export(
        LINE_ROWS,
        {"format": "line", "include_timestamps": True, "include_speakers": True},
    )
    assert rough.splitlines()[0] == "00:16 - 00:20 [Диктор 2] потихонечку сокращается."

    # время:голос:текст одной строкой без диапазона.
    colon, _ = render_export(
        LINE_ROWS,
        {
            "format": "line",
            "include_timestamps": True,
            "include_speakers": True,
            "time_mode": "start",
            "field_separator": "colon",
            "speaker_style": "plain",
        },
    )
    assert colon.splitlines()[0] == "00:16:Диктор 2:потихонечку сокращается."

    # Имя только при смене голоса: у второй фразы тот же говорящий.
    once, _ = render_export(
        LINE_ROWS,
        {
            "format": "line",
            "include_timestamps": False,
            "include_speakers": True,
            "speaker_once": True,
        },
    )
    assert once.splitlines() == ["[Диктор 2] потихонечку сокращается.", "а вот и ответ."]


def test_table_and_lrc_formats_keep_their_own_rules() -> None:
    table, ext = render_export(
        LINE_ROWS,
        {
            "format": "csv",
            "include_timestamps": True,
            "include_speakers": True,
            "include_header": True,
            "include_confidence": True,
            "csv_delimiter": "semicolon",
        },
    )
    assert ext == "csv"
    rows = table.splitlines()
    assert rows[0] == "начало;конец;голос;текст;уверенность"
    assert rows[1] == "00:16;00:20;Диктор 2;потихонечку сокращается.;0.930"

    lrc, ext_lrc = render_export(LINE_ROWS, {"format": "lrc", "time_precision": "seconds"})
    assert ext_lrc == "lrc"
    # Плеер ждёт сотые в mm:ss.xx, поэтому формат не отдаёт точность наружу.
    assert lrc.splitlines()[0] == "[00:16.08][Диктор 2] потихонечку сокращается."


def test_export_options_are_validated_and_formats_force_what_they_need() -> None:
    loose = normalise_export_options(
        {
            "format": "srt",
            "include_timestamps": False,
            "time_precision": "seconds",
            "speaker_style": "неизвестно",
            "subtitle_max_chars": 5000,
            "subtitle_max_duration": "nope",
        }
    )
    assert loose["include_timestamps"] is True
    assert loose["time_precision"] == "millis"
    assert loose["speaker_style"] == "bracket"
    assert loose["subtitle_max_chars"] == 200
    assert loose["subtitle_max_duration"] == 6.0
    assert loose["ext"] == "srt"

    # Без таймкодов строка не должна получить режим диапазона.
    silent = normalise_export_options({"format": "line", "include_timestamps": False})
    assert silent["time_mode"] == "none"
    # Excel читает кириллицу в CSV только с меткой UTF-8.
    assert normalise_export_options({"format": "csv"})["encoding"] == "utf-8-sig"
    assert normalise_export_options({"format": "csv", "csv_bom": False})["encoding"] == "utf-8"
    assert normalise_export_options({"format": "txt"})["encoding"] == "utf-8"

    with pytest.raises(ValueError):
        normalise_export_options({"format": "docx"})

    keys = {item["key"] for item in export_format_list()}
    assert {"txt", "line", "csv", "lrc", "srt", "json"} <= keys
    choices = export_option_choices()
    assert {row["key"] for row in choices["time_precision"]} == {
        "seconds",
        "tenths",
        "hundredths",
        "millis",
    }


def test_merged_turns_join_one_voice_and_keep_the_weakest_confidence() -> None:
    rows = export_rows(
        [
            *LINE_ROWS,
            {"start": 24.5, "end": 25.0, "text": "", "speaker": "Диктор 1", "role": 1},
            {"start": 25.0, "end": 26.0, "text": "Другой голос.", "speaker": "Диктор 1", "role": 1},
        ],
        {"format": "line", "merge_turns": True},
    )
    assert len(rows) == 2
    assert rows[0]["text"] == "потихонечку сокращается. а вот и ответ."
    assert rows[0]["end"] == 24.0
    assert rows[0]["confidence"] == 0.88
    assert rows[1]["text"] == "Другой голос."


def test_model_diff_picks_winner() -> None:
    a = [{"start": 0, "end": 1, "text": "привет мир", "confidence": 0.6}]
    b = [{"start": 0, "end": 1, "text": "привет мир сегодня", "confidence": 0.9}]
    report = diff_transcripts(a, b, baseline_model="tiny", challenger_model="small")
    assert report["winner"] == "small"
    assert report["changeCount"] >= 1
