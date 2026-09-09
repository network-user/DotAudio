"""Портативный FFmpeg рядом с данными приложения.

Сначала берём ``ffmpeg`` из PATH. Если его нет - бинарник в
``data_dir/tools/ffmpeg``. Нужен для караоке-экспорта и HTTP-эфиров.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from threading import Event
from typing import Any, Callable

import httpx
from platformdirs import user_data_path

ProgressCallback = Callable[[dict[str, Any]], None]

# Готовая Windows-сборка BtbN (GPL). Размер плавает; оценка для брифинга.
FFMPEG_RELEASE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
FFMPEG_DOWNLOAD_MB = 95
CHUNK_BYTES = 1024 * 1024
PROGRESS_STEP_BYTES = 2 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60.0


class FfmpegCancelled(RuntimeError):
    """Загрузка FFmpeg остановлена; ``*.part`` остаётся для продолжения."""


def default_data_dir() -> Path:
    return Path(user_data_path("DotAudio", "DotCore"))


def tools_root(data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else default_data_dir()
    return root / "tools" / "ffmpeg"


def local_binary(data_dir: Path | None = None) -> Path:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    return tools_root(data_dir) / name


def resolve_ffmpeg(data_dir: Path | None = None) -> str:
    """Путь к ffmpeg: PATH, затем портативная копия в data_dir."""

    found = shutil.which("ffmpeg")
    if found:
        return found
    portable = local_binary(data_dir)
    if portable.is_file():
        return str(portable)
    return ""


def ffmpeg_available(data_dir: Path | None = None) -> bool:
    return bool(resolve_ffmpeg(data_dir))


def _download_file(
    url: str,
    target: Path,
    *,
    cancel: Event | None = None,
    on_progress: ProgressCallback | None = None,
    progress_start: float = 0.0,
    progress_span: float = 100.0,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Accept-Encoding": "identity"}
    if done:
        headers["Range"] = f"bytes={done}-"
    expected = 0

    def report() -> None:
        if on_progress is None:
            return
        ratio = (done / expected) if expected else 0.0
        on_progress(
            {
                "phase": "download",
                "percent": progress_start + min(progress_span, ratio * progress_span),
                "message": (
                    f"FFmpeg · {done / (1024 * 1024):.0f}"
                    + (f" / {expected / (1024 * 1024):.0f}" if expected else "")
                    + " МБ"
                ),
                "bytes": done,
                "total": expected,
            }
        )

    with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as client:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 416 and part.exists():
                part.replace(target)
                report()
                return
            if done and response.status_code == 200:
                done = 0
                part.unlink(missing_ok=True)
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            if length and length.isdigit():
                expected = done + int(length)
            mode = "ab" if done else "wb"
            next_report = done
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    if cancel is not None and cancel.is_set():
                        handle.flush()
                        raise FfmpegCancelled("загрузка FFmpeg остановлена")
                    handle.write(chunk)
                    done += len(chunk)
                    if done >= next_report:
                        next_report = done + PROGRESS_STEP_BYTES
                        report()
    part.replace(target)
    report()


def _find_ffmpeg_in_tree(root: Path) -> Path | None:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    direct = root / name
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(name))
    return matches[0] if matches else None


def ensure_ffmpeg(
    data_dir: Path | None = None,
    *,
    cancel: Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Вернуть путь к ffmpeg, скачав портативную сборку при необходимости."""

    existing = resolve_ffmpeg(data_dir)
    if existing:
        if on_progress is not None:
            on_progress({"phase": "ready", "percent": 100.0, "message": "FFmpeg уже есть"})
        return existing

    if sys.platform != "win32":
        raise RuntimeError(
            "Портативный FFmpeg в автонастройке пока только для Windows. "
            "Установите ffmpeg в PATH."
        )

    root = tools_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "ffmpeg-win64-gpl.zip"

    def progress(phase: str, percent: float, message: str) -> None:
        if on_progress is not None:
            on_progress({"phase": phase, "percent": percent, "message": message})

    progress("download", 2.0, "Скачиваем FFmpeg…")
    _download_file(
        FFMPEG_RELEASE_URL,
        archive,
        cancel=cancel,
        on_progress=on_progress,
        progress_start=2.0,
        progress_span=75.0,
    )
    if cancel is not None and cancel.is_set():
        raise FfmpegCancelled("загрузка FFmpeg остановлена")

    progress("extract", 80.0, "Распаковываем FFmpeg…")
    extract = Path(tempfile.mkdtemp(prefix="dotaudio-ffmpeg-"))
    try:
        from dotaudio.archiveutil import safe_extract_zip

        safe_extract_zip(archive, extract)
        found = _find_ffmpeg_in_tree(extract)
        if found is None:
            raise RuntimeError("в архиве FFmpeg нет исполняемого файла")
        target = local_binary(data_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, target)
        # Рядом иногда нужны dll из той же bin/.
        for sibling in found.parent.glob("*.dll"):
            shutil.copy2(sibling, target.parent / sibling.name)
    finally:
        shutil.rmtree(extract, ignore_errors=True)

    if not target.is_file():
        raise RuntimeError("не удалось установить портативный FFmpeg")
    progress("ready", 100.0, "FFmpeg готов")
    return str(target)


__all__ = [
    "FFMPEG_DOWNLOAD_MB",
    "FfmpegCancelled",
    "default_data_dir",
    "ensure_ffmpeg",
    "ffmpeg_available",
    "local_binary",
    "resolve_ffmpeg",
    "tools_root",
]
