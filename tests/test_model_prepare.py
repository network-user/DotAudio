from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np

from dotaudio.engine import Engine, RecognitionConfig


def test_prepare_uses_local_model_cache_and_reports_ready(monkeypatch) -> None:
    loaded: list[tuple[str, str, str]] = []

    def model(name, *, device, compute_type, cpu_threads):
        assert 1 <= cpu_threads <= 4
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


def test_prepare_warms_live_decoder_when_requested(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeModel:
        def transcribe(self, source, **kwargs):
            calls.append({"source": source, **kwargs})
            return iter(()), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    device = Engine().prepare(
        RecognitionConfig(model="tiny", device="cpu", live_stream=True)
    )
    assert device == "cpu"
    assert len(calls) == 1
    assert isinstance(calls[0]["source"], np.ndarray)
    assert calls[0]["beam_size"] == 1
    assert calls[0]["without_timestamps"] is True


def test_prepare_live_falls_back_to_cpu_when_cuda_warmup_fails(monkeypatch) -> None:
    created: list[str] = []

    class FakeModel:
        def __init__(self, device: str) -> None:
            self.device = device

        def transcribe(self, _source, **_kwargs):
            if self.device == "cuda":
                raise RuntimeError("cublas runtime failure")
            return iter(()), object()

    def model(_name, *, device, compute_type, cpu_threads):
        assert 1 <= cpu_threads <= 4
        del compute_type
        created.append(device)
        return FakeModel(device)

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=model),
    )
    events: list[str] = []
    engine = Engine()

    device = engine.prepare(
        RecognitionConfig(device="auto", live_stream=True), events.append
    )

    assert device == "cpu"
    assert created == ["cuda", "cpu"]
    assert events == [
        "loading_model",
        "gpu_unavailable_falling_back_cpu",
        "model_ready",
    ]


def test_download_tracker_reports_real_bytes_and_speed(monkeypatch) -> None:
    from dotaudio.engine import DownloadTracker

    ticks = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0])
    monkeypatch.setattr("dotaudio.engine.time.monotonic", lambda: next(ticks, 2.0))
    tracker = DownloadTracker(lambda _info: None, interval=0.0)
    mb = 1048576

    tracker.register(10 * mb, 0)
    tracker.add(2 * mb)
    mid = tracker._snapshot()
    assert mid["phase"] == "download"
    assert mid["percent"] == 20.0
    assert mid["received_mb"] == 2.0
    assert mid["total_mb"] == 10.0

    # Закрытый бар добирает остаток: файл мог уже лежать в кеше.
    tracker.finish(10 * mb, 2 * mb)
    done = tracker._snapshot()
    assert done["percent"] == 100.0
    # Скорость по скользящему окну: 10 МБ за 2 с между первым и последним
    # сэмплом фальшивых часов.
    assert done["speed_mb_s"] == 5.0


def test_prepare_reports_download_progress_without_network(monkeypatch) -> None:
    # Модель уже в кеше: движок не должен трогать сеть и что-то отчитывать.
    events: list[str] = []
    progress: list[dict] = []
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *_a, **_k: object()))
    monkeypatch.setattr(
        Engine, "disk_status", staticmethod(lambda _name: {"ready": True, "bytes": 10, "message": "", "path": "", "model": _name})
    )
    device = Engine().prepare(
        RecognitionConfig(model="tiny", device="cpu"), events.append, progress.append
    )
    assert device == "cpu"
    assert progress == []
