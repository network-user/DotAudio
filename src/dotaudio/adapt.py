"""Адаптация Whisper/Live под измеренное железо (без Qt).

Один план на машину: модель, профиль, device, greedy-финалы и подпись.
Опирается на факты из ``hardware`` / ``compute_advice``, не на бренд ноутбука.

Целевые классы, под которые калибровались пороги:

* ноутбук с CUDA (пример: i5-12500H + RTX 3060 + 16 ГБ) - ``cuda_*``;
* слабый CPU / только Iris (пример: Surface Laptop 4, 4 потока) - ``cpu_weak``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


def _gpu_vram_gb(hardware: dict) -> float | None:
    vram = hardware.get("gpuVramGb")
    if vram is None:
        vram = hardware.get("vram_gb")
    return _float_or_none(vram)


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
    vram = _gpu_vram_gb(hardware)
    nvidia = _has_nvidia(hardware)

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
    "classify_tier",
    "integrated_whisper_hint",
    "live_cpu_threads",
    "plan_whisper",
    "recommend_device",
    "recommended_whisper",
]
