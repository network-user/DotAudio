"""Тесты опроса CUDA runtime и рекомендаций GPU."""

from __future__ import annotations

from dotaudio.controller import recommended_model
from dotaudio.cuda_runtime import compute_advice, missing_packages, packages_present
from dotaudio.hardware import VENDOR_AMD, VENDOR_NVIDIA, GpuDevice, HardwareProfile, reset_cache


def test_packages_present_keys() -> None:
    status = packages_present()
    assert set(status) == {
        "nvidia-cublas-cu12",
        "nvidia-cuda-runtime-cu12",
        "nvidia-cudnn-cu12",
        "nvidia-cuda-nvrtc-cu12",
    }
    assert missing_packages() == [name for name, ready in status.items() if not ready]


def test_compute_advice_cpu_only() -> None:
    profile = HardwareProfile(threads=8, ram_gb=16.0, gpus=(), cuda_runtime_devices=0)
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "cpu_only"
    assert advice["computeAction"] == ""
    assert advice["cudaReady"] is False


def test_compute_advice_nvidia_needs_runtime() -> None:
    gpu = GpuDevice(index=0, name="NVIDIA GeForce RTX 3060", vendor=VENDOR_NVIDIA, vram_mb=12288)
    profile = HardwareProfile(threads=12, ram_gb=32.0, gpus=(gpu,), cuda_runtime_devices=0)
    advice = compute_advice(profile)
    assert advice["nvidiaPresent"] is True
    assert advice["computeAdvice"] == "needs_runtime"
    assert advice["computeAction"] == "setup_gpu"
    assert advice["manualSteps"]
    assert "pip install" in advice["installCommand"]


def test_compute_advice_cuda_ready() -> None:
    gpu = GpuDevice(index=0, name="NVIDIA GeForce RTX 4070", vendor=VENDOR_NVIDIA, vram_mb=12288)
    profile = HardwareProfile(threads=16, ram_gb=32.0, gpus=(gpu,), cuda_runtime_devices=1)
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "ready"
    assert advice["computeAction"] == "use_gpu"
    assert advice["manualSteps"] == []


def test_compute_advice_other_gpu() -> None:
    gpu = GpuDevice(index=0, name="AMD Radeon RX 6800", vendor=VENDOR_AMD, vram_mb=16384)
    profile = HardwareProfile(threads=8, ram_gb=16.0, gpus=(gpu,), cuda_runtime_devices=0)
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "other_gpu"
    assert advice["nvidiaPresent"] is False


def test_compute_advice_integrated_iris() -> None:
    from dotaudio.hardware import VENDOR_INTEL

    gpu = GpuDevice(
        index=0,
        name="Intel(R) Iris(R) Xe Graphics",
        vendor=VENDOR_INTEL,
        vram_mb=2048,
        integrated=True,
    )
    profile = HardwareProfile(threads=4, ram_gb=16.0, gpus=(gpu,), cuda_runtime_devices=0)
    advice = compute_advice(profile)
    assert advice["computeAdvice"] == "integrated"
    assert "Iris" in advice["computeHint"]
    assert advice["computeAction"] == ""
    assert recommended_model({"threads": 4, "ram_gb": 16.0, "cuda_devices": 0, "gpus": [gpu.as_dict()]}) == "base"


def test_recommended_model_prefers_medium_on_roomy_gpu() -> None:
    assert recommended_model({"threads": 8, "ram_gb": 32.0, "cuda_devices": 1, "gpuVramGb": 8.0}) == "medium"
    assert recommended_model({"threads": 8, "ram_gb": 16.0, "cuda_devices": 1, "gpuVramGb": 4.0}) == "small"
    assert recommended_model({"threads": 8, "ram_gb": 16.0, "cuda_devices": 0}) == "small"


def test_hardware_summary_includes_advice(monkeypatch) -> None:
    from dotaudio import controller
    from dotaudio.hardware import HardwareProfile

    reset_cache()
    gpu = GpuDevice(index=0, name="NVIDIA GeForce RTX 3060", vendor=VENDOR_NVIDIA, vram_mb=12288)

    def fake_probe(refresh: bool = False):
        del refresh
        return HardwareProfile(threads=12, ram_gb=32.0, gpus=(gpu,), cuda_runtime_devices=0)

    monkeypatch.setattr("dotaudio.hardware.probe", fake_probe)
    monkeypatch.setattr(controller, "hardware_summary", controller.hardware_summary)
    # hardware_summary импортирует probe внутри — патчим там же.
    monkeypatch.setattr("dotaudio.cuda_runtime.register_cuda_dll_directories", lambda: [])
    import dotaudio.hardware as hw

    monkeypatch.setattr(hw, "probe", fake_probe)
    summary = controller.hardware_summary(refresh=True)
    assert summary["nvidiaPresent"] is True
    assert summary["computeAdvice"] == "needs_runtime"
    assert summary["gpuName"] == "NVIDIA GeForce RTX 3060"
    assert summary["cuda_devices"] == 0
