"""Планирование первой настройки устройства."""

from __future__ import annotations

from dotaudio.setup import (
    build_briefing,
    build_steps,
    can_skip_setup,
    merge_briefing,
    recommend_device,
    recommended_whisper,
)


def test_recommended_whisper_prefers_small_on_cpu():
    assert recommended_whisper({"threads": 8, "cuda_devices": 0}) == "small"
    assert recommended_whisper({"threads": 4, "cuda_devices": 0}) == "base"
    assert recommended_whisper({"threads": 2, "cuda_devices": 0}) == "base"
    assert recommended_whisper({"threads": 1, "cuda_devices": 0}) == "tiny"


def test_recommended_whisper_uses_gpu_vram():
    assert recommended_whisper({"threads": 8, "cuda_devices": 1, "gpuVramGb": 8}) == "medium"
    assert recommended_whisper({"threads": 8, "cuda_devices": 1, "gpuVramGb": 4}) == "small"


def test_recommend_device_from_advice():
    assert recommend_device({"computeAdvice": "ready", "cuda_devices": 1}) == "cuda"
    assert recommend_device({"computeAdvice": "needs_runtime", "cuda_devices": 0}) == "auto"
    assert recommend_device({"computeAdvice": "cpu_only", "cuda_devices": 0}) == "cpu"


def test_build_briefing_includes_ffmpeg_download_when_missing():
    hardware = {
        "threads": 12,
        "ram_gb": 32,
        "cuda_devices": 0,
        "computeAdvice": "cpu_only",
        "gpus": [],
        "platform": "Windows",
        "notes": [],
    }
    briefing = build_briefing(
        hardware,
        whisper_ready=True,
        llm_ready=True,
        nemo_ready=True,
        ffmpeg_ready=False,
        system_audio_ready=True,
    )
    assert briefing["downloadFfmpeg"] is True
    assert briefing["ffmpegMb"] > 0
    assert "ffmpeg" in [step["id"] for step in build_steps(briefing)]


def test_build_briefing_exposes_macos_system_audio_hint(monkeypatch):
    monkeypatch.setattr("dotaudio.capture.system_audio_supported", lambda: False)
    monkeypatch.setattr(
        "dotaudio.capture.system_audio_hint",
        lambda: "BlackHole",
    )
    hardware = {
        "threads": 8,
        "ram_gb": 16,
        "cuda_devices": 0,
        "computeAdvice": "cpu_only",
        "gpus": [],
        "platform": "darwin",
        "notes": [],
    }
    briefing = build_briefing(
        hardware,
        whisper_ready=True,
        llm_ready=True,
        nemo_ready=True,
        ffmpeg_ready=True,
        system_audio_ready=False,
    )
    assert briefing["systemAudioReady"] is False
    assert "BlackHole" in briefing["systemAudioHint"]


def test_can_skip_setup_when_everything_ready():
    hardware = {
        "threads": 8,
        "ram_gb": 16,
        "cuda_devices": 1,
        "computeAdvice": "ready",
        "gpus": [],
        "platform": "Windows",
        "notes": [],
    }
    briefing = build_briefing(
        hardware,
        whisper_ready=True,
        llm_ready=True,
        nemo_ready=True,
        ffmpeg_ready=True,
    )
    assert can_skip_setup(briefing) is True


def test_cannot_skip_when_cuda_runtime_needed():
    hardware = {
        "threads": 12,
        "ram_gb": 32,
        "cuda_devices": 0,
        "computeAdvice": "needs_runtime",
        "gpuLabel": "RTX",
        "gpus": [{"index": 0, "name": "RTX", "vendor": "nvidia", "vramMb": 8192, "integrated": False, "source": "t"}],
        "platform": "Windows",
        "notes": [],
    }
    briefing = build_briefing(
        hardware,
        whisper_ready=True,
        llm_ready=True,
        nemo_ready=True,
        ffmpeg_ready=True,
    )
    assert briefing["cudaNeeded"] is True
    assert can_skip_setup(briefing) is False


def test_merge_briefing_can_disable_ffmpeg():
    hardware = {
        "threads": 8,
        "ram_gb": 16,
        "cuda_devices": 0,
        "computeAdvice": "cpu_only",
        "gpus": [],
        "platform": "Windows",
        "notes": [],
    }
    base = build_briefing(
        hardware,
        whisper_ready=True,
        llm_ready=True,
        nemo_ready=True,
        ffmpeg_ready=False,
    )
    merged = merge_briefing(base, {"downloadFfmpeg": False})
    assert merged["downloadFfmpeg"] is False
    assert "ffmpeg" not in [step["id"] for step in build_steps(merged)]
    # Без FFmpeg пропуск всё равно возможен, если остальное готово.
    assert can_skip_setup(merged) is True


def test_build_briefing_and_steps_include_cuda_and_nemo():
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
    briefing = build_briefing(
        hardware,
        whisper_ready=False,
        llm_ready=False,
        nemo_ready=False,
        ffmpeg_ready=True,
    )
    assert briefing["cudaNeeded"] is True
    assert briefing["downloadNemo"] is True
    steps = build_steps(briefing)
    ids = [step["id"] for step in steps]
    assert "cuda" in ids
    assert "nemo" in ids
    assert "whisper" in ids
