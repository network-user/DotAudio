"""Портативный FFmpeg рядом с данными приложения.

Сначала берём ``ffmpeg`` из PATH. Если его нет - бинарник в
``data_dir/tools/ffmpeg``. Нужен для караоке-экспорта и HTTP-эфиров.

Автоскачивание:
- Windows: BtbN win64-gpl.zip
- Linux x86_64 / aarch64: BtbN linux*-gpl.tar.xz
- macOS: ``brew install ffmpeg`` при наличии Homebrew; иначе evermeet (Intel)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Event
from typing import Any, Callable

import httpx
from platformdirs import user_data_path

ProgressCallback = Callable[[dict[str, Any]], None]

CHUNK_BYTES = 1024 * 1024
PROGRESS_STEP_BYTES = 2 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60.0

# Оценки для брифинга мастера; фактический размер плавает.
FFMPEG_DOWNLOAD_MB = 95

_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
_EVERMEET = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"


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
    if portable.is_file() and os.access(portable, os.X_OK if sys.platform != "win32" else os.F_OK):
        return str(portable)
    if portable.is_file():
        return str(portable)
    return ""


def ffmpeg_available(data_dir: Path | None = None) -> bool:
    return bool(resolve_ffmpeg(data_dir))


def _machine_tag() -> str:
    machine = platform.machine().casefold()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine


def ffmpeg_release_spec() -> dict[str, str] | None:
    """URL и имя архива для текущей платформы, либо None если автоскачивание недоступно."""

    if sys.platform == "win32":
        return {
            "url": f"{_BTBN}/ffmpeg-master-latest-win64-gpl.zip",
            "archive": "ffmpeg-win64-gpl.zip",
            "kind": "zip",
            "hint": "",
        }
    if sys.platform.startswith("linux"):
        tag = _machine_tag()
        if tag == "x86_64":
            name = "ffmpeg-master-latest-linux64-gpl.tar.xz"
        elif tag == "arm64":
            name = "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
        else:
            return None
        return {
            "url": f"{_BTBN}/{name}",
            "archive": name,
            "kind": "tar",
            "hint": "",
        }
    if sys.platform == "darwin":
        # Homebrew - основной путь на macOS; evermeet только Intel.
        if _machine_tag() == "x86_64":
            return {
                "url": _EVERMEET,
                "archive": "ffmpeg-evermeet.zip",
                "kind": "zip",
                "hint": "brew install ffmpeg",
            }
        return {
            "url": "",
            "archive": "",
            "kind": "brew",
            "hint": "brew install ffmpeg",
        }
    return None


# Совместимость со старыми импортами/тестами.
FFMPEG_RELEASE_URL = (
    f"{_BTBN}/ffmpeg-master-latest-win64-gpl.zip"
    if sys.platform == "win32"
    else (ffmpeg_release_spec() or {}).get("url", "")
)


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


def _try_brew_install(
    *,
    cancel: Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> str:
    brew = shutil.which("brew")
    if not brew:
        return ""
    if on_progress is not None:
        on_progress({"phase": "install", "percent": 20.0, "message": "Устанавливаем FFmpeg через Homebrew…"})
    if cancel is not None and cancel.is_set():
        raise FfmpegCancelled("загрузка FFmpeg остановлена")
    try:
        proc = subprocess.run(
            [brew, "install", "ffmpeg"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Homebrew не смог установить FFmpeg: {exc}") from exc
    found = shutil.which("ffmpeg")
    if found:
        if on_progress is not None:
            on_progress({"phase": "ready", "percent": 100.0, "message": "FFmpeg готов (Homebrew)"})
        return found
    detail = (proc.stderr or proc.stdout or "").strip()[:400]
    raise RuntimeError(
        "Homebrew не установил ffmpeg в PATH. "
        + (detail or "Выполните вручную: brew install ffmpeg")
    )


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

    spec = ffmpeg_release_spec()
    if spec is None:
        raise RuntimeError(
            "Автоустановка FFmpeg для этой платформы не настроена. "
            "Установите ffmpeg в PATH (apt/brew/pacman)."
        )

    def progress(phase: str, percent: float, message: str) -> None:
        if on_progress is not None:
            on_progress({"phase": phase, "percent": percent, "message": message})

    if spec["kind"] == "brew" or (sys.platform == "darwin" and shutil.which("brew")):
        # На macOS сначала Homebrew - надёжнее статических сборок.
        try:
            brewed = _try_brew_install(cancel=cancel, on_progress=on_progress)
            if brewed:
                return brewed
        except FfmpegCancelled:
            raise
        except RuntimeError:
            if spec["kind"] == "brew" or not spec.get("url"):
                raise

    if not spec.get("url"):
        raise RuntimeError(
            "Портативный FFmpeg на Apple Silicon ставится через Homebrew: "
            "brew install ffmpeg"
        )

    root = tools_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / spec["archive"]

    progress("download", 2.0, "Скачиваем FFmpeg…")
    _download_file(
        spec["url"],
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
    target = local_binary(data_dir)
    try:
        if spec["kind"] == "tar":
            from dotaudio.archiveutil import safe_extract_tar

            safe_extract_tar(archive, extract)
        else:
            from dotaudio.archiveutil import safe_extract_zip

            safe_extract_zip(archive, extract)
        found = _find_ffmpeg_in_tree(extract)
        if found is None:
            raise RuntimeError("в архиве FFmpeg нет исполняемого файла")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, target)
        if sys.platform != "win32":
            target.chmod(target.stat().st_mode | 0o111)
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
    "FFMPEG_RELEASE_URL",
    "FfmpegCancelled",
    "default_data_dir",
    "ensure_ffmpeg",
    "ffmpeg_available",
    "ffmpeg_release_spec",
    "local_binary",
    "resolve_ffmpeg",
    "tools_root",
]
