"""Адаптация Whisper/Live под измеренное железо (без Qt).

Один план на машину: модель, профиль, device, greedy-финалы и подпись.
Опирается на факты из ``hardware`` / ``compute_advice``, не на бренд ноутбука.

Целевые классы, под которые калибровались пороги:

* ноутбук с CUDA (пример: i5-12500H + RTX 3060 + 16 ГБ) - ``cuda_*``;
* слабый CPU / только Iris (пример: Surface Laptop 4, 4 потока) - ``cpu_weak``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any

PROFILE_FOR_MODEL = {
    "tiny": "fast",
    "base": "fast",
    "small": "balanced",
    "medium": "balanced",
    "large-v3": "quality",
    "turbo": "quality",
}

# Потоки целиком заняты inference на Surface-классе: UI и ОС делят те же
# ядра. На 16-потоковом CPU cap 4 оставляет запас; на 4 потоках - нет.
WEAK_CPU_THREADS = 4
# На машине с запасом ядер small держит Live (замер проекта). Ниже -
# base + greedy, иначе очередь отстаёт.
STRONG_CPU_THREADS = 8
# RTX 3060 Laptop обычно 6 ГБ: medium влезает при CUDA float16.
COMFORTABLE_VRAM_GB = 6.0

# These are conservative *load budgets*, not speed benchmarks.  The model
# catalogue in the UI describes the same families by download size and total
# RAM; this table adds headroom for the native runtime and temporary buffers so
# a model is rejected before CTranslate2 starts an avoidable CUDA allocation.
WHISPER_MODEL_DISK_MB = {
    "tiny": 75,
    "base": 142,
    "small": 483,
    "medium": 1530,
    "large-v3": 3100,
    "turbo": 1620,
}
WHISPER_MODEL_RAM_MB = {
    "tiny": 1536,
    "base": 2048,
    "small": 3072,
    "medium": 6144,
    "large-v3": 12288,
    "turbo": 8192,
}
WHISPER_MODEL_VRAM_MB = {
    "tiny": 1024,
    "base": 1536,
    "small": 2560,
    "medium": 5120,
    "large-v3": 10240,
    "turbo": 7680,
}

_COMPUTE_MEMORY_MULTIPLIER = {
    "float16": 1.0,
    "int8": 0.78,
    "int8_float16": 0.9,
    "int8_float32": 1.0,
    "float32": 1.8,
}


def normalise_whisper_model(model: str) -> str:
    """Return the built-in model key, preserving custom model paths."""

    value = str(model or "").strip().casefold()
    if value in {"large-v3-turbo", "faster-whisper-large-v3-turbo"}:
        return "turbo"
    if value.startswith("faster-whisper-"):
        value = value.removeprefix("faster-whisper-")
    return value


def _number(mapping: dict, *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _gpu_budget_gb(
    hardware: dict,
    *,
    device_index: int | None = None,
) -> float | None:
    """Prefer current free VRAM; fall back to total VRAM when it is unknown."""

    if device_index is not None:
        for gpu in hardware.get("gpus") or ():
            if not isinstance(gpu, dict):
                continue
            try:
                index = int(gpu.get("index"))
            except (TypeError, ValueError):
                continue
            if index != device_index:
                continue
            vendor = str(gpu.get("vendor") or "").casefold()
            name = str(gpu.get("name") or "").casefold()
            if vendor != "nvidia" and "nvidia" not in name:
                return None
            free = _number(gpu, "vramFreeMb", "vram_free_mb")
            total = _number(gpu, "vramMb", "vram_mb")
            value = free if free is not None else total
            return None if value is None else max(0.0, value) / 1024.0
        return None

    direct_free = _number(
        hardware,
        "cudaVramFreeGb",
        "gpuVramFreeGb",
        "vram_free_gb",
    )
    if direct_free is not None:
        return max(0.0, direct_free)
    direct_total = _number(
        hardware,
        "cudaVramGb",
        "gpuVramGb",
        "vram_gb",
    )
    if direct_total is not None:
        return max(0.0, direct_total)

    candidates: list[float] = []
    for gpu in hardware.get("gpus") or ():
        if not isinstance(gpu, dict):
            continue
        vendor = str(gpu.get("vendor") or "").casefold()
        name = str(gpu.get("name") or "").casefold()
        if vendor not in {"nvidia", ""} and "nvidia" not in name:
            continue
        free = _number(gpu, "vramFreeMb", "vram_free_mb")
        total = _number(gpu, "vramMb", "vram_mb")
        value = free if free is not None else total
        if value is not None:
            candidates.append(max(0.0, value) / 1024.0)
    return max(candidates) if candidates else None


def whisper_memory_requirements(
    model: str,
    *,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    """Return conservative memory requirements for a built-in Whisper model.

    Unknown names (including custom local models) intentionally return
    ``known=False``.  The engine must still try those models and let their
    backend decide; inventing a budget for an arbitrary model would be less
    safe than reporting that the estimate is unavailable.
    """

    name = normalise_whisper_model(model)
    disk_mb = WHISPER_MODEL_DISK_MB.get(name)
    ram_mb = WHISPER_MODEL_RAM_MB.get(name)
    vram_mb = WHISPER_MODEL_VRAM_MB.get(name)
    if disk_mb is None or ram_mb is None or vram_mb is None:
        return {
            "known": False,
            "model": name,
            "device": device,
            "compute_type": compute_type,
            "disk_mb": None,
            "ram_mb": None,
            "vram_mb": None,
        }

    multiplier = _COMPUTE_MEMORY_MULTIPLIER.get(compute_type, 1.0)
    if device == "cuda":
        vram_mb = ceil(vram_mb * multiplier)
        # CUDA still needs host-side metadata and staging buffers.
        ram_mb = ceil(ram_mb * 0.75)
    else:
        ram_mb = ceil(ram_mb * multiplier)
        vram_mb = 0
    return {
        "known": True,
        "model": name,
        "device": device,
        "compute_type": compute_type,
        "disk_mb": disk_mb,
        "ram_mb": ram_mb,
        "vram_mb": vram_mb,
    }


def assess_whisper_model_fit(
    model: str,
    hardware: dict,
    *,
    device: str = "cpu",
    compute_type: str = "int8",
    device_index: int | None = None,
) -> dict[str, Any]:
    """Assess whether a model has enough *currently available* memory.

    ``state=unknown`` is deliberately non-blocking: missing telemetry should
    not make a custom model unusable.  ``insufficient`` is only returned when
    the relevant available-memory value is known and below the conservative
    budget.
    """

    requirement = whisper_memory_requirements(
        model, device=device, compute_type=compute_type
    )
    if not requirement["known"]:
        return {
            **requirement,
            "state": "unknown",
            "available_mb": None,
            "headroom_mb": None,
            "reason": "Нет безопасной оценки для пользовательской модели.",
        }

    available_ram_gb = _number(
        hardware, "ram_available_gb", "ramAvailableGb", "available_ram_gb"
    )
    available_ram_mb = (
        None if available_ram_gb is None else max(0.0, available_ram_gb * 1024)
    )
    available_vram_gb = _gpu_budget_gb(hardware, device_index=device_index)
    available_vram_mb = (
        None if available_vram_gb is None else max(0.0, available_vram_gb * 1024)
    )

    if device == "cuda":
        available_mb = available_vram_mb
        required_mb = float(requirement["vram_mb"])
        resource_name = "VRAM"
    else:
        available_mb = available_ram_mb
        required_mb = float(requirement["ram_mb"])
        resource_name = "ОЗУ"

    if available_mb is None:
        state = "unknown"
        headroom_mb = None
        reason = f"Свободная {resource_name} не определена; проверка будет выполнена движком."
    else:
        headroom_mb = available_mb - required_mb
        state = "fit" if headroom_mb >= 0 else "insufficient"
        reason = (
            f"Нужно около {required_mb / 1024:.1f} ГБ {resource_name}, "
            f"доступно {available_mb / 1024:.1f} ГБ."
        )

    ram_state = "unknown"
    if available_ram_mb is not None:
        ram_state = (
            "fit"
            if available_ram_mb >= float(requirement["ram_mb"])
            else "insufficient"
        )
    if ram_state == "insufficient":
        state = "insufficient"
        reason += " Недостаточно доступного ОЗУ для безопасной загрузки."

    return {
        **requirement,
        "state": state,
        "available_mb": None if available_mb is None else round(available_mb),
        "available_ram_mb": None
        if available_ram_mb is None
        else round(available_ram_mb),
        "available_vram_mb": None
        if available_vram_mb is None
        else round(available_vram_mb),
        "headroom_mb": None if headroom_mb is None else round(headroom_mb),
        "ram_state": ram_state,
        "reason": reason,
    }


@dataclass(frozen=True, slots=True)
class WhisperPlan:
    """Готовые настройки распознавания под эту машину."""

    tier: str
    model: str
    profile: str
    device: str
    live_greedy_finals: bool
    note: str
    label: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_nvidia(hardware: dict) -> bool:
    if hardware.get("nvidiaPresent"):
        return True
    for item in hardware.get("gpus") or ():
        if isinstance(item, dict) and str(item.get("vendor") or "") == "nvidia":
            return True
    return False


def _has_integrated_only(hardware: dict) -> bool:
    """Есть только встроенная графика (Iris/UHD), без дискретной NVIDIA/AMD."""

    gpus = [item for item in (hardware.get("gpus") or ()) if isinstance(item, dict)]
    if not gpus:
        return False
    if any(not bool(item.get("integrated")) for item in gpus):
        return False
    return True


def classify_tier(hardware: dict) -> str:
    """Класс машины для выбора модели и Live-режима."""

    cuda = int(hardware.get("cuda_devices") or 0)
    advice = str(hardware.get("computeAdvice") or "")
    threads = int(hardware.get("threads") or 0)
    # A card can have plenty of total VRAM but almost none free because of a
    # browser, game, or another local model.  Prefer the live free value when
    # it is available; the old total-only behaviour remains the fallback.
    vram = _gpu_budget_gb(hardware)
    nvidia = _has_nvidia(hardware)
    available_ram = _number(
        hardware, "ram_available_gb", "ramAvailableGb", "available_ram_gb"
    )

    if available_ram is not None and available_ram < 1.5:
        return "cpu_minimal"

    if cuda > 0 or advice == "ready":
        if vram is not None and vram >= COMFORTABLE_VRAM_GB:
            return "cuda_strong"
        return "cuda_ready"

    # NVIDIA есть, runtime ещё не стоит: уже планируем GPU-модель, device=auto.
    if nvidia or advice == "needs_runtime":
        if vram is not None and vram >= COMFORTABLE_VRAM_GB:
            return "cuda_pending_strong"
        return "cuda_pending"

    if threads <= 1:
        return "cpu_minimal"
    if threads <= WEAK_CPU_THREADS:
        return "cpu_weak"
    if _has_integrated_only(hardware) and threads < STRONG_CPU_THREADS:
        return "cpu_weak"
    if threads < STRONG_CPU_THREADS:
        return "cpu_mid"
    return "cpu_strong"


def recommend_device(hardware: dict) -> str:
    """Вычислительное устройство по факту CUDA, не по желанию."""

    advice = str(hardware.get("computeAdvice") or "")
    if advice == "ready" or int(hardware.get("cuda_devices") or 0) > 0:
        return "cuda"
    if advice == "needs_runtime" or _has_nvidia(hardware):
        return "auto"
    return "cpu"


def plan_whisper(hardware: dict) -> WhisperPlan:
    """Единый план Whisper/Live под сводку железа."""

    tier = classify_tier(hardware)
    device = recommend_device(hardware)

    if tier == "cuda_strong":
        return WhisperPlan(
            tier=tier,
            model="medium",
            profile="balanced",
            device=device,
            live_greedy_finals=True,
            note="CUDA и запас VRAM: medium для файлов, greedy-финалы для Live.",
            label="Ноутбук с NVIDIA",
        )
    if tier == "cuda_ready":
        return WhisperPlan(
            tier=tier,
            model="small",
            profile="balanced",
            device=device,
            live_greedy_finals=True,
            note="CUDA есть, VRAM скромная: small и greedy-финалы Live.",
            label="NVIDIA с ограниченной памятью",
        )
    if tier == "cuda_pending_strong":
        return WhisperPlan(
            tier=tier,
            model="medium",
            profile="balanced",
            device="auto",
            live_greedy_finals=True,
            note="NVIDIA найдена: после CUDA runtime возьмём medium.",
            label="NVIDIA без runtime",
        )
    if tier == "cuda_pending":
        return WhisperPlan(
            tier=tier,
            model="small",
            profile="balanced",
            device="auto",
            live_greedy_finals=True,
            note="NVIDIA найдена: после CUDA runtime останемся на small.",
            label="NVIDIA без runtime",
        )
    if tier == "cpu_weak":
        return WhisperPlan(
            tier=tier,
            model="base",
            profile="fast",
            device="cpu",
            live_greedy_finals=True,
            note=(
                "Мало потоков или только встроенная графика (Iris/UHD): "
                "Whisper на CPU, профиль «Быстро», greedy-финалы."
            ),
            label="Слабый CPU / Iris",
        )
    if tier == "cpu_mid":
        return WhisperPlan(
            tier=tier,
            model="small",
            profile="balanced",
            device="cpu",
            live_greedy_finals=True,
            note="Средний CPU без CUDA: small и greedy-финалы, чтобы Live не копился.",
            label="Средний CPU",
        )
    if tier == "cpu_minimal":
        return WhisperPlan(
            tier=tier,
            model="tiny",
            profile="fast",
            device="cpu",
            live_greedy_finals=True,
            note="Потоки не измерены или их почти нет: tiny.",
            label="Минимальный CPU",
        )
    return WhisperPlan(
        tier=tier,
        model="small",
        profile="balanced",
        device="cpu",
        live_greedy_finals=False,
        note="Достаточно потоков CPU: small на процессоре.",
        label="Сильный CPU",
    )


def recommended_whisper(hardware: dict) -> str:
    """Имя модели Whisper по умолчанию."""

    return plan_whisper(hardware).model


def live_cpu_threads(total: int | None = None) -> int:
    """Потоки CTranslate2: не больше четырёх, на слабом CPU оставляем ядро UI.

    На 16-потоковом CPU четыре потока дали лучший decode (замер engine.py).
    На 4-потоковом Surface те же четыре забирают всё: оставляем один поток
    системе и интерфейсу.
    """

    import os

    count = total if total is not None else (os.cpu_count() or 1)
    count = max(1, int(count))
    if count <= WEAK_CPU_THREADS:
        return max(1, count - 1)
    return min(4, count)


def integrated_whisper_hint(hardware: dict) -> str:
    """Честная подпись, когда ускорить Whisper нечем."""

    if int(hardware.get("cuda_devices") or 0) > 0:
        return ""
    if _has_nvidia(hardware):
        return ""
    if _has_integrated_only(hardware):
        name = str(hardware.get("gpuName") or hardware.get("gpuLabel") or "встроенная графика")
        return (
            f"{name} не ускоряет Whisper (нужна CUDA NVIDIA). "
            "Распознавание идёт на процессоре; выбран быстрый профиль."
        )
    return ""


__all__ = [
    "COMFORTABLE_VRAM_GB",
    "PROFILE_FOR_MODEL",
    "STRONG_CPU_THREADS",
    "WEAK_CPU_THREADS",
    "WhisperPlan",
    "assess_whisper_model_fit",
    "classify_tier",
    "integrated_whisper_hint",
    "live_cpu_threads",
    "normalise_whisper_model",
    "plan_whisper",
    "recommend_device",
    "recommended_whisper",
    "whisper_memory_requirements",
]
