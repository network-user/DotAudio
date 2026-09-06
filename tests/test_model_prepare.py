from __future__ import annotations

import sys
from types import SimpleNamespace

from dotaudio.engine import Engine, RecognitionConfig


def test_prepare_uses_local_model_cache_and_reports_ready(monkeypatch) -> None:
    loaded: list[tuple[str, str, str]] = []

    def model(name, *, device, compute_type):
        loaded.append((name, device, compute_type))
        return object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    events: list[str] = []
    device = Engine().prepare(RecognitionConfig(model="tiny", device="cpu"), events.append)
    assert device == "cpu"
    assert events == ["loading_model", "model_ready"]
    assert loaded == [("tiny", "cpu", "int8")]


def test_prepare_leaves_remote_model_to_server() -> None:
    events: list[str] = []
    assert Engine().prepare(RecognitionConfig(backend="remote"), events.append) == "remote"
    assert events == ["remote_model_managed_by_server"]
