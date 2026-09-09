"""Professional transcript helpers: edit, quality, export presets, model diff.

Qt-free so rules stay unit-testable. Controllers call these; QML never imports
them directly.
"""

from __future__ import annotations

import csv
import io
import math
import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

from dotaudio.transcripts import TIME_PRECISION_DIGITS, format_time

# Lower confidence → "needs review". Mapped from Whisper avg_logprob.
LOW_CONFIDENCE = 0.55
# Soft warning band (yellow), below is red/problematic.
WARN_CONFIDENCE = 0.72

EXPORT_PRESETS: dict[str, dict[str, Any]] = {
    "court": {
        "label": "Суд / протокол заседания",
        "format": "txt",
        "include_timestamps": True,
        "include_speakers": True,
        "include_confidence": True,
        "include_review_flags": True,
        "include_header": True,
        "include_phrase_numbers": True,
        "style": "court",
    },
    "protocol": {
        "label": "Чистый протокол (текст + голоса)",
        "format": "txt",
        "include_timestamps": False,
        "include_speakers": True,
        "include_confidence": False,
        "include_review_flags": False,
        "include_header": False,
        "include_phrase_numbers": False,
        "style": "protocol",
    },
    "youtube": {
        "label": "Субтитры YouTube (SRT)",
        "format": "srt",
        "include_timestamps": True,
        "include_speakers": False,
        "include_confidence": False,
        "include_review_flags": False,
        "include_header": False,
        "include_phrase_numbers": False,
        "style": "youtube",
    },
    "broadcast": {
        "label": "Субтитры с говорящими (VTT)",
        "format": "vtt",
        "include_timestamps": True,
        "include_speakers": True,
        "include_confidence": False,
        "include_review_flags": False,
        "include_header": False,
        "include_phrase_numbers": False,
        "style": "broadcast",
    },
    "json_pipeline": {
        "label": "JSON для пайплайна",
        "format": "json",
        "include_timestamps": True,
        "include_speakers": True,
        "include_confidence": True,
        "include_review_flags": True,
        "include_header": False,
        "include_phrase_numbers": False,
        "style": "json",
    },
    "plain": {
        "label": "Только текст",
        "format": "txt",
        "include_timestamps": False,
        "include_speakers": False,
        "include_confidence": False,
        "include_review_flags": False,
        "include_header": False,
        "include_phrase_numbers": False,
        "style": "plain",
    },
}

_OPTION_KEYS = (
    "include_timestamps",
    "include_speakers",
    "include_confidence",
    "include_review_flags",
    "include_header",
    "include_phrase_numbers",
)

# Каталог видов файла. `times: "locked"` - формат не существует без
# таймкодов, переключатель в окне сохранения выключен. `precision` -
# точность, которую формат требует и не отдаёт пользователю.
EXPORT_FORMATS: tuple[dict[str, Any], ...] = (
    {
        "key": "txt",
        "ext": "txt",
        "label": "TXT · простой текст",
        "hint": "Фраза в строке. Годится для чтения и правки в любом редакторе.",
        "filter": "Текст (*.txt)",
        "times": "optional",
        "speakers": True,
        "header": True,
        "numbers": True,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "line",
        "ext": "txt",
        "label": "Строка · время, голос, текст",
        "hint": "00:16 - 00:20 [Диктор 2] текст. Разделители и вид имени настраиваются.",
        "filter": "Текст (*.txt)",
        "times": "optional",
        "speakers": True,
        "header": False,
        "numbers": True,
        "layout": True,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "protocol",
        "ext": "txt",
        "label": "Реплики · по ролям",
        "hint": "Имя голоса строкой, под ним реплика. Читается как пьеса.",
        "filter": "Текст (*.txt)",
        "times": "optional",
        "speakers": True,
        "header": False,
        "numbers": False,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "court",
        "ext": "txt",
        "label": "Протокол · суд и заседание",
        "hint": "Формальный документ: шапка, номера фраз, говорящие, отметки проверки.",
        "filter": "Текст (*.txt)",
        "times": "optional",
        "speakers": True,
        "header": True,
        "numbers": True,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "md",
        "ext": "md",
        "label": "MD · Markdown",
        "hint": "Заголовки говорящих и таймкоды кодом. Для заметок и статей.",
        "filter": "Markdown (*.md)",
        "times": "optional",
        "speakers": True,
        "header": True,
        "numbers": True,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "srt",
        "ext": "srt",
        "label": "SRT · субтитры",
        "hint": "Реплики режутся под строку субтитра. Миллисекунды обязательны.",
        "filter": "Субтитры SRT (*.srt)",
        "times": "locked",
        "precision": "millis",
        "speakers": True,
        "header": False,
        "numbers": False,
        "layout": False,
        "notes": True,
        "subtitles": True,
        "table": False,
    },
    {
        "key": "vtt",
        "ext": "vtt",
        "label": "VTT · веб-субтитры",
        "hint": "То же, что SRT, но для браузера и HTML5-плеера.",
        "filter": "Субтитры VTT (*.vtt)",
        "times": "locked",
        "precision": "millis",
        "speakers": True,
        "header": False,
        "numbers": False,
        "layout": False,
        "notes": True,
        "subtitles": True,
        "table": False,
    },
    {
        "key": "csv",
        "ext": "csv",
        "label": "CSV · таблица",
        "hint": "Колонки для Excel и обработки: время, голос, текст, уверенность.",
        "filter": "Таблица CSV (*.csv)",
        "times": "optional",
        "speakers": True,
        "header": True,
        "numbers": True,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": True,
    },
    {
        "key": "json",
        "ext": "json",
        "label": "JSON · данные",
        "hint": "Полные поля со словами: для своих скриптов и пайплайнов.",
        "filter": "JSON (*.json)",
        "times": "optional",
        "speakers": True,
        "header": False,
        "numbers": False,
        "layout": False,
        "notes": True,
        "subtitles": False,
        "table": False,
    },
    {
        "key": "lrc",
        "ext": "lrc",
        "label": "LRC · для плеера",
        "hint": "Текст с таймкодом строки: плееры и караоке. Точность - сотые.",
        "filter": "Текст песни LRC (*.lrc)",
        "times": "locked",
        "precision": "hundredths",
        "speakers": True,
        "header": True,
        "numbers": False,
        "layout": False,
        "notes": False,
        "subtitles": False,
        "table": False,
    },
)

EXPORT_FORMAT_KEYS = tuple(item["key"] for item in EXPORT_FORMATS)

# Точность таймкода. Пользователь просил не сыпать миллисекундами в тексте,
# поэтому по умолчанию целые секунды; субтитры получают свою точность сами.
TIME_PRECISION_LABELS = {
    "seconds": "Секунды · 00:16",
    "tenths": "Десятые · 00:16.1",
    "hundredths": "Сотые · 00:16.08",
    "millis": "Миллисекунды · 00:16.080",
}

TIME_MODE_LABELS = {
    "range": "Начало и конец",
    "start": "Только начало",
    "none": "Без времени в строке",
}

TIME_HOURS_LABELS = {
    "auto": "Часы, когда нужны",
    "always": "Всегда часы · 00:00:16",
    "never": "Без часов · 75:20",
}

# Разделитель между полями строки: время, голос, текст.
FIELD_SEPARATORS = {
    "space": " ",
    "dash": " - ",
    "pipe": " | ",
    "colon": ":",
    "colon_space": ": ",
    "middot": " · ",
    "tab": "\t",
}

FIELD_SEPARATOR_LABELS = {
    "space": "Пробел",
    "dash": "Тире · время - голос - текст",
    "pipe": "Вертикальная черта",
    "colon": "Двоеточие · время:голос:текст",
    "colon_space": "Двоеточие с пробелом",
    "middot": "Точка по центру",
    "tab": "Табуляция",
}

# Разделитель начала и конца внутри таймкода.
RANGE_SEPARATORS = {
    "dash": " - ",
    "arrow": " --> ",
    "comma": ", ",
    "space": " ",
    "slash": " / ",
}

RANGE_SEPARATOR_LABELS = {
    "dash": "00:16 - 00:20",
    "arrow": "00:16 --> 00:20",
    "comma": "00:16, 00:20",
    "space": "00:16 00:20",
    "slash": "00:16 / 00:20",
}

SPEAKER_STYLE_LABELS = {
    "bracket": "[Диктор 2]",
    "angle": "<Диктор 2>",
    "paren": "(Диктор 2)",
    "colon": "Диктор 2:",
    "plain": "Диктор 2",
    "none": "Без имени",
}

CSV_DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t"}

CSV_DELIMITER_LABELS = {
    "comma": "Запятая",
    "semicolon": "Точка с запятой · Excel RU",
    "tab": "Табуляция",
}

_BOOL_OPTIONS: dict[str, bool] = {
    "include_timestamps": False,
    "include_speakers": True,
    "include_confidence": False,
    "include_review_flags": False,
    "include_header": False,
    "include_phrase_numbers": False,
    "only_flagged": False,
    "speaker_once": False,
    "merge_turns": False,
    "blank_between": False,
    "skip_empty": True,
    "include_duration": False,
    "csv_bom": True,
}

_ENUM_OPTIONS: dict[str, tuple[dict[str, Any], str]] = {
    "time_precision": (TIME_PRECISION_DIGITS, "seconds"),
    "time_mode": (TIME_MODE_LABELS, "range"),
    "time_hours": (TIME_HOURS_LABELS, "auto"),
    "field_separator": (FIELD_SEPARATORS, "space"),
    "range_separator": (RANGE_SEPARATORS, "dash"),
    "speaker_style": (SPEAKER_STYLE_LABELS, "bracket"),
    "csv_delimiter": (CSV_DELIMITERS, "comma"),
}

SUBTITLE_CHAR_LIMITS = (24, 200)
SUBTITLE_DURATION_LIMITS = (1.0, 30.0)


def export_format(key: str) -> dict[str, Any]:
    """Metadata of one file kind; unknown keys fall back to TXT."""

    want = str(key or "txt").strip().lower()
    for item in EXPORT_FORMATS:
        if item["key"] == want:
            return dict(item)
    return dict(EXPORT_FORMATS[0])


def export_format_list() -> list[dict[str, Any]]:
    """Catalogue for the save dialog: label, hint and what the format allows."""

    return [dict(item) for item in EXPORT_FORMATS]


def export_option_choices() -> dict[str, list[dict[str, str]]]:
    """Dropdown contents for the save dialog, keyed by option name."""

    def rows(labels: dict[str, str]) -> list[dict[str, str]]:
        return [{"key": key, "label": label} for key, label in labels.items()]

    return {
        "time_precision": rows(TIME_PRECISION_LABELS),
        "time_mode": rows(TIME_MODE_LABELS),
        "time_hours": rows(TIME_HOURS_LABELS),
        "field_separator": rows(FIELD_SEPARATOR_LABELS),
        "range_separator": rows(RANGE_SEPARATOR_LABELS),
        "speaker_style": rows(SPEAKER_STYLE_LABELS),
        "csv_delimiter": rows(CSV_DELIMITER_LABELS),
    }


def normalise_export_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and complete the save options coming from the UI or settings.

    Every renderer reads the result, so an unknown value never reaches a
    document: it falls back to the default. Formats that cannot exist without
    timings get them forced on, together with the precision they require.
    """

    raw = dict(options or {})
    fmt = str(raw.get("format") or "txt").strip().lower()
    if fmt not in EXPORT_FORMAT_KEYS:
        raise ValueError(f"unsupported transcript format: {fmt}")
    meta = export_format(fmt)
    opts: dict[str, Any] = {"format": fmt}
    for name, fallback in _BOOL_OPTIONS.items():
        value = raw.get(name, fallback)
        opts[name] = bool(value)
    for name, (allowed, fallback) in _ENUM_OPTIONS.items():
        value = str(raw.get(name, fallback) or fallback).strip().lower()
        opts[name] = value if value in allowed else fallback

    if meta["times"] == "locked":
        opts["include_timestamps"] = True
    forced = meta.get("precision")
    if forced:
        opts["time_precision"] = str(forced)
    if not opts["include_timestamps"]:
        opts["time_mode"] = "none"
    elif opts["time_mode"] == "none":
        opts["time_mode"] = "start"

    try:
        speaker_key = int(raw.get("speaker_key") or 0)
    except (TypeError, ValueError):
        speaker_key = 0
    opts["speaker_key"] = max(0, speaker_key)

    low, high = SUBTITLE_CHAR_LIMITS
    try:
        chars = int(raw.get("subtitle_max_chars", 42))
    except (TypeError, ValueError):
        chars = 42
    opts["subtitle_max_chars"] = max(low, min(high, chars))
    low_d, high_d = SUBTITLE_DURATION_LIMITS
    try:
        span = float(raw.get("subtitle_max_duration", 6.0))
    except (TypeError, ValueError):
        span = 6.0
    if not math.isfinite(span):
        span = 6.0
    opts["subtitle_max_duration"] = round(max(low_d, min(high_d, span)), 2)

    for name in ("title", "source", "model"):
        opts[name] = str(raw.get(name) or "")

    opts["ext"] = str(meta["ext"])
    opts["label"] = str(meta["label"])
    opts["filter"] = str(meta["filter"])
    # Excel читает кириллицу в CSV только с BOM; остальные форматы - чистый UTF-8.
    opts["encoding"] = (
        "utf-8-sig" if fmt == "csv" and opts["csv_bom"] else "utf-8"
    )
    return opts


def _stamp_options(
    precision: str = "millis",
    mode: str = "range",
    hours: str = "auto",
    separator: str = "dash",
) -> dict[str, Any]:
    """Minimal option set that ``_time_token`` needs, with safe fallbacks."""

    return {
        "time_precision": (
            precision if precision in TIME_PRECISION_DIGITS else "millis"
        ),
        "time_mode": mode if mode in TIME_MODE_LABELS else "range",
        "time_hours": hours if hours in TIME_HOURS_LABELS else "auto",
        "range_separator": separator if separator in RANGE_SEPARATORS else "dash",
    }


def _time_token(row: dict[str, Any], opts: dict[str, Any]) -> str:
    mode = str(opts["time_mode"])
    if mode == "none":
        return ""
    start = float(row.get("start", 0.0))
    head = format_time(
        start,
        precision=str(opts["time_precision"]),
        hours=str(opts["time_hours"]),
    )
    if mode != "range":
        return head
    end = float(row.get("end", start))
    tail = format_time(
        max(start, end),
        precision=str(opts["time_precision"]),
        hours=str(opts["time_hours"]),
    )
    return f"{head}{RANGE_SEPARATORS[str(opts['range_separator'])]}{tail}"


def _speaker_token(name: str, style: str) -> str:
    label = str(name or "").strip()
    if not label or style == "none":
        return ""
    if style == "bracket":
        return f"[{label}]"
    if style == "angle":
        return f"<{label}>"
    if style == "paren":
        return f"({label})"
    if style == "colon":
        return f"{label}:"
    return label


def merge_speaker_turns(
    segments: list[dict[str, Any]],
    *,
    max_gap: float | None = None,
) -> list[dict[str, Any]]:
    """Join neighbouring phrases of one speaker into a single turn.

    A turn keeps the first start and the last end; confidence drops to the
    weakest known value, because the whole turn is only as reliable as its
    worst phrase.
    """

    rows: list[dict[str, Any]] = []
    for row in segments or []:
        item = dict(row)
        if not rows:
            rows.append(item)
            continue
        previous = rows[-1]
        same_voice = str(previous.get("speaker") or "").strip() == str(
            item.get("speaker") or ""
        ).strip() and int(previous.get("role") or 0) == int(item.get("role") or 0)
        gap = float(item.get("start", 0.0)) - float(previous.get("end", 0.0))
        if not same_voice or (max_gap is not None and gap > float(max_gap)):
            rows.append(item)
            continue
        text = " ".join(
            part
            for part in (
                str(previous.get("text") or "").strip(),
                str(item.get("text") or "").strip(),
            )
            if part
        )
        left = segment_confidence(previous)
        right = segment_confidence(item)
        if left >= 0 and right >= 0:
            confidence = min(left, right)
        else:
            confidence = left if left >= 0 else right
        previous.update(
            {
                "end": max(float(previous.get("end", 0.0)), float(item.get("end", 0.0))),
                "text": text,
                "words": list(previous.get("words") or []) + list(item.get("words") or []),
                "confidence": confidence,
                "reviewed": bool(previous.get("reviewed")) and bool(item.get("reviewed")),
            }
        )
    return rows


def line_document(
    segments: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> str:
    """One phrase per line: time, speaker and text joined by chosen separators."""

    opts = normalise_export_options({**(options or {}), "format": "line"})
    joiner = FIELD_SEPARATORS[str(opts["field_separator"])]
    style = str(opts["speaker_style"])
    lines: list[str] = []
    previous_speaker: str | None = None
    for index, row in enumerate(segments, start=1):
        text = str(row.get("text") or "").strip()
        if not text and opts["skip_empty"]:
            previous_speaker = None
            continue
        speaker = str(row.get("speaker") or "").strip()
        show_speaker = bool(opts["include_speakers"])
        if show_speaker and opts["speaker_once"] and speaker == previous_speaker:
            show_speaker = False
        fields: list[str] = []
        if opts["include_phrase_numbers"]:
            fields.append(f"{index}.")
        stamp = _time_token(row, opts)
        if stamp:
            fields.append(stamp)
        if opts["include_duration"]:
            span = max(0.0, float(row.get("end", 0.0)) - float(row.get("start", 0.0)))
            fields.append(f"({span:.1f} с)")
        if show_speaker:
            token = _speaker_token(speaker, style)
            if token:
                fields.append(token)
        fields.append(
            _annotate_text(
                text,
                row,
                include_confidence=bool(opts["include_confidence"]),
                include_review_flags=bool(opts["include_review_flags"]),
            )
        )
        lines.append(joiner.join(field for field in fields if field))
        if opts["blank_between"]:
            lines.append("")
        previous_speaker = speaker
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def table_document(
    segments: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> str:
    """CSV/TSV rows for spreadsheets: only the requested columns appear."""

    opts = normalise_export_options({**(options or {}), "format": "csv"})
    delimiter = CSV_DELIMITERS[str(opts["csv_delimiter"])]
    columns: list[str] = []
    if opts["include_phrase_numbers"]:
        columns.append("№")
    if opts["include_timestamps"]:
        columns.append("начало")
        if str(opts["time_mode"]) == "range":
            columns.append("конец")
    if opts["include_duration"]:
        columns.append("длительность")
    if opts["include_speakers"]:
        columns.append("голос")
    columns.append("текст")
    if opts["include_confidence"]:
        columns.append("уверенность")
    if opts["include_review_flags"]:
        columns.append("проверено")

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    if opts["include_header"]:
        writer.writerow(columns)
    precision = str(opts["time_precision"])
    hours = str(opts["time_hours"])
    for index, row in enumerate(segments, start=1):
        text = str(row.get("text") or "").strip()
        if not text and opts["skip_empty"]:
            continue
        start = float(row.get("start", 0.0))
        end = max(start, float(row.get("end", start)))
        cells: list[str] = []
        if opts["include_phrase_numbers"]:
            cells.append(str(index))
        if opts["include_timestamps"]:
            cells.append(format_time(start, precision=precision, hours=hours))
            if str(opts["time_mode"]) == "range":
                cells.append(format_time(end, precision=precision, hours=hours))
        if opts["include_duration"]:
            cells.append(f"{end - start:.2f}")
        if opts["include_speakers"]:
            cells.append(str(row.get("speaker") or "").strip())
        cells.append(text)
        if opts["include_confidence"]:
            score = segment_confidence(row)
            cells.append("" if score < 0 else f"{score:.3f}")
        if opts["include_review_flags"]:
            flagged = needs_review(row) and not bool(row.get("reviewed"))
            cells.append("нет" if flagged else "да")
        writer.writerow(cells)
    return buffer.getvalue()


def lrc_document(
    segments: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> str:
    """Lyrics timing file: ``[mm:ss.xx]`` and the phrase, as players expect."""

    opts = normalise_export_options({**(options or {}), "format": "lrc"})
    lines: list[str] = []
    if opts["include_header"]:
        title = str(opts.get("title") or "").strip()
        if title:
            lines.append(f"[ti:{title}]")
        model = str(opts.get("model") or "").strip()
        if model:
            lines.append(f"[re:DotAudio Whisper {model}]")
    style = str(opts["speaker_style"])
    for row in segments:
        text = str(row.get("text") or "").strip()
        if not text and opts["skip_empty"]:
            continue
        # Плееры читают только mm:ss.xx без часов, длинная запись копит минуты.
        stamp = format_time(
            float(row.get("start", 0.0)), precision="hundredths", hours="never"
        )
        body = text
        if opts["include_speakers"]:
            token = _speaker_token(str(row.get("speaker") or ""), style)
            if token:
                body = f"{token} {text}".strip()
        lines.append(f"[{stamp}]{body}")
    return "\n".join(lines) + ("\n" if lines else "")


def resolve_export_options(
    preset_key: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge preset defaults with user overrides for export filters."""

    key = str(preset_key or "plain").strip().lower()
    preset = dict(EXPORT_PRESETS.get(key) or EXPORT_PRESETS["plain"])
    options = {
        "preset": key,
        "format": str(preset.get("format") or "txt"),
        "style": str(preset.get("style") or "plain"),
        "label": str(preset.get("label") or key),
    }
    for name in _OPTION_KEYS:
        options[name] = bool(preset.get(name, False))
    for name, value in (overrides or {}).items():
        if name in _OPTION_KEYS:
            options[name] = bool(value)
    return options


def preset_defaults(preset_key: str) -> dict[str, Any]:
    """Defaults for QML toggles when the user picks a preset."""

    options = resolve_export_options(preset_key)
    return {name: options[name] for name in _OPTION_KEYS}


def confidence_from_logprob(avg_logprob: float) -> float:
    """Map Whisper avg_logprob (~-1..0) to a 0..1 confidence score."""

    try:
        value = float(avg_logprob)
    except (TypeError, ValueError):
        return -1.0
    if not math.isfinite(value):
        return -1.0
    # avg_logprob of 0 → 1.0; -1.0 → ~0.37; -2 → ~0.14
    score = math.exp(max(-5.0, min(0.0, value)))
    return round(max(0.0, min(1.0, score)), 4)


def segment_confidence(segment: dict[str, Any]) -> float:
    """Read confidence from a segment; -1 when unknown."""

    raw = segment.get("confidence")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return -1.0
    if not math.isfinite(value):
        return -1.0
    return value


def needs_review(segment: dict[str, Any], threshold: float = LOW_CONFIDENCE) -> bool:
    """Whether a phrase should be inspected before court/protocol export."""

    score = segment_confidence(segment)
    if score < 0:
        # Unknown confidence: treat empty or very short as review.
        text = str(segment.get("text") or "").strip()
        return len(text) < 2
    return score < float(threshold)


def quality_stats(segments: list[dict[str, Any]]) -> dict[str, Any]:
    rows = list(segments or [])
    flagged = [row for row in rows if needs_review(row)]
    known = [segment_confidence(row) for row in rows if segment_confidence(row) >= 0]
    return {
        "total": len(rows),
        "flagged": len(flagged),
        "checked": max(0, len(rows) - len(flagged)),
        "meanConfidence": round(sum(known) / len(known), 3) if known else -1.0,
        "unknown": sum(1 for row in rows if segment_confidence(row) < 0),
    }


def apply_dictionary(
    text: str,
    dictionary: list[dict[str, Any]] | None,
    *,
    snippets: list[dict[str, Any]] | None = None,
) -> str:
    """Apply misheard→term and optional snippets to one string."""

    result = str(text or "")
    for entry in dictionary or []:
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term", "")).strip()
        misheard = str(entry.get("misheard", "")).strip()
        if term and misheard:
            result = re.sub(
                rf"(?<!\w){re.escape(misheard)}(?!\w)",
                term,
                result,
                flags=re.IGNORECASE,
            )
    for entry in snippets or []:
        if not isinstance(entry, dict):
            continue
        trigger = str(entry.get("trigger", "")).strip()
        expansion = str(entry.get("expansion", "")).strip()
        if trigger and expansion:
            result = re.sub(
                rf"(?<!\w){re.escape(trigger)}(?!\w)",
                expansion,
                result,
                flags=re.IGNORECASE,
            )
    return result


def find_replace(
    segments: list[dict[str, Any]],
    find: str,
    replace: str,
    *,
    match_case: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Replace in segment texts. Returns (new_rows, replacement_count)."""

    needle = str(find or "")
    if not needle:
        return deepcopy(segments), 0
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile(re.escape(needle), flags)
    count = 0
    result: list[dict[str, Any]] = []
    for row in segments:
        item = deepcopy(row)
        text = str(item.get("text") or "")
        new_text, n = pattern.subn(str(replace or ""), text)
        if n:
            item["text"] = new_text
            count += n
        result.append(item)
    return result, count


def merge_segments(
    segments: list[dict[str, Any]],
    index: int,
) -> list[dict[str, Any]]:
    """Merge ``index`` with the next segment. Raises ValueError if impossible."""

    rows = deepcopy(list(segments))
    if index < 0 or index >= len(rows) - 1:
        raise ValueError("Нет соседней фразы для склейки")
    left = rows[index]
    right = rows[index + 1]
    left_speaker = str(left.get("speaker") or "").strip()
    right_speaker = str(right.get("speaker") or "").strip()
    if left_speaker and right_speaker and left_speaker != right_speaker:
        raise ValueError("Нельзя склеить фразы разных говорящих")
    text = " ".join(
        part for part in (str(left.get("text") or "").strip(), str(right.get("text") or "").strip()) if part
    )
    words = list(left.get("words") or []) + list(right.get("words") or [])
    conf_l = segment_confidence(left)
    conf_r = segment_confidence(right)
    if conf_l >= 0 and conf_r >= 0:
        confidence = min(conf_l, conf_r)
    else:
        confidence = conf_l if conf_l >= 0 else conf_r
    merged = {
        **left,
        "start": float(left["start"]),
        "end": float(right["end"]),
        "text": text,
        "words": words,
        "speaker": left_speaker or right_speaker,
        "confidence": confidence,
        "reviewed": bool(left.get("reviewed")) and bool(right.get("reviewed")),
    }
    return rows[:index] + [merged] + rows[index + 2 :]


def split_segment(
    segments: list[dict[str, Any]],
    index: int,
    at_seconds: float,
) -> list[dict[str, Any]]:
    """Split segment at time. Text split on nearest word boundary when possible."""

    rows = deepcopy(list(segments))
    if index < 0 or index >= len(rows):
        raise ValueError("Фраза не найдена")
    row = rows[index]
    start = float(row["start"])
    end = float(row["end"])
    cut = float(at_seconds)
    if not math.isfinite(cut) or cut <= start + 0.05 or cut >= end - 0.05:
        raise ValueError("Точка разреза должна быть внутри фразы")
    words = list(row.get("words") or [])
    left_words = [w for w in words if float(w.get("end", start)) <= cut + 1e-6]
    right_words = [w for w in words if float(w.get("start", end)) >= cut - 1e-6]
    if left_words and right_words:
        left_text = " ".join(str(w.get("text") or "").strip() for w in left_words).strip()
        right_text = " ".join(str(w.get("text") or "").strip() for w in right_words).strip()
    else:
        # No safe word timings: keep full text on the left, empty marker on right.
        body = str(row.get("text") or "").strip()
        tokens = body.split()
        if len(tokens) < 2:
            raise ValueError("Слишком короткая фраза для разреза")
        ratio = (cut - start) / max(1e-6, end - start)
        mid = max(1, min(len(tokens) - 1, int(round(len(tokens) * ratio))))
        left_text = " ".join(tokens[:mid])
        right_text = " ".join(tokens[mid:])
        left_words = []
        right_words = []
    conf = segment_confidence(row)
    left = {
        **row,
        "start": start,
        "end": cut,
        "text": left_text,
        "words": left_words,
        "confidence": conf,
        "reviewed": False,
    }
    right = {
        **{k: v for k, v in row.items() if k != "id"},
        "start": cut,
        "end": end,
        "text": right_text,
        "words": right_words,
        "speaker": row.get("speaker") or "",
        "confidence": conf,
        "reviewed": False,
        "role": row.get("role"),
    }
    return rows[:index] + [left, right] + rows[index + 1 :]


def set_phrase_window(
    segments: list[dict[str, Any]],
    index: int,
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    """Move phrase timing; clamp to neighbours."""

    rows = deepcopy(list(segments))
    if index < 0 or index >= len(rows):
        raise ValueError("Фраза не найдена")
    try:
        a = float(start)
        b = float(end)
    except (TypeError, ValueError) as error:
        raise ValueError("Некорректные границы") from error
    if not math.isfinite(a) or not math.isfinite(b) or b <= a:
        raise ValueError("Конец должен быть позже начала")
    if index > 0:
        a = max(a, float(rows[index - 1]["end"]))
    if index + 1 < len(rows):
        b = min(b, float(rows[index + 1]["start"]))
    if b <= a + 0.04:
        raise ValueError("Слишком узкое окно фразы")
    rows[index]["start"] = a
    rows[index]["end"] = b
    rows[index]["reviewed"] = False
    return rows


def mark_reviewed(
    segments: list[dict[str, Any]],
    index: int,
    reviewed: bool = True,
) -> list[dict[str, Any]]:
    rows = deepcopy(list(segments))
    if 0 <= index < len(rows):
        rows[index]["reviewed"] = bool(reviewed)
    return rows


def filter_problematic(
    segments: list[dict[str, Any]],
    *,
    only_flagged: bool,
) -> list[dict[str, Any]]:
    if not only_flagged:
        return list(segments)
    return [
        row
        for row in segments
        if needs_review(row) and not bool(row.get("reviewed"))
    ]


def court_document(
    segments: list[dict[str, Any]],
    *,
    title: str = "",
    source: str = "",
    model: str = "",
    include_timestamps: bool = True,
    include_speakers: bool = True,
    include_confidence: bool = True,
    include_review_flags: bool = True,
    include_header: bool = True,
    include_phrase_numbers: bool = True,
    time_precision: str = "millis",
    time_mode: str = "range",
    time_hours: str = "auto",
    range_separator: str = "dash",
) -> str:
    """Formal transcript for court / hearing protocol use."""

    stamp = _stamp_options(time_precision, time_mode, time_hours, range_separator)
    lines: list[str] = []
    if include_header:
        lines.extend(["ПРОТОКОЛ РАСШИФРОВКИ АУДИОЗАПИСИ", ""])
        if title:
            lines.append(f"Материал: {title}")
        if source:
            lines.append(f"Файл: {source}")
        if model:
            lines.append(f"Модель распознавания: {model}")
        stats = quality_stats(segments)
        lines.append(f"Фраз: {stats['total']}")
        if include_review_flags and stats["flagged"]:
            lines.append(
                f"Требуют проверки (низкая уверенность): {stats['flagged']}"
            )
        lines.append("")
        lines.append("-" * 48)
        lines.append("")
    for index, row in enumerate(segments, start=1):
        start = float(row.get("start", 0.0))
        end = float(row.get("end", start))
        speaker = str(row.get("speaker") or "").strip() or "НЕ УКАЗАН"
        text = str(row.get("text") or "").strip()
        conf = segment_confidence(row)
        head_parts: list[str] = []
        if include_phrase_numbers:
            head_parts.append(f"{index}.")
        if include_timestamps:
            head_parts.append(_time_token({"start": start, "end": end}, stamp))
        head_parts = [part for part in head_parts if part]
        if head_parts:
            lines.append(" ".join(head_parts))
        flag = ""
        if include_review_flags and needs_review(row) and not row.get("reviewed"):
            flag = " [НА ПРОВЕРКУ]"
        elif include_confidence and conf >= 0:
            flag = f" [уверенность {conf:.0%}]"
        if include_speakers:
            lines.append(f"   Говорящий: {speaker}{flag}")
        elif flag:
            lines.append(f"   {flag.strip()}")
        lines.append(f"   {text}" if include_speakers or include_phrase_numbers or include_timestamps else text)
        lines.append("")
    if include_header:
        lines.append("-" * 48)
        lines.append("Конец протокола.")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def protocol_document(
    segments: list[dict[str, Any]],
    *,
    include_timestamps: bool = False,
    include_speakers: bool = True,
    include_confidence: bool = False,
    include_review_flags: bool = False,
    time_precision: str = "millis",
    time_mode: str = "range",
    time_hours: str = "auto",
    range_separator: str = "dash",
) -> str:
    """Speaker-labelled protocol; optional timestamps and confidence notes."""

    stamp = _stamp_options(time_precision, time_mode, time_hours, range_separator)
    blocks: list[str] = []
    previous = None
    for row in segments:
        speaker = str(row.get("speaker") or "").strip() or "Голос"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        notes: list[str] = []
        if include_timestamps:
            notes.append(_time_token(row, stamp))
        conf = segment_confidence(row)
        if include_review_flags and needs_review(row) and not row.get("reviewed"):
            notes.append("на проверку")
        elif include_confidence and conf >= 0:
            notes.append(f"{conf:.0%}")
        notes = [note for note in notes if note]
        suffix = f" ({'; '.join(notes)})" if notes else ""
        if include_speakers:
            if speaker != previous:
                blocks.append(f"{speaker}:")
                previous = speaker
            blocks.append(f"{text}{suffix}")
        else:
            blocks.append(f"{text}{suffix}")
        blocks.append("")
    return "\n".join(blocks).rstrip() + ("\n" if blocks else "")


def _annotate_text(
    text: str,
    row: dict[str, Any],
    *,
    include_confidence: bool,
    include_review_flags: bool,
) -> str:
    body = str(text or "").strip()
    notes: list[str] = []
    conf = segment_confidence(row)
    if include_review_flags and needs_review(row) and not row.get("reviewed"):
        notes.append("на проверку")
    elif include_confidence and conf >= 0:
        notes.append(f"{conf:.0%}")
    if not notes:
        return body
    return f"{body} [{'; '.join(notes)}]".strip()


def filter_export_rows(
    segments: list[dict[str, Any]],
    *,
    speaker_key: int = 0,
    only_flagged: bool = False,
) -> list[dict[str, Any]]:
    """Keep phrases that match save filters (voice and review)."""

    rows = list(segments or [])
    key = int(speaker_key or 0)
    if key > 0:
        rows = [row for row in rows if int(row.get("role") or 0) == key]
    if only_flagged:
        rows = [row for row in rows if needs_review(row) and not bool(row.get("reviewed"))]
    return rows


def export_rows(
    segments: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Phrases the current options actually save, after filters and merging."""

    opts = normalise_export_options(options)
    rows = filter_export_rows(
        list(segments or []),
        speaker_key=int(opts["speaker_key"]),
        only_flagged=bool(opts["only_flagged"]),
    )
    if opts["skip_empty"]:
        rows = [row for row in rows if str(row.get("text") or "").strip()]
    if opts["merge_turns"]:
        rows = merge_speaker_turns(rows)
    return rows


def formatted_document(
    segments: list[dict[str, Any]],
    *,
    fmt: str = "txt",
    title: str = "",
    source: str = "",
    include_timestamps: bool = True,
    include_speakers: bool = True,
    include_confidence: bool = False,
    include_review_flags: bool = False,
    include_header: bool = True,
    include_phrase_numbers: bool = True,
    time_precision: str = "millis",
    time_mode: str = "range",
    time_hours: str = "auto",
    range_separator: str = "dash",
) -> str:
    """Readable TXT/MD dump driven by the same save toggles as the preview."""

    kind = str(fmt or "txt").strip().lower()
    stamp_options = {
        "time_mode": str(time_mode),
        "time_precision": str(time_precision),
        "time_hours": str(time_hours),
        "range_separator": (
            range_separator if range_separator in RANGE_SEPARATORS else "dash"
        ),
    }
    lines: list[str] = []
    if include_header:
        if kind == "md":
            lines.append("# Расшифровка")
            if title:
                lines.append(f"**Файл:** {title}")
            if source and source != title:
                lines.append(f"**Источник:** {source}")
            lines.append(f"**Фраз:** {len(segments)}")
            lines.append("")
        else:
            lines.append("Расшифровка")
            if title:
                lines.append(f"Файл: {title}")
            if source and source != title:
                lines.append(f"Источник: {source}")
            lines.append(f"Фраз: {len(segments)}")
            lines.append("")
    for index, row in enumerate(segments, start=1):
        start = float(row.get("start", 0.0))
        end = float(row.get("end", start))
        speaker = str(row.get("speaker") or "").strip()
        text = str(row.get("text") or "").strip()
        notes: list[str] = []
        if include_review_flags and needs_review(row) and not row.get("reviewed"):
            notes.append("на проверку")
        elif include_confidence:
            conf = segment_confidence(row)
            if conf >= 0:
                notes.append(f"{conf:.0%}")
        note = f" [{'; '.join(notes)}]" if notes else ""
        head_parts: list[str] = []
        if include_phrase_numbers:
            head_parts.append(f"{index}.")
        if include_timestamps:
            head_parts.append(_time_token({"start": start, "end": end}, stamp_options))
        head = " ".join(part for part in head_parts if part)
        if kind == "md":
            who = f"**{speaker}.** " if include_speakers and speaker else ""
            prefix = f"{head} " if head else ""
            lines.append(f"{prefix}{who}{text}{note}".strip())
            lines.append("")
        else:
            if head:
                lines.append(head)
            if include_speakers and speaker:
                indent = "   " if head else ""
                lines.append(f"{indent}{speaker}: {text}{note}")
            else:
                indent = "   " if head else ""
                lines.append(f"{indent}{text}{note}")
            lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def render_export(
    segments: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Build the saved document from format + filter toggles.

    Returns ``(text, file_extension)``. Empty text means no phrases matched.
    """

    from dotaudio.transcripts import export_transcript, regroup_for_subtitles

    opts = normalise_export_options(options)
    fmt = str(opts["format"])
    ext = str(opts["ext"])
    rows = export_rows(segments, opts)
    if not rows:
        return "", ext

    with_times = bool(opts["include_timestamps"])
    with_speakers = bool(opts["include_speakers"])
    with_conf = bool(opts["include_confidence"])
    with_flags = bool(opts["include_review_flags"])
    with_header = bool(opts["include_header"])
    with_numbers = bool(opts["include_phrase_numbers"])
    precision = str(opts["time_precision"])
    time_mode = str(opts["time_mode"])
    time_hours = str(opts["time_hours"])

    if fmt == "line":
        return line_document(rows, opts), ext
    if fmt == "csv":
        return table_document(rows, opts), ext
    if fmt == "lrc":
        return lrc_document(rows, opts), ext
    if fmt == "court":
        return (
            court_document(
                rows,
                title=str(opts.get("title") or ""),
                source=str(opts.get("source") or ""),
                model=str(opts.get("model") or ""),
                include_timestamps=with_times,
                include_speakers=with_speakers,
                include_confidence=with_conf,
                include_review_flags=with_flags,
                include_header=with_header,
                include_phrase_numbers=with_numbers,
                time_precision=precision,
                time_mode=time_mode,
                time_hours=time_hours,
                range_separator=str(opts["range_separator"]),
            ),
            ext,
        )
    if fmt == "protocol":
        return (
            protocol_document(
                rows,
                include_timestamps=with_times,
                include_speakers=with_speakers,
                include_confidence=with_conf,
                include_review_flags=with_flags,
                time_precision=precision,
                time_mode=time_mode,
                time_hours=time_hours,
                range_separator=str(opts["range_separator"]),
            ),
            ext,
        )

    if fmt in ("txt", "md") and (with_header or with_numbers):
        return (
            formatted_document(
                rows,
                fmt=fmt,
                title=str(opts.get("title") or ""),
                source=str(opts.get("source") or ""),
                include_timestamps=with_times,
                include_speakers=with_speakers,
                include_confidence=with_conf,
                include_review_flags=with_flags,
                include_header=with_header,
                include_phrase_numbers=with_numbers,
                time_precision=precision,
                time_mode=time_mode,
                time_hours=time_hours,
                range_separator=str(opts["range_separator"]),
            ),
            ext,
        )

    if fmt in ("srt", "vtt"):
        cues = regroup_for_subtitles(
            rows,
            max_chars=int(opts["subtitle_max_chars"]),
            max_duration=float(opts["subtitle_max_duration"]),
        )
        enriched: list[dict[str, Any]] = []
        for cue in cues:
            mid = (float(cue["start"]) + float(cue["end"])) / 2.0
            speaker = ""
            source_row: dict[str, Any] = cue
            for seg in rows:
                if float(seg["start"]) <= mid <= float(seg["end"]):
                    speaker = str(seg.get("speaker") or "").strip()
                    source_row = seg
                    break
            item = {**cue, "speaker": speaker}
            item["text"] = _annotate_text(
                str(cue.get("text") or ""),
                source_row,
                include_confidence=with_conf,
                include_review_flags=with_flags,
            )
            enriched.append(item)
        return (
            export_transcript(
                enriched,
                fmt,
                include_timestamps=True,
                include_speakers=with_speakers,
                time_precision=precision,
            ),
            ext,
        )

    annotated = []
    for row in rows:
        item = dict(row)
        if fmt != "json":
            item["text"] = _annotate_text(
                str(row.get("text") or ""),
                row,
                include_confidence=with_conf,
                include_review_flags=with_flags,
            )
        annotated.append(item)
    return (
        export_transcript(
            annotated,
            fmt,
            include_timestamps=with_times,
            include_speakers=with_speakers,
            include_confidence=with_conf if fmt == "json" else False,
            include_review_flags=with_flags if fmt == "json" else False,
            time_precision=precision,
            time_mode=time_mode,
            time_hours=time_hours,
            range_join=RANGE_SEPARATORS[str(opts["range_separator"])],
        ),
        ext,
    )


def export_with_preset(
    segments: list[dict[str, Any]],
    preset_key: str,
    *,
    title: str = "",
    source: str = "",
    model: str = "",
    options: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Return (text, format_ext, suggested_filename_stem).

    ``options`` overrides preset defaults: timestamps, speakers, confidence,
    review flags, header, phrase numbers.
    """

    opts = resolve_export_options(preset_key, options)
    style = str(opts["style"])
    rows = list(segments)
    with_times = bool(opts["include_timestamps"])
    with_speakers = bool(opts["include_speakers"])
    with_conf = bool(opts["include_confidence"])
    with_flags = bool(opts["include_review_flags"])

    if style == "court":
        return (
            court_document(
                rows,
                title=title,
                source=source,
                model=model,
                include_timestamps=with_times,
                include_speakers=with_speakers,
                include_confidence=with_conf,
                include_review_flags=with_flags,
                include_header=bool(opts["include_header"]),
                include_phrase_numbers=bool(opts["include_phrase_numbers"]),
            ),
            "txt",
            "protocol_court",
        )
    if style == "protocol":
        return (
            protocol_document(
                rows,
                include_timestamps=with_times,
                include_speakers=with_speakers,
                include_confidence=with_conf,
                include_review_flags=with_flags,
            ),
            "txt",
            "protocol",
        )

    payload = dict(opts)
    payload["title"] = title
    payload["source"] = source
    payload["model"] = model
    body, ext = render_export(rows, payload)
    if style == "plain":
        return body, "txt", "transcript"
    if ext in ("srt", "vtt"):
        return body, ext, f"subtitles_{ext}"
    return body, ext, f"transcript_{ext}"


def diff_transcripts(
    baseline: list[dict[str, Any]],
    challenger: list[dict[str, Any]],
    *,
    baseline_model: str,
    challenger_model: str,
) -> dict[str, Any]:
    """Compare two transcript runs for the model bake-off UI."""

    a = " ".join(str(row.get("text") or "").strip() for row in baseline).split()
    b = " ".join(str(row.get("text") or "").strip() for row in challenger).split()
    matcher = SequenceMatcher(a=a, b=b)
    ratio = matcher.ratio()
    opcodes = matcher.get_opcodes()
    changes = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        changes.append(
            {
                "op": tag,
                "baseline": " ".join(a[i1:i2]),
                "challenger": " ".join(b[j1:j2]),
            }
        )
    # Prefer higher mean confidence, then longer (more complete) text.
    conf_a = quality_stats(baseline)["meanConfidence"]
    conf_b = quality_stats(challenger)["meanConfidence"]
    len_a = sum(len(str(r.get("text") or "")) for r in baseline)
    len_b = sum(len(str(r.get("text") or "")) for r in challenger)
    if conf_b > conf_a + 0.02:
        winner = challenger_model
        reason = "выше средняя уверенность модели"
    elif conf_a > conf_b + 0.02:
        winner = baseline_model
        reason = "выше средняя уверенность модели"
    elif abs(len_b - len_a) > max(40, 0.08 * max(len_a, len_b, 1)):
        winner = challenger_model if len_b > len_a else baseline_model
        reason = "больше распознанного текста без обрезки"
    elif ratio > 0.92:
        winner = baseline_model
        reason = "результаты почти совпадают; оставлена базовая модель"
    else:
        winner = challenger_model if ratio < 0.85 and len_b >= len_a else baseline_model
        reason = "по сходству и полноте текста"

    return {
        "baselineModel": baseline_model,
        "challengerModel": challenger_model,
        "similarity": round(ratio, 4),
        "changes": changes[:80],
        "changeCount": len(changes),
        "baselineStats": quality_stats(baseline),
        "challengerStats": quality_stats(challenger),
        "winner": winner,
        "reason": reason,
        "baselineSegments": len(baseline),
        "challengerSegments": len(challenger),
    }


def serialize_compare_report(report: dict[str, Any]) -> str:
    """Human-readable bake-off summary."""

    lines = [
        "Сравнение прогонов Whisper",
        f"База: {report.get('baselineModel')} ({report.get('baselineSegments')} фраз)",
        f"Кандидат: {report.get('challengerModel')} ({report.get('challengerSegments')} фраз)",
        f"Сходство: {float(report.get('similarity') or 0):.1%}",
        f"Отличий: {report.get('changeCount')}",
        f"Лучше справилась: {report.get('winner')} - {report.get('reason')}",
        "",
    ]
    for item in (report.get("changes") or [])[:20]:
        op = item.get("op")
        if op == "replace":
            lines.append(f"~ «{item.get('baseline')}» → «{item.get('challenger')}»")
        elif op == "delete":
            lines.append(f"- «{item.get('baseline')}»")
        elif op == "insert":
            lines.append(f"+ «{item.get('challenger')}»")
    return "\n".join(lines)


def preset_list() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, meta in EXPORT_PRESETS.items():
        row: dict[str, Any] = {"key": key, "label": str(meta["label"])}
        for name in _OPTION_KEYS:
            row[name] = bool(meta.get(name, False))
        rows.append(row)
    return rows


__all__ = [
    "EXPORT_FORMATS",
    "EXPORT_FORMAT_KEYS",
    "EXPORT_PRESETS",
    "LOW_CONFIDENCE",
    "WARN_CONFIDENCE",
    "apply_dictionary",
    "confidence_from_logprob",
    "court_document",
    "diff_transcripts",
    "export_format",
    "export_format_list",
    "export_option_choices",
    "export_rows",
    "export_with_preset",
    "filter_problematic",
    "find_replace",
    "line_document",
    "lrc_document",
    "mark_reviewed",
    "merge_segments",
    "merge_speaker_turns",
    "needs_review",
    "normalise_export_options",
    "preset_defaults",
    "preset_list",
    "protocol_document",
    "quality_stats",
    "resolve_export_options",
    "segment_confidence",
    "serialize_compare_report",
    "set_phrase_window",
    "split_segment",
    "table_document",
]
