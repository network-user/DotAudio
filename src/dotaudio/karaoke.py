"""ASS karaoke export built from Whisper word timestamps.

The module generates a portable subtitle track.  Rendering it to video is
then a normal FFmpeg task, keeping expensive media work out of the Qt thread.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotaudio.tools_ffmpeg import resolve_ffmpeg


def _ass_time(seconds: float) -> str:
    total = max(0, int(round(float(seconds) * 100)))
    hours, remainder = divmod(total, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _words(
    segment: dict[str, Any],
    *,
    uniform_fallback: bool = False,
) -> list[tuple[str, float, float]]:
    """Collect word timings for karaoke \\k tags.

    Default: only real ``words``. Equal-time fake-split of the phrase text is
    opt-in via ``uniform_fallback`` so karaoke export never silently invents
    per-word timing for songs.
    """
    start = float(segment["start"])
    end = max(start, float(segment["end"]))
    raw = segment.get("words")
    result: list[tuple[str, float, float]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            try:
                word_start, word_end = float(item.get("start", start)), float(item.get("end", start))
            except (TypeError, ValueError):
                continue
            if text and math.isfinite(word_start) and math.isfinite(word_end):
                result.append((text, max(start, word_start), min(end, max(word_start, word_end))))
    if result:
        return result
    if not uniform_fallback:
        return []
    tokens = str(segment["text"]).split()
    if not tokens:
        return []
    duration = (end - start) / len(tokens)
    return [
        (token, start + index * duration, start + (index + 1) * duration)
        for index, token in enumerate(tokens)
    ]


def export_ass(
    segments: Iterable[dict[str, Any]],
    *,
    uniform_karaoke: bool = False,
) -> str:
    """Return an ASS file for karaoke or phrase-level dialogue.

    With word timestamps: fill-style \\k per word. Without words: one
    Dialogue line for the whole phrase (no fake word split). Pass
    ``uniform_karaoke=True`` only when the caller explicitly wants equal \\k
    slices from whitespace tokens.
    """

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Karaoke,Segoe UI,58,&H00FFFFFF,&H006A5CFF,&HDD101116,&H88000000,1,0,0,0,100,100,1,0,1,3,0,2,90,90,90,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    for segment in segments:
        words = _words(segment, uniform_fallback=uniform_karaoke)
        if words:
            chunks = []
            for text, start, end in words:
                centiseconds = max(1, int(round((end - start) * 100)))
                chunks.append("{\\k%s}%s" % (centiseconds, _escape(text)))
            lines.append(
                "Dialogue: 0,%s,%s,Karaoke,,0,0,0,,%s\n"
                % (_ass_time(words[0][1]), _ass_time(words[-1][2]), " ".join(chunks))
            )
            continue
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment["start"])
        end = max(start, float(segment["end"]))
        lines.append(
            "Dialogue: 0,%s,%s,Karaoke,,0,0,0,,%s\n"
            % (_ass_time(start), _ass_time(end), _escape(text))
        )
    return "".join(lines)


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov"}


def render_video(
    media_path: str,
    ass_path: str,
    output_path: str,
    cover_path: str | None = None,
) -> None:
    """Render a subtitle video with FFmpeg without involving a shell.

    A video source keeps its picture.  Audio-only input needs a user-selected
    cover that becomes the static background, while the ASS track animates the
    recognised words.
    """

    source = str(media_path)
    is_video = source.lower().endswith(tuple(VIDEO_EXTENSIONS))
    if not is_video and not cover_path:
        raise ValueError("для аудио выберите обложку перед экспортом видео")
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg не найден. Запустите автонастройку или установите FFmpeg в PATH."
        )
    # Путь пользователя не попадает в -vf: только фиксированное имя в temp cwd.
    work = Path(tempfile.mkdtemp(prefix="dotaudio-karaoke-"))
    try:
        safe_ass = work / "subs.ass"
        shutil.copy2(ass_path, safe_ass)
        subtitle_filter = "ass=filename=subs.ass"
        if is_video:
            command = [
                ffmpeg, "-y", "-i", source, "-vf", subtitle_filter,
                "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-c:a", "copy", output_path,
            ]
        else:
            command = [
                ffmpeg, "-y", "-loop", "1", "-i", str(cover_path), "-i", source,
                "-vf", subtitle_filter, "-c:v", "libx264", "-crf", "20",
                "-preset", "medium", "-c:a", "aac", "-shortest", output_path,
            ]
        try:
            subprocess.run(
                command,
                check=True,
                cwd=str(work),
                stdin=subprocess.DEVNULL,
                capture_output=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "FFmpeg не найден. Запустите автонастройку или установите FFmpeg в PATH."
            ) from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode("utf-8", errors="replace").strip().splitlines()
            message = detail[-1] if detail else "FFmpeg завершился с ошибкой"
            raise RuntimeError(message[:500]) from error
    finally:
        shutil.rmtree(work, ignore_errors=True)
