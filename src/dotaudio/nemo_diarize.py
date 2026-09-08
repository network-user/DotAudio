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

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

import numpy as np

StatusCallback = Callable[[str], None]

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
    "NemoUnavailable",
    "Turn",
    "diarize_audio",
    "ensure_model",
    "executable",
    "install_command",
    "parse_turns",
    "probe",
    "write_wav",
]
