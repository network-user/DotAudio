"""Deterministic timing rules for the karaoke editor.

Editing a phrase is a user intention against the audio: a word or phrase
boundary is pushed to a new second.  Whisper word timing is measured per
word, so words may contain short pauses between them.  The rules here
therefore never guess timings or fabricate words: a change is applied only
when it keeps every word on a sane, monotonic timeline inside the phrase,
and the caller is told what was clamped and why.

The module is deliberately Qt-free so the rules can be unit-tested without
a GUI and reused by any future offline realign pass.
"""

from __future__ import annotations

from typing import Any

Segment = dict[str, Any]
Word = dict[str, Any]


EPS = 1e-6


def sanitize_word(word: Any) -> Word | None:
    """Return a copy of a word with finite, ordered timings, else ``None``."""
    if not isinstance(word, dict):
        return None
    try:
        text = str(word.get("text", "")).strip()
        start = float(word["start"])
        end = float(word["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not text:
        return None
    if not _finite(start) or not _finite(end):
        return None
    if start < 0 or end < start:
        return None
    return {"text": text, "start": start, "end": end}


def _finite(value: float) -> bool:
    import math

    return math.isfinite(value)


def sanitize_row(segment: Any) -> Segment | None:
    """Validate a row (ids dropped by callers) to the store's contract."""
    if not isinstance(segment, dict):
        return None
    try:
        text = str(segment.get("text", ""))
        start = float(segment["start"])
        end = float(segment["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _finite(start) or not _finite(end):
        return None
    if start < 0 or end < start:
        return None
    words = []
    for raw in segment.get("words") or []:
        word = sanitize_word(raw)
        if word is not None and start <= word["start"] <= word["end"] <= end:
            words.append(word)
    return {"start": start, "end": end, "text": text, "words": words}


def clamp_row(segment: Segment, *, start: float | None, end: float | None) -> Segment:
    """Clamp the phrase window, never dropping a word outside it.

    The phrase window is meant to hold its words.  ``start`` is clamped to
    ``[0, words[0].start]`` and ``end`` to ``[start, words[-1].end]`` when
    words are present, so an over-eager edit cannot silently remove a word.
    Without words the window only asks for a non-negative, ordered range.
    """
    current_start = float(segment["start"])
    current_end = float(segment["end"])
    words = [dict(w) for w in (segment.get("words") or [])]
    clamped = False
    new_start = current_start if start is None else float(start)
    new_end = current_end if end is None else float(end)
    if not _finite(new_start) or not _finite(new_end):
        return {**segment, "clamped": True}
    if words:
        first = float(words[0]["start"])
        last = float(words[-1]["end"])
        if new_start > first:
            new_start = first
            clamped = True
        if new_end < last:
            new_end = last
            clamped = True
    if new_start < 0:
        new_start = 0.0
        clamped = True
    if new_end < new_start:
        new_end = new_start
        clamped = True
    out = sanitize_row({
        "start": new_start, "end": new_end,
        "text": segment.get("text", ""), "words": words,
    })
    out["clamped"] = clamped
    return out


def word_bounds(segment: Segment, index: int, edge: str) -> tuple[float, float]:
    """Return the [lo, hi] seconds a word edge may take without breaking order."""
    words = segment.get("words") or []
    count = len(words)
    if index < 0 or index >= count:
        raise IndexError("word index out of range")
    row_start = float(segment["start"])
    row_end = float(segment["end"])
    word = words[index]
    if edge == "start":
        lo = words[index - 1]["end"] if index > 0 else row_start
        hi = word["end"]
    elif edge == "end":
        lo = word["start"]
        hi = words[index + 1]["start"] if index + 1 < count else row_end
    else:
        raise ValueError("edge must be 'start' or 'end'")
    if lo < row_start:
        lo = row_start
    if hi > row_end:
        hi = row_end
    if hi <= lo:
        hi = lo
    return lo, hi


def apply_word(segment: Segment, index: int, edge: str, value: float) -> Segment:
    """Clamp a word edge to a legal position and return an edited copy.

    ``value`` is a suggested second; neighbours and the phrase window bound it.
    The result carries ``clamped`` (the request fell outside the allowed range
    and was pulled to the nearest legal second) and ``changed`` (the stored
    value differs from the one already on the row).  ``segment`` is untouched.
    """
    words = [dict(w) for w in (segment.get("words") or [])]
    if index < 0 or index >= len(words):
        raise IndexError("word index out of range")
    word = words[index]
    previous = word["start"] if edge == "start" else word["end"]
    lo, hi = word_bounds(segment, index, edge)
    if not _finite(value):
        value = previous
    requested = value
    value = min(max(value, lo), hi)
    clamped = requested < lo - EPS or requested > hi + EPS
    if edge == "start":
        word["start"] = value
        if word["end"] < value:
            word["end"] = value
    else:
        word["end"] = value
    out = dict(segment)
    out["words"] = words
    result = sanitize_row(out)
    result["clamped"] = clamped
    result["changed"] = value != previous
    return result


def rebuild_text(words: list[Word]) -> str:
    """Join recognised words into a phrase the way exporters expect.

    Each word carries its own leading-space convention from Whisper, but a
    user edit may supply bare words.  Joining stripped tokens with a single
    space keeps a phrase free of accidental double gaps while punctuation that
    sits inside a token survives as it is.
    """
    parts = [str(w.get("text", "")).strip() for w in words]
    return " ".join(part for part in parts if part)


def set_word_text(segment: Segment, index: int, text: str) -> Segment:
    """Change the text of one word and keep the phrase text consistent."""
    words = [dict(w) for w in (segment.get("words") or [])]
    if index < 0 or index >= len(words):
        raise IndexError("word index out of range")
    new_text = str(text).strip()
    if not new_text:
        raise ValueError("word text must not be empty")
    words[index]["text"] = new_text
    out = dict(segment)
    out["text"] = rebuild_text(words)
    out["words"] = words
    return sanitize_row(out)
