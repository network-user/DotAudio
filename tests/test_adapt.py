"""Адаптация Whisper/Live под два целевых класса железа."""

from __future__ import annotations

from dotaudio.adapt import (
    classify_tier,
    live_cpu_threads,
    plan_whisper,
    recommend_device,
    recommended_whisper,
)
from dotaudio.cuda_runtime import compute_advice
from dotaudio.hardware import (
    VENDOR_INTEL,
    VENDOR_NVIDIA,
    GpuDevice,
    HardwareProfile,
)
from dotaudio.setup import build_briefing


def _rtx_3060_laptop(*, cuda_devices: int = 1) -> dict:
    """i5-12500H + RTX 3060 Laptop 6 ГБ + 16 ГБ ОЗУ (типичный dual-GPU)."""

    uhd = GpuDevice(
        index=0,
        name="Intel(R) UHD Graphics",
        vendor=VENDOR_INTEL,
        vram_mb=128,
        integrated=True,
        source="test",
    )
    rtx = GpuDevice(
        index=1,
        name="NVIDIA GeForce RTX 3060 Laptop GPU",
        vendor=VENDOR_NVIDIA,
        vram_mb=6144,
        integrated=False,
        source="test",
    )
    profile = HardwareProfile(
        threads=16,
        ram_gb=16.0,
        gpus=(uhd, rtx),
        platform="win32",
        cuda_runtime_devices=cuda_devices,
    )
    summary = profile.as_dict()
    summary.update(compute_advice(profile))
    return summary


def _surface_iris() -> dict:
    """Surface Laptop 4: Iris Xe ~2 ГБ shared, 4 потока, 16 ГБ ОЗУ."""

    iris = GpuDevice(
        index=0,
        name="Intel(R) Iris(R) Xe Graphics",
        vendor=VENDOR_INTEL,
        vram_mb=2048,
        integrated=True,
        source="test",
    )
    profile = HardwareProfile(
        threads=4,
        ram_gb=16.0,
        gpus=(iris,),
        platform="win32",
        cuda_runtime_devices=0,
    )
    summary = profile.as_dict()
    summary.update(compute_advice(profile))
    return summary


def test_rtx_laptop_prefers_dedicated_gpu_and_medium() -> None:
    hardware = _rtx_3060_laptop(cuda_devices=1)
    assert hardware["hasDedicatedGpu"] is True
    assert "3060" in str(hardware["gpuName"])
    assert hardware["computeAdvice"] == "ready"
    plan = plan_whisper(hardware)
    assert plan.tier == "cuda_strong"
    assert plan.model == "medium"
    assert plan.profile == "balanced"
    assert plan.device == "cuda"
    assert plan.live_greedy_finals is True
    assert recommended_whisper(hardware) == "medium"


def test_rtx_laptop_without_runtime_still_plans_medium() -> None:
    hardware = _rtx_3060_laptop(cuda_devices=0)
    assert hardware["computeAdvice"] == "needs_runtime"
    plan = plan_whisper(hardware)
    assert plan.tier == "cuda_pending_strong"
    assert plan.model == "medium"
    assert plan.device == "auto"
    briefing = build_briefing(hardware)
    assert briefing["whisperModel"] == "medium"
    assert briefing["liveGreedyFinals"] is True
    assert briefing["cudaNeeded"] is True


def test_surface_iris_uses_fast_cpu_plan() -> None:
    hardware = _surface_iris()
    assert hardware["hasDedicatedGpu"] is False
    assert hardware["computeAdvice"] == "integrated"
    assert "Iris" in hardware["computeHint"]
    plan = plan_whisper(hardware)
    assert plan.tier == "cpu_weak"
    assert plan.model == "base"
    assert plan.profile == "fast"
    assert plan.device == "cpu"
    assert plan.live_greedy_finals is True
    briefing = build_briefing(hardware)
    assert briefing["whisperModel"] == "base"
    assert briefing["profile"] == "fast"
    assert briefing["liveGreedyFinals"] is True
    assert briefing["useGpu"] is False
    cards = {card["id"]: card for card in briefing["technologies"]}
    assert cards["gpu"]["title"] == "Встроенная графика"


def test_live_cpu_threads_leave_core_on_weak_cpu() -> None:
    assert live_cpu_threads(16) == 4
    assert live_cpu_threads(8) == 4
    assert live_cpu_threads(4) == 3
    assert live_cpu_threads(2) == 1
    assert live_cpu_threads(1) == 1


def test_classify_strong_cpu_without_gpu() -> None:
    assert classify_tier({"threads": 12, "cuda_devices": 0, "gpus": []}) == "cpu_strong"
    assert recommend_device({"computeAdvice": "cpu_only", "cuda_devices": 0}) == "cpu"
    assert recommended_whisper({"threads": 12, "cuda_devices": 0}) == "small"
