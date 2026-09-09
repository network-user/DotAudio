"""Определение говорящих через нативный рантайм NVIDIA NeMo.

Python-пакет `nemo_toolkit` не поддерживает Windows: в матрице поддержки
NeMo Framework для `windows-amd64` стоит «No support yet», а официальная
инструкция предлагает WSL. Поэтому здесь используется NeMo-Speech.cpp -
собственный нативный рантайм NVIDIA для тех же моделей Nemotron/Sortformer.
Он ставится одним архивом, не тянет torch и работает на CPU.

Модуль вызывает CLI как обычный процесс со списком аргументов, без shell,
и остаётся Qt-free: диаризация не знает про интерфейс, а интерфейс не знает
про NeMo. Аудио не покидает машину - CLI скачивает только веса модели.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

import httpx
import numpy as np

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[dict[str, Any]], None]

CLI_NAME = "nemo-speech"
# Индексный идентификатор модели по умолчанию: потоковый Sortformer на
# четыре голоса. Столько же поддерживает и офлайн-вариант; больше голосов
# эта архитектура не различает, и это ограничение модели, а не обёртки.
DEFAULT_MODEL = "sortformer"
MAX_SPEAKERS = 4

INSTALL_COMMAND_WINDOWS = (
    "irm https://github.com/NVIDIA/NeMo-Speech.cpp/raw/main/scripts/install.ps1 | iex"
)
INSTALL_COMMAND_UNIX = (
    "curl -fsSL https://github.com/NVIDIA/NeMo-Speech.cpp/raw/main/scripts/install.sh | sh"
)

VERSION_URL = "https://raw.githubusercontent.com/NVIDIA/NeMo-Speech.cpp/main/VERSION"
RELEASE_BASE = os.environ.get(
    "NEMO_SPEECH_RELEASE_BASE_URL",
    "https://github.com/NVIDIA/NeMo-Speech.cpp/releases",
).rstrip("/")
# Оценки для брифинга автонастройки (замерено по опубликованным артефактам).
RUNTIME_DOWNLOAD_MB = 101
MODEL_DOWNLOAD_MB = 140
CHUNK_BYTES = 1024 * 1024
PROGRESS_STEP_BYTES = 2 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60.0

# Бюджеты времени. Скачивание весов вынесено в отдельный шаг `pull`, чтобы
# медленная сеть не съедала бюджет самого прохода. Замерено на этом CPU:
# 19 с звука прошли за 10,8 с, то есть RTF около 0,56; множитель 6 оставляет
# запас для машины втрое медленнее, а слагаемое покрывает загрузку модели.
PULL_TIMEOUT_SECONDS = 1800.0
DIARIZE_BASE_SECONDS = 180.0
DIARIZE_PER_SECOND = 6.0
PROBE_TIMEOUT_SECONDS = 60.0
# Шаг опроса процесса. Отмена должна ощущаться мгновенной, но не должна
# крутить процессор вхолостую весь проход.
POLL_SECONDS = 0.1

SAMPLE_RATE = 16000


class NemoUnavailable(RuntimeError):
    """Рантайм NeMo не установлен или собран без диаризации."""


class InstallCancelled(RuntimeError):
    """Установка прервана; частичный zip остаётся в кеше для докачки."""


@dataclass(slots=True, frozen=True)
class Turn:
    """Отрезок речи одного голоса: секунды от начала записи."""

    start: float
    end: float
    speaker: str


def install_command() -> str:
    """Команда установки рантайма для текущей ОС."""

    return INSTALL_COMMAND_WINDOWS if sys.platform == "win32" else INSTALL_COMMAND_UNIX


def _candidate_paths() -> list[Path]:
    """Штатные каталоги установщика NeMo-Speech.cpp.

    Установщик дописывает каталог в пользовательский PATH, но уже
    запущенный процесс получил своё окружение раньше. Без этой проверки
    приложение считало бы рантайм отсутствующим до перезапуска сеанса.
    """

    paths: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            paths.append(Path(local) / "Programs" / "NeMoSpeech" / "bin" / "nemo-speech.exe")
    else:
        paths.append(Path.home() / ".local" / "bin" / CLI_NAME)
        paths.append(Path("/usr/local/bin") / CLI_NAME)
    return paths


def executable() -> str:
    """Путь к `nemo-speech` или пустая строка, если его нет."""

    found = shutil.which(CLI_NAME)
    if found:
        return found
    for path in _candidate_paths():
        if path.is_file():
            return str(path)
    return ""


def _creation_flags() -> int:
    """Не показывать окно консоли поверх интерфейса на Windows."""

    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _run(
    command: list[str],
    timeout: float,
    cancel: Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Запустить CLI списком аргументов и дождаться его, слушая отмену.

    Отмена здесь настоящая, в отличие от кооперативной остановки нативного
    декодера: диаризация живёт в отдельном процессе, и его можно убить.
    """

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    deadline = time.monotonic() + max(1.0, timeout)
    while True:
        try:
            out, err = process.communicate(timeout=POLL_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        else:
            return subprocess.CompletedProcess(command, process.returncode, out, err)
        if cancel is not None and cancel.is_set():
            process.kill()
            process.communicate()
            raise RuntimeError("определение голосов отменено")
        if time.monotonic() > deadline:
            process.kill()
            process.communicate()
            raise RuntimeError(
                f"NeMo не ответил за {int(timeout)} с и был остановлен"
            )


def _fail(result: subprocess.CompletedProcess[str], action: str) -> None:
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    message = detail[-1].strip() if detail else f"код {result.returncode}"
    raise RuntimeError(f"{action}: {message[:400]}")


def probe(cancel: Event | None = None) -> dict[str, Any]:
    """Опросить рантайм: версия, бэкенды, есть ли диаризация.

    Возвращает описание в одном виде и когда рантайма нет, чтобы интерфейс
    показывал причину, а не пустое место.
    """

    path = executable()
    if not path:
        return {
            "available": False,
            "path": "",
            "version": "",
            "device": "",
            "reason": "not_installed",
            "message": "Рантайм NVIDIA NeMo не установлен на этом компьютере.",
        }
    try:
        result = _run([path, "--json", "doctor"], PROBE_TIMEOUT_SECONDS, cancel)
        report = json.loads(result.stdout or "{}")
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "available": False,
            "path": path,
            "version": "",
            "device": "",
            "reason": "broken",
            "message": f"NeMo найден, но не отвечает: {exc}",
        }
    features = report.get("features") or {}
    version = str(report.get("version") or "")
    if not features.get("diarization"):
        return {
            "available": False,
            "path": path,
            "version": version,
            "device": "",
            "reason": "no_diarization",
            "message": "Эта сборка NeMo собрана без диаризации.",
        }
    devices = report.get("devices") or []
    names = [str(item.get("description") or item.get("name") or "") for item in devices]
    accelerated = bool(report.get("accelerator_available"))
    device = next((name for name in names if name), "CPU")
    return {
        "available": True,
        "path": path,
        "version": version,
        "device": device,
        "accelerated": accelerated,
        "reason": "",
        "message": f"NeMo {version} · {'GPU' if accelerated else 'CPU'} · {device}".strip(),
    }


def ensure_model(
    model: str = "",
    cancel: Event | None = None,
    on_status: StatusCallback | None = None,
) -> None:
    """Скачать веса заранее, вне бюджета самого прохода.

    Повторный вызов на уже скачанной модели только сверяет размер и SHA-256,
    поэтому его можно делать перед каждой записью.
    """

    path = executable()
    if not path:
        raise NemoUnavailable("рантайм NeMo не установлен")
    if on_status is not None:
        on_status("Проверяем модель голосов NVIDIA…")
    result = _run([path, "pull", model or DEFAULT_MODEL], PULL_TIMEOUT_SECONDS, cancel)
    if result.returncode != 0:
        _fail(result, "не удалось скачать модель голосов")


def install_prefix() -> Path:
    """Каталог установки NeMo-Speech.cpp на этой ОС."""

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "Programs" / "NeMoSpeech"
    return Path.home() / ".local" / "nemo-speech"


def download_cache_dir() -> Path:
    """Устойчивый кеш zip: не в tempfile, чтобы отмена сохраняла докачку."""

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        root = Path(local) / "DotAudio" / "cache" / "nemo"
    else:
        root = Path.home() / ".cache" / "dotaudio" / "nemo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_release_version(cancel: Event | None = None) -> str:
    """Версия из upstream VERSION; при сбое - пустая строка."""

    if cancel is not None and cancel.is_set():
        raise InstallCancelled("установка NeMo отменена")
    try:
        with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as client:
            response = client.get(VERSION_URL)
            response.raise_for_status()
            match = re.search(
                r"(?m)^NEMO_SPEECH_VERSION:\s*([^\s]+)\s*$",
                response.text or "",
            )
            if match:
                return match.group(1).strip()
    except (httpx.HTTPError, OSError, ValueError):
        return ""
    return ""


def _host_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    raise RuntimeError(f"архитектура {machine} не поддержана установщиком NeMo")


def preferred_backend(*, prefer_cuda: bool = False) -> str:
    """Бэкенд архива: cuda при NVIDIA, иначе cpu. Vulkan не трогаем."""

    if prefer_cuda and sys.platform == "win32":
        return "cuda"
    return "cpu"


def _download_file(
    url: str,
    target: Path,
    *,
    cancel: Event | None = None,
    on_progress: ProgressCallback | None = None,
    progress_start: float = 0.0,
    progress_span: float = 100.0,
) -> None:
    """Скачать URL в файл с процентом внутри заданного окна."""

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Accept-Encoding": "identity"}
    if done:
        headers["Range"] = f"bytes={done}-"
    expected = 0

    def report(force: bool = False) -> None:
        if on_progress is None:
            return
        ratio = (done / expected) if expected else 0.0
        on_progress(
            {
                "phase": "download",
                "percent": progress_start + min(progress_span, ratio * progress_span),
                "message": (
                    f"Скачиваем NeMo · {done / (1024 * 1024):.0f}"
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
                report(force=True)
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
                        raise InstallCancelled("установка NeMo отменена")
                    handle.write(chunk)
                    done += len(chunk)
                    if done >= next_report:
                        next_report = done + PROGRESS_STEP_BYTES
                        report()
    part.replace(target)
    report(force=True)


def _verify_sha256(archive: Path, digest_file: Path) -> None:
    expected = digest_file.read_text(encoding="utf-8", errors="replace").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("контрольная сумма NeMo повреждена")
    hasher = hashlib.sha256()
    with archive.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
    if hasher.hexdigest().lower() != expected:
        raise RuntimeError("SHA-256 архива NeMo не совпал")


def install_runtime(
    *,
    backend: str = "auto",
    prefer_cuda: bool = False,
    prefix: Path | None = None,
    cancel: Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Скачать готовый архив NeMo-Speech.cpp и поставить в prefix.

    Без PowerShell и без сборки из исходников: только опубликованный zip
    с GitHub Releases. На Windows путь совпадает с официальным установщиком.
    """

    def progress(phase: str, percent: float, message: str) -> None:
        if on_progress is not None:
            on_progress({"phase": phase, "percent": percent, "message": message})

    if sys.platform != "win32":
        raise RuntimeError(
            "Автоустановка NeMo сейчас есть только для Windows. "
            f"Вручную: {INSTALL_COMMAND_UNIX}"
        )

    existing = executable()
    if existing:
        report = probe(cancel)
        if report.get("available"):
            progress("ready", 100.0, str(report.get("message") or "NeMo уже установлен"))
            return {"ok": True, "path": existing, "installed": False, "message": report.get("message")}

    progress("resolve", 2.0, "Определяем версию NeMo…")
    version = resolve_release_version(cancel)
    if not version:
        raise RuntimeError("не удалось узнать версию NeMo-Speech.cpp")
    if cancel is not None and cancel.is_set():
        raise InstallCancelled("установка NeMo отменена")

    selected = preferred_backend(prefer_cuda=prefer_cuda) if backend == "auto" else backend
    if selected not in {"cpu", "cuda"}:
        selected = "cpu"
    arch = _host_arch()
    tag = version if version.startswith("v") else f"v{version}"
    release_version = version.lstrip("v")
    archive_name = f"nemo-speech-{release_version}-windows-{arch}-{selected}.zip"
    url = f"{RELEASE_BASE}/download/{tag}/{archive_name}"

    target_root = Path(prefix) if prefix is not None else install_prefix()
    cache = download_cache_dir()
    archive_path = cache / archive_name
    digest_path = cache / f"{archive_name}.sha256"
    work = Path(tempfile.mkdtemp(prefix="dotaudio-nemo-setup-"))
    try:
        progress("download", 5.0, f"Скачиваем {archive_name}…")
        try:
            _download_file(
                url,
                archive_path,
                cancel=cancel,
                on_progress=on_progress,
                progress_start=5.0,
                progress_span=55.0,
            )
        except InstallCancelled:
            raise
        except Exception:
            if selected == "cuda":
                # Нет CUDA-сборки - берём CPU, диаризация всё равно работает.
                selected = "cpu"
                archive_name = f"nemo-speech-{release_version}-windows-{arch}-{selected}.zip"
                url = f"{RELEASE_BASE}/download/{tag}/{archive_name}"
                archive_path = cache / archive_name
                digest_path = cache / f"{archive_name}.sha256"
                _download_file(
                    url,
                    archive_path,
                    cancel=cancel,
                    on_progress=on_progress,
                    progress_start=5.0,
                    progress_span=55.0,
                )
            else:
                raise

        if cancel is not None and cancel.is_set():
            raise InstallCancelled("установка NeMo отменена")

        progress("checksum", 62.0, "Проверяем контрольную сумму…")
        _download_file(
            f"{url}.sha256",
            digest_path,
            cancel=cancel,
            on_progress=None,
        )
        _verify_sha256(archive_path, digest_path)

        progress("extract", 70.0, "Распаковываем рантайм…")
        extract = work / "extract"
        extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract)
        entries = list(extract.iterdir())
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else extract
        staged = root / "bin" / "nemo-speech.exe"
        if not staged.is_file():
            raise RuntimeError("в архиве нет bin\\nemo-speech.exe")

        progress("activate", 88.0, "Подключаем установку…")
        identity = f"{release_version} windows {arch} {selected}"
        (root / ".nemo-speech-install").write_text(identity, encoding="utf-8")
        target_root.parent.mkdir(parents=True, exist_ok=True)
        next_dir = Path(str(target_root) + ".new")
        old_dir = Path(str(target_root) + ".old")
        shutil.rmtree(next_dir, ignore_errors=True)
        shutil.rmtree(old_dir, ignore_errors=True)
        shutil.move(str(root), str(next_dir))
        if target_root.exists():
            shutil.move(str(target_root), str(old_dir))
        try:
            shutil.move(str(next_dir), str(target_root))
        except OSError:
            if old_dir.exists():
                shutil.move(str(old_dir), str(target_root))
            raise
        shutil.rmtree(old_dir, ignore_errors=True)

        path = str(target_root / "bin" / "nemo-speech.exe")
        if not Path(path).is_file():
            raise RuntimeError("после установки не найден nemo-speech.exe")
        # Zip больше не нужен: место на диске важнее повторной распаковки.
        archive_path.unlink(missing_ok=True)
        digest_path.unlink(missing_ok=True)
        progress("ready", 100.0, f"NeMo {release_version} · {selected}")
        return {
            "ok": True,
            "path": path,
            "installed": True,
            "backend": selected,
            "version": release_version,
            "message": f"NeMo {release_version} установлен ({selected})",
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_wav(audio: np.ndarray, target: str | Path, sample_rate: int = SAMPLE_RATE) -> None:
    """Сохранить моно float32 как PCM16 WAV: этот формат CLI читает сам."""

    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(sample_rate))
        out.writeframes(pcm.tobytes())


def parse_turns(payload: str) -> list[Turn]:
    """Разобрать `--format json` в отрезки речи.

    Формат CLI: {"file": ..., "segments": [{"start", "end", "speaker"}]}.
    Номер говорящего в выводе начинается с единицы; здесь он остаётся
    строковой меткой, а сквозную нумерацию ролей делает speaker_id.
    """

    try:
        document = json.loads(payload or "{}")
    except ValueError as exc:
        raise RuntimeError("NeMo вернул неразборчивый ответ") from exc
    rows = document.get("segments") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise RuntimeError("в ответе NeMo нет списка сегментов")
    turns: list[Turn] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            start = float(row.get("start", 0.0))
            end = float(row.get("end", start))
        except (TypeError, ValueError):
            continue
        speaker = str(row.get("speaker", "")).strip()
        if not speaker or end <= start:
            continue
        turns.append(Turn(start=max(0.0, start), end=end, speaker=speaker))
    turns.sort(key=lambda turn: (turn.start, turn.end))
    return turns


def diarize_audio(
    audio: np.ndarray,
    model: str = "",
    device: str = "",
    cancel: Event | None = None,
    on_status: StatusCallback | None = None,
) -> list[Turn]:
    """Разметить моно 16 кГц по голосам и вернуть отрезки речи.

    Звук передаётся временным WAV рядом с системным temp и удаляется
    сразу после прохода. Пустое значение ``device`` и "auto" оставляют
    выбор рантайму: он сам берёт ускоритель, если сборка его умеет.
    """

    path = executable()
    if not path:
        raise NemoUnavailable("рантайм NeMo не установлен")
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    seconds = data.size / float(SAMPLE_RATE)
    if seconds <= 0:
        return []

    ensure_model(model, cancel, on_status)
    if on_status is not None:
        on_status("Определяем говорящих моделью NVIDIA Sortformer…")

    workdir = Path(tempfile.mkdtemp(prefix="dotaudio-nemo-"))
    source = workdir / "input.wav"
    target = workdir / "turns.json"
    try:
        write_wav(data, source)
        command = [
            path, "diarize", str(source),
            "--format", "json",
            "--output", str(target),
            "--force",
        ]
        if model:
            command += ["--model", model]
        if device and device != "auto":
            command += ["--device", device]
        budget = DIARIZE_BASE_SECONDS + DIARIZE_PER_SECOND * seconds
        result = _run(command, budget, cancel)
        if result.returncode != 0:
            _fail(result, "определение голосов не удалось")
        if not target.is_file():
            raise RuntimeError("NeMo не создал файл с разметкой голосов")
        return parse_turns(target.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


__all__ = [
    "MAX_SPEAKERS",
    "MODEL_DOWNLOAD_MB",
    "NemoUnavailable",
    "InstallCancelled",
    "RUNTIME_DOWNLOAD_MB",
    "Turn",
    "diarize_audio",
    "download_cache_dir",
    "ensure_model",
    "executable",
    "install_command",
    "install_prefix",
    "install_runtime",
    "parse_turns",
    "preferred_backend",
    "probe",
    "resolve_release_version",
    "write_wav",
]
