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


def test_live_session_stop_before_start_still_completes() -> None:
    completed = Event()
    errors: list[tuple[str, bool]] = []
    capture = _Capture()
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda error, cancelled: (errors.append((error, cancelled)), completed.set()),
    )
    session.stop(cancel=True)
    assert completed.wait(2)
    assert errors == [("", True)]
    session.start(capture)
    assert capture.started is False


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
    partials: list[dict] = []
    session = LiveSession(
        _Engine(), RecognitionConfig(), segments.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), partials.append,
        preview_min_seconds=0.2, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    session.stop(cancel=True)
    assert completed.wait(2)
    assert segments == []
    assert partials == []


def test_live_session_cancel_suppresses_an_inflight_partial() -> None:
    class SlowEngine:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()

        def transcribe(self, audio, _config, _cancel, on_segment, _on_status):
            self.started.set()
            assert self.release.wait(2)
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "поздно"})
            return []

    engine = SlowEngine()
    completed = Event()
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: completed.set(), partials.append,
        preview_min_seconds=0.05, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert engine.started.wait(2)
    session.stop(cancel=True)
    engine.release.set()
    assert completed.wait(2)
    assert partials == []


def test_live_session_emits_partial_before_the_utterance_ends() -> None:
    partial_ready = Event()
    completed = Event()
    finals: list[dict] = []
    partials: list[dict] = []

    def partial(segment: dict) -> None:
        partials.append(segment)
        partial_ready.set()

    session = LiveSession(
        _Engine(), RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), partial,
        preview_min_seconds=0.05, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert partial_ready.wait(2)
    assert finals == []
    assert partials[0]["text"] == "готово"
    assert partials[0]["stable_text"] == ""
    assert partials[0]["end"] == 0.1
    assert partials[0]["latency_ms"] >= 0
    session.stop(cancel=True)
    assert completed.wait(2)


def test_live_session_coalesces_preview_and_prioritises_final() -> None:
    class Engine:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.first_started = Event()
            self.second_started = Event()
            self.first_release = Event()
            self.second_release = Event()

        def transcribe(self, audio, _config, cancel, on_segment, _on_status):
            self.calls.append(len(audio))
            call_number = len(self.calls)
            if call_number == 1:
                self.first_started.set()
                assert self.first_release.wait(2)
            elif call_number == 2:
                self.second_started.set()
                assert self.second_release.wait(2)
            if not cancel.is_set():
                on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "текст"})
            return []

    engine = Engine()
    completed = Event()
    finals: list[dict] = []
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), partials.append,
        preview_min_seconds=0.05, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    speech = np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32)
    session.feed(speech)
    assert engine.first_started.wait(2)
    session.feed(speech)
    session.feed(speech)
    engine.first_release.set()
    assert engine.second_started.wait(2)

    # This endpoints the utterance while a preview is running.  The pending
    # preview is discarded and the final transcription runs exactly once.
    session.feed(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
    session.stop()
    engine.second_release.set()
    assert completed.wait(2)
    assert engine.calls == [SAMPLE_RATE // 10, SAMPLE_RATE * 3 // 10, SAMPLE_RATE * 8 // 10]
    assert partials == []
    assert [segment["text"] for segment in finals] == ["текст"]


def _speech(seconds: float = 0.1) -> np.ndarray:
    return np.full(int(SAMPLE_RATE * seconds), 0.4, dtype=np.float32)


def _silence(seconds: float = 0.5) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def test_live_session_without_catch_up_stops_when_the_queue_is_full() -> None:
    class SlowEngine:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()

        def transcribe(self, audio, _config, _cancel, on_segment, _on_status):
            if not self.started.is_set():
                self.started.set()
                assert self.release.wait(2)
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "фраза"})
            return []

    engine = SlowEngine()
    completed = Event()
    errors: list[tuple[str, bool]] = []
    statuses: list[str] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, statuses.append,
        lambda error, cancelled: (errors.append((error, cancelled)), completed.set()),
    )
    session.start(_Capture())
    session.feed(_speech())
    session.feed(_silence())
    assert engine.started.wait(2)
    session.feed(_speech())
    session.feed(_silence())
    session.feed(_speech())
    session.feed(_silence())
    session.feed(_speech())
    session.feed(_silence())
    engine.release.set()
    assert completed.wait(2)
    assert session.failed.startswith("Модель не успевает")
    assert errors[0][0].startswith("Модель не успевает")


def test_catch_up_drops_stale_finals_instead_of_stopping() -> None:
    class SlowEngine:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.lengths: list[int] = []

        def transcribe(self, audio, _config, cancel, on_segment, _on_status):
            self.lengths.append(len(audio))
            if len(self.lengths) == 1:
                self.started.set()
                assert self.release.wait(2)
            if not cancel.is_set():
                on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "сейчас"})
            return []

    engine = SlowEngine()
    completed = Event()
    finals: list[dict] = []
    statuses: list[str] = []
    errors: list[tuple[str, bool]] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, statuses.append,
        lambda error, cancelled: (errors.append((error, cancelled)), completed.set()),
        catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(0.2))
    session.feed(_silence())
    assert engine.started.wait(2)
    session.feed(_speech(0.3))
    session.feed(_silence())
    session.feed(_speech(0.4))
    session.feed(_silence())
    session.stop()
    engine.release.set()
    assert completed.wait(2)
    assert session.failed == ""
    assert errors == [("", False)]
    assert "live_backlog" in statuses
    # In-flight first phrase plus the newest queued phrase. The middle
    # utterance is dropped so captions stay on the current sound.
    assert len(engine.lengths) == 2
    assert engine.lengths[0] == int(SAMPLE_RATE * 0.2) + int(SAMPLE_RATE * 0.5)
    assert engine.lengths[1] == int(SAMPLE_RATE * 0.4) + int(SAMPLE_RATE * 0.5)
    assert finals[-1]["text"] == "сейчас"


def test_catch_up_preview_uses_a_rolling_window() -> None:
    class Engine:
        def __init__(self) -> None:
            self.lengths: list[int] = []
            self.ready = Event()

        def transcribe(self, audio, config, _cancel, on_segment, _on_status):
            self.lengths.append(len(audio))
            if config.live_preview:
                on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": "черновик"})
                self.ready.set()
            return []

    engine = Engine()
    completed = Event()
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: completed.set(), lambda _partial: None,
        catch_up=True, preview_min_seconds=0.2, preview_interval_seconds=0.2,
        preview_window_seconds=0.4,
    )
    session.start(_Capture())
    session.feed(_speech(1.0))
    assert engine.ready.wait(2)
    session.stop(cancel=True)
    assert completed.wait(2)
    assert engine.lengths
    assert max(engine.lengths) <= int(SAMPLE_RATE * 0.4) + 1


def test_catch_up_defaults_keep_a_one_second_preview_window() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    assert session.buffer.limit == int(1.5 * SAMPLE_RATE)
    assert session.buffer.silence_limit == int(0.24 * SAMPLE_RATE)
    assert session._preview_window_samples == int(1.05 * SAMPLE_RATE)
    assert session._preview_interval_samples == int(0.35 * SAMPLE_RATE)
