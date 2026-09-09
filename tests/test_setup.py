"""Планирование первой настройки устройства."""

from __future__ import annotations

from dotaudio.setup import (
    build_briefing,
    build_steps,
    merge_briefing,
    recommend_device,
    recommended_whisper,
)


def test_recommended_whisper_prefers_small_on_cpu():
    assert recommended_whisper({"threads": 8, "cuda_devices": 0}) == "small"
    assert recommended_whisper({"threads": 2, "cuda_devices": 0}) == "base"
    assert recommended_whisper({"threads": 1, "cuda_devices": 0}) == "tiny"


def test_recommended_whisper_uses_gpu_vram():
    assert recommended_whisper({"threads": 8, "cuda_devices": 1, "gpuVramGb": 8}) == "medium"
    assert recommended_whisper({"threads": 8, "cuda_devices": 1, "gpuVramGb": 4}) == "small"


def test_recommend_device_from_advice():
    assert recommend_device({"computeAdvice": "ready", "cuda_devices": 1}) == "cuda"
    assert recommend_device({"computeAdvice": "needs_runtime", "cuda_devices": 0}) == "auto"
    assert recommend_device({"computeAdvice": "cpu_only", "cuda_devices": 0}) == "cpu"


def test_build_briefing_and_steps_include_cuda_when_needed():
    hardware = {
        "threads": 12,
        "ram_gb": 32,
        "cuda_devices": 0,
        "computeAdvice": "needs_runtime",
        "computeHint": "Нужен runtime",
        "gpuLabel": "RTX 3060",
        "gpuName": "RTX 3060",
        "gpus": [
            {
                "index": 0,
                "name": "RTX 3060",
                "vendor": "nvidia",
                "vramMb": 12288,
                "integrated": False,
                "source": "test",
            }
        ],
        "platform": "Windows",
        "notes": [],
    }
    briefing = build_briefing(hardware, whisper_ready=False, llm_ready=False)
    assert briefing["cudaNeeded"] is True
    assert briefing["useGpu"] is True
    assert briefing["downloadWhisper"] is True
    assert briefing["downloadLlm"] is True
    assert briefing["totalMb"] > 0
    steps = build_steps(briefing)
    ids = [step["id"] for step in steps]
    assert ids[0] == "settings"
    assert "cuda" in ids
    assert "whisper" in ids
    assert "llm" in ids


def test_merge_briefing_can_disable_gpu_and_llm():
    hardware = {
        "threads": 8,
        "ram_gb": 16,
        "cuda_devices": 0,
        "computeAdvice": "cpu_only",
        "gpus": [],
        "platform": "Windows",
        "notes": [],
    }
    base = build_briefing(hardware, whisper_ready=True, llm_ready=False)
    merged = merge_briefing(base, {"useGpu": False, "downloadLlm": False, "downloadWhisper": False})
    assert merged["device"] == "cpu"
    assert merged["downloadLlm"] is False
    steps = build_steps(merged)
    ids = [step["id"] for step in steps]
    assert "cuda" not in ids
    assert "llm" not in ids
    assert "whisper" in ids  # прогрев даже из кеша
