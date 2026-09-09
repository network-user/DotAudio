"""CUDA runtime для Whisper / CTranslate2 на Windows.

Whisper в DotAudio идёт через faster-whisper → CTranslate2. Колёса CT2
умеют GPU, но на Windows DLL (cublas, cudnn, cudart) часто не находятся:
Python 3.8+ не ищет их в PATH. Рабочий путь для пользователя без полного
CUDA Toolkit - pip-пакеты NVIDIA и ``os.add_dll_directory`` до первого
обращения к CUDA.

Модуль Qt-free: контроллер только показывает прогресс и статусы.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from dotaudio.hardware import VENDOR_NVIDIA, HardwareProfile, _no_window_kwargs

ProgressCallback = Callable[[dict], None]

# Минимальный набор, с которым CT2/faster-whisper обычно поднимают CUDA 12.
# Объём большой (~1+ ГБ суммарно), поэтому ставим только по явному запросу.
CUDA_RUNTIME_PACKAGES: tuple[str, ...] = (
    "nvidia-cublas-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cuda-nvrtc-cu12",
)

CUDA_HELP_URL = "https://developer.nvidia.com/cuda-downloads"
CUDNN_HELP_URL = "https://developer.nvidia.com/cudnn"

_dll_lock = threading.Lock()
_dll_registered: set[str] = set()

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


def _nvidia_site_packages() -> Path:
    return Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"


def nvidia_dll_directories() -> list[Path]:
    """Каталоги с DLL из pip-пакетов NVIDIA и типичных установок Toolkit."""

    found: list[Path] = []
    root = _nvidia_site_packages()
    if root.is_dir():
        for child in root.iterdir():
            if not child.is_dir():
                continue
            for sub in ("bin", "lib", "lib/x64"):
                path = child / sub
                if path.is_dir():
                    found.append(path)
            # cuDNN 9 иногда кладёт DLL глубже: bin/12.x
            bin_dir = child / "bin"
            if bin_dir.is_dir():
                for nested in bin_dir.iterdir():
                    if nested.is_dir() and any(nested.glob("*.dll")):
                        found.append(nested)

    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        toolkit = program_files / "NVIDIA GPU Computing Toolkit" / "CUDA"
        if toolkit.is_dir():
            for version in toolkit.iterdir():
                bin_dir = version / "bin"
                if bin_dir.is_dir():
                    found.append(bin_dir)
        cudnn_root = program_files / "NVIDIA" / "CUDNN"
        if cudnn_root.is_dir():
            for version in cudnn_root.iterdir():
                bin_dir = version / "bin"
                if not bin_dir.is_dir():
                    continue
                found.append(bin_dir)
                for nested in bin_dir.iterdir():
                    if nested.is_dir() and any(nested.glob("*.dll")):
                        found.append(nested)

        ollama = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "Ollama"
            / "lib"
            / "ollama"
            / "cuda_v12"
        )
        if ollama.is_dir():
            found.append(ollama)

    # Уникальные существующие пути, порядок сохранён.
    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = str(path.resolve()) if path.exists() else ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def register_cuda_dll_directories() -> list[str]:
    """Зарегистрировать каталоги DLL до загрузки CUDA в CTranslate2.

    Повторный вызов безопасен. На не-Windows ничего не делает.
    """

    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return []
    registered: list[str] = []
    with _dll_lock:
        for path in nvidia_dll_directories():
            key = str(path.resolve())
            if key in _dll_registered:
                continue
            try:
                os.add_dll_directory(key)
            except (OSError, FileNotFoundError):
                continue
            # PATH тоже расширяем: часть нативных загрузчиков смотрит туда.
            current = os.environ.get("PATH", "")
            if key.lower() not in current.lower():
                os.environ["PATH"] = key + os.pathsep + current
            _dll_registered.add(key)
            registered.append(key)
    return registered


def packages_present() -> dict[str, bool]:
    """Какие из необходимых pip-пакетов уже лежат в site-packages."""

    root = _nvidia_site_packages()
    mapping = {
        "nvidia-cublas-cu12": root / "cublas",
        "nvidia-cuda-runtime-cu12": root / "cuda_runtime",
        "nvidia-cudnn-cu12": root / "cudnn",
        "nvidia-cuda-nvrtc-cu12": root / "cuda_nvrtc",
    }
    return {name: path.is_dir() for name, path in mapping.items()}


def missing_packages() -> list[str]:
    return [name for name, ready in packages_present().items() if not ready]


def install_command() -> str:
    """Команда для ручной установки, если автопуть не сработал."""

    pkgs = " ".join(CUDA_RUNTIME_PACKAGES)
    return f'"{sys.executable}" -m pip install {pkgs}'


def manual_steps(*, nvidia_present: bool, cuda_ready: bool) -> list[str]:
    """Короткие шаги для карточки «GPU есть, CUDA нет»."""

    if cuda_ready:
        return []
    if not nvidia_present:
        return [
            "Для ускорения Whisper нужна видеокарта NVIDIA с актуальным драйвером.",
            "AMD и Intel в текущем движке (CTranslate2) для Whisper не используются.",
        ]
    return [
        "Установите драйвер NVIDIA (если ещё не стоит).",
        "Нажмите «Настроить GPU» — приложение скачает CUDA-библиотеки через pip.",
        "Если после установки CUDA всё ещё «нет», перезапустите DotAudio.",
        f"Вручную: {install_command()}",
        f"Либо поставьте CUDA Toolkit 12.x: {CUDA_HELP_URL}",
    ]


def compute_advice(profile: HardwareProfile) -> dict:
    """Сводка для UI: что предложить по вычислениям."""

    nvidia = any(gpu.vendor == VENDOR_NVIDIA for gpu in profile.gpus)
    other_dedicated = any(
        (not gpu.integrated) and gpu.vendor != VENDOR_NVIDIA for gpu in profile.gpus
    )
    integrated_only = bool(profile.gpus) and all(gpu.integrated for gpu in profile.gpus)
    cuda_ready = profile.cuda_runtime_devices > 0
    packages = packages_present()
    missing = [name for name, ready in packages.items() if not ready]

    if cuda_ready:
        state = "ready"
        hint = "Видеокарта готова для Whisper. Можно выбрать «Видеокарта» в настройках."
        action = "use_gpu"
    elif nvidia:
        state = "needs_runtime"
        hint = (
            "Карта NVIDIA есть, но CUDA для Whisper недоступна. "
            "Можно скачать runtime автоматически или по инструкции."
        )
        action = "setup_gpu"
    elif other_dedicated:
        state = "other_gpu"
        hint = "Найдена видеокарта без CUDA. Whisper останется на процессоре."
        action = ""
    elif integrated_only:
        igpu = next((gpu for gpu in profile.gpus if gpu.integrated), None)
        name = igpu.name if igpu is not None else "встроенная графика"
        state = "integrated"
        hint = (
            f"{name} не ускоряет Whisper (CTranslate2 умеет только CUDA NVIDIA). "
            "Распознавание идёт на процессоре; для Live лучше профиль «Быстро»."
        )
        action = ""
    else:
        state = "cpu_only"
        hint = "Работаем на процессоре. Для ускорения нужна NVIDIA с CUDA."
        action = ""

    return {
        "cudaReady": cuda_ready,
        "nvidiaPresent": nvidia,
        "cudaPackages": packages,
        "cudaPackagesMissing": missing,
        "computeAdvice": state,
        "computeHint": hint,
        "computeAction": action,
        "manualSteps": manual_steps(nvidia_present=nvidia, cuda_ready=cuda_ready),
        "helpUrl": CUDA_HELP_URL,
        "cudnnHelpUrl": CUDNN_HELP_URL,
        "installCommand": install_command(),
    }


def _emit(on_progress: ProgressCallback | None, **payload: object) -> None:
    if on_progress is None:
        return
    try:
        on_progress(dict(payload))
    except Exception:
        return


def _parse_pip_percent(line: str) -> float | None:
    match = _PERCENT_RE.search(line)
    if not match:
        return None
    value = int(match.group(1))
    if 0 <= value <= 100:
        return float(value)
    return None


def install_cuda_packages(
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Поставить недостающие nvidia-*-cu12 в текущий интерпретатор."""

    needed = missing_packages()
    if not needed:
        _emit(on_progress, phase="runtime", percent=100.0, message="CUDA-библиотеки уже установлены")
        return

    _emit(
        on_progress,
        phase="runtime",
        percent=0.0,
        message=f"Скачиваем CUDA runtime ({len(needed)} пак.)…",
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *needed,
        "--progress-bar",
        "on",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_no_window_kwargs(),
    )
    assert process.stdout is not None
    last_percent = 0.0
    for raw in process.stdout:
        if cancel is not None and cancel.is_set():
            process.terminate()
            raise RuntimeError("Установка CUDA отменена")
        line = raw.strip()
        if not line:
            continue
        parsed = _parse_pip_percent(line)
        if parsed is not None:
            # Pip крутит 0–100 на каждом файле; держим монотонный прогресс
            # в первой половине шкалы настройки.
            last_percent = max(last_percent, min(95.0, parsed * 0.9))
        short = line if len(line) < 120 else line[:117] + "…"
        _emit(
            on_progress,
            phase="runtime",
            percent=last_percent,
            message=short,
        )
    code = process.wait(timeout=30)
    if code != 0:
        raise RuntimeError(
            f"Не удалось установить CUDA runtime (код {code}). "
            f"Попробуйте вручную: {install_command()}"
        )
    _emit(on_progress, phase="runtime", percent=100.0, message="CUDA-библиотеки установлены")


def verify_cuda_devices() -> int:
    """Сколько CUDA-устройств видит CTranslate2 после регистрации DLL."""

    register_cuda_dll_directories()
    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except Exception:
        return 0


def setup_whisper_cuda(
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> dict:
    """Полный цикл: pip runtime → DLL → проверка CUDA.

    Возвращает ``{"ok": bool, "cuda_devices": int, "restart_required": bool,
    "message": str}``.
    """

    _emit(on_progress, phase="check", percent=2.0, message="Проверяем видеокарту…")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Настройка GPU отменена")

    before = verify_cuda_devices()
    if before > 0:
        return {
            "ok": True,
            "cuda_devices": before,
            "restart_required": False,
            "message": f"CUDA уже доступна ({before})",
        }

    install_cuda_packages(on_progress, cancel)
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Настройка GPU отменена")

    _emit(on_progress, phase="register", percent=96.0, message="Подключаем библиотеки CUDA…")
    register_cuda_dll_directories()
    after = verify_cuda_devices()
    if after > 0:
        return {
            "ok": True,
            "cuda_devices": after,
            "restart_required": False,
            "message": f"CUDA готова ({after})",
        }

    return {
        "ok": False,
        "cuda_devices": 0,
        "restart_required": True,
        "message": (
            "Библиотеки установлены, но CTranslate2 пока не видит GPU. "
            "Перезапустите DotAudio и снова выберите «Видеокарта». "
            f"Если не поможет — CUDA Toolkit 12.x: {CUDA_HELP_URL}"
        ),
    }
