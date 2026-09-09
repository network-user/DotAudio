"""Professional transcript helpers: edit, quality, export presets, model diff.

Qt-free so rules stay unit-testable. Controllers call these; QML never imports
them directly.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

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
) -> str:
    """Formal transcript for court / hearing protocol use."""

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
            head_parts.append(_fmt_range(start, end))
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
) -> str:
    """Speaker-labelled protocol; optional timestamps and confidence notes."""

    blocks: list[str] = []
    previous = None
    for row in segments:
        speaker = str(row.get("speaker") or "").strip() or "Голос"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        notes: list[str] = []
        if include_timestamps:
            notes.append(_fmt_range(float(row.get("start", 0.0)), float(row.get("end", 0.0))))
        conf = segment_confidence(row)
        if include_review_flags and needs_review(row) and not row.get("reviewed"):
            notes.append("на проверку")
        elif include_confidence and conf >= 0:
            notes.append(f"{conf:.0%}")
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
) -> str:
    """Readable TXT/MD dump driven by the same save toggles as the preview."""

    kind = str(fmt or "txt").strip().lower()
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
            head_parts.append(_fmt_range(start, end))
        head = " ".join(head_parts)
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

    Returns ``(text, format_ext)``. Empty text means no phrases matched.
    """

    from dotaudio.transcripts import export_transcript, regroup_for_subtitles

    opts = dict(options or {})
    fmt = str(opts.get("format") or "txt").strip().lower()
    if fmt not in ("txt", "md", "srt", "vtt", "json"):
        raise ValueError(f"unsupported transcript format: {fmt}")
    rows = filter_export_rows(
        list(segments or []),
        speaker_key=int(opts.get("speaker_key") or 0),
        only_flagged=bool(opts.get("only_flagged")),
    )
    if not rows:
        return "", fmt

    with_times = bool(opts.get("include_timestamps"))
    with_speakers = bool(opts.get("include_speakers"))
    with_conf = bool(opts.get("include_confidence"))
    with_flags = bool(opts.get("include_review_flags"))
    with_header = bool(opts.get("include_header"))
    with_numbers = bool(opts.get("include_phrase_numbers"))
    if fmt in ("srt", "vtt"):
        with_times = True

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
            ),
            fmt,
        )

    if fmt in ("srt", "vtt"):
        cues = regroup_for_subtitles(rows)
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
            ),
            fmt,
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
        ),
        fmt,
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


def _fmt_range(start: float, end: float) -> str:
    return f"{_fmt_ts(start)} - {_fmt_ts(end)}"


def _fmt_ts(seconds: float) -> str:
    total_ms = int(math.floor(max(0.0, float(seconds)) * 1000 + 0.5))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"
    return f"{minutes:02d}:{secs:02d}.{ms:03d}"


def preset_list() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, meta in EXPORT_PRESETS.items():
        row: dict[str, Any] = {"key": key, "label": str(meta["label"])}
        for name in _OPTION_KEYS:
            row[name] = bool(meta.get(name, False))
        rows.append(row)
    return rows


__all__ = [
    "EXPORT_PRESETS",
    "LOW_CONFIDENCE",
    "WARN_CONFIDENCE",
    "apply_dictionary",
    "confidence_from_logprob",
    "court_document",
    "diff_transcripts",
    "export_with_preset",
    "filter_problematic",
    "find_replace",
    "mark_reviewed",
    "merge_segments",
    "needs_review",
    "preset_defaults",
    "preset_list",
    "protocol_document",
    "quality_stats",
    "resolve_export_options",
    "segment_confidence",
    "serialize_compare_report",
    "set_phrase_window",
    "split_segment",
]
