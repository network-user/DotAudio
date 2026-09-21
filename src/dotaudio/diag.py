"""Диагностика транскрибации: журнал на диск и понятные отказы.

Модуль Qt-free. Контроллер пишет сюда шаги распознавания, а кнопка
«Диагностика» собирает проверки без скачивания моделей: есть ли Whisper
в кеше, открывается ли файл, отвечает ли рантайм на короткой тишине.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_MAX_BYTES = 2_000_000
TRACE_LIMIT = 40
DIAGNOSTIC_REPORT_FORMAT = "dotaudio-diagnostic-report"
DIAGNOSTIC_REPORT_VERSION = 1
DIAGNOSTIC_REPORT_MAX_BYTES = 64_000

_REPORT_MAX_STRING = 512
_REPORT_MAX_CHECKS = 64
_REPORT_MAX_ACTIONS = 32
_REPORT_MAX_ENVIRONMENT_FIELDS = 32
_REPORT_MAX_LIST_ITEMS = 16
_REPORT_REDACTED = "[redacted]"
_REPORT_PATH_REDACTED = "[path redacted]"
_REPORT_TRUNCATED = "… [truncated]"

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "cookie",
    "bearer",
    "jwt",
    "refresh_token",
    "client_secret",
    "clientsecret",
    "ssh_key",
    "privatekey",
    "accesskey",
    "refreshtoken",
)
_PATH_KEY_PARTS = (
    "path",
    "file",
    "filepath",
    "filename",
    "directory",
    "dir",
    "root",
    "cache",
    "cwd",
    "home",
    "location",
    "logfile",
    "socket",
)
_REPORT_RESERVED_KEYS = {
    "actions",
    "canfix",
    "checks",
    "diagnostic",
    "environment",
    "extra",
    "fixes",
    "message",
    "phase",
    "report",
    "summary",
}
_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\|/)[^\s,;|]+")
_ABSOLUTE_PATH_WITH_SPACES_RE = re.compile(
    r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\|~[\\/])[^<>\"'`\r\n]*"
)
_SECRET_FILE_RE = re.compile(
    r"(?i)(?<![\w.-])(?:\.env(?:\.[\w.-]+)?|"
    r"(?:secrets?|credentials?|tokens?|passwords?)[\\/][^\s,;|]+|"
    r"[^\s,;|]+\.(?:pem|key|p12|pfx))(?![\w.-])"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?(?:password|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|accesskey|private[_-]?key|privatekey|client[_-]?secret|clientsecret|"
    r"refresh[_-]?token|refreshtoken|authorization|"
    r"cookie|bearer)[\"']?\s*[:=]\s*)"
    r"(?:[\"'][^\"']*[\"']|[^\s,;\]}]+)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|secret|password|api[_-]?key|access[_-]?key)=)[^&#\s]+"
)
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[^\s,;]+")
_TOKEN_PREFIX_RE = re.compile(r"\b(?:sk|ghp|gho|github_pat|hf|xoxb|xoxp)_[A-Za-z0-9_-]{12,}\b")
_PATH_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:path|file|filepath|filename|directory|dir|cache|cwd|home|root|location|"
    r"log(?:[_-]?path)?|data[_-]?dir)\s*[:=]\s*)[^\r\n]+"
)
_REPORT_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"'`]+")


def _empty_setup_error() -> dict:
    """Пустая ошибка в стабильном формате для первого запуска и QML."""

    return {
        "active": False,
        "code": "",
        "title": "",
        "message": "",
        "detail": "",
        "phase": "",
        "stepId": "",
        "severity": "info",
        "advice": [],
        "actions": [],
        "retryable": False,
        "recoverable": False,
    }


def normalise_setup_progress(
    info: dict | None = None,
    *,
    step_id: str = "",
    default_message: str = "",
) -> dict:
    """Привести callback прогресса к bounded-контракту первого запуска.

    Процент считается достоверным только если его сообщил источник или если
    известны обе границы скачивания. Для этапов загрузки/прогрева, где
    библиотека не знает размер работы, возвращается ``determinate=False`` и
    ``percent=None`` — интерфейс обязан показать indeterminate-состояние.
    """

    raw = dict(info or {})
    message = str(raw.get("message") or default_message or "")
    phase = str(raw.get("phase") or step_id or "")

    def number(value, default=None):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if math.isfinite(result) else default

    received = number(raw.get("bytes"), None)
    total = number(raw.get("total"), None)
    if received is not None:
        received = max(0, int(received))
    if total is not None:
        total = max(0, int(total))

    percent = number(raw.get("percent"), None)
    if percent is not None and 0 <= percent <= 100:
        percent = max(0.0, min(100.0, percent))
    else:
        percent = None

    ratio = number(raw.get("ratio"), None)
    if ratio is None and received is not None and total and total > 0:
        ratio = received / total
    if ratio is not None:
        ratio = max(0.0, min(1.0, ratio))
    if percent is None and ratio is not None and total and total > 0:
        percent = ratio * 100.0

    explicit_determinate = raw.get("determinate")
    if explicit_determinate is None:
        determinate = percent is not None and not bool(raw.get("indeterminate"))
    else:
        determinate = bool(explicit_determinate)
    if not determinate:
        percent = None

    eta = number(raw.get("etaSeconds"), None)
    if eta is not None:
        eta = max(0, int(eta))

    result = {
        "stepId": str(raw.get("stepId") or step_id or ""),
        "phase": phase,
        "message": message,
        "determinate": bool(determinate),
        "indeterminate": not bool(determinate),
        "percent": round(percent, 2) if percent is not None else None,
        "bytes": received,
        "totalBytes": total,
        "ratio": round(ratio, 6) if ratio is not None else None,
        "etaSeconds": eta,
    }
    for key in ("component", "source", "status"):
        if raw.get(key) not in (None, ""):
            result[key] = str(raw[key])
    if raw.get("advice"):
        result["advice"] = [str(item) for item in raw["advice"] if str(item).strip()]
    return result


def classify_setup_error(
    error: BaseException | str,
    *,
    phase: str = "",
    step_id: str = "",
    cancelled: bool = False,
) -> dict:
    """Сделать из исключения первого запуска понятную ошибку и совет.

    Поля намеренно плоские и сериализуемые: их можно передать через Qt
    ``QVariantMap``, записать в отчёт и показать без знания конкретного
    backend. ``detail`` сохраняет техническую причину, а ``message`` и
    ``advice`` предназначены для пользователя.
    """

    if isinstance(error, BaseException):
        detail = str(error).strip() or type(error).__name__
        raw = f"{type(error).__name__}: {detail}"
    else:
        detail = str(error or "").strip()
        raw = detail
    low = raw.casefold()
    if "modelpreflighterror" in low or "insufficient" in low or "недостаточно" in low:
        return (
            "Для выбранной модели сейчас не хватает доступной памяти. Выберите модель меньше, "
            "закройте приложения, использующие GPU, или переключитесь на процессор. "
            f"{detail}"
        )
    result = _empty_setup_error()
    result.update(
        {
            "active": True,
            "phase": str(phase or ""),
            "stepId": str(step_id or ""),
            "detail": detail[:1200],
        }
    )

    is_cancelled = cancelled or any(
        token in low for token in ("cancel", "cancelled", "отмен", "останов")
    )
    if is_cancelled:
        result.update(
            {
                "code": "cancelled",
                "title": "Подготовка остановлена",
                "message": "Подготовка остановлена. Скачанные файлы можно использовать при следующем запуске.",
                "severity": "info",
                "advice": ["Нажмите «Повторить», чтобы продолжить с уже скачанного места."],
                "actions": ["retry", "close"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("out of memory", "oom", "std::bad_alloc", "не хват", "memory")):
        result.update(
            {
                "code": "out_of_memory",
                "title": "Не хватило памяти",
                "message": "Модель не поместилась в доступную память видеокарты или процессора.",
                "severity": "error",
                "advice": [
                    "Выберите tiny, base или small.",
                    "Закройте приложения, которые используют видеопамять.",
                    "Если ошибка повторится, выберите «Процессор»." ,
                ],
                "actions": ["smaller_model", "cpu", "retry"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("cuda", "cublas", "cudnn", "cudart", "nvrtc", "nvidia", "видеокарт")):
        result.update(
            {
                "code": "cuda_unavailable",
                "title": "Видеокарта не запустила компонент",
                "message": "CUDA или драйвер не позволили подготовить модель на видеокарте.",
                "severity": "error",
                "advice": [
                    "Повторите подготовку после обновления драйвера NVIDIA.",
                    "Можно продолжить на процессоре с моделью меньшего размера.",
                    "Проверьте подробности в отчёте диагностики.",
                ],
                "actions": ["cpu", "retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("timed out", "timeout", "завис", "не ответил", "hang")):
        result.update(
            {
                "code": "timeout",
                "title": "Этап выполняется слишком долго",
                "message": "Компонент не ответил в ожидаемое время и был остановлен.",
                "severity": "error",
                "advice": [
                    "Повторите этап с моделью меньшего размера.",
                    "Если проблема связана с GPU, выберите «Процессор».",
                    "Сохраните отчёт, если зависание повторяется.",
                ],
                "actions": ["smaller_model", "cpu", "retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("huggingface", "hf_hub", "401", "403", "resolve", "getaddrinfo", "connection", "network", "сеть")):
        result.update(
            {
                "code": "network_unavailable",
                "title": "Не удалось скачать компонент",
                "message": "Для первой загрузки нужен доступ к интернету; незавершённую загрузку можно продолжить позже.",
                "severity": "error",
                "advice": [
                    "Проверьте соединение и доступ к Hugging Face/GitHub.",
                    "Повторите попытку — загрузки поддерживают докачку, если backend её предоставляет.",
                ],
                "actions": ["retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("permission", "access is denied", "доступ", "denied")):
        result.update(
            {
                "code": "permission_denied",
                "title": "Нет доступа к каталогу данных",
                "message": "Приложение не может записать модель или runtime в выбранную папку.",
                "severity": "error",
                "advice": [
                    "Проверьте права на каталог данных DotAudio.",
                    "Освободите папку от блокировки антивирусом и повторите попытку.",
                ],
                "actions": ["retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("no space", "disk full", "enospc", "места на диске")):
        result.update(
            {
                "code": "disk_full",
                "title": "Недостаточно места на диске",
                "message": "Для выбранных компонентов не хватает свободного места.",
                "severity": "error",
                "advice": [
                    "Освободите место и повторите подготовку.",
                    "В брифинге можно отключить необязательные компоненты.",
                ],
                "actions": ["retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("nemo", "sortformer", "diariz", "голос")):
        result.update(
            {
                "code": "diarization_unavailable",
                "title": "Не удалось подготовить определение голосов",
                "message": "Распознавание текста можно использовать без разметки голосов.",
                "severity": "warning",
                "advice": [
                    "Повторите установку NeMo на CPU или освободите VRAM.",
                    "Если проблема останется, отключите определение голосов.",
                ],
                "actions": ["cpu", "retry", "continue_without_diarization"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    if any(token in low for token in ("no module", "modulenotfound", "not found", "не найден", "не установлен")):
        result.update(
            {
                "code": "missing_dependency",
                "title": "Не найден обязательный компонент",
                "message": "Подготовка не смогла найти нужную библиотеку или файл.",
                "severity": "error",
                "advice": [
                    "Запустите подготовку ещё раз, чтобы восстановить компонент.",
                    "Если ошибка повторяется, приложите отчёт диагностики.",
                ],
                "actions": ["retry", "report"],
                "retryable": True,
                "recoverable": True,
            }
        )
        return result

    result.update(
        {
            "code": "setup_failed",
            "title": "Подготовка не завершилась",
            "message": "Компонент не удалось подготовить. Подробность сохранена в отчёте.",
            "severity": "error",
            "advice": [
                "Повторите этот этап.",
                "Если ошибка повторяется, скопируйте отчёт диагностики.",
            ],
            "actions": ["retry", "report"],
            "retryable": True,
            "recoverable": True,
        }
    )
    return result

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


_REPORT_OMIT = object()
_REPORT_ENVIRONMENT_KEYS = {
    "app_version",
    "architecture",
    "backend",
    "compute",
    "compute_type",
    "cuda",
    "cuda_devices",
    "cuda_version",
    "device",
    "gpu",
    "gpu_count",
    "gpu_name",
    "language",
    "model",
    "os",
    "platform",
    "python",
    "ram",
    "task",
    "threads",
    "version",
    "vram",
}


def _report_key(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text[:80] or "field"


def _report_normalised_key(value: object) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _report_is_sensitive_key(value: object) -> bool:
    key = _report_normalised_key(value)
    return bool(key) and any(part in key for part in _SENSITIVE_KEY_PARTS)


def _report_is_path_key(value: object) -> bool:
    key = _report_normalised_key(value)
    if not key:
        return False
    return any(part in key.split("_") or key.endswith(part) for part in _PATH_KEY_PARTS)


def _truncate_report_text(text: str, limit: int = _REPORT_MAX_STRING) -> str:
    if len(text) <= limit:
        return text
    marker = _REPORT_TRUNCATED
    if limit <= len(marker):
        return marker[:limit]
    return text[: limit - len(marker)].rstrip() + marker


def _redact_report_text(text: str) -> str:
    """Удалить из диагностической строки секреты и абсолютные пути."""

    text = _PATH_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{_REPORT_PATH_REDACTED}", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{_REPORT_REDACTED}", text)
    text = _SECRET_QUERY_RE.sub(lambda match: f"{match.group(1)}{_REPORT_REDACTED}", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)}{_REPORT_REDACTED}", text)
    text = _TOKEN_PREFIX_RE.sub(_REPORT_REDACTED, text)
    text = _REPORT_URL_RE.sub("[url redacted]", text)
    text = _ABSOLUTE_PATH_WITH_SPACES_RE.sub(_REPORT_PATH_REDACTED, text)
    text = _ABSOLUTE_PATH_RE.sub(_REPORT_PATH_REDACTED, text)
    return _SECRET_FILE_RE.sub(_REPORT_PATH_REDACTED, text)


def _safe_report_text(value: object, *, key: object = "", limit: int = _REPORT_MAX_STRING) -> str:
    if _report_is_sensitive_key(key):
        return _REPORT_REDACTED
    if isinstance(value, Path) or _report_is_path_key(key):
        return _REPORT_PATH_REDACTED
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return f"<{type(value).__name__}>"
    text = _redact_report_text(text)
    text = " ".join(text.split())
    return _truncate_report_text(text, limit)


def _safe_report_value(value: object, *, key: object = "", depth: int = 0) -> object:
    """Вернуть JSON-совместимое bounded-значение или специальный omit-маркер."""

    if _report_is_sensitive_key(key):
        return _REPORT_OMIT
    if isinstance(value, Path) or _report_is_path_key(key):
        return _REPORT_PATH_REDACTED
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return max(-1_000_000_000_000, min(1_000_000_000_000, value))
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _safe_report_text(value, key=key)
    if depth >= 2:
        return f"<{type(value).__name__} omitted>"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        raw_keys = sorted(value, key=lambda item: str(item).casefold())
        for raw_key in raw_keys[:_REPORT_MAX_LIST_ITEMS]:
            if _report_is_sensitive_key(raw_key):
                continue
            safe_key = _report_key(raw_key)
            safe_value = _safe_report_value(value[raw_key], key=raw_key, depth=depth + 1)
            if safe_value is not _REPORT_OMIT:
                result[safe_key] = safe_value
        if len(raw_keys) > _REPORT_MAX_LIST_ITEMS:
            result["_truncated"] = True
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value[:_REPORT_MAX_LIST_ITEMS]:
            safe_item = _safe_report_value(item, depth=depth + 1)
            if safe_item is not _REPORT_OMIT:
                result.append(safe_item)
        if len(value) > _REPORT_MAX_LIST_ITEMS:
            result.append(_REPORT_TRUNCATED)
        return result
    return f"<{type(value).__name__}>"


def _report_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        value_casefold = value.strip().casefold()
        if value_casefold in {"1", "true", "yes", "ok", "passed", "success"}:
            return True
        if value_casefold in {"0", "false", "no", "fail", "failed", "error"}:
            return False
    return None


def _report_count(value: object, default: int = 0) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(1_000_000, count))


def _report_sequence(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, Mapping):
        return [value[key] for key in sorted(value, key=lambda item: str(item).casefold())]
    return []


def _report_first(sources: list[Mapping[str, Any]], *keys: str) -> object:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _normalise_report_check(value: object, index: int) -> dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    check_id = _safe_report_text(source.get("id") or f"check-{index}", key="id", limit=80)
    raw_ok = _report_bool(source.get("ok"))
    if raw_ok is None:
        raw_ok = _report_bool(source.get("status"))
    ok = bool(raw_ok)
    label = _safe_report_text(source.get("label") or check_id, key="label", limit=160)
    raw_detail = value if not isinstance(value, Mapping) else (
        source.get("detail") or source.get("message") or source.get("error") or ""
    )
    detail = _safe_report_text(
        raw_detail,
        key="detail",
    )
    fix = _safe_report_text(source.get("fix") or source.get("action") or "", key="fix", limit=160)
    advice = []
    raw_advice = source.get("advice") or source.get("recommendations")
    for item in _report_sequence(raw_advice)[:8]:
        text = _safe_report_text(item, key="advice", limit=256)
        if text:
            advice.append(text)
    return {
        "id": check_id,
        "ok": ok,
        "label": label,
        "detail": detail,
        "fix": fix,
        "advice": advice,
    }


def _report_action_text(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("label") or value.get("message") or value.get("action") or value.get("id")
    return _safe_report_text(value, key="action", limit=256)


def _collect_report_actions(
    sources: list[Mapping[str, Any]],
    checks: list[dict[str, object]],
) -> tuple[list[str], bool]:
    values: list[object] = []
    for source in sources:
        for key in (
            "actions",
            "fixes",
            "recommended_actions",
            "recommendedActions",
            "recommendations",
            "advice",
        ):
            values.extend(_report_sequence(source.get(key)))
    for check in checks:
        if check["fix"]:
            values.append(check["fix"])
        values.extend(check["advice"])

    actions: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _report_action_text(value)
        marker = text.casefold()
        if not text or marker in seen:
            continue
        seen.add(marker)
        actions.append(text)
        if len(actions) >= _REPORT_MAX_ACTIONS:
            break
    return actions, len(values) > len(actions)


def _collect_report_environment(
    result: Mapping[str, Any],
    diagnostic: Mapping[str, Any] | None,
) -> tuple[dict[str, object], bool]:
    sources: list[Mapping[str, Any]] = []
    for container in (diagnostic, result):
        if not isinstance(container, Mapping):
            continue
        for key in ("environment", "extra"):
            value = container.get(key)
            if isinstance(value, Mapping):
                sources.append(value)

    top_level_sources = [source for source in (diagnostic, result) if isinstance(source, Mapping)]
    collected: dict[str, object] = {}
    truncated = False
    for source in sources:
        keys = sorted(source, key=lambda item: str(item).casefold())
        for raw_key in keys:
            if len(collected) >= _REPORT_MAX_ENVIRONMENT_FIELDS:
                truncated = True
                break
            if _report_is_sensitive_key(raw_key) or _report_normalised_key(raw_key) in _REPORT_RESERVED_KEYS:
                continue
            safe_key = _report_key(raw_key)
            safe_value = _safe_report_value(source[raw_key], key=raw_key)
            if safe_value is not _REPORT_OMIT and safe_key not in collected:
                collected[safe_key] = safe_value

    for source in top_level_sources:
        for raw_key in sorted(_REPORT_ENVIRONMENT_KEYS):
            if len(collected) >= _REPORT_MAX_ENVIRONMENT_FIELDS:
                truncated = True
                break
            if raw_key not in source or raw_key in collected:
                continue
            safe_value = _safe_report_value(source[raw_key], key=raw_key)
            if safe_value is not _REPORT_OMIT:
                collected[raw_key] = safe_value
    return dict(sorted(collected.items(), key=lambda item: item[0].casefold())), truncated


def _report_contains_truncation(value: object) -> bool:
    if isinstance(value, str):
        return _REPORT_TRUNCATED in value
    if isinstance(value, Mapping):
        return any(_report_contains_truncation(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_report_contains_truncation(item) for item in value)
    return False


def _shrink_report_value(value: object, limit: int = 128) -> object:
    if isinstance(value, str):
        return _truncate_report_text(value, limit)
    if isinstance(value, list):
        return [_shrink_report_value(item, limit) for item in value[:8]]
    if isinstance(value, dict):
        return {key: _shrink_report_value(item, limit) for key, item in list(value.items())[:8]}
    return value


def _shrink_report_payload(payload: dict[str, object]) -> dict[str, object]:
    sections = payload["sections"]
    assert isinstance(sections, dict)
    summary = sections["summary"]
    assert isinstance(summary, dict)
    summary["message"] = _shrink_report_value(summary.get("message", ""), 128)
    environment = sections["environment"]
    assert isinstance(environment, dict)
    sections["environment"] = {
        key: _shrink_report_value(value, 128) for key, value in list(environment.items())[:8]
    }
    checks = sections["checks"]
    assert isinstance(checks, list)
    sections["checks"] = [_shrink_report_value(item, 128) for item in checks[:8]]
    actions = sections["actions"]
    assert isinstance(actions, list)
    sections["actions"] = [_shrink_report_value(item, 128) for item in actions[:8]]
    truncated = payload["truncated"]
    assert isinstance(truncated, dict)
    truncated.update({"environment": True, "checks": True, "actions": True})
    return payload


def _minimal_report_payload(payload: dict[str, object]) -> dict[str, object]:
    sections = payload["sections"]
    assert isinstance(sections, dict)
    summary = sections["summary"]
    assert isinstance(summary, dict)
    return {
        "format": DIAGNOSTIC_REPORT_FORMAT,
        "format_version": DIAGNOSTIC_REPORT_VERSION,
        "sections": {
            "summary": {
                "status": summary.get("status", "unknown"),
                "message": _truncate_report_text(str(summary.get("message") or ""), 128),
                "phase": _truncate_report_text(str(summary.get("phase") or ""), 64),
                "failed": summary.get("failed", 0),
                "total": summary.get("total", 0),
                "can_fix": bool(summary.get("can_fix")),
                "fix_label": _truncate_report_text(str(summary.get("fix_label") or ""), 128),
            },
            "environment": {},
            "checks": [],
            "actions": [],
        },
        "truncated": {"environment": True, "checks": True, "actions": True},
    }


def _render_report_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False) + "\n"


def _render_report_text(payload: dict[str, object]) -> str:
    sections = payload["sections"]
    assert isinstance(sections, dict)
    summary = sections["summary"]
    environment = sections["environment"]
    checks = sections["checks"]
    actions = sections["actions"]
    assert isinstance(summary, dict)
    assert isinstance(environment, dict)
    assert isinstance(checks, list)
    assert isinstance(actions, list)

    lines = [
        "DotAudio diagnostic report",
        f"format: {DIAGNOSTIC_REPORT_FORMAT}",
        f"format_version: {DIAGNOSTIC_REPORT_VERSION}",
        "",
        "[summary]",
        f"status: {summary['status']}",
        f"message: {summary['message']}",
        f"phase: {summary['phase']}",
        f"failed: {summary['failed']}",
        f"total: {summary['total']}",
        f"can_fix: {'yes' if summary['can_fix'] else 'no'}",
        f"fix_label: {summary['fix_label']}",
        "",
        "[environment]",
    ]
    if environment:
        lines.extend(f"{key}: {_report_text_value(value)}" for key, value in environment.items())
    else:
        lines.append("none")
    lines.extend(["", "[checks]"])
    if checks:
        for index, check in enumerate(checks, start=1):
            lines.append(
                f"{index}. {'ok' if check['ok'] else 'failed'} | id={check['id']} | "
                f"label={check['label']} | detail={check['detail']} | fix={check['fix']}"
            )
            for advice in check["advice"]:
                lines.append(f"   advice: {advice}")
    else:
        lines.append("none")
    lines.extend(["", "[actions]"])
    if actions:
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("none")
    truncated = payload["truncated"]
    assert isinstance(truncated, dict)
    lines.extend(
        [
            "",
            "[limits]",
            f"environment_truncated: {'yes' if truncated['environment'] else 'no'}",
            f"checks_truncated: {'yes' if truncated['checks'] else 'no'}",
            f"actions_truncated: {'yes' if truncated['actions'] else 'no'}",
        ]
    )
    return "\n".join(lines) + "\n"


def _report_text_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def export_diagnostic_report(result: Mapping[str, Any] | None, *, format: str = "text") -> str:
    """Экспортировать bounded-отчёт диагностики для копирования или сохранения.

    В отчёт попадают только фиксированные секции ``summary``, ``environment``,
    ``checks`` и ``actions``. Сырые логи, traceback, произвольные поля и старый
    текстовый отчёт намеренно не копируются. ``format`` принимает ``text`` или
    ``json``; оба варианта имеют одну и ту же версию формата и лимиты.
    """

    output_format = str(format or "").casefold()
    if output_format not in {"text", "json"}:
        raise ValueError("format must be 'text' or 'json'")

    root: Mapping[str, Any] = result if isinstance(result, Mapping) else {}
    diagnostic = root.get("diagnostic")
    diagnostic_map = diagnostic if isinstance(diagnostic, Mapping) else None
    summary_map = root.get("summary")
    summary_map = summary_map if isinstance(summary_map, Mapping) else None
    summary_sources = [source for source in (summary_map, diagnostic_map, root) if source is not None]

    raw_checks = _report_first(
        [source for source in (diagnostic_map, root) if source is not None],
        "checks",
    )
    check_items = _report_sequence(raw_checks)
    checks_truncated = len(check_items) > _REPORT_MAX_CHECKS
    checks = [
        _normalise_report_check(item, index)
        for index, item in enumerate(check_items[:_REPORT_MAX_CHECKS], start=1)
    ]
    failed_from_checks = sum(1 for check in checks if not check["ok"])
    explicit_ok = _report_bool(_report_first(summary_sources, "ok"))
    explicit_failed = _report_first(summary_sources, "failed")
    explicit_total = _report_first(summary_sources, "total")
    failed = _report_count(explicit_failed, failed_from_checks)
    total = _report_count(explicit_total, len(check_items))
    if explicit_ok is True:
        status = "ok"
    elif explicit_ok is False or failed:
        status = "failed"
    elif total and not checks_truncated:
        status = "ok"
    else:
        status = "unknown"

    actions, actions_truncated = _collect_report_actions(summary_sources, checks)
    can_fix = _report_bool(_report_first(summary_sources, "canFix", "can_fix"))
    if can_fix is None:
        can_fix = bool(actions)
    summary = {
        "status": status,
        "message": _safe_report_text(
            _report_first(summary_sources, "message", "error", "detail") or "",
            key="message",
        ),
        "phase": _safe_report_text(_report_first(summary_sources, "phase") or "", key="phase", limit=80),
        "failed": failed,
        "total": total,
        "can_fix": can_fix,
        "fix_label": _safe_report_text(
            _report_first(summary_sources, "fixLabel", "fix_label") or "",
            key="fix_label",
            limit=160,
        ),
    }
    environment, environment_truncated = _collect_report_environment(root, diagnostic_map)
    payload: dict[str, object] = {
        "format": DIAGNOSTIC_REPORT_FORMAT,
        "format_version": DIAGNOSTIC_REPORT_VERSION,
        "sections": {
            "summary": summary,
            "environment": environment,
            "checks": checks,
            "actions": actions,
        },
        "truncated": {
            "environment": environment_truncated,
            "checks": checks_truncated,
            "actions": actions_truncated,
        },
    }
    truncated = payload["truncated"]
    assert isinstance(truncated, dict)
    truncated["environment"] = bool(truncated["environment"] or _report_contains_truncation(environment))
    truncated["checks"] = bool(truncated["checks"] or _report_contains_truncation(checks))
    truncated["actions"] = bool(truncated["actions"] or _report_contains_truncation(actions))

    render = _render_report_json if output_format == "json" else _render_report_text
    report = render(payload)
    if len(report.encode("utf-8")) > DIAGNOSTIC_REPORT_MAX_BYTES:
        report = render(_shrink_report_payload(payload))
    if len(report.encode("utf-8")) > DIAGNOSTIC_REPORT_MAX_BYTES:
        report = render(_minimal_report_payload(payload))
    return report


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
    "DIAGNOSTIC_REPORT_FORMAT",
    "DIAGNOSTIC_REPORT_MAX_BYTES",
    "DIAGNOSTIC_REPORT_VERSION",
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
    "export_diagnostic_report",
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
