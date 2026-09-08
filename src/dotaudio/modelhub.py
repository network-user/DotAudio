"""Загрузка файлов моделей на диск: прогресс, докачка, отмена.

Модуль Qt-free и ничего не знает о том, что за модель качает. Whisper
приходит через свой пакет, а всё, что лежит одним файлом - GGUF для чата,
будущие эмбеддинги, голосовые модели - берётся отсюда.

Файл сначала пишется рядом с целевым именем как ``*.part`` и переименовывается
только после полной загрузки. Прерванная закачка продолжается с той же точки,
поэтому четыре гигабайта не начинаются заново из-за обрыва связи.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_ENDPOINT = "https://huggingface.co"
CHUNK_BYTES = 1024 * 1024
# Раз в сколько байт сообщать прогресс. Слишком частые уведомления заставляют
# интерфейс перерисовываться вместо того, чтобы качать.
PROGRESS_STEP_BYTES = 2 * 1024 * 1024


class DownloadCancelled(RuntimeError):
    """Загрузка остановлена по просьбе пользователя."""


@dataclass(frozen=True)
class ModelFile:
    """Один файл модели в репозитории Hugging Face."""

    repo: str
    filename: str
    revision: str = "main"
    size_bytes: int | None = None

    @property
    def url(self) -> str:
        endpoint = os.environ.get("DOTAUDIO_HF_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
        return f"{endpoint}/{self.repo}/resolve/{self.revision}/{self.filename}"


def models_root(data_dir: Path, kind: str = "llm") -> Path:
    """Каталог для моделей заданного вида внутри папки данных приложения."""

    return Path(data_dir) / "models" / kind


def local_path(root: Path, entry: ModelFile) -> Path:
    """Куда ложится файл. Имя репозитория входит в путь, чтобы одинаковые
    имена файлов из разных репозиториев не затирали друг друга."""

    return Path(root) / entry.repo.replace("/", "__") / entry.filename


def partial_path(root: Path, entry: ModelFile) -> Path:
    return local_path(root, entry).with_suffix(local_path(root, entry).suffix + ".part")


def disk_status(root: Path, entry: ModelFile) -> dict:
    """Что из этой модели уже лежит на диске. Без обращения к сети."""

    target = local_path(root, entry)
    part = partial_path(root, entry)
    total = entry.size_bytes
    if target.exists():
        size = target.stat().st_size
        # Файл считается готовым, когда он есть и не меньше заявленного
        # размера. Обрезанный файл честнее показать как незавершённый, чем
        # отдать его модели и получить непонятную ошибку загрузки.
        ready = total is None or size >= total * 0.999
        return {
            "ready": ready,
            "bytes": size,
            "total": total or size,
            "path": str(target),
            "partial": not ready,
        }
    if part.exists():
        size = part.stat().st_size
        return {
            "ready": False,
            "bytes": size,
            "total": total or 0,
            "path": str(target),
            "partial": True,
        }
    return {"ready": False, "bytes": 0, "total": total or 0, "path": str(target), "partial": False}


def download(
    entry: ModelFile,
    root: Path,
    on_progress=None,
    cancel: threading.Event | None = None,
    timeout: float = 30.0,
) -> Path:
    """Скачать файл модели и вернуть путь к нему.

    ``on_progress`` получает словарь с числом байт, общим размером и долей.
    ``cancel`` проверяется между блоками: отмена оставляет ``*.part``, чтобы
    следующая попытка продолжила с того же места.
    """

    target = local_path(root, entry)
    if target.exists():
        status = disk_status(root, entry)
        if status["ready"]:
            return target
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    part = partial_path(root, entry)
    done = part.stat().st_size if part.exists() else 0

    headers = {"Accept-Encoding": "identity"}
    if done:
        headers["Range"] = f"bytes={done}-"

    def report(force: bool = False) -> None:
        if on_progress is None:
            return
        total = expected or entry.size_bytes or 0
        on_progress(
            {
                "bytes": done,
                "total": total,
                "ratio": (done / total) if total else 0.0,
                "file": entry.filename,
                "forced": force,
            }
        )

    expected = entry.size_bytes or 0
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        with client.stream("GET", entry.url, headers=headers) as response:
            if response.status_code == 416:
                # Сервер считает, что запрошенный диапазон уже за концом файла:
                # значит .part дописан полностью и осталось только переименовать.
                part.replace(target)
                report(force=True)
                return target
            if done and response.status_code == 200:
                # Докачка не поддержана - начинаем заново, иначе получится
                # склейка двух начал файла.
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
                        raise DownloadCancelled(entry.filename)
                    handle.write(chunk)
                    done += len(chunk)
                    if done >= next_report:
                        next_report = done + PROGRESS_STEP_BYTES
                        report()
    part.replace(target)
    report(force=True)
    return target


def remove(root: Path, entry: ModelFile) -> bool:
    """Удалить скачанный файл модели. Вызывается только по действию пользователя."""

    removed = False
    for path in (local_path(root, entry), partial_path(root, entry)):
        if path.exists():
            path.unlink()
            removed = True
    parent = local_path(root, entry).parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
    return removed
