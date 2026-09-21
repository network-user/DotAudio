from types import SimpleNamespace

import pytest

from dotaudio.engine import Engine, ModelPreflightError


def _patch_probe(monkeypatch: pytest.MonkeyPatch, hardware: dict) -> None:
    monkeypatch.setattr(
        "dotaudio.hardware.probe",
        lambda **_kwargs: SimpleNamespace(as_dict=lambda: hardware),
    )


def test_preflight_ignores_transient_low_cpu_free_memory_with_total_headroom(monkeypatch) -> None:
    _patch_probe(
        monkeypatch,
        {"ram_gb": 16.0, "ram_available_gb": 1.0, "cuda_devices": 0},
    )

    assert Engine._preflight_model("base", "cpu", "int8") is None


def test_preflight_blocks_cpu_when_total_memory_is_below_model_budget(monkeypatch) -> None:
    _patch_probe(
        monkeypatch,
        {"ram_gb": 1.5, "ram_available_gb": 1.0, "cuda_devices": 0},
    )

    with pytest.raises(ModelPreflightError, match="ОЗУ"):
        Engine._preflight_model("base", "cpu", "int8")


def test_preflight_keeps_cuda_vram_as_a_hard_gate(monkeypatch) -> None:
    _patch_probe(
        monkeypatch,
        {
            "ram_gb": 16.0,
            "ram_available_gb": 1.0,
            "cuda_devices": 1,
            "cudaVramGb": 2.0,
            "cudaVramFreeGb": 0.5,
        },
    )

    with pytest.raises(ModelPreflightError, match="VRAM"):
        Engine._preflight_model("small", "cuda", "int8")
