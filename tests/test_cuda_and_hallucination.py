"""Tests for Whisper hallucination filtering and CUDA runtime helpers."""

from __future__ import annotations

from dotaudio.cuda_runtime import compute_advice, packages_present
from dotaudio.hallucination import looks_invented
from dotaudio.hardware import VENDOR_AMD, VENDOR_NVIDIA, GpuDevice, HardwareProfile


def test_looks_invented_drops_youtube_credits() -> None:
    assert looks_invented("Субтитры создавал DimaTorzok")
    assert looks_invented("Продолжение следует…")
    assert looks_invented("Thanks for watching!")
    assert not looks_invented("Привет, как дела")


def test_looks_invented_confidence_gate() -> None:
    assert looks_invented("шум", no_speech_prob=0.9, avg_logprob=-1.2)
    assert not looks_invented("нормальная фраза", no_speech_prob=0.1, avg_logprob=-0.3)


def test_compute_advice_needs_runtime_when_nvidia_without_cuda() -> None:
    profile = HardwareProfile(
        threads=8,
        ram_gb=16.0,
        gpus=(
            GpuDevice(0, "NVIDIA GeForce RTX 3060", vendor=VENDOR_NVIDIA, vram_mb=12288),
        ),
        cuda_runtime_devices=0,
    )
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "needs_runtime"
    assert advice["computeAction"] == "setup_gpu"
    assert advice["nvidiaPresent"] is True
    assert advice["cudaReady"] is False


def test_compute_advice_other_gpu_stays_on_cpu() -> None:
    profile = HardwareProfile(
        threads=8,
        gpus=(GpuDevice(0, "AMD Radeon RX 6800", vendor=VENDOR_AMD, vram_mb=16384),),
        cuda_runtime_devices=0,
    )
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "other_gpu"
    assert advice["computeAction"] == ""


def test_packages_present_returns_mapping() -> None:
    present = packages_present()
    assert set(present) >= {
        "nvidia-cublas-cu12",
        "nvidia-cuda-runtime-cu12",
        "nvidia-cudnn-cu12",
        "nvidia-cuda-nvrtc-cu12",
    }
