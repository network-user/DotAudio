from __future__ import annotations

from threading import Event

import numpy as np

from dotaudio.engine import RecognitionConfig
from dotaudio.pipeline import SAMPLE_RATE, LiveSession, SpeechBuffer


def test_speech_buffer_keeps_preroll_and_flushes_after_silence() -> None:
    buffer = SpeechBuffer(max_seconds=5, silence_seconds=0.2, threshold=0.1)
    assert buffer.feed(np.zeros(SAMPLE_RATE // 4, dtype=np.float32)) is None
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.5, dtype=np.float32)) is None
    chunk = buffer.feed(np.zeros(SAMPLE_RATE // 5, dtype=np.float32))
    assert chunk is not None
    start, audio = chunk
    assert start == 0.0
    assert len(audio) == SAMPLE_RATE // 4 + SAMPLE_RATE // 10 + SAMPLE_RATE // 5


def test_speech_buffer_flushes_at_maximum_chunk_length() -> None:
    buffer = SpeechBuffer(max_seconds=0.2, silence_seconds=1, threshold=0.1)
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32)) is None
    chunk = buffer.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert chunk is not None
    assert len(chunk[1]) == SAMPLE_RATE // 5


class _Capture:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _Engine:
    def transcribe(self, audio, _config, cancel, on_segment, on_status):
        on_status("transcribing_cpu")
        if not cancel.is_set():
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "готово"})
        return []


def test_live_session_drains_the_last_phrase_before_completion() -> None:
    completed = Event()
    segments: list[dict] = []
    statuses: list[str] = []
    errors: list[tuple[str, bool]] = []
    capture = _Capture()
    session = LiveSession(
        _Engine(), RecognitionConfig(), segments.append, statuses.append,
        lambda error, cancelled: (errors.append((error, cancelled)), completed.set()),
    )
    session.start(capture)
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    session.stop()
    assert completed.wait(2)
    assert capture.started and capture.stopped
    assert statuses == ["transcribing_cpu"]
    assert segments and segments[0]["text"] == "готово"
    assert errors == [("", False)]


def test_live_session_cancel_does_not_emit_a_partial_phrase() -> None:
    completed = Event()
    segments: list[dict] = []
    session = LiveSession(
        _Engine(), RecognitionConfig(), segments.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(),
    )
    session.start(_Capture())
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    session.stop(cancel=True)
    assert completed.wait(2)
    assert segments == []
