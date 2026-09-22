from __future__ import annotations

import pytest

import dotaudio.hardware as hardware
from dotaudio.hardware import build_hardware_validation, validate_hardware


def _cuda_snapshot(*, ram_gb: float, vram_free_gb: float) -> dict:
    return {
        "ram_available_gb": ram_gb,
        "cuda_devices": 1,
        "gpus": [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 4060 Laptop GPU",
                "vendor": "nvidia",
                "vramMb": 8192,
                "vramFreeGb": vram_free_gb,
                "integrated": False,
            }
        ],
    }


def test_hardware_validation_reports_ready_for_known_fit() -> None:
    result = build_hardware_validation(
        "medium",
        _cuda_snapshot(ram_gb=12.0, vram_free_gb=7.0),
        device="cuda",
    )

    assert result.state == "ready"
    assert result.can_run is True
    assert result.device == "cuda"
    assert result.model_known is True
    assert result.available_memory_gb == 7.0
    assert result.required_vram_gb == 5.0
    assert result.required_ram_gb == 4.5
    assert result.as_dict()["status"] == "ready"
    assert result.as_dict()["availableVramGb"] == 7.0


def test_hardware_validation_uses_the_selected_gpu_not_the_best_gpu() -> None:
    snapshot = {
        "ram_available_gb": 16.0,
        "cuda_devices": 2,
        "gpus": [
            {
                "index": 0,
                "name": "NVIDIA GTX 1050 Ti",
                "vendor": "nvidia",
                "vramMb": 4096,
                "vramFreeGb": 0.5,
                "integrated": False,
            },
            {
                "index": 1,
                "name": "NVIDIA RTX 4060",
                "vendor": "nvidia",
                "vramMb": 8192,
                "vramFreeGb": 7.0,
                "integrated": False,
            },
        ],
    }

    selected_small = validate_hardware(
        "medium", snapshot, device="cuda", device_index=0
    )
    selected_large = validate_hardware(
        "medium", snapshot, device="cuda", device_index=1
    )

    assert selected_small.state == "fallback"
    assert selected_small.available_vram_gb == 0.5
    assert selected_small.device_index is None
    assert selected_large.state == "ready"
    assert selected_large.available_vram_gb == 7.0
    assert selected_large.device_index == 1


def test_hardware_validation_falls_back_to_cpu_when_vram_is_insufficient() -> None:
    result = validate_hardware(
        "medium",
        _cuda_snapshot(ram_gb=16.0, vram_free_gb=2.0),
        device="cuda",
    )

    assert result.state == "fallback"
    assert result.can_run is True
    assert result.requested_device == "cuda"
    assert result.device == "cpu"
    assert result.fallback_device == "cpu"
    assert result.available_memory_gb == 16.0
    assert result.required_memory_gb == pytest.approx(result.required_ram_gb)
    assert result.available_vram_gb == 2.0
    assert result.required_vram_gb == 5.0
    assert "fallback_cpu" in result.telemetry


def test_hardware_validation_is_unknown_for_incomplete_telemetry() -> None:
    result = validate_hardware(
        "medium",
        {
            "cuda_devices": 1,
            "gpus": [
                {
                    "name": "NVIDIA GeForce RTX 4060",
                    "vendor": "nvidia",
                    "vramMb": 8192,
                }
            ],
            "ram_gb": 16.0,
        },
        device="cuda",
    )

    assert result.state == "unknown"
    assert result.is_unknown is True
    assert result.can_run is False
    assert result.available_ram_gb is None
    assert result.available_vram_gb is None
    assert result.required_vram_gb == 5.0
    assert result.recommendations


def test_hardware_validation_keeps_unknown_for_custom_model_budget() -> None:
    result = validate_hardware(
        "my-local-whisper-model",
        _cuda_snapshot(ram_gb=32.0, vram_free_gb=12.0),
        device="cuda",
    )

    assert result.state == "unknown"
    assert result.model_known is False
    assert result.device == "cuda"
    assert result.required_memory_gb is None


def test_auto_hardware_validation_marks_cpu_fallback_when_cuda_is_missing() -> None:
    result = validate_hardware(
        "base",
        {
            "ram_available_gb": 8.0,
            "cuda_devices": 0,
            "gpus": [
                {
                    "name": "NVIDIA GeForce RTX 4060",
                    "vendor": "nvidia",
                    "vramMb": 8192,
                }
            ],
        },
        device="auto",
    )

    assert result.state == "fallback"
    assert result.device == "cpu"
    assert result.fallback_device == "cpu"
    assert result.cuda_runtime_available is False


def test_hardware_validation_does_not_probe_for_missing_telemetry(monkeypatch) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("validation must not probe or run inference")

    monkeypatch.setattr(hardware, "probe", fail_probe)

    result = validate_hardware("medium")

    assert result.state == "unknown"
    assert result.is_unknown is True
