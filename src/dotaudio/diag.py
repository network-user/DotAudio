"""Диагностика транскрибации: журнал на диск и понятные отказы.

Модуль Qt-free. Контроллер пишет сюда шаги распознавания, а кнопка
«Диагностика» собирает проверки без скачивания моделей: есть ли Whisper
в кеше, открывается ли файл, отвечает ли рантайм на короткой тишине.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

LOG_MAX_BYTES = 2_000_000
TRACE_LIMIT = 40

JOB_MODE_LABELS = {
    "live": "Live",
    "dictation": "диктовка",
    "dictation_refine": "уточнение диктовки",
    "media": "медиа",
    "live_process": "обработка Live",
    "watch": "папка наблюдения",
}


class FileLog:
    """Журнал в data_dir: дописывается с любой нити, ротация по размеру."""

    def __init__(self, path: Path, max_bytes: int = LOG_MAX_BYTES) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, tone: str, message: str) -> None:
        line = format_log_line(tone, message)
        with self._lock:
            self._rotate_unlocked()
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _rotate_unlocked(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.max_bytes:
            return
        backup = self.path.with_suffix(self.path.suffix + ".1")
        try:
            backup.unlink(missing_ok=True)
            self.path.replace(backup)
        except OSError:
            return


def format_log_line(tone: str, message: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = " ".join(str(message or "").split())
    return f"{stamp} [{tone}] {text}\n"


def humanize_status(raw: str, labels: dict[str, str] | None = None) -> str:
    """Коды движка вроде loading_model -> человеческая строка."""

    text = str(raw or "").strip()
    if not text:
        return ""
    key = text.casefold()
    table = labels or {}
    if key in table:
        return table[key]
    return text


def explain_transcribe_error(error: BaseException | str) -> str:
    """Короткое объяснение, почему файл не расшифровался."""

    if isinstance(error, BaseException):
        raw = f"{type(error).__name__}: {error}".strip()
        detail = str(error).strip() or type(error).__name__
    else:
        raw = str(error or "").strip()
        detail = raw
    low = raw.casefold()
    if not detail:
        return "Распознавание оборвалось без текста ошибки."
    if any(token in low for token in ("huggingface", "hf_hub", "401", "403", "hub")):
        return (
            "Не удалось скачать модель Whisper. Нужен интернет до Hugging Face. "
            f"{detail}"
        )
    if any(token in low for token in ("failed to resolve", "getaddrinfo", "timed out", "connection")):
        return (
            "Сеть недоступна, а модели нет в кеше. Скачайте её на странице "
            f"«Модели» или кнопкой «Починить». {detail}"
        )
    if any(token in low for token in ("cuda", "cublas", "cudnn", "cudart", "nvrtc")):
        return (
            "Видеокарта не приняла модель. Можно переключить устройство на "
            f"процессор и повторить. {detail}"
        )
    if "compute type" in low or ("float16" in low and "support" in low):
        return (
            "Эта видеокарта не считает Whisper в float16. Программа должна "
            f"сама перейти на int8; если ошибка осталась, выберите процессор. {detail}"
        )
    if any(token in low for token in ("memory", "out of memory", "oom", "std::bad_alloc")):
        return (
            "Не хватило памяти на эту модель. Выберите tiny/base/small. "
            f"{detail}"
        )
    if any(
        token in low
        for token in (
            "av.error",
            "invalid data",
            "no decoder",
            "could not find codec",
            "moov atom",
            "end of file",
        )
    ):
        return (
            "Не удалось прочитать звук файла. Кодек не поддерживается или файл "
            f"повреждён. {detail}"
        )
    if "permission" in low or "access is denied" in low:
        return f"Нет доступа к файлу или каталогу моделей. {detail}"
    if "no such file" in low or "filenotfound" in low:
        return f"Файл не найден. Откройте его снова. {detail}"
    return f"Ошибка распознавания: {detail}"


def busy_job_reason(jobs: dict) -> str:
    """Почему «Расшифровать» молчит, если уже идёт Live или диктовка."""

    if not jobs:
        return ""
    first = next(iter(jobs.values()), {}) or {}
    mode = str(first.get("mode") or "")
    name = str(first.get("name") or "")
    label = JOB_MODE_LABELS.get(mode, name or "другая задача")
    return (
        f"Сейчас идёт {label}. Остановите запись и снова нажмите «Расшифровать»."
    )


def empty_transcript_reason(model: str, disk_ready: bool) -> str:
    if not disk_ready:
        return (
            f"Модель «{model}» не скачана, поэтому фраз нет. Нажмите "
            "«Диагностика», затем «Починить» - нужен интернет на первую загрузку."
        )
    return (
        "Распознавание закончилось, но фраз нет. Часто так бывает, если в файле "
        "нет речи, звуковая дорожка не читается или модель не докачалась. "
        "Откройте «Диагностика»."
    )


def probe_media_duration(path: str | Path) -> float:
    """Длительность из заголовка контейнера, без полной раскодировки звука."""

    media = Path(path)
    if not media.is_file():
        return 0.0
    if media.suffix.lower() == ".wav":
        import wave

        try:
            with wave.open(str(media), "rb") as handle:
                rate = int(handle.getframerate() or 0)
                frames = int(handle.getnframes() or 0)
            if rate > 0 and frames > 0:
                return frames / float(rate)
        except Exception:  # noqa: BLE001
            pass
    try:
        import av

        with av.open(str(media)) as container:
            if container.duration is not None and container.duration > 0:
                return float(container.duration) / 1_000_000.0
            for stream in container.streams:
                if stream.type != "audio":
                    continue
                if stream.duration is None or stream.time_base is None:
                    continue
                seconds = float(stream.duration * stream.time_base)
                if seconds > 0:
                    return seconds
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.0


def format_duration_ru(seconds: float) -> str:
    total = int(round(max(0.0, float(seconds))))
    if total <= 0:
        return ""
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{sec} с"


def transcribe_wait_note(
    elapsed_s: float,
    phrases: int,
    duration_s: float = 0.0,
) -> str:
    """Пока нет фраз: объяснить, что MP3 сначала читается целиком."""

    elapsed = max(0, int(elapsed_s))
    if phrases > 0:
        return f"Идёт распознавание: {phrases} фраз · {elapsed} с"
    length = format_duration_ru(duration_s)
    if length:
        return (
            f"Читаем файл (~{length}) и считаем первый кусок. "
            f"Уже {elapsed} с, фразы появятся после этого шага."
        )
    return (
        f"Модель считает первый кусок звука ({elapsed} с). "
        "Для MP3 файл сначала читается целиком."
    )


def running_transcribe_check(file_name: str = "") -> dict:
    """Карточка анализа, когда Whisper уже занят расшифровкой."""

    name = str(file_name or "").strip()
    detail = (
        "Расшифровка идёт. Это не ошибка: MP3 сначала читается целиком, "
        "первая фраза появляется позже."
    )
    if name:
        detail = f"Сейчас распознаём «{name}». {detail}"
    return _check("running", True, "Распознавание", detail)


def transcript_start_note(
    path: Path,
    *,
    model: str,
    device: str,
    disk_ready: bool,
    download_mb: int | None = None,
    duration_s: float = 0.0,
) -> str:
    try:
        size_mb = path.stat().st_size / 1048576
        size_text = f"{size_mb:.1f} МБ"
    except OSError:
        size_text = "размер неизвестен"
    cache = "в кеше" if disk_ready else "не скачана"
    extra = ""
    if not disk_ready and download_mb:
        extra = f" (~{int(download_mb)} МБ, нужен интернет)"
    length = format_duration_ru(duration_s)
    length_bit = f" · ~{length}" if length else ""
    return (
        f"Файл {path.name} · {size_text}{length_bit} · модель {model} ({cache}{extra}) · "
        f"устройство {device}"
    )


def check_python() -> dict:
    import platform
    import sys

    version = sys.version.split()[0]
    impl = platform.python_implementation()
    return _check("python", True, "Python", f"{impl} {version}")


def check_hardware(hw: dict) -> dict:
    if not hw:
        return _check("hardware", False, "Железо", "Сводка железа ещё не готова")
    parts: list[str] = []
    threads = hw.get("threads")
    if threads is not None:
        parts.append(f"потоков: {threads}")
    ram = hw.get("ram")
    if ram is not None:
        parts.append(f"RAM: {ram}")
    cuda_devices = hw.get("cuda_devices")
    if isinstance(cuda_devices, (list, tuple)):
        if cuda_devices:
            parts.append(f"CUDA: {', '.join(str(item) for item in cuda_devices)}")
    elif cuda_devices not in (None, "", 0):
        parts.append(f"CUDA устройств: {cuda_devices}")
    compute_label = hw.get("compute_label") or hw.get("computeAdvice") or ""
    if compute_label:
        parts.append(str(compute_label))
    detail = "; ".join(parts) if parts else "железо определено"
    return _check("hardware", True, "Железо", detail)


def check_ctranslate2() -> dict:
    try:
        import ctranslate2

        version = str(getattr(ctranslate2, "__version__", "") or "").strip()
        detail = f"CTranslate2 {version}" if version else "CTranslate2 импортируется"
        if hasattr(ctranslate2, "get_cuda_device_count"):
            try:
                count = ctranslate2.get_cuda_device_count()
                detail += f"; CUDA устройств: {count}"
            except Exception:  # noqa: BLE001
                detail += "; CUDA устройств: 0"
        return _check("ctranslate2", True, "CTranslate2", detail)
    except Exception as exc:  # noqa: BLE001
        return _check(
            "ctranslate2",
            False,
            "CTranslate2",
            f"Библиотека CTranslate2 не импортируется: {exc}",
        )


def check_pyav() -> dict:
    try:
        import av

        version = str(getattr(av, "__version__", "") or "").strip()
        detail = f"PyAV {version}" if version else "PyAV импортируется"
        return _check("pyav", True, "Чтение медиа", detail)
    except Exception as exc:  # noqa: BLE001
        return _check(
            "pyav",
            False,
            "Чтение медиа",
            "Библиотека PyAV не открывается: без неё аудио из файла не прочитать. "
            + explain_transcribe_error(exc),
        )


def check_ffmpeg(data_dir: Path | None = None) -> dict:
    from dotaudio.tools_ffmpeg import resolve_ffmpeg

    found = resolve_ffmpeg(data_dir)
    if found:
        return _check("ffmpeg", True, "FFmpeg", found)
    return _check(
        "ffmpeg",
        False,
        "FFmpeg",
        "Отдельный FFmpeg не найден. Часть mp3/mp4 PyAV читает сам; если плеер "
        "молчит, запустите автонастройку.",
        fix="setup",
    )


def check_whisper_disk(
    model: str,
    *,
    catalog: dict | None = None,
    disk: dict | None = None,
) -> dict:
    from dotaudio.engine import Engine

    info = dict(disk) if disk is not None else Engine.disk_status(model)
    ready = bool(info.get("ready"))
    size = int(info.get("bytes") or 0)
    expected = None
    if catalog and model in catalog:
        try:
            expected = int(catalog[model].get("download_mb") or 0) * 1048576
        except (TypeError, ValueError):
            expected = None
    if not ready:
        hint = f"~{expected // 1048576} МБ" if expected else "файл модели"
        return _check(
            "whisper_files",
            False,
            f"Whisper «{model}»",
            f"Модели нет в кеше ({hint}). На чистой установке её нет, пока не "
            "скачаете. Без этого кнопка «Расшифровать» крутится или сразу "
            "заканчивается пустым списком.",
            fix="prepare_model",
        )
    if expected and size < int(expected * 0.4):
        return _check(
            "whisper_files",
            False,
            f"Whisper «{model}»",
            f"В кеше только {size / 1048576:.0f} МБ из ~{expected // 1048576} МБ. "
            "Докачайте модель.",
            fix="prepare_model",
        )
    return _check(
        "whisper_files",
        True,
        f"Whisper «{model}»",
        f"В кеше {size / 1048576:.0f} МБ",
    )


def check_media_file(path: str) -> dict | None:
    if not str(path or "").strip():
        return None
    media = Path(path)
    if not media.is_file():
        return _check(
            "media",
            False,
            "Файл",
            f"Путь не существует: {media.name}. Откройте файл снова.",
        )
    size_mb = media.stat().st_size / 1048576
    try:
        import av

        with av.open(str(media)) as container:
            has_audio = any(stream.type == "audio" for stream in container.streams)
        if not has_audio:
            return _check(
                "media",
                False,
                "Файл",
                f"{media.name}: звуковой дорожки нет.",
            )
        length = format_duration_ru(probe_media_duration(media))
        extra = f" · ~{length}" if length else ""
        return _check(
            "media",
            True,
            "Файл",
            f"{media.name} · есть звук · {size_mb:.1f} МБ{extra}",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            "media",
            False,
            "Файл",
            f"{media.name} не читается. {explain_transcribe_error(exc)}",
        )


def whisper_runtime_check(result: dict, model: str) -> dict:
    """Снимок Engine.probe_runtime -> карточка проверки."""

    ok = bool(result.get("ok"))
    detail = str(result.get("detail") or "")
    device = str(result.get("device") or "")
    code = str(result.get("code") or "")
    if ok:
        return _check(
            "whisper_runtime",
            True,
            "Whisper отвечает",
            detail or f"Модель {model} загрузилась" + (f" на {device}" if device else ""),
        )
    fix = "prepare_model" if code == "missing" else ""
    if code == "error" and any(
        token in detail.casefold()
        for token in ("cuda", "видеокарт", "float16", "compute type", "int8")
    ):
        fix = "cpu"
    return _check(
        "whisper_runtime",
        False,
        "Whisper отвечает",
        detail or "Модель не загрузилась.",
        fix=fix,
    )


def summarize_doctor(checks: list[dict]) -> dict:
    """Итог для кнопки «Починить»: какие действия ещё нужны."""

    visible = [item for item in checks if item]
    failed = [item for item in visible if not item.get("ok")]
    fixes: list[str] = []
    for item in failed:
        action = str(item.get("fix") or "")
        if action and action not in fixes:
            fixes.append(action)
    if not failed:
        message = "Проверки прошли: Whisper на месте и отвечает."
        label = ""
    elif "prepare_model" in fixes:
        message = "Модель Whisper не готова. «Починить» скачает и загрузит её."
        label = "Починить: скачать модель"
    elif "cpu" in fixes:
        message = "Видеокарта не подошла. «Починить» переключит распознавание на процессор."
        label = "Починить: процессор"
    elif "setup" in fixes:
        message = "Не хватает инструментов. «Починить» откроет автонастройку."
        label = "Починить: автонастройка"
    else:
        message = failed[0].get("detail") or "Есть ошибки. Смотрите список ниже."
        label = ""
    return {
        "ok": not failed,
        "message": message,
        "canFix": bool(fixes),
        "fixLabel": label,
        "fixes": fixes,
        "failed": len(failed),
        "total": len(visible),
    }


def format_doctor_report(
    checks: list[dict],
    message: str = "",
    extra: dict | None = None,
) -> str:
    lines = ["Диагностика DotAudio"]
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if extra:
        for key, value in extra.items():
            lines.append(f"{key}: {value}")
    if message:
        lines.append(message)
    lines.append("")
    for item in checks:
        mark = "ok" if item.get("ok") else "fail"
        lines.append(f"[{mark}] {item.get('label')}: {item.get('detail')}")
    return "\n".join(lines)


def _check(key: str, ok: bool, label: str, detail: str, fix: str = "") -> dict:
    return {
        "id": key,
        "ok": bool(ok),
        "label": label,
        "detail": detail,
        "fix": fix,
    }


__all__ = [
    "TRACE_LIMIT",
    "FileLog",
    "busy_job_reason",
    "check_ctranslate2",
    "check_ffmpeg",
    "check_hardware",
    "check_media_file",
    "check_pyav",
    "check_python",
    "check_whisper_disk",
    "empty_transcript_reason",
    "explain_transcribe_error",
    "format_doctor_report",
    "format_duration_ru",
    "format_log_line",
    "humanize_status",
    "probe_media_duration",
    "running_transcribe_check",
    "summarize_doctor",
    "transcribe_wait_note",
    "transcript_start_note",
    "whisper_runtime_check",
]
