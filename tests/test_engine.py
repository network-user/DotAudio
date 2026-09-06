from __future__ import annotations

import sys
from threading import Event
from types import SimpleNamespace

import numpy as np

from dotaudio.engine import Engine, RecognitionConfig


class _Segment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


def test_local_engine_caches_model_and_normalises_segments(monkeypatch) -> None:
    created: list[tuple[str, str, str]] = []

    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["vad_filter"] is True
            assert kwargs["beam_size"] == 5
            assert kwargs["word_timestamps"] is True
            return iter([_Segment(0, 0.5, " first "), _Segment(0.5, 1, "")]), object()

    def model(name: str, *, device: str, compute_type: str):
        created.append((name, device, compute_type))
        return FakeModel()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    engine = Engine()
    config = RecognitionConfig(device="cpu")
    assert engine.transcribe(np.zeros(1600, dtype=np.float32), config) == [
        {"start": 0.0, "end": 0.5, "text": "first"}
    ]
    engine.transcribe(np.zeros(1600, dtype=np.float32), config)
    assert created == [("base", "cpu", "int8")]


def test_local_engine_cancellation_stops_between_segments(monkeypatch) -> None:
    cancel = Event()

    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter([_Segment(0, 1, "one"), _Segment(1, 2, "two")]), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    seen: list[dict] = []

    def receive(segment: dict) -> None:
        seen.append(segment)
        cancel.set()

    result = Engine().transcribe(np.zeros(1600), RecognitionConfig(device="cpu"), cancel, receive)
    assert result == [{"start": 0.0, "end": 1.0, "text": "one"}]
    assert seen == result


def test_auto_device_retries_cuda_runtime_error_on_cpu(monkeypatch) -> None:
    attempts: list[tuple[str, str]] = []

    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter([_Segment(0, 1, "ready")]), object()

    def model(_name: str, *, device: str, compute_type: str):
        attempts.append((device, compute_type))
        if device == "cuda":
            raise RuntimeError("could not load cublas64_12.dll")
        return FakeModel()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    assert Engine().transcribe(np.zeros(1600), RecognitionConfig()) == [
        {"start": 0.0, "end": 1.0, "text": "ready"}
    ]
    assert attempts == [("cuda", "float16"), ("cpu", "int8")]


def test_remote_backend_posts_form_and_returns_segments(monkeypatch) -> None:
    calls: dict = {}

    class Response:
        status_code = 200

        def iter_bytes(self):
            yield b'{"segments":[{"start":1,"end":2,"text":"hello"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, method, url, **kwargs):
            calls.update(method=method, url=url, **kwargs)
            return Response()

    fake_httpx = SimpleNamespace(Client=Client, Timeout=lambda *args, **kwargs: object())
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    result = Engine().transcribe(
        np.zeros(1600), RecognitionConfig(backend="remote", language="ru")
    )
    assert result == [{"start": 1.0, "end": 2.0, "text": "hello"}]
    assert calls["method"] == "POST"
    assert calls["url"] == "http://127.0.0.1:8765/v1/transcribe"
    assert calls["data"] == {"model": "base", "language": "ru", "task": "transcribe"}


def test_media_recipe_keeps_sung_words_and_word_timings(monkeypatch) -> None:
    class Word:
        word, start, end = "привет", 0.1, 0.5

    class Segment:
        start, end, text, words = 0.0, 1.0, "привет", [Word()]

    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["vad_filter"] is False
            assert kwargs["compression_ratio_threshold"] == 2.4
            return iter([Segment()]), object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()))
    assert Engine().transcribe(np.zeros(1600), RecognitionConfig(device="cpu", media_mode=True)) == [
        {"start": 0.0, "end": 1.0, "text": "привет", "words": [{"text": "привет", "start": 0.1, "end": 0.5}]}
    ]
