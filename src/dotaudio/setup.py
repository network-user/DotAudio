"""Планирование первой настройки устройства (без Qt).

Собирает короткий план под измеренное железо: что поставить, что скачать,
какие настройки применить. Сама загрузка и pip живут в ``setup_controller``.
"""

from __future__ import annotations

from typing import Any

from dotaudio.llm import MODELS_BY_ID, get_model, recommend_model

# Оценки размера кеша faster-whisper. Должны совпадать с MODEL_CATALOG
# в controller.py; здесь дублируются, чтобы модуль оставался Qt-free.
WHISPER_DOWNLOAD_MB = {
    "tiny": 75,
    "base": 142,
    "small": 483,
    "medium": 1530,
    "large-v3": 3100,
    "turbo": 1620,
}

WHISPER_LABELS = {
    "tiny": "Whisper Tiny",
    "base": "Whisper Base",
    "small": "Whisper Small",
    "medium": "Whisper Medium",
    "large-v3": "Whisper Large v3",
    "turbo": "Whisper Turbo",
}

PROFILE_FOR_MODEL = {
    "tiny": "fast",
    "base": "fast",
    "small": "balanced",
    "medium": "balanced",
    "large-v3": "quality",
    "turbo": "quality",
}


def _mb(value: float | int | None) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def recommended_whisper(hardware: dict) -> str:
    """Модель Whisper по умолчанию под это устройство."""

    if int(hardware.get("cuda_devices") or 0) > 0:
        vram = hardware.get("gpuVramGb")
        if vram is None:
            vram = hardware.get("vram_gb")
        try:
            if vram is not None and float(vram) >= 6.0:
                return "medium"
        except (TypeError, ValueError):
            pass
        return "small"
    threads = int(hardware.get("threads") or 0)
    if threads >= 4:
        return "small"
    if threads >= 2:
        return "base"
    return "tiny"


def recommend_device(hardware: dict) -> str:
    """Вычислительное устройство по факту CUDA, не по желанию."""

    advice = str(hardware.get("computeAdvice") or "")
    if advice == "ready" or int(hardware.get("cuda_devices") or 0) > 0:
        return "cuda"
    if advice == "needs_runtime":
        return "auto"
    return "cpu"


def recommend_llm_id(hardware: dict) -> str:
    """Идентификатор чат-модели под сводку железа из контроллера."""

    from dotaudio.hardware import GpuDevice, HardwareProfile

    gpus = []
    for item in hardware.get("gpus") or []:
        if not isinstance(item, dict):
            continue
        vram = item.get("vramMb")
        if vram is None:
            vram = item.get("vram_mb")
        try:
            vram_mb = int(vram) if vram is not None else None
        except (TypeError, ValueError):
            vram_mb = None
        gpus.append(
            GpuDevice(
                index=int(item.get("index") or 0),
                name=str(item.get("name") or ""),
                vendor=str(item.get("vendor") or "unknown"),
                vram_mb=vram_mb,
                integrated=bool(item.get("integrated")),
                source=str(item.get("source") or "unknown"),
            )
        )
    profile = HardwareProfile(
        threads=int(hardware.get("threads") or 0),
        ram_gb=hardware.get("ram_gb"),
        gpus=tuple(gpus),
        platform=str(hardware.get("platform") or ""),
        cuda_runtime_devices=int(hardware.get("cuda_devices") or 0),
        llama_gpu_offload=bool(hardware.get("llamaGpuOffload")),
        notes=tuple(str(note) for note in (hardware.get("notes") or ())),
    )
    return recommend_model(profile)


def technology_cards(hardware: dict) -> list[dict[str, Any]]:
    """Короткий список найденных технологий для брифинга."""

    advice = str(hardware.get("computeAdvice") or "")
    gpu_label = str(hardware.get("gpuLabel") or hardware.get("gpuName") or "")
    cards: list[dict[str, Any]] = [
        {
            "id": "cpu",
            "title": "Процессор",
            "detail": f"{int(hardware.get('threads') or 0)} потоков",
            "state": "ready",
        },
        {
            "id": "ram",
            "title": "Память",
            "detail": (
                f"{hardware.get('ram_gb')} ГБ"
                if hardware.get("ram_gb") is not None
                else "не измерена"
            ),
            "state": "ready",
        },
    ]
    if advice == "ready":
        cards.append(
            {
                "id": "cuda",
                "title": "CUDA",
                "detail": gpu_label or "видеокарта готова",
                "state": "ready",
            }
        )
    elif advice == "needs_runtime":
        cards.append(
            {
                "id": "cuda",
                "title": "CUDA runtime",
                "detail": f"{gpu_label or 'NVIDIA'} · пакеты ещё не стоят",
                "state": "needed",
            }
        )
    elif advice == "other_gpu":
        cards.append(
            {
                "id": "gpu",
                "title": "Видеокарта",
                "detail": gpu_label or "без CUDA для Whisper",
                "state": "info",
            }
        )
    else:
        cards.append(
            {
                "id": "gpu",
                "title": "Видеокарта",
                "detail": "не найдена · работа на CPU",
                "state": "info",
            }
        )
    cards.append(
        {
            "id": "whisper",
            "title": "Whisper",
            "detail": "локальное распознавание речи",
            "state": "needed",
        }
    )
    cards.append(
        {
            "id": "llm",
            "title": "Ассистент",
            "detail": "локальная языковая модель",
            "state": "needed",
        }
    )
    return cards


def build_briefing(
    hardware: dict,
    *,
    whisper_ready: bool = False,
    llm_ready: bool = False,
) -> dict[str, Any]:
    """Рекомендации и оценки размера для экрана брифинга."""

    model = recommended_whisper(hardware)
    device = recommend_device(hardware)
    llm_id = recommend_llm_id(hardware)
    llm = get_model(llm_id)
    advice = str(hardware.get("computeAdvice") or "")
    whisper_mb = _mb(WHISPER_DOWNLOAD_MB.get(model))
    llm_mb = _mb((llm.size_bytes / (1024 * 1024)) if llm else 0)
    cuda_needed = advice == "needs_runtime"
    cuda_mb = 1800 if cuda_needed else 0
    total_mb = 0
    if cuda_needed:
        total_mb += cuda_mb
    if not whisper_ready:
        total_mb += whisper_mb
    if not llm_ready:
        total_mb += llm_mb
    return {
        "whisperModel": model,
        "whisperLabel": WHISPER_LABELS.get(model, model),
        "whisperMb": whisper_mb,
        "whisperReady": bool(whisper_ready),
        "profile": PROFILE_FOR_MODEL.get(model, "balanced"),
        "device": device,
        "deviceLabel": {
            "cuda": "Видеокарта (CUDA)",
            "cpu": "Процессор (CPU)",
            "auto": "Авто",
        }.get(device, device),
        "useGpu": device in ("cuda", "auto") and advice in ("ready", "needs_runtime"),
        "cudaNeeded": cuda_needed,
        "cudaMb": cuda_mb,
        "llmId": llm_id,
        "llmLabel": llm.label if llm else llm_id,
        "llmMb": llm_mb,
        "llmReady": bool(llm_ready),
        "downloadLlm": not llm_ready,
        "downloadWhisper": not whisper_ready,
        "totalMb": total_mb,
        "computeHint": str(hardware.get("computeHint") or ""),
        "gpuLabel": str(hardware.get("gpuLabel") or hardware.get("gpuName") or ""),
        "technologies": technology_cards(hardware),
    }


def build_steps(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Упорядоченные шаги выполнения по выбранному брифингу."""

    steps: list[dict[str, Any]] = [
        {
            "id": "settings",
            "title": "Настройки",
            "detail": "Применяем профиль под это устройство",
            "weight": 5,
        }
    ]
    if briefing.get("useGpu") and briefing.get("cudaNeeded"):
        steps.append(
            {
                "id": "cuda",
                "title": "CUDA runtime",
                "detail": "Пакеты ускорения Whisper для NVIDIA",
                "weight": 25,
            }
        )
    if briefing.get("downloadWhisper"):
        label = briefing.get("whisperLabel") or briefing.get("whisperModel")
        steps.append(
            {
                "id": "whisper",
                "title": str(label),
                "detail": f"Модель распознавания · ~{int(briefing.get('whisperMb') or 0)} МБ",
                "weight": 40,
            }
        )
    else:
        steps.append(
            {
                "id": "whisper",
                "title": str(briefing.get("whisperLabel") or "Whisper"),
                "detail": "Уже в кеше · прогрев",
                "weight": 15,
            }
        )
    if briefing.get("downloadLlm"):
        steps.append(
            {
                "id": "llm",
                "title": str(briefing.get("llmLabel") or "Ассистент"),
                "detail": f"Языковая модель · ~{int(briefing.get('llmMb') or 0)} МБ",
                "weight": 30,
            }
        )
    return steps


def merge_briefing(base: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Применить правки с экрана брифинга, сохранив оценки размеров."""

    result = dict(base)
    data = dict(overrides or {})
    model = str(data.get("whisperModel") or result.get("whisperModel") or "small")
    if model not in WHISPER_DOWNLOAD_MB:
        model = str(result.get("whisperModel") or "small")
    result["whisperModel"] = model
    result["whisperLabel"] = WHISPER_LABELS.get(model, model)
    result["whisperMb"] = _mb(WHISPER_DOWNLOAD_MB.get(model))
    result["profile"] = PROFILE_FOR_MODEL.get(model, "balanced")

    if "useGpu" in data:
        result["useGpu"] = bool(data["useGpu"])
    if "downloadLlm" in data:
        result["downloadLlm"] = bool(data["downloadLlm"])
    if "downloadWhisper" in data:
        result["downloadWhisper"] = bool(data["downloadWhisper"])

    llm_id = str(data.get("llmId") or result.get("llmId") or "")
    if llm_id in MODELS_BY_ID:
        llm = MODELS_BY_ID[llm_id]
        result["llmId"] = llm.id
        result["llmLabel"] = llm.label
        result["llmMb"] = _mb(llm.size_bytes / (1024 * 1024))

    if result.get("useGpu"):
        advice_needed = bool(result.get("cudaNeeded"))
        result["device"] = "cuda" if not advice_needed else "auto"
    else:
        result["device"] = "cpu"
    result["deviceLabel"] = {
        "cuda": "Видеокарта (CUDA)",
        "cpu": "Процессор (CPU)",
        "auto": "Авто",
    }.get(str(result["device"]), str(result["device"]))

    total = 0
    if result.get("useGpu") and result.get("cudaNeeded"):
        total += int(result.get("cudaMb") or 0)
    if result.get("downloadWhisper"):
        total += int(result.get("whisperMb") or 0)
    if result.get("downloadLlm"):
        total += int(result.get("llmMb") or 0)
    result["totalMb"] = total
    return result


__all__ = [
    "PROFILE_FOR_MODEL",
    "WHISPER_DOWNLOAD_MB",
    "WHISPER_LABELS",
    "build_briefing",
    "build_steps",
    "merge_briefing",
    "recommend_device",
    "recommend_llm_id",
    "recommended_whisper",
    "technology_cards",
]
