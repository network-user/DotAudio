"""Планирование первой настройки устройства (без Qt).

Собирает короткий план под измеренное железо: что поставить, что скачать,
какие настройки применить. Сама загрузка и pip живут в ``setup_controller``.
"""

from __future__ import annotations

from typing import Any

from dotaudio.adapt import (
    PROFILE_FOR_MODEL,
    integrated_whisper_hint,
    plan_whisper,
    recommend_device,
    recommended_whisper,
)
from dotaudio.llm import MODELS_BY_ID, get_model, recommend_model
from dotaudio.nemo_diarize import MODEL_DOWNLOAD_MB, RUNTIME_DOWNLOAD_MB
from dotaudio.tools_ffmpeg import FFMPEG_DOWNLOAD_MB
from dotaudio.tools_ffmpeg import ffmpeg_available as _ffmpeg_available

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


def _mb(value: float | int | None) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def ffmpeg_available(data_dir=None) -> bool:
    """FFmpeg в PATH или портативная копия в data_dir."""

    return _ffmpeg_available(data_dir)


def can_skip_setup(briefing: dict[str, Any]) -> bool:
    """Всё нужное уже на диске: мастер можно не показывать.

    CUDA runtime, если ещё нужен, блокирует пропуск. Whisper, LLM, NeMo и
    FFmpeg должны быть готовы (или явно отключены в брифинге).
    """

    if briefing.get("useGpu") and briefing.get("cudaNeeded"):
        return False
    if briefing.get("downloadWhisper"):
        return False
    if briefing.get("downloadLlm"):
        return False
    if briefing.get("downloadNemo"):
        return False
    if briefing.get("downloadFfmpeg"):
        return False
    # Рекомендованный Whisper хотя бы в кеше.
    if not briefing.get("whisperReady"):
        return False
    return True


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


def technology_cards(
    hardware: dict,
    *,
    nemo_ready: bool = False,
    ffmpeg_ready: bool = False,
) -> list[dict[str, Any]]:
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
    elif advice == "integrated":
        cards.append(
            {
                "id": "gpu",
                "title": "Встроенная графика",
                "detail": gpu_label or "Iris/UHD · Whisper на CPU",
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
            "id": "nemo",
            "title": "NVIDIA NeMo",
            "detail": (
                "голоса в транскрибации · готово"
                if nemo_ready
                else "голоса в транскрибации · рантайм + Sortformer"
            ),
            "state": "ready" if nemo_ready else "needed",
        }
    )
    cards.append(
        {
            "id": "ffmpeg",
            "title": "FFmpeg",
            "detail": (
                "в PATH или портативный"
                if ffmpeg_ready
                else "нужен для караоке и эфиров"
            ),
            "state": "ready" if ffmpeg_ready else "needed",
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
    nemo_ready: bool = False,
    ffmpeg_ready: bool | None = None,
) -> dict[str, Any]:
    """Рекомендации и оценки размера для экрана брифинга."""

    plan = plan_whisper(hardware)
    model = plan.model
    device = plan.device
    llm_id = recommend_llm_id(hardware)
    llm = get_model(llm_id)
    advice = str(hardware.get("computeAdvice") or "")
    whisper_mb = _mb(WHISPER_DOWNLOAD_MB.get(model))
    llm_mb = _mb((llm.size_bytes / (1024 * 1024)) if llm else 0)
    cuda_needed = advice == "needs_runtime"
    cuda_mb = 1800 if cuda_needed else 0
    prefer_cuda = advice in {"ready", "needs_runtime"} or int(hardware.get("cuda_devices") or 0) > 0
    nemo_mb = 0 if nemo_ready else (RUNTIME_DOWNLOAD_MB + MODEL_DOWNLOAD_MB)
    if ffmpeg_ready is None:
        ffmpeg_ready = ffmpeg_available()
    ffmpeg_mb = 0 if ffmpeg_ready else FFMPEG_DOWNLOAD_MB
    total_mb = 0
    if cuda_needed:
        total_mb += cuda_mb
    if not whisper_ready:
        total_mb += whisper_mb
    if not llm_ready:
        total_mb += llm_mb
    if not nemo_ready:
        total_mb += nemo_mb
    if not ffmpeg_ready:
        total_mb += ffmpeg_mb
    hint = str(hardware.get("computeHint") or "") or integrated_whisper_hint(hardware) or plan.note
    return {
        "whisperModel": model,
        "whisperLabel": WHISPER_LABELS.get(model, model),
        "whisperMb": whisper_mb,
        "whisperReady": bool(whisper_ready),
        "profile": plan.profile,
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
        "nemoReady": bool(nemo_ready),
        "downloadNemo": not nemo_ready,
        "nemoMb": nemo_mb if not nemo_ready else 0,
        "nemoPreferCuda": prefer_cuda,
        "ffmpegReady": bool(ffmpeg_ready),
        "downloadFfmpeg": not bool(ffmpeg_ready),
        "ffmpegMb": ffmpeg_mb,
        "totalMb": total_mb,
        "computeHint": hint,
        "gpuLabel": str(hardware.get("gpuLabel") or hardware.get("gpuName") or ""),
        "tier": plan.tier,
        "tierLabel": plan.label,
        "liveGreedyFinals": plan.live_greedy_finals,
        "technologies": technology_cards(
            hardware,
            nemo_ready=bool(nemo_ready),
            ffmpeg_ready=bool(ffmpeg_ready),
        ),
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
                "weight": 20,
            }
        )
    if briefing.get("downloadWhisper"):
        label = briefing.get("whisperLabel") or briefing.get("whisperModel")
        steps.append(
            {
                "id": "whisper",
                "title": str(label),
                "detail": f"Модель распознавания · ~{int(briefing.get('whisperMb') or 0)} МБ",
                "weight": 30,
            }
        )
    else:
        steps.append(
            {
                "id": "whisper",
                "title": str(briefing.get("whisperLabel") or "Whisper"),
                "detail": "Уже в кеше · прогрев",
                "weight": 12,
            }
        )
    if briefing.get("downloadNemo"):
        steps.append(
            {
                "id": "nemo",
                "title": "NVIDIA NeMo",
                "detail": (
                    f"Рантайм + Sortformer · ~{int(briefing.get('nemoMb') or 0)} МБ"
                ),
                "weight": 25,
            }
        )
    elif briefing.get("nemoReady"):
        steps.append(
            {
                "id": "nemo",
                "title": "NVIDIA NeMo",
                "detail": "Уже установлен · сверяем модель Sortformer",
                "weight": 8,
            }
        )
    if briefing.get("downloadLlm"):
        steps.append(
            {
                "id": "llm",
                "title": str(briefing.get("llmLabel") or "Ассистент"),
                "detail": f"Языковая модель · ~{int(briefing.get('llmMb') or 0)} МБ",
                "weight": 20,
            }
        )
    if briefing.get("downloadFfmpeg"):
        steps.append(
            {
                "id": "ffmpeg",
                "title": "FFmpeg",
                "detail": f"Портативная сборка · ~{int(briefing.get('ffmpegMb') or 0)} МБ",
                "weight": 12,
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
    result["liveGreedyFinals"] = result["profile"] == "fast"
    if "liveGreedyFinals" in data:
        result["liveGreedyFinals"] = bool(data["liveGreedyFinals"])

    if "useGpu" in data:
        result["useGpu"] = bool(data["useGpu"])
    if "downloadLlm" in data:
        result["downloadLlm"] = bool(data["downloadLlm"])
    if "downloadWhisper" in data:
        result["downloadWhisper"] = bool(data["downloadWhisper"])
    if "downloadNemo" in data:
        result["downloadNemo"] = bool(data["downloadNemo"])
    if "downloadFfmpeg" in data:
        result["downloadFfmpeg"] = bool(data["downloadFfmpeg"])

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

    if result.get("downloadNemo") and not result.get("nemoReady"):
        result["nemoMb"] = RUNTIME_DOWNLOAD_MB + MODEL_DOWNLOAD_MB
    elif result.get("downloadNemo"):
        result["nemoMb"] = MODEL_DOWNLOAD_MB
    else:
        result["nemoMb"] = 0

    if result.get("downloadFfmpeg") and not result.get("ffmpegReady"):
        result["ffmpegMb"] = FFMPEG_DOWNLOAD_MB
    else:
        result["ffmpegMb"] = 0

    total = 0
    if result.get("useGpu") and result.get("cudaNeeded"):
        total += int(result.get("cudaMb") or 0)
    if result.get("downloadWhisper"):
        total += int(result.get("whisperMb") or 0)
    if result.get("downloadNemo"):
        total += int(result.get("nemoMb") or 0)
    if result.get("downloadLlm"):
        total += int(result.get("llmMb") or 0)
    if result.get("downloadFfmpeg"):
        total += int(result.get("ffmpegMb") or 0)
    result["totalMb"] = total
    return result


__all__ = [
    "PROFILE_FOR_MODEL",
    "WHISPER_DOWNLOAD_MB",
    "WHISPER_LABELS",
    "build_briefing",
    "build_steps",
    "can_skip_setup",
    "ffmpeg_available",
    "merge_briefing",
    "plan_whisper",
    "recommend_device",
    "recommend_llm_id",
    "recommended_whisper",
    "technology_cards",
]
