"""Export and keyword helpers for transcript segments."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

_SENTENCE_END = re.compile(r"[.!?…](?:[\"'»)]*)$")

# Live cuts speech into phrases of a few seconds so that a caption can be
# decoded quickly; a sentence usually spans several of them.  The pieces are
# joined back for reading by these rules.  A pause longer than this between two
# finals means the speaker finished the thought, whatever the punctuation.
LIVE_SENTENCE_GAP_SECONDS = 2.0
# A sentence longer than this is closed so the live row stays readable.
# Tuned for ~2-3 lines at stage type (fs 30-34 on a ~600-700 px card).
LIVE_SENTENCE_MAX_CHARS = 140
# Soft window for what the live row paints. History keeps the full sentence.
LIVE_CAPTION_VISIBLE_CHARS = 110


def sentence_open(text: str, cut: bool = False) -> bool:
    """Whether a recognised phrase is still waiting for the rest of its sentence.

    The decoder ends nearly every live window with a full stop, so its
    punctuation only counts when the phrase ended because the speaker paused.
    A phrase that ended because it hit the length limit (``cut``) is the middle
    of a sentence by construction.
    """

    clean = str(text).strip()
    if not clean:
        return False
    if cut:
        return True
    return _SENTENCE_END.search(clean) is None


def continues_sentence(
    previous_text: str,
    previous_cut: bool,
    next_text: str,
    gap_seconds: float,
) -> bool:
    """Whether ``next_text`` is the continuation of the open ``previous_text``."""

    previous, following = str(previous_text).strip(), str(next_text).strip()
    if not previous or not following:
        return False
    if gap_seconds > LIVE_SENTENCE_GAP_SECONDS:
        return False
    if len(previous) + len(following) + 1 > LIVE_SENTENCE_MAX_CHARS:
        return False
    if sentence_open(previous, previous_cut):
        return True
    # A phrase that opens in lower case continues the previous one even when
    # the decoder closed that one with a full stop.
    first = following[0]
    return first.isalpha() and first.islower()


def blend_fragments(previous_text: str, previous_cut: bool, next_text: str) -> tuple[str, str]:
    """Adjust the seam between two fragments of one sentence.

    A window cut mid-sentence comes back as "…почти мгновенно." and the next
    one as "Даже на слабом…": the decoder saw each on its own.  Once they are
    known to be one sentence the stop becomes a comma and the capital is
    lowered, so the reader sees "…почти мгновенно, даже на слабом…".  Nothing
    else is rewritten; a question or exclamation mark is left as the decoder
    put it, and a word with more than its first letter in capitals is treated
    as a name or an abbreviation.
    """

    previous, following = str(previous_text).strip(), str(next_text).strip()
    if not previous or not following:
        return previous, following
    if not previous_cut:
        return previous, following
    if previous.endswith(".") and not previous.endswith(".."):
        previous = previous[:-1].rstrip() + ","
        first, rest = following[0], following[1:]
        if first.isupper() and (not rest[:1].isalpha() or rest[:1].islower()):
            following = first.lower() + rest
    return previous, following


def join_fragments(previous_text: str, previous_cut: bool, next_text: str) -> str:
    """The two fragments as one sentence for the transcript."""

    previous, following = blend_fragments(previous_text, previous_cut, next_text)
    return " ".join(part for part in (previous, following) if part)


def window_caption(text: str, max_chars: int = LIVE_CAPTION_VISIBLE_CHARS) -> str:
    """Keep a live caption to its readable tail without cutting a word in half."""

    clean = str(text).strip()
    limit = max(24, int(max_chars))
    if len(clean) <= limit:
        return clean
    tail = clean[-limit:]
    space = tail.find(" ")
    if space >= 0 and space < len(tail) - 12:
        return tail[space + 1 :].lstrip()
    return tail.lstrip()


def split_caption_window(
    confirmed: str,
    pending: str,
    max_chars: int = LIVE_CAPTION_VISIBLE_CHARS,
) -> tuple[str, str]:
    """Apply window_caption while preserving the confirmed/pending seam."""

    head = str(confirmed).strip()
    tail = str(pending).strip()
    full = " ".join(part for part in (head, tail) if part)
    visible = window_caption(full, max_chars)
    if not visible:
        return "", ""
    if not tail:
        return visible, ""
    if not head:
        return "", visible
    if visible == full:
        return head, tail
    if full.endswith(tail) and visible.endswith(tail) and len(visible) > len(tail):
        prefix = visible[: -len(tail)].rstrip()
        return prefix, tail
    if tail.endswith(visible) or visible == tail:
        return "", visible
    return "", visible


def text_after_prefix(text: str, prefix: str) -> str:
    """Хвост после согласованного префикса: точное или пословное совпадение."""

    body = str(text or "").strip()
    head = str(prefix or "").strip()
    if not head:
        return body
    if not body:
        return ""
    if body.startswith(head):
        return body[len(head):].lstrip()
    body_words = body.split()
    head_words = head.split()
    index = 0
    while (
        index < len(head_words)
        and index < len(body_words)
        and body_words[index].casefold() == head_words[index].casefold()
    ):
        index += 1
    return " ".join(body_words[index:])


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


def _word_units(
    segment: dict[str, Any], start: float, end: float
) -> list[dict[str, Any]] | None:
    """Return validated word units, or ``None`` when timings are unusable.

    A subtitle must never receive guessed word timings.  Missing or malformed
    optional word data therefore makes the caller retain the source segment as
    one atomic cue instead of interpolating timings from its text.
    """
    raw_words = segment.get("words")
    if not isinstance(raw_words, list) or not raw_words:
        return None

    result: list[dict[str, Any]] = []
    previous_start = start
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            return None
        text = raw_word.get("text")
        if not isinstance(text, str) or not (text := text.strip()):
            return None
        try:
            word_start = float(raw_word["start"])
            word_end = float(raw_word["end"])
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not math.isfinite(word_start)
            or not math.isfinite(word_end)
            or word_start < start
            or word_end < word_start
            or word_end > end
            or word_start < previous_start
        ):
            return None
        result.append(
            {
                "start": word_start,
                "end": word_end,
                "text": text,
                "word": {"start": word_start, "end": word_end, "text": text},
            }
        )
        previous_start = word_start
    return result


def _cue_values(units: list[dict[str, Any]]) -> tuple[float, float, str]:
    start = float(units[0]["start"])
    end = max(float(unit["end"]) for unit in units)
    text = " ".join(str(unit["text"]) for unit in units)
    return start, end, text


def _ends_sentence(unit: dict[str, Any]) -> bool:
    return bool(_SENTENCE_END.search(str(unit["text"])))


def regroup_for_subtitles(
    segments: Iterable[dict[str, Any]],
    *,
    max_chars: int = 42,
    max_duration: float = 6.0,
) -> list[dict[str, Any]]:
    """Regroup transcript segments into readable, timestamp-safe subtitle cues.

    Word timestamps are used to split long source segments and are copied to
    the resulting cue.  If a source lacks complete, ordered word timings, it
    remains atomic: deriving timings from text would misrepresent the audio.
    Cues prefer a sentence-ending punctuation boundary when a size limit is
    reached.  An individual word or atomic source segment may exceed a limit
    because dropping or inventing text is less safe than preserving it.
    """
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    try:
        duration_limit = float(max_duration)
    except (TypeError, ValueError) as error:
        raise ValueError("max_duration must be a positive finite value") from error
    if not math.isfinite(duration_limit) or duration_limit <= 0:
        raise ValueError("max_duration must be a positive finite value")

    units: list[dict[str, Any]] = []
    for segment in segments:
        start, end, text = _segment_values(segment)
        if not (text := text.strip()):
            continue
        word_units = _word_units(segment, start, end)
        if word_units is not None:
            units.extend(word_units)
        else:
            units.append({"start": start, "end": end, "text": text})

    result: list[dict[str, Any]] = []

    def append_cue(cue_units: list[dict[str, Any]]) -> None:
        start, end, text = _cue_values(cue_units)
        cue: dict[str, Any] = {"start": start, "end": end, "text": text}
        if all("word" in unit for unit in cue_units):
            cue["words"] = [unit["word"] for unit in cue_units]
        result.append(cue)

    current: list[dict[str, Any]] = []
    for unit in units:
        while current:
            start, end, text = _cue_values([*current, unit])
            fits = len(text) <= max_chars and end - start <= duration_limit
            if fits:
                break

            punctuation_index = next(
                (
                    index
                    for index in range(len(current) - 1, -1, -1)
                    if _ends_sentence(current[index])
                ),
                None,
            )
            if punctuation_index is None:
                append_cue(current)
                current = []
            else:
                append_cue(current[: punctuation_index + 1])
                current = current[punctuation_index + 1 :]

        current.append(unit)

    if current:
        append_cue(current)
    return result


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


def _speaker_label(segment: dict[str, Any]) -> str:
    raw = segment.get("speaker")
    if raw is None:
        return ""
    return str(raw).strip()


def _line_text(
    text: str,
    *,
    speaker: str,
    include_speakers: bool,
) -> str:
    body = text.strip()
    if not include_speakers or not speaker:
        return body
    return f"[{speaker}] {body}".strip()


def export_transcript(
    segments: Iterable[dict[str, Any]],
    format: str,
    *,
    include_timestamps: bool | None = None,
    include_speakers: bool = False,
) -> str:
    """Export segments as TXT, MD, SRT, VTT or a compact JSON document.

    ``include_timestamps`` defaults to off for TXT/MD and on for JSON.
    SRT/VTT always keep cue timings (the format requires them); the flag only
    affects whether a line-prefix time is added to plain text and whether
    JSON rows keep ``start``/``end``.
    ``include_speakers`` prefixes ``[speaker]`` when the segment has a label.
    """
    source_segments = list(segments)
    prepared = [_segment_values(segment) for segment in source_segments]
    speakers = [_speaker_label(segment) for segment in source_segments]
    output_format = format.strip().upper()

    if output_format in ("TXT", "MD"):
        with_times = False if include_timestamps is None else bool(include_timestamps)
        if output_format == "TXT":
            lines: list[str] = []
            for (start, _end, text), speaker in zip(prepared, speakers, strict=True):
                body = _line_text(text, speaker=speaker, include_speakers=include_speakers)
                if with_times:
                    stamp = timestamp(start, ".")
                    lines.append(f"[{stamp}] {body}".strip() if body else f"[{stamp}]")
                else:
                    lines.append(body)
            return "\n".join(lines)
        # Markdown: optional speaker headings when labels are requested.
        blocks: list[str] = []
        previous = None
        for (start, _end, text), speaker in zip(prepared, speakers, strict=True):
            body = text.strip()
            if include_speakers and speaker and speaker != previous:
                blocks.append(f"### {speaker}")
                previous = speaker
            if with_times:
                stamp = timestamp(start, ".")
                blocks.append(f"`{stamp}` {body}".strip() if body else f"`{stamp}`")
            else:
                blocks.append(body)
        return "\n\n".join(part for part in blocks if part)

    if output_format == "JSON":
        with_times = True if include_timestamps is None else bool(include_timestamps)
        rows: list[dict[str, Any]] = []
        for (start, end, text), segment, speaker in zip(
            prepared, source_segments, speakers, strict=True
        ):
            row: dict[str, Any] = {
                "text": _line_text(
                    text, speaker=speaker, include_speakers=False
                ),
            }
            if with_times:
                row["start"] = start
                row["end"] = end
            if include_speakers and speaker:
                row["speaker"] = speaker
            words = segment.get("words")
            if isinstance(words, list) and words:
                row["words"] = words
            rows.append(row)
        return json.dumps(rows, ensure_ascii=False, indent=2)

    cues = []
    for index, ((start, end, text), speaker) in enumerate(
        zip(prepared, speakers, strict=True), start=1
    ):
        body = _line_text(text, speaker=speaker, include_speakers=include_speakers)
        timing = f"{timestamp(start, '.' if output_format == 'VTT' else ',')} --> "
        timing += timestamp(end, '.' if output_format == 'VTT' else ',')
        if output_format == "SRT":
            cues.append(f"{index}\n{timing}\n{body}")
        elif output_format == "VTT":
            cues.append(f"{timing}\n{body}")
        else:
            raise ValueError(f"unsupported transcript format: {format}")

    if output_format == "SRT":
        return "\n\n".join(cues) + ("\n" if cues else "")
    if output_format == "VTT":
        return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")
    raise ValueError(f"unsupported transcript format: {format}")


def apply_keyword_cooldown(
    matches: list[str],
    last_fired: dict[str, float],
    now: float,
    cooldown_seconds: float = 20.0,
) -> list[str]:
    """Keep the first hit of a keyword, then ignore repeats until cooldown elapses."""

    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be >= 0")
    fresh: list[str] = []
    for keyword in matches:
        key = _normalise(keyword)
        previous = last_fired.get(key)
        if previous is not None and now - previous < cooldown_seconds:
            continue
        last_fired[key] = now
        fresh.append(keyword)
    return fresh


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
