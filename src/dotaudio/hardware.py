"""Опрос устройства и выбор ускорителя для локальных моделей.

Модуль Qt-free и не тянет тяжёлых зависимостей: им пользуются и страница
моделей Whisper, и локальный ассистент, и всё, что появится позже. Здесь
только измеренные факты об этой машине - число потоков, объём ОЗУ, список
видеокарт с их памятью - и правила подбора сборки llama.cpp под них.

Видеокарты перечисляются по вендору, а не «есть ли CUDA»: одна и та же
логика должна отвечать и про NVIDIA, и про Radeon, и про встроенную Intel,
потому что дальше в проект будут добавляться другие модели и рантаймы.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import Any, Literal

VENDOR_NVIDIA = "nvidia"
VENDOR_AMD = "amd"
VENDOR_INTEL = "intel"
VENDOR_APPLE = "apple"
VENDOR_UNKNOWN = "unknown"

VENDOR_LABELS = {
    VENDOR_NVIDIA: "NVIDIA",
    VENDOR_AMD: "AMD",
    VENDOR_INTEL: "Intel",
    VENDOR_APPLE: "Apple",
    VENDOR_UNKNOWN: "Видеокарта",
}

# Названия адаптеров, по которым определяется вендор. Проверяется по порядку:
# у Intel Arc в имени бывает и «Intel», и «Arc», а у виртуальных адаптеров -
# ни того ни другого, и они честно остаются неизвестными.
_VENDOR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (VENDOR_NVIDIA, ("nvidia", "geforce", "rtx ", "gtx ", "quadro", "tesla", "titan")),
    (VENDOR_AMD, ("amd", "radeon", "vega", "firepro", "ryzen graphics")),
    (VENDOR_INTEL, ("intel", "arc ", "iris", "uhd graphics", "hd graphics")),
    (VENDOR_APPLE, ("apple",)),
)

# Встроенное видео делит память с системой, поэтому «свободная VRAM» у него
# ничего не значит для выгрузки слоёв модели.
_INTEGRATED_MARKERS = ("uhd graphics", "hd graphics", "iris", "vega 8", "vega 7", "radeon graphics")

# Свежие результаты опроса живут недолго: карта могла занять память под
# другую задачу, а страница моделей показывает именно текущее состояние.
PROBE_TTL_SECONDS = 20.0

_probe_lock = threading.Lock()
_cached: tuple[float, "HardwareProfile"] | None = None


def _no_window_kwargs() -> dict:
    """Не показывать консольное окно, когда GUI спрашивает nvidia-smi."""

    if sys.platform != "win32":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _run(args: list[str], timeout: float = 6.0) -> str:
    try:
        finished = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return finished.stdout or ""


def vendor_of(name: str) -> str:
    """Вендор по названию адаптера."""

    low = (name or "").casefold()
    for vendor, markers in _VENDOR_MARKERS:
        if any(marker in low for marker in markers):
            return vendor
    return VENDOR_UNKNOWN


def _looks_integrated(name: str, vram_mb: int | None) -> bool:
    low = (name or "").casefold()
    if any(marker in low for marker in _INTEGRATED_MARKERS):
        return True
    # Дискретная карта с меньше чем 1,5 ГБ своей памяти встречается только
    # среди очень старых моделей; для выгрузки слоёв она всё равно бесполезна.
    return vram_mb is not None and vram_mb < 1536


@dataclass(frozen=True)
class GpuDevice:
    """Одна видеокарта такой, какой её видно с этой машины."""

    index: int
    name: str
    vendor: str = VENDOR_UNKNOWN
    vram_mb: int | None = None
    vram_free_mb: int | None = None
    driver: str = ""
    compute: str = ""
    integrated: bool = False
    source: str = ""

    @property
    def vendor_label(self) -> str:
        return VENDOR_LABELS.get(self.vendor, VENDOR_LABELS[VENDOR_UNKNOWN])

    @property
    def vram_gb(self) -> float | None:
        if self.vram_mb is None:
            return None
        return round(self.vram_mb / 1024, 1)

    @property
    def vram_free_gb(self) -> float | None:
        if self.vram_free_mb is None:
            return None
        return round(max(0, self.vram_free_mb) / 1024, 1)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "vendor": self.vendor,
            "vendorLabel": self.vendor_label,
            "vramMb": self.vram_mb,
            "vramGb": self.vram_gb,
            "vramFreeMb": self.vram_free_mb,
            "vramFreeGb": self.vram_free_gb,
            "driver": self.driver,
            "compute": self.compute,
            "integrated": self.integrated,
            "source": self.source,
        }


@dataclass(frozen=True)
class HardwareProfile:
    """Сводка машины: потоки, память, видеокарты, доступность рантаймов."""

    threads: int = 0
    ram_gb: float | None = None
    ram_available_gb: float | None = None
    gpus: tuple[GpuDevice, ...] = ()
    platform: str = ""
    # Сколько CUDA-устройств видит именно CTranslate2 (движок Whisper). Это
    # не то же самое, что «карта есть»: без нужных runtime-библиотек он
    # вернёт ноль и уйдёт на CPU.
    cuda_runtime_devices: int = 0
    # Умеет ли установленная сборка llama.cpp выгружать слои на видеокарту.
    # Факт от самой библиотеки, а не вывод из наличия карты.
    llama_gpu_offload: bool | None = None
    notes: tuple[str, ...] = field(default=())

    @property
    def best_gpu(self) -> GpuDevice | None:
        """Карта с наибольшей собственной памятью; встроенная - в последнюю очередь."""

        usable = [gpu for gpu in self.gpus if not gpu.integrated]
        pool = usable or list(self.gpus)
        if not pool:
            return None
        return max(pool, key=lambda gpu: (gpu.vram_mb or 0, -gpu.index))

    @property
    def vram_mb(self) -> int | None:
        gpu = self.best_gpu
        return None if gpu is None else gpu.vram_mb

    @property
    def cuda_gpu(self) -> GpuDevice | None:
        """NVIDIA adapter with the largest currently usable VRAM budget."""

        candidates = [
            gpu
            for gpu in self.gpus
            if gpu.vendor == VENDOR_NVIDIA and not gpu.integrated
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda gpu: (
                gpu.vram_free_mb if gpu.vram_free_mb is not None else -1,
                gpu.vram_mb or 0,
                -gpu.index,
            ),
        )

    @property
    def has_dedicated_gpu(self) -> bool:
        return any(not gpu.integrated for gpu in self.gpus)

    def as_dict(self) -> dict:
        """Плоский вид для QML и журналов.

        Ключи ``threads``/``ram_gb``/``cuda_devices``/``compute_label``
        сохранены: на них уже опирается страница моделей Whisper.
        """

        gpu = self.best_gpu
        return {
            "threads": self.threads,
            "ram_gb": self.ram_gb,
            "ram_available_gb": self.ram_available_gb,
            "ramAvailableGb": self.ram_available_gb,
            "cuda_devices": self.cuda_runtime_devices,
            "compute_label": (
                "Видеокарта (CUDA)" if self.cuda_runtime_devices > 0 else "Процессор (CPU)"
            ),
            "gpus": [item.as_dict() for item in self.gpus],
            "gpuName": "" if gpu is None else gpu.name,
            "gpuVendor": "" if gpu is None else gpu.vendor,
            "gpuVramGb": None if gpu is None else gpu.vram_gb,
            "gpuVramFreeGb": None if gpu is None else gpu.vram_free_gb,
            "gpuVramFreeMb": None if gpu is None else gpu.vram_free_mb,
            "cudaGpuName": "" if self.cuda_gpu is None else self.cuda_gpu.name,
            "cudaGpuIndex": None if self.cuda_gpu is None else self.cuda_gpu.index,
            "cudaVramGb": None if self.cuda_gpu is None else self.cuda_gpu.vram_gb,
            "cudaVramFreeGb": (
                None if self.cuda_gpu is None else self.cuda_gpu.vram_free_gb
            ),
            "gpuLabel": gpu_label(gpu),
            "hasDedicatedGpu": self.has_dedicated_gpu,
            "llamaGpuOffload": self.llama_gpu_offload,
            "platform": self.platform,
            "notes": list(self.notes),
        }


HardwareValidationState = Literal[
    "ready",
    "fallback",
    "insufficient",
    "unknown",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class HardwareValidationResult:
    """Pure, serialisable result of a model/device readiness check.

    The result deliberately describes a *plan*, not a successful model load.
    ``state='unknown'`` means that the available telemetry is not sufficient
    to prove readiness; it never means that inference was attempted.  This
    makes the same object safe to pass to a CLI, QML or a setup wizard.
    """

    model: str
    requested_device: str
    device: str
    compute_type: str
    state: HardwareValidationState
    model_known: bool
    cuda_runtime_available: bool | None
    available_memory_gb: float | None
    available_ram_gb: float | None
    available_vram_gb: float | None
    required_memory_gb: float | None
    required_ram_gb: float | None
    required_vram_gb: float | None
    reason: str
    recommendations: tuple[str, ...] = ()
    fallback_device: str | None = None
    telemetry: tuple[str, ...] = ()
    # Actual CUDA adapter used by the selected path.  CPU fallbacks keep this
    # empty because no GPU allocation is planned.
    device_index: int | None = None

    @property
    def can_run(self) -> bool:
        """Whether the selected plan is backed by known memory telemetry."""

        return self.state in {"ready", "fallback"}

    @property
    def is_unknown(self) -> bool:
        return self.state == "unknown"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON/QML-friendly snapshot without dataclass objects."""

        recommendations = list(self.recommendations)
        telemetry = list(self.telemetry)
        return {
            "model": self.model,
            "requested_device": self.requested_device,
            "requestedDevice": self.requested_device,
            "device": self.device,
            "compute_type": self.compute_type,
            "computeType": self.compute_type,
            "state": self.state,
            "status": self.state,
            "model_known": self.model_known,
            "modelKnown": self.model_known,
            "cuda_runtime_available": self.cuda_runtime_available,
            "cudaRuntimeAvailable": self.cuda_runtime_available,
            "available_memory_gb": self.available_memory_gb,
            "availableMemoryGb": self.available_memory_gb,
            "available_ram_gb": self.available_ram_gb,
            "availableRamGb": self.available_ram_gb,
            "available_vram_gb": self.available_vram_gb,
            "availableVramGb": self.available_vram_gb,
            "required_memory_gb": self.required_memory_gb,
            "requiredMemoryGb": self.required_memory_gb,
            "required_ram_gb": self.required_ram_gb,
            "requiredRamGb": self.required_ram_gb,
            "required_vram_gb": self.required_vram_gb,
            "requiredVramGb": self.required_vram_gb,
            "reason": self.reason,
            "recommendations": recommendations,
            "fallback_device": self.fallback_device,
            "fallbackDevice": self.fallback_device,
            "telemetry": telemetry,
            "device_index": self.device_index,
            "deviceIndex": self.device_index,
            "can_run": self.can_run,
            "canRun": self.can_run,
        }

    to_dict = as_dict


def _validation_snapshot(
    hardware: HardwareProfile | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if hardware is None:
        return {}
    if isinstance(hardware, HardwareProfile):
        return hardware.as_dict()
    if isinstance(hardware, Mapping):
        return dict(hardware)
    raise TypeError("hardware must be HardwareProfile or a mapping")


def _validation_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number) or number < 0:
        return None
    return number


def _validation_first_number(
    mapping: Mapping[str, Any],
    *keys: str,
) -> float | None:
    for key in keys:
        if key not in mapping:
            continue
        number = _validation_number(mapping[key])
        if number is not None:
            return number
    return None


def _validation_gpu_items(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    raw = snapshot.get("gpus")
    if isinstance(raw, (list, tuple)):
        return tuple(raw)
    return ()


def _validation_gpu_value(gpu: Any, *keys: str) -> Any:
    if isinstance(gpu, GpuDevice):
        values = gpu.as_dict()
    elif isinstance(gpu, Mapping):
        values = gpu
    else:
        return None
    for key in keys:
        if key in values:
            return values[key]
    return None


def _validation_gpu_is_nvidia(gpu: Any) -> bool:
    vendor = str(_validation_gpu_value(gpu, "vendor") or "").casefold()
    name = str(_validation_gpu_value(gpu, "name") or "").casefold()
    return vendor == VENDOR_NVIDIA or "nvidia" in name or "geforce" in name or "quadro" in name


def _validation_nvidia_presence(snapshot: Mapping[str, Any]) -> bool | None:
    """Return whether an NVIDIA adapter is known, without probing the host."""

    for key in ("nvidiaPresent", "nvidia_present"):
        if key not in snapshot:
            continue
        value = snapshot[key]
        if isinstance(value, bool):
            return value

    if "gpus" not in snapshot:
        return None
    gpus = _validation_gpu_items(snapshot)
    if not gpus:
        return False
    known = False
    for gpu in gpus:
        if _validation_gpu_is_nvidia(gpu):
            return True
        vendor = str(_validation_gpu_value(gpu, "vendor") or "").casefold()
        name = str(_validation_gpu_value(gpu, "name") or "").strip()
        if vendor or name:
            known = True
    return False if known else None


def _validation_cuda_runtime(snapshot: Mapping[str, Any]) -> bool | None:
    for key in ("cuda_devices", "cudaDevices", "cuda_runtime_devices", "cudaRuntimeDevices"):
        if key not in snapshot:
            continue
        number = _validation_number(snapshot[key])
        if number is not None:
            return number > 0
    for key in ("cuda_available", "cudaAvailable"):
        if key in snapshot and isinstance(snapshot[key], bool):
            return snapshot[key]

    nvidia = _validation_nvidia_presence(snapshot)
    if nvidia is False:
        return False
    return None


def _validation_available_ram(snapshot: Mapping[str, Any]) -> float | None:
    return _validation_first_number(
        snapshot,
        "ram_available_gb",
        "ramAvailableGb",
        "available_ram_gb",
        "availableMemoryGb",
        "available_memory_gb",
    )


def _validation_gpu_index(gpu: Any) -> int | None:
    value = _validation_number(_validation_gpu_value(gpu, "index"))
    if value is None or int(value) != value:
        return None
    return int(value)


def _validation_gpu_free_vram(gpu: Any) -> float | None:
    free_gb = _validation_number(
        _validation_gpu_value(gpu, "vramFreeGb", "vram_free_gb")
    )
    if free_gb is not None:
        return free_gb
    free_mb = _validation_number(
        _validation_gpu_value(gpu, "vramFreeMb", "vram_free_mb")
    )
    return None if free_mb is None else free_mb / 1024.0


def _validation_available_vram(
    snapshot: Mapping[str, Any],
    device_index: int | None = None,
) -> float | None:
    # Once the user picked an adapter, never use the aggregate/best-GPU
    # telemetry: that can approve a load for GPU 1 using GPU 0's free VRAM.
    if device_index is not None:
        for gpu in _validation_gpu_items(snapshot):
            if (
                _validation_gpu_index(gpu) == device_index
                and _validation_gpu_is_nvidia(gpu)
            ):
                return _validation_gpu_free_vram(gpu)
        return None

    direct = _validation_first_number(
        snapshot,
        "cudaVramFreeGb",
        "gpuVramFreeGb",
        "vram_free_gb",
        "cuda_vram_free_gb",
    )
    if direct is not None:
        return direct

    direct_mb = _validation_first_number(
        snapshot,
        "cudaVramFreeMb",
        "gpuVramFreeMb",
        "vram_free_mb",
        "cuda_vram_free_mb",
    )
    if direct_mb is not None:
        return direct_mb / 1024.0

    candidates: list[float] = []
    for gpu in _validation_gpu_items(snapshot):
        if not _validation_gpu_is_nvidia(gpu):
            continue
        free_gb = _validation_gpu_free_vram(gpu)
        if free_gb is not None:
            candidates.append(free_gb)
    return max(candidates) if candidates else None


def model_memory_requirements(
    model: str,
    *,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    """Return the conservative built-in Whisper memory estimate.

    This is a pure catalogue lookup.  Unknown/custom models return
    ``known=False`` instead of receiving an invented memory budget.
    """

    from dotaudio.adapt import whisper_memory_requirements

    return whisper_memory_requirements(
        model,
        device=device,
        compute_type=compute_type,
    )


def _validation_device(value: str | None) -> str:
    normalized = "auto" if value is None else str(value).strip().casefold()
    aliases = {"automatic": "auto", "gpu": "cuda", "processor": "cpu"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"auto", "cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    return normalized


def _validation_device_index(value: int | str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("device_index must be a non-negative integer") from exc
    if index < 0:
        raise ValueError("device_index must be a non-negative integer")
    return index


def _validation_compute_type(value: str | None, device: str) -> str:
    normalized = "auto" if value is None else str(value).strip().casefold()
    if not normalized or normalized == "auto":
        return "float16" if device == "cuda" else "int8"
    return normalized


def _validation_unique(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return tuple(result)


def _validation_path(
    snapshot: Mapping[str, Any],
    model: str,
    *,
    device: str,
    compute_type: str,
    cuda_runtime: bool | None,
    device_index: int | None = None,
) -> dict[str, Any]:
    requirements = model_memory_requirements(
        model,
        device=device,
        compute_type=compute_type,
    )
    available_ram = _validation_available_ram(snapshot)
    available_vram = _validation_available_vram(snapshot, device_index)
    required_ram = (
        None
        if requirements.get("ram_mb") is None
        else float(requirements["ram_mb"]) / 1024.0
    )
    required_vram = (
        None
        if requirements.get("vram_mb") is None
        else float(requirements["vram_mb"]) / 1024.0
    )
    base = {
        "device": device,
        "compute_type": compute_type,
        "model_known": bool(requirements.get("known")),
        "available_ram_gb": available_ram,
        "available_vram_gb": available_vram,
        "required_ram_gb": required_ram,
        "required_vram_gb": required_vram,
        "device_index": device_index if device == "cuda" else None,
    }

    if not requirements.get("known"):
        return {
            **base,
            "state": "unknown",
            "available_memory_gb": available_vram if device == "cuda" else available_ram,
            "required_memory_gb": required_vram if device == "cuda" else required_ram,
            "reason": "Для этой модели нет безопасной оценки требований к памяти.",
            "recommendations": (
                "Проверьте модель в её документации или запустите её с ручным контролем памяти.",
            ),
        }

    if device == "cuda":
        if cuda_runtime is False:
            return {
                **base,
                "state": "unavailable",
                "available_memory_gb": available_vram,
                "required_memory_gb": required_vram,
                "reason": "Доступный CUDA runtime для Whisper не подтверждён.",
                "recommendations": (
                    "Проверьте установку CUDA/CTranslate2 или выберите процессор.",
                ),
            }
        if cuda_runtime is None:
            return {
                **base,
                "state": "unknown",
                "available_memory_gb": available_vram,
                "required_memory_gb": required_vram,
                "reason": "Нельзя подтвердить доступность CUDA без телеметрии runtime.",
                "recommendations": (
                    "Обновите проверку железа и явно проверьте CUDA runtime.",
                ),
            }
        if available_ram is None or available_vram is None:
            missing = []
            if available_ram is None:
                missing.append("доступной ОЗУ")
            if available_vram is None:
                missing.append("свободной VRAM")
            return {
                **base,
                "state": "unknown",
                "available_memory_gb": available_vram,
                "required_memory_gb": required_vram,
                "reason": f"Неизвестно значение: {', '.join(missing)}.",
                "recommendations": (
                    "Повторите проверку после получения полной телеметрии памяти.",
                ),
            }
        if required_ram is not None and available_ram < required_ram:
            return {
                **base,
                "state": "insufficient",
                "available_memory_gb": available_vram,
                "required_memory_gb": required_vram,
                "reason": (
                    f"Для загрузки нужно около {required_ram:.1f} ГБ ОЗУ, "
                    f"доступно {available_ram:.1f} ГБ."
                ),
                "recommendations": (
                    "Освободите ОЗУ или выберите меньшую модель.",
                ),
            }
        if required_vram is not None and available_vram < required_vram:
            return {
                **base,
                "state": "insufficient",
                "available_memory_gb": available_vram,
                "required_memory_gb": required_vram,
                "reason": (
                    f"Для модели нужно около {required_vram:.1f} ГБ свободной VRAM, "
                    f"доступно {available_vram:.1f} ГБ."
                ),
                "recommendations": (
                    "Переключитесь на CPU или выберите меньшую модель/тип вычислений.",
                ),
            }
        return {
            **base,
            "state": "ready",
            "available_memory_gb": available_vram,
            "required_memory_gb": required_vram,
            "reason": "Модель помещается в измеренные RAM и VRAM.",
            "recommendations": ("Можно запускать транскрибацию на CUDA.",),
        }

    if available_ram is None:
        return {
            **base,
            "state": "unknown",
            "available_memory_gb": available_ram,
            "required_memory_gb": required_ram,
            "reason": "Свободная оперативная память не определена.",
            "recommendations": (
                "Повторите проверку с доступной RAM или выберите модель вручную.",
            ),
        }
    if required_ram is not None and available_ram < required_ram:
        return {
            **base,
            "state": "insufficient",
            "available_memory_gb": available_ram,
            "required_memory_gb": required_ram,
            "reason": (
                f"Для загрузки нужно около {required_ram:.1f} ГБ ОЗУ, "
                f"доступно {available_ram:.1f} ГБ."
            ),
            "recommendations": (
                "Освободите ОЗУ или выберите меньшую модель.",
            ),
        }
    return {
        **base,
        "state": "ready",
        "available_memory_gb": available_ram,
        "required_memory_gb": required_ram,
        "reason": "Модель помещается в измеренную оперативную память.",
        "recommendations": ("Можно запускать транскрибацию на CPU.",),
    }


def _validation_result(
    path: Mapping[str, Any],
    *,
    model: str,
    requested_device: str,
    cuda_runtime: bool | None,
    state: HardwareValidationState | None = None,
    reason: str | None = None,
    recommendations: tuple[str, ...] = (),
    fallback_device: str | None = None,
    telemetry: tuple[str, ...] = (),
) -> HardwareValidationResult:
    merged_recommendations = _validation_unique(
        tuple(path.get("recommendations") or ()) + recommendations
    )
    return HardwareValidationResult(
        model=str(model),
        requested_device=requested_device,
        device=str(path.get("device") or requested_device),
        compute_type=str(path.get("compute_type") or ""),
        state=state or path["state"],
        model_known=bool(path.get("model_known")),
        cuda_runtime_available=cuda_runtime,
        available_memory_gb=path.get("available_memory_gb"),
        available_ram_gb=path.get("available_ram_gb"),
        available_vram_gb=path.get("available_vram_gb"),
        required_memory_gb=path.get("required_memory_gb"),
        required_ram_gb=path.get("required_ram_gb"),
        required_vram_gb=path.get("required_vram_gb"),
        reason=str(reason or path.get("reason") or ""),
        recommendations=merged_recommendations,
        fallback_device=fallback_device,
        telemetry=telemetry,
        device_index=path.get("device_index"),
    )


def build_hardware_validation(
    model: str,
    hardware: HardwareProfile | Mapping[str, Any] | None = None,
    *,
    device: str = "auto",
    compute_type: str = "auto",
    device_index: int | str | None = None,
) -> HardwareValidationResult:
    """Build a no-inference readiness result from supplied hardware facts.

    ``hardware`` must be a snapshot, not an instruction to probe the machine.
    Missing values remain missing and produce ``state='unknown'`` where they
    affect the requested path.  A known VRAM/RAM failure may produce a CPU
    ``fallback`` when the CPU path itself is proven to fit.
    """

    snapshot = _validation_snapshot(hardware)
    requested_device = _validation_device(device)
    requested_device_index = _validation_device_index(device_index)
    cuda_runtime = _validation_cuda_runtime(snapshot)
    nvidia_presence = _validation_nvidia_presence(snapshot)

    if requested_device == "auto":
        if cuda_runtime is True:
            candidate = "cuda"
        elif cuda_runtime is False:
            candidate = "cpu"
        elif nvidia_presence is True:
            candidate = "cuda"
        else:
            candidate = "cpu"
    else:
        candidate = requested_device

    candidate_compute_type = _validation_compute_type(compute_type, candidate)
    candidate_path = _validation_path(
        snapshot,
        model,
        device=candidate,
        compute_type=candidate_compute_type,
        cuda_runtime=cuda_runtime,
        device_index=(requested_device_index if candidate == "cuda" else None),
    )

    if (
        requested_device == "auto"
        and candidate == "cpu"
        and cuda_runtime is False
        and nvidia_presence is True
        and candidate_path["state"] == "ready"
    ):
        return _validation_result(
            candidate_path,
            model=model,
            requested_device=requested_device,
            cuda_runtime=cuda_runtime,
            state="fallback",
            reason=(
                "NVIDIA GPU обнаружена, но CUDA runtime недоступен. "
                "Выбран безопасный fallback на CPU."
            ),
            recommendations=(
                "Проверьте установку CUDA/CTranslate2, если нужен GPU-режим.",
            ),
            fallback_device="cpu",
            telemetry=("cuda_unavailable", "fallback_cpu"),
        )

    should_try_cpu = candidate == "cuda" and candidate_path["state"] in {
        "unavailable",
        "insufficient",
    }
    if should_try_cpu:
        cpu_compute_type = _validation_compute_type(compute_type, "cpu")
        cpu_path = _validation_path(
            snapshot,
            model,
            device="cpu",
            compute_type=cpu_compute_type,
            cuda_runtime=cuda_runtime,
        )
        if cpu_path["state"] == "ready":
            fallback = _validation_result(
                cpu_path,
                model=model,
                requested_device=requested_device,
                cuda_runtime=cuda_runtime,
                state="fallback",
                reason=(
                    f"CUDA недоступна для выбранного плана: {candidate_path['reason']} "
                    "Выбран безопасный fallback на CPU."
                ),
                recommendations=(
                    "Проверьте CUDA/VRAM позже, если нужен GPU-режим.",
                ),
                fallback_device="cpu",
                telemetry=("cuda_path_rejected", "cpu_path_ready", "fallback_cpu"),
            )
            # Keep the rejected accelerator budget visible to UI/CLI callers;
            # ``available_memory_gb`` and ``required_memory_gb`` still refer
            # to the selected CPU path.
            return replace(
                fallback,
                available_vram_gb=candidate_path["available_vram_gb"],
                required_vram_gb=candidate_path["required_vram_gb"],
            )
        if cpu_path["state"] == "insufficient":
            return _validation_result(
                candidate_path,
                model=model,
                requested_device=requested_device,
                cuda_runtime=cuda_runtime,
                reason=(
                    f"Не подходит CUDA: {candidate_path['reason']} "
                    f"CPU fallback также невозможен: {cpu_path['reason']}"
                ),
                recommendations=(
                    "Выберите меньшую модель или освободите RAM и VRAM.",
                ),
                telemetry=("cuda_path_rejected", "cpu_path_insufficient"),
            )
        return _validation_result(
            cpu_path,
            model=model,
            requested_device=requested_device,
            cuda_runtime=cuda_runtime,
            reason=(
                f"CUDA-путь не подтверждён: {candidate_path['reason']} "
                f"CPU fallback нельзя подтвердить: {cpu_path['reason']}"
            ),
            recommendations=(
                "Не запускайте автоматический inference до получения полной телеметрии.",
            ),
            telemetry=("cuda_path_rejected", "cpu_path_unknown"),
        )

    return _validation_result(
        candidate_path,
        model=model,
        requested_device=requested_device,
        cuda_runtime=cuda_runtime,
        telemetry=("selected_cpu",) if candidate == "cpu" else ("selected_cuda",),
    )


def validate_hardware(
    model: str,
    hardware: HardwareProfile | Mapping[str, Any] | None = None,
    *,
    device: str = "auto",
    compute_type: str = "auto",
    device_index: int | str | None = None,
) -> HardwareValidationResult:
    """Alias with an action-oriented name for CLI/UI callers."""

    return build_hardware_validation(
        model,
        hardware,
        device=device,
        compute_type=compute_type,
        device_index=device_index,
    )


def gpu_label(gpu: GpuDevice | None) -> str:
    """Короткая подпись карты для интерфейса."""

    if gpu is None:
        return "Видеокарта не найдена"
    vram = gpu.vram_gb
    if vram is None:
        return gpu.name
    return f"{gpu.name}, {vram:g} ГБ"


# CTranslate2 требует «efficient» FP16: Turing (7.0) и новее.
# На Pascal (GTX 10xx, часть MX) WhisperModel(float16) часто не падает,
# а зависает на минуты - GUI при этом ждёт lock.
_FLOAT16_MIN_CC = 7.0
_PRE_TURING_MARKERS = (
    "gtx 10",
    "geforce gtx 10",
    "gtx 9",
    "gtx 8",
    "gtx 7",
    "mx110",
    "mx130",
    "mx150",
    "mx230",
    "mx250",
    "mx330",
    "quadro p",
    "quadro m",
    "tesla p",
    "tesla m",
    "tesla k",
)


def parse_compute_cap(value: str) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    match = re.match(r"(\d+(?:\.\d+)?)", text)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def gpu_allows_efficient_float16(
    hardware: dict | None = None,
    device_index: int | None = None,
) -> bool | None:
    """True - float16 можно. False - сразу int8. None - неизвестно."""

    if not hardware:
        return None
    gpus = list(hardware.get("gpus") or [])
    if not gpus:
        return None

    def _nvidia(gpu: dict) -> bool:
        vendor = str(gpu.get("vendor") or "").casefold()
        name = str(gpu.get("name") or "").casefold()
        return vendor == "nvidia" or any(
            token in name for token in ("nvidia", "geforce", "gtx ", "rtx ", "quadro", "tesla")
        )

    pool = [gpu for gpu in gpus if _nvidia(gpu)] or gpus
    if device_index is not None:
        selected = []
        for gpu in pool:
            try:
                index = int(gpu.get("index"))
            except (TypeError, ValueError):
                continue
            if index == device_index:
                selected.append(gpu)
        if not selected:
            return None
        pool = selected
    best = max(pool, key=lambda gpu: float(gpu.get("vramMb") or gpu.get("vram_mb") or 0))
    cap = parse_compute_cap(str(best.get("compute") or ""))
    if cap is not None:
        return cap >= _FLOAT16_MIN_CC
    name = str(best.get("name") or "").casefold()
    if any(marker in name for marker in _PRE_TURING_MARKERS):
        return False
    return None


def physical_memory_gb() -> float | None:
    """Реальный объём ОЗУ; вне Windows или при отказе API - неизвестно."""

    if sys.platform != "win32":
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, ValueError, OSError):
            return None
        return round(pages * size / (1024**3), 1)
    try:
        import ctypes

        # ULONGLONG в ctypes.wintypes нет: обращение к нему поднимало
        # AttributeError, и объём памяти всегда оставался «неизвестно».
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        kb = ctypes.c_ulonglong(0)
        if not kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return None
        return round(kb.value / (1024 * 1024), 1)
    except (OSError, AttributeError):
        return None


def available_memory_gb() -> float | None:
    """Best-effort currently available physical memory for model preflight."""

    if sys.platform == "win32":
        try:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return round(status.ullAvailPhys / (1024**3), 1)
        except (OSError, AttributeError, TypeError):
            return None

    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * size / (1024**3), 1)
    except (AttributeError, ValueError, OSError):
        pass

    # macOS and restricted containers may not expose sysconf's available-page
    # key.  /proc is a cheap fallback where it exists.
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                value = line.split()[1]
                return round(float(value) / (1024 * 1024), 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def ctranslate2_cuda_devices() -> int:
    """Сколько CUDA-устройств видит CTranslate2 прямо сейчас."""

    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except Exception:
        return 0


@contextmanager
def tolerant_dll_directories():
    """Не давать несуществующей папке DLL сорвать импорт нативной библиотеки.

    llama.cpp при импорте регистрирует в поиске DLL пути из ``CUDA_PATH`` и
    ``HIP_PATH``. Если переменная осталась от удалённой версии Toolkit - а это
    обычное дело после обновления драйвера, - ``os.add_dll_directory``
    поднимает FileNotFoundError, и библиотека не загружается вовсе. Здесь
    терпимой становится только регистрация каталога: сами переменные окружения
    не меняются, потому что на них рассчитывают и другие библиотеки.
    """

    original = getattr(os, "add_dll_directory", None)
    if original is None:
        yield
        return

    def safe(path):
        try:
            return original(path)
        except OSError:
            return None

    os.add_dll_directory = safe
    try:
        yield
    finally:
        os.add_dll_directory = original


def import_llama_cpp():
    """Модуль llama_cpp или ``None``, если его нет или он не загрузился.

    Сборка с CUDA ищет cublas и cudart рядом с собой и в ``CUDA_PATH``. Если
    библиотеки пришли pip-пакетами nvidia-*, их каталоги нужно зарегистрировать
    до загрузки - и сделать это здесь, а не надеяться, что раньше кто-то вызвал
    опрос устройства.
    """

    try:
        from dotaudio.cuda_runtime import register_cuda_dll_directories

        register_cuda_dll_directories()
    except Exception:
        pass
    try:
        with tolerant_dll_directories():
            import llama_cpp
    except Exception:
        return None
    return llama_cpp


def llama_gpu_offload_supported() -> bool | None:
    """Умеет ли установленная сборка llama.cpp считать на видеокарте.

    ``None`` значит, что библиотеки нет вовсе, и об этом нужно сказать
    иначе, чем про «сборка без ускорения».
    """

    module = import_llama_cpp()
    if module is None:
        return None
    try:
        return bool(module.llama_supports_gpu_offload())
    except Exception:
        return False


def _parse_nvidia_smi(raw: str) -> list[GpuDevice]:
    devices: list[GpuDevice] = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        index, name, total, free, driver, compute = parts[:6]

        def mb(value: str) -> int | None:
            digits = re.sub(r"[^0-9]", "", value)
            return int(digits) if digits else None

        devices.append(
            GpuDevice(
                index=int(index),
                name=name,
                vendor=VENDOR_NVIDIA,
                vram_mb=mb(total),
                vram_free_mb=mb(free),
                driver=driver,
                compute=compute,
                integrated=False,
                source="nvidia-smi",
            )
        )
    return devices


def nvidia_gpus() -> list[GpuDevice]:
    """Карты NVIDIA с точной памятью и compute capability."""

    raw = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.free,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    return _parse_nvidia_smi(raw)


def _registry_display_adapters() -> list[GpuDevice]:
    """Адаптеры из реестра Windows: работает для любого вендора.

    ``HardwareInformation.qwMemorySize`` даёт настоящий объём видеопамяти,
    в отличие от ``Win32_VideoController.AdapterRAM``, который обрезан
    четырьмя гигабайтами.
    """

    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    class_key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    devices: list[GpuDevice] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_key) as root:
            position = 0
            while True:
                try:
                    child = winreg.EnumKey(root, position)
                except OSError:
                    break
                position += 1
                if not child.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, child) as entry:
                        name = _reg_str(winreg, entry, "DriverDesc")
                        if not name:
                            continue
                        vram = _reg_vram_mb(winreg, entry)
                        driver = _reg_str(winreg, entry, "DriverVersion")
                except OSError:
                    continue
                devices.append(
                    GpuDevice(
                        index=int(child),
                        name=name,
                        vendor=vendor_of(name),
                        vram_mb=vram,
                        driver=driver,
                        integrated=_looks_integrated(name, vram),
                        source="registry",
                    )
                )
    except OSError:
        return []
    return devices


def _reg_str(winreg, key, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def _reg_vram_mb(winreg, key) -> int | None:
    for name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        try:
            value, kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        number: int | None = None
        if isinstance(value, int):
            number = value
        elif isinstance(value, bytes) and value:
            number = int.from_bytes(value, "little")
        if number:
            return int(number / (1024 * 1024))
    return None


def _merge_gpus(primary: list[GpuDevice], extra: list[GpuDevice]) -> tuple[GpuDevice, ...]:
    """Дополнить точные данные вендорной утилиты списком из системы.

    nvidia-smi знает про свои карты больше всех, но не видит Radeon и Intel.
    Совпадения ищутся по названию, чтобы одна карта не попала в список дважды.
    """

    merged = list(primary)
    known = {gpu.name.casefold() for gpu in merged}
    used_indexes = {gpu.index for gpu in merged}
    next_index = max(used_indexes, default=-1) + 1
    for gpu in extra:
        low = gpu.name.casefold()
        if any(low == name or low in name or name in low for name in known):
            continue
        # Registry/Display adapters are not guaranteed to use the same ordinal
        # as nvidia-smi.  Keep nvidia-smi's CUDA indexes stable and assign
        # non-CUDA extras after them instead of renumbering every adapter.
        index = gpu.index if gpu.index not in used_indexes else next_index
        while index in used_indexes:
            index += 1
        merged.append(replace(gpu, index=index))
        used_indexes.add(index)
        next_index = max(next_index, index + 1)
        known.add(low)
    return tuple(merged)


def _add_missing_cuda_devices(
    gpus: list[GpuDevice],
    runtime_devices: int,
) -> list[GpuDevice]:
    """Represent CUDA ordinals even when nvidia-smi is unavailable.

    CTranslate2 is the runtime that will receive ``device_index``.  A machine
    can therefore have a usable CUDA device while the vendor utility is not
    installed or is blocked by policy.  The synthetic entry keeps that fact
    selectable in the UI without inventing VRAM numbers.
    """

    if runtime_devices <= 0:
        return gpus
    result = list(gpus)
    nvidia = [gpu for gpu in result if gpu.vendor == VENDOR_NVIDIA]
    known_indexes = {gpu.index for gpu in nvidia}
    next_index = max((gpu.index for gpu in result), default=-1) + 1
    for index in range(runtime_devices):
        if index in known_indexes:
            continue
        while next_index in {gpu.index for gpu in result}:
            next_index += 1
        result.append(
            GpuDevice(
                index=index,
                name=f"NVIDIA GPU {index + 1}",
                vendor=VENDOR_NVIDIA,
                source="ctranslate2",
            )
        )
        known_indexes.add(index)
        next_index += 1
    return result


def list_gpus() -> tuple[GpuDevice, ...]:
    """Все видеокарты этой машины, каждая с тем, что удалось измерить."""

    return _merge_gpus(nvidia_gpus(), _registry_display_adapters())


def probe(
    refresh: bool = False,
    *,
    include_optional: bool = True,
) -> HardwareProfile:
    """Сводка устройства; повторный вызов отдаёт свежий кеш.

    Опрос запускает внешний процесс и читает реестр, поэтому его нельзя
    звать из обработчика кадра. Кеш живёт ``PROBE_TTL_SECONDS``.
    """

    global _cached
    now = time.monotonic()
    with _probe_lock:
        if not refresh and _cached is not None and now - _cached[0] < PROBE_TTL_SECONDS:
            return _cached[1]
    # DLL из pip-пакетов NVIDIA должны быть зарегистрированы до опроса
    # CTranslate2, иначе CUDA останется «нет» даже после установки.
    try:
        from dotaudio.cuda_runtime import register_cuda_dll_directories

        register_cuda_dll_directories()
    except Exception:
        pass
    gpus = list_gpus()
    notes: list[str] = []
    cuda_runtime = ctranslate2_cuda_devices()
    gpus = _add_missing_cuda_devices(gpus, cuda_runtime)
    if cuda_runtime == 0 and any(gpu.vendor == VENDOR_NVIDIA for gpu in gpus):
        notes.append(
            "Карта NVIDIA есть, но CTranslate2 её не видит: Whisper пойдёт на процессоре."
        )
    profile = HardwareProfile(
        threads=os.cpu_count() or 0,
        ram_gb=physical_memory_gb(),
        ram_available_gb=available_memory_gb(),
        gpus=gpus,
        platform=sys.platform,
        cuda_runtime_devices=cuda_runtime,
        llama_gpu_offload=(
            llama_gpu_offload_supported() if include_optional else None
        ),
        notes=tuple(notes),
    )
    with _probe_lock:
        _cached = (time.monotonic(), profile)
    return profile


def reset_cache() -> None:
    """Сбросить кеш опроса; нужно тестам и после установки ускорения."""

    global _cached
    with _probe_lock:
        _cached = None


@dataclass(frozen=True)
class Accelerator:
    """Сборка llama.cpp под определённое железо.

    Новый ускоритель добавляется одной записью: индекс колёс, условие
    пригодности и подпись. Остальной код про вендоров ничего не знает.
    """

    id: str
    label: str
    detail: str
    wheel_index: str | None = None
    vendors: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    # Готовые колёса собраны не под все версии Python; заявлять установку
    # там, где её нет, нельзя.
    python_versions: tuple[tuple[int, int], ...] = ()
    priority: int = 0

    def suits(self, profile: HardwareProfile) -> bool:
        if self.platforms and profile.platform not in self.platforms:
            return False
        if not self.vendors:
            return True
        return any(gpu.vendor in self.vendors and not gpu.integrated for gpu in profile.gpus)

    def wheels_for_current_python(self) -> bool:
        if not self.python_versions:
            return True
        return sys.version_info[:2] in self.python_versions


# Индексы готовых колёс llama-cpp-python. Состав проверен по опубликованным
# индексам: под CPU есть сборки для всех поддерживаемых версий Python, под
# CUDA - для 3.10-3.12, а Vulkan и ROCm на момент проверки собраны не под
# каждую версию. Поэтому пригодность считается, а не заявляется.
CUDA_PYTHON = ((3, 10), (3, 11), (3, 12))
ACCELERATORS: tuple[Accelerator, ...] = (
    Accelerator(
        id="cuda",
        label="CUDA",
        detail="Видеокарты NVIDIA",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cu124",
        vendors=(VENDOR_NVIDIA,),
        platforms=("win32", "linux"),
        python_versions=CUDA_PYTHON,
        priority=40,
    ),
    Accelerator(
        id="vulkan",
        label="Vulkan",
        detail="Любая карта с драйвером Vulkan: NVIDIA, Radeon, Intel Arc",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/vulkan",
        vendors=(VENDOR_NVIDIA, VENDOR_AMD, VENDOR_INTEL),
        platforms=("win32", "linux"),
        priority=30,
    ),
    Accelerator(
        id="rocm",
        label="ROCm",
        detail="Radeon на Linux и HIP-сборка для Windows",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/hip-radeon",
        vendors=(VENDOR_AMD,),
        platforms=("win32", "linux"),
        priority=25,
    ),
    Accelerator(
        id="metal",
        label="Metal",
        detail="Apple Silicon",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/metal",
        platforms=("darwin",),
        priority=35,
    ),
    Accelerator(
        id="cpu",
        label="Процессор",
        detail="Работает везде, скорость зависит от числа потоков",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cpu",
        priority=10,
    ),
)


def accelerator_options(profile: HardwareProfile | None = None) -> list[dict]:
    """Сборки llama.cpp по пригодности этому железу, лучшая первой."""

    profile = profile or probe()
    options: list[dict] = []
    for accelerator in ACCELERATORS:
        suits = accelerator.suits(profile)
        wheels = accelerator.wheels_for_current_python()
        if suits and not wheels:
            reason = (
                f"Готовой сборки под Python "
                f"{sys.version_info.major}.{sys.version_info.minor} нет"
            )
        elif suits:
            reason = accelerator.detail
        else:
            reason = "Нет подходящего устройства"
        options.append(
            {
                "id": accelerator.id,
                "label": accelerator.label,
                "detail": accelerator.detail,
                "available": bool(suits and wheels),
                "reason": reason,
                "wheelIndex": accelerator.wheel_index,
                "command": install_command(accelerator.id),
                "priority": accelerator.priority,
            }
        )
    options.sort(key=lambda item: (not item["available"], -item["priority"]))
    return options


def recommended_accelerator(profile: HardwareProfile | None = None) -> str:
    """Ускоритель, который стоит поставить на этой машине."""

    for option in accelerator_options(profile):
        if option["available"]:
            return str(option["id"])
    return "cpu"


def install_command(accelerator_id: str) -> str:
    """Команда установки сборки llama.cpp для показа пользователю."""

    for accelerator in ACCELERATORS:
        if accelerator.id != accelerator_id:
            continue
        if not accelerator.wheel_index:
            return "pip install llama-cpp-python"
        return (
            "pip install llama-cpp-python --upgrade --force-reinstall "
            f"--extra-index-url {accelerator.wheel_index}"
        )
    return ""


def install_arguments(accelerator_id: str) -> list[str]:
    """Аргументы pip для установки выбранной сборки без shell."""

    for accelerator in ACCELERATORS:
        if accelerator.id != accelerator_id:
            continue
        args = ["-m", "pip", "install", "llama-cpp-python", "--upgrade", "--force-reinstall"]
        if accelerator.wheel_index:
            args += ["--extra-index-url", accelerator.wheel_index]
        return args
    return []


# Сборка llama.cpp с CUDA ищет cublas и cudart от CUDA 12. На машине бывает
# только новый Toolkit или вообще ни одного, и тогда библиотека загружается,
# но GPU не находит. Эти pip-пакеты закрывают вопрос без установки Toolkit;
# проверено на этой машине: CUDA появилась и у llama.cpp, и у CTranslate2.
CUDA_RUNTIME_FOR_LLAMA: tuple[str, ...] = (
    "nvidia-cublas-cu12",
    "nvidia-cuda-runtime-cu12",
)


def install_steps(accelerator_id: str) -> list[list[str]]:
    """Все шаги установки ускорителя по порядку.

    Разделены, потому что ``--force-reinstall`` относится ко всей команде: он
    нужен для самой сборки, но заново качать гигабайты библиотек CUDA незачем.
    """

    steps: list[list[str]] = []
    if accelerator_id == "cuda":
        steps.append(["-m", "pip", "install", *CUDA_RUNTIME_FOR_LLAMA])
    wheel = install_arguments(accelerator_id)
    if wheel:
        steps.append(wheel)
    return steps
