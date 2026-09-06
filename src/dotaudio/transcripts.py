"""Export and keyword helpers for transcript segments."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Any


def _normalise(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().replace("ё", "е")


def _segment_values(segment: dict[str, Any]) -> tuple[float, float, str]:
    try:
        start = float(segment["start"])
        end = float(segment["end"])
        text = segment["text"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("segment must contain start, end and text") from error
    if not isinstance(text, str):
        raise ValueError("segment text must be a string")
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("segment timestamps must be finite")
    if start < 0 or end < start:
        raise ValueError("segment timestamps are invalid")
    return start, end, text


def timestamp(seconds: float, separator: str = ",") -> str:
    """Format seconds as an SRT/VTT timestamp, rounding to milliseconds."""
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("timestamp seconds must be a non-negative finite value")
    total_ms = int(math.floor(seconds * 1000 + 0.5))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        f"{separator}{milliseconds:03d}"
    )


def export_transcript(
    segments: Iterable[dict[str, Any]], format: str
) -> str:
    """Export segments as TXT, SRT, VTT or a compact JSON document."""
    source_segments = list(segments)
    prepared = [_segment_values(segment) for segment in source_segments]
    output_format = format.strip().upper()

    if output_format == "TXT":
        return "\n".join(text for _, _, text in prepared)
    if output_format == "JSON":
        return json.dumps(
            [
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    **({"words": segment["words"]} if isinstance(segment.get("words"), list) and segment["words"] else {}),
                }
                for (start, end, text), segment in zip(prepared, source_segments, strict=True)
            ],
            ensure_ascii=False,
            indent=2,
        )

    cues = []
    for index, (start, end, text) in enumerate(prepared, start=1):
        timing = f"{timestamp(start, '.' if output_format == 'VTT' else ',')} --> "
        timing += timestamp(end, '.' if output_format == 'VTT' else ',')
        if output_format == "SRT":
            cues.append(f"{index}\n{timing}\n{text}")
        elif output_format == "VTT":
            cues.append(f"{timing}\n{text}")
        else:
            raise ValueError(f"unsupported transcript format: {format}")

    if output_format == "SRT":
        return "\n\n".join(cues) + ("\n" if cues else "")
    if output_format == "VTT":
        return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")
    raise ValueError(f"unsupported transcript format: {format}")


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return supplied words or phrases found on Unicode word boundaries."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    haystack = _normalise(text)
    matched: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        if not isinstance(keyword, str):
            raise ValueError("keywords must contain only strings")
        normalised = _normalise(keyword).strip()
        if not normalised or normalised in seen:
            continue
        seen.add(normalised)
        pattern = rf"(?<!\w){re.escape(normalised)}(?!\w)"
        if re.search(pattern, haystack):
            matched.append(keyword)
    return matched
