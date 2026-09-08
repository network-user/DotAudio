from __future__ import annotations

import sys
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from dotaudio.engine import RecognitionConfig
from dotaudio.pipeline import (
    FINAL_MERGE_LIMIT_SECONDS,
    LIVE_PHRASE_SECONDS,
    LIVE_PREVIEW_INTERVAL_SECONDS,
    LIVE_PREVIEW_WINDOW_SECONDS,
    LIVE_SILENCE_SECONDS,
    LIVE_SPEECH_THRESHOLD,
    SAMPLE_RATE,
    LiveSession,
    SpeechBuffer,
    VoiceActivity,
    open_voice_activity,
    preload_voice_activity,
)


def test_speech_buffer_keeps_preroll_and_flushes_after_silence() -> None:
    buffer = SpeechBuffer(max_seconds=5, silence_seconds=0.2, threshold=0.1)
    assert buffer.feed(np.zeros(SAMPLE_RATE // 4, dtype=np.float32)) is None
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.5, dtype=np.float32)) is None
    chunk = buffer.feed(np.zeros(SAMPLE_RATE // 5, dtype=np.float32))
    assert chunk is not None
    start, audio = chunk
    assert start == 0.0
    assert len(audio) == SAMPLE_RATE // 4 + SAMPLE_RATE // 10 + SAMPLE_RATE // 5


def test_speech_buffer_keeps_quiet_speech_after_a_louder_start() -> None:
    buffer = SpeechBuffer(max_seconds=5, silence_seconds=1, threshold=0.2)
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.3, dtype=np.float32)) is None
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.12, dtype=np.float32)) is None
    assert buffer.size > 0


def test_speech_buffer_flushes_at_maximum_chunk_length() -> None:
    buffer = SpeechBuffer(max_seconds=0.2, silence_seconds=1, threshold=0.1)
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32)) is None
    chunk = buffer.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert chunk is not None
    assert len(chunk[1]) == SAMPLE_RATE // 5


def test_speech_buffer_cuts_a_long_phrase_at_the_last_pause() -> None:
    buffer = SpeechBuffer(max_seconds=1.0, silence_seconds=1.0, threshold=0.1)
    buffer.feed(np.full(int(SAMPLE_RATE * 0.4), 0.4, dtype=np.float32))
    buffer.feed(np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.float32))
    chunk = buffer.feed(np.full(int(SAMPLE_RATE * 0.5), 0.4, dtype=np.float32))

    assert chunk is not None
    start, audio = chunk
    assert start == 0.0
    assert len(audio) == int(SAMPLE_RATE * 0.4)
    # The pause and the speech after it open the next phrase instead of being
    # lost or cut mid-word at the limit.
    assert buffer.size == int(SAMPLE_RATE * 0.7)
    assert buffer.start == int(SAMPLE_RATE * 0.4)


def test_speech_buffer_at_the_limit_falls_back_to_a_plain_cut() -> None:
    buffer = SpeechBuffer(max_seconds=0.2, silence_seconds=1.0, threshold=0.1)
    buffer.feed(np.full(int(SAMPLE_RATE * 0.1), 0.4, dtype=np.float32))
    chunk = buffer.feed(np.full(int(SAMPLE_RATE * 0.1), 0.4, dtype=np.float32))

    assert chunk is not None
    assert len(chunk[1]) == int(SAMPLE_RATE * 0.2)
    assert buffer.size == 0


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


def test_live_session_reports_capture_gap_once_without_cancelling() -> None:
    statuses: list[str] = []
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, statuses.append,
        lambda _error, _cancelled: None, catch_up=True,
    )

    session.note_audio_gap(2)
    session.note_audio_gap(1)

    assert statuses == ["live_audio_gap"]
    assert session.cancel.is_set() is False


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

    # This endpoints the utterance while the second preview is running.  The
    # first completed preview remains visible, while the in-flight second one
    # is invalidated by the final transcription.
    session.feed(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
    session.stop()
    engine.second_release.set()
    assert completed.wait(2)
    assert engine.calls == [SAMPLE_RATE // 10, SAMPLE_RATE * 3 // 10, SAMPLE_RATE * 8 // 10]
    assert len(partials) == 1
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


class _SlowEngine:
    """Hold the first phrase until released, so the rest queues up behind it."""

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


def test_catch_up_joins_waiting_phrases_instead_of_dropping_one() -> None:
    engine = _SlowEngine()
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
    # The two phrases that waited behind the slow one are the same stretch of
    # sound, so they are recognised together rather than one of them being lost.
    assert "live_backlog" not in statuses
    assert len(engine.lengths) == 2
    assert engine.lengths[0] == int(SAMPLE_RATE * 0.7)
    assert engine.lengths[1] == int(SAMPLE_RATE * 1.7)
    assert finals[-1]["text"] == "сейчас"


def test_speech_buffer_carries_the_end_of_a_phrase_forward() -> None:
    buffer = SpeechBuffer(max_seconds=5, silence_seconds=0.2, threshold=0.1)
    buffer.feed(np.full(SAMPLE_RATE // 2, 0.5, dtype=np.float32))
    assert buffer.feed(np.zeros(SAMPLE_RATE // 5, dtype=np.float32)) is not None
    assert not len(buffer.lead)

    buffer.feed(np.full(SAMPLE_RATE // 2, 0.5, dtype=np.float32))
    assert buffer.feed(np.zeros(SAMPLE_RATE // 5, dtype=np.float32)) is not None
    # The second phrase is handed the first one, ending where it began.
    assert len(buffer.lead) == SAMPLE_RATE // 2 + SAMPLE_RATE // 5
    assert buffer.lead_end == pytest.approx(0.7)


def test_catch_up_drops_audio_only_when_the_join_grows_past_one_window() -> None:
    engine = _SlowEngine()
    completed = Event()
    statuses: list[str] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, statuses.append,
        lambda _error, _cancelled: completed.set(), catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(0.2))
    session.feed(_silence())
    assert engine.started.wait(2)
    for _ in range(4):
        session.feed(_speech(FINAL_MERGE_LIMIT_SECONDS / 2))
        session.feed(_silence())
    session.stop()
    engine.release.set()
    assert completed.wait(2)
    assert "live_backlog" in statuses
    assert max(engine.lengths) <= int(FINAL_MERGE_LIMIT_SECONDS * SAMPLE_RATE)


def test_catch_up_keeps_a_phrase_that_stop_finds_still_waiting() -> None:
    engine = _SlowEngine()
    completed = Event()
    finals: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(0.2))
    session.feed(_silence())
    assert engine.started.wait(2)
    session.feed(_speech(1.0))
    session.feed(_silence())
    # Stop asks to keep what was said. The phrase queued behind the slow decode
    # is part of that, so it is recognised and not thrown away with the tail.
    session.stop()
    engine.release.set()
    assert completed.wait(2)
    assert len(engine.lengths) == 2
    assert engine.lengths[1] == int(SAMPLE_RATE * 1.5)
    assert len(finals) == 2


class _ScriptedEngine:
    """Answer each call with the next line, and say when a call is over.

    The short-phrase path only exists when the phrase before it has already
    been recognised, so the test has to wait for that instead of racing it.
    """

    def __init__(self, *lines: str) -> None:
        self.lines = list(lines)
        self.lengths: list[int] = []
        self.answered = Event()

    def transcribe(self, audio, _config, _cancel, on_segment, _on_status):
        self.lengths.append(len(audio))
        words = self.lines[min(len(self.lengths), len(self.lines)) - 1]
        on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": words})
        self.answered.set()
        return []


def test_a_phrase_too_short_to_recognise_is_given_the_one_before_it() -> None:
    engine = _ScriptedEngine("первая фраза", "первая фраза и хвост")
    completed = Event()
    finals: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(2.0))
    session.feed(_silence())
    assert engine.answered.wait(2)
    session.feed(_speech(0.2))
    session.stop()
    assert completed.wait(2)
    # The half-second phrase was recognised together with the end of the one
    # before it, and the words that came back twice were removed.
    assert engine.lengths[1] > int(SAMPLE_RATE * 0.7)
    assert [final["text"] for final in finals] == ["первая фраза", "и хвост"]
    assert finals[1]["start"] == pytest.approx(2.5, abs=0.1)


def test_a_short_phrase_is_asked_about_alone_when_the_decodes_disagree() -> None:
    engine = _ScriptedEngine("первая фраза", "совсем другое", "хвост")
    completed = Event()
    finals: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(2.0))
    session.feed(_silence())
    assert engine.answered.wait(2)
    session.feed(_speech(0.2))
    session.stop()
    assert completed.wait(2)
    # Nothing in the wider decode repeated the previous phrase, so the caption
    # is what the phrase alone says rather than a guess at what is new in it.
    assert len(engine.lengths) == 3
    assert engine.lengths[2] == int(SAMPLE_RATE * 0.2)
    assert [final["text"] for final in finals] == ["первая фраза", "хвост"]


def test_finals_from_different_utterances_are_not_joined() -> None:
    early = (0.0, np.zeros(SAMPLE_RATE, dtype=np.float32), None)
    much_later = (30.0, np.zeros(SAMPLE_RATE, dtype=np.float32), None)
    assert LiveSession._merge_finals(early, much_later) is None


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


def test_catch_up_defaults_keep_whole_phrases_for_the_model() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    assert session.buffer.limit == int(LIVE_PHRASE_SECONDS * SAMPLE_RATE)
    assert session.buffer.silence_limit == int(LIVE_SILENCE_SECONDS * SAMPLE_RATE)
    assert session.buffer.threshold == LIVE_SPEECH_THRESHOLD
    assert session._preview_window_samples == int(LIVE_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE)
    assert session._preview_interval_samples == int(LIVE_PREVIEW_INTERVAL_SECONDS * SAMPLE_RATE)


def test_preview_interval_follows_a_slow_machine() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    assert session._preview_interval() == session._preview_interval_samples

    session._note_decode(0.6)

    # Where a window takes 0.6 s to decode, asking twice a second only queues
    # snapshots that are stale before inference starts.
    assert session._preview_interval() == int(0.6 * 1.5 * SAMPLE_RATE)

    session._note_decode(6.0)

    # Но пауза между черновиками не может стать длиннее половины фразы: иначе
    # одна медленная расшифровка выключила бы черновики до конца реплики.
    assert session._preview_interval() == session.buffer.limit // 2


def test_dictation_keeps_its_own_preview_cadence() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None,
    )
    session._note_decode(2.0)

    assert session._preview_window_samples == int(1.8 * SAMPLE_RATE)
    assert session._preview_interval() == int(0.8 * SAMPLE_RATE)


def test_slow_final_does_not_suppress_the_next_short_preview() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    session._note_decode(0.2)
    session._note_decode(12.0, 15.0, preview=False)
    session.feed(_speech(1.3))

    task = session._next_task()
    assert task is not None and task[0] == "preview"


def test_previews_resume_in_each_phrase_after_a_very_slow_decode() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    session._note_decode(10.0)
    previews_per_phrase = []
    previews = 0
    for _ in range(int(LIVE_PHRASE_SECONDS * 10) * 4):
        session.feed(_speech(0.1))
        task = session._next_task()
        if task is not None and task[0] == "preview":
            previews += 1
        elif task is not None and task[0] == "final":
            previews_per_phrase.append(previews)
            previews = 0

    assert len(previews_per_phrase) == 4
    assert all(count >= 1 for count in previews_per_phrase)


def test_preview_keeps_an_agreed_prefix_across_hypotheses() -> None:
    class Engine:
        def __init__(self) -> None:
            self.n = 0
            self.second = Event()

        def transcribe(self, audio, config, _cancel, on_segment, _on_status):
            if not config.live_preview:
                return []
            self.n += 1
            text = "раз два три" if self.n == 1 else "раз два четыре"
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": text})
            if self.n == 1:
                self.first.set()
            if self.n >= 2:
                self.second.set()
            return []

    engine = Engine()
    engine.first = Event()
    completed = Event()
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: completed.set(), partials.append,
        preview_min_seconds=0.05, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert engine.first.wait(2)
    session.feed(np.full(SAMPLE_RATE // 10, 0.4, dtype=np.float32))
    assert engine.second.wait(2)
    session.stop(cancel=True)
    assert completed.wait(2)
    assert partials[0]["stable_text"] == ""
    assert any(item["stable_text"] == "раз два" for item in partials)


def test_preview_agreement_keeps_words_when_only_punctuation_changes() -> None:
    assert LiveSession._common_word_prefix(
        "сегодня будет дождь", "Сегодня, будет дождь. Потом солнце"
    ) == "Сегодня, будет дождь."


def test_rolling_preview_keeps_a_stable_overlap_after_its_window_moves() -> None:
    engine = _ScriptedEngine("раз два три четыре", "Два, три четыре. пять")
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1

    session._transcribe_preview(0.0, _speech(1.8), 0.0, 1)
    session._transcribe_preview(0.8, _speech(1.8), 0.0, 1)

    # Окно сдвинулось, и «раз» из него вышло. Слово не исчезает с экрана:
    # оно уже сказано и больше не уточняется, поэтому идёт впереди
    # подтверждённого перекрытия.
    assert [part["stable_text"] for part in partials] == ["", "раз Два, три четыре."]
    assert partials[-1]["text"] == "раз Два, три четыре. пять"


def test_rolling_preview_does_not_confirm_a_single_matching_word() -> None:
    engine = _ScriptedEngine("раз два три", "три четыре")
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1

    session._transcribe_preview(0.0, _speech(1.0), 0.0, 1)
    session._transcribe_preview(0.5, _speech(1.0), 0.0, 1)

    # Одно совпавшее слово - не согласие двух окон: где кончается сказанное,
    # по нему не определить. Такое окно не показывается вовсе, иначе на экран
    # вместо реплики попал бы её обрывок.
    assert [part["text"] for part in partials] == ["раз два три"]
    assert partials[0]["stable_text"] == ""


def test_preview_window_that_skipped_ahead_keeps_the_speech_it_passed() -> None:
    """На медленной машине окно может перескочить через сказанное.

    Между окнами [0,1] и [2,3] лежит речь той же фразы. Она уже прозвучала и
    не уточняется, так что предыдущее окно переходит в подтверждённую часть,
    а не пропадает из субтитра.
    """

    engine = _ScriptedEngine("раз два", "пять шесть")
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1

    session._transcribe_preview(0.0, _speech(1.0), 0.0, 1)
    session._transcribe_preview(2.0, _speech(1.0), 0.0, 1)

    assert partials[-1]["stable_text"] == "раз два"
    assert partials[-1]["text"] == "раз два пять шесть"


def test_new_phrase_starts_the_caption_from_nothing() -> None:
    engine = _ScriptedEngine("раз два три четыре", "Два, три четыре. пять", "новая фраза")
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1

    session._transcribe_preview(0.0, _speech(1.8), 0.0, 1)
    session._transcribe_preview(0.8, _speech(1.8), 0.0, 1)
    # Фраза закончилась: перенесённое начало относится к ней и не должно
    # приклеиться к следующей.
    session._transcribe_final(2.6, _speech(1.0))
    session._transcribe_preview(3.6, _speech(1.0), 0.0, 1)

    assert partials[-1]["text"] == "новая фраза"
    assert partials[-1]["stable_text"] == ""


def test_preview_skips_a_snapshot_replaced_before_inference() -> None:
    class Engine:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, *_args):
            self.calls += 1
            return []

    engine = Engine()
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    session._preview_generation = 2
    session._preview = (0.1, _speech(), 0.0, 2)

    session._transcribe_preview(0.0, _speech(), 0.0, 1)

    assert engine.calls == 0


def test_preview_releases_a_confirmed_prefix_when_the_decoder_revises_it() -> None:
    engine = _ScriptedEngine("раз два три", "раз два четыре", "три четыре", "три четыре пять")
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1
    for _ in range(4):
        session._transcribe_preview(0.0, _speech(), 0.0, 1)

    assert [part["stable_text"] for part in partials] == ["", "раз два", "", "три четыре"]
    assert all(part["text"].startswith(part["stable_text"]) for part in partials)


def test_inflight_preview_emits_when_a_newer_snapshot_arrives() -> None:
    class SlowEngine:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()

        def transcribe(self, audio, config, _cancel, on_segment, _on_status):
            if not config.live_preview:
                return []
            self.started.set()
            assert self.release.wait(2)
            on_segment({
                "start": 0.0,
                "end": len(audio) / SAMPLE_RATE,
                "text": "первый результат",
            })
            return []

    engine = SlowEngine()
    completed = Event()
    partial_ready = Event()
    partials: list[dict] = []

    def on_partial(segment: dict) -> None:
        partials.append(segment)
        partial_ready.set()

    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: completed.set(), on_partial, catch_up=True,
        preview_min_seconds=0.05, preview_interval_seconds=0.05,
    )
    session.start(_Capture())
    session.feed(_speech(0.1))
    assert engine.started.wait(2)

    # A newer rolling window arrives while native inference is still running.
    # The completed result must remain visible instead of being discarded.
    session.feed(_speech(0.1))
    engine.release.set()

    assert partial_ready.wait(2)
    assert partials[0]["text"] == "первый результат"
    session.stop(cancel=True)
    assert completed.wait(2)


def test_catch_up_runs_a_final_even_when_a_newer_preview_waits() -> None:
    class Engine:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, *_args):
            self.calls += 1
            return []

    engine = Engine()
    statuses: list[str] = []
    session = LiveSession(
        engine, RecognitionConfig(), lambda _segment: None, statuses.append,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    session._preview_generation = 1
    session._preview = (1.0, _speech(), 0.0, 1)

    session._transcribe_final(0.0, _speech())

    # Continuous speech produces a preview before every final.  Yielding to it
    # would postpone the phrase that goes into history for as long as the user
    # keeps talking, so the final is decoded and the queue stays empty.
    assert engine.calls == 1
    assert session.queue.empty()
    assert statuses == ["live_no_text"]


def test_catch_up_yields_one_fresh_preview_between_finals_while_recording() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    first_final = (0.0, _speech(), None)
    second_final = (1.0, _speech(), None)
    preview = (1.0, _speech(), 0.0, 1)
    session.queue.put_nowait(first_final)
    kind, payload = session._next_task()
    assert kind == "final"
    assert payload is first_final
    session.queue.put_nowait(second_final)
    session._preview = preview

    # A live caption remains fresh even when the next completed phrase is
    # waiting. The following turn still persists that phrase.
    kind, payload = session._next_task()
    assert kind == "preview"
    assert payload is preview
    kind, payload = session._next_task()
    assert kind == "final"
    assert payload is second_final


def test_catch_up_stop_drains_final_before_a_waiting_preview() -> None:
    session = LiveSession(
        _Engine(), RecognitionConfig(), lambda _segment: None, lambda _status: None,
        lambda _error, _cancelled: None, lambda _partial: None, catch_up=True,
    )
    final = (0.0, _speech(), None)
    preview = (1.0, _speech(), 0.0, 1)
    session._last_task = "final"
    session.queue.put_nowait(final)
    session._preview = preview
    session.closed.set()

    kind, payload = session._next_task()
    assert kind == "final"
    assert payload is final


class _FakeVadSession:
    """Stands in for the Silero ONNX session: one score per frame."""

    def __init__(self, scores) -> None:
        self.scores = list(scores)
        self.batches: list[np.ndarray] = []

    def run(self, _outputs, inputs):
        self.batches.append(inputs["input"].copy())
        score = self.scores.pop(0) if self.scores else 0.0
        return np.array([[score]], dtype=np.float32), inputs["h"], inputs["c"]


def test_voice_activity_scores_every_frame_with_the_previous_context() -> None:
    session = _FakeVadSession([0.9, 0.9])
    detector = VoiceActivity(session)
    audio = np.arange(VoiceActivity.FRAME * 2, dtype=np.float32)

    assert detector(audio) is True
    assert len(session.batches) == 2
    assert session.batches[0].shape == (1, VoiceActivity.FRAME + VoiceActivity.CONTEXT)
    assert np.array_equal(session.batches[0][0, : VoiceActivity.CONTEXT], np.zeros(64))
    # The second frame is prefixed with the tail of the first one, so a word
    # split across two capture blocks is still scored as one stream.
    assert np.array_equal(
        session.batches[1][0, : VoiceActivity.CONTEXT],
        audio[VoiceActivity.FRAME - VoiceActivity.CONTEXT : VoiceActivity.FRAME],
    )


def test_voice_activity_holds_a_phrase_through_a_dip() -> None:
    session = _FakeVadSession([0.9, 0.4, 0.2])
    detector = VoiceActivity(session)
    frame = np.zeros(VoiceActivity.FRAME, dtype=np.float32)

    assert detector(frame) is True
    assert detector(frame) is True
    assert detector(frame) is False


def test_voice_activity_keeps_its_answer_for_a_partial_frame() -> None:
    session = _FakeVadSession([0.9])
    detector = VoiceActivity(session)

    assert detector(np.zeros(VoiceActivity.FRAME, dtype=np.float32)) is True
    assert detector(np.zeros(10, dtype=np.float32)) is True
    assert len(session.batches) == 1


def test_voice_activity_keeps_speech_before_a_quiet_end_of_block() -> None:
    detector = VoiceActivity(_FakeVadSession([0.9, 0.2, 0.1, 0.4]))
    frame = np.zeros(VoiceActivity.FRAME, dtype=np.float32)

    assert detector(np.tile(frame, 3)) is True
    # The block carried speech, but the last frame released hysteresis. A
    # sub-trigger score in the next block must not extend the utterance.
    assert detector(frame) is False


def test_speech_buffer_follows_the_detector_and_not_loudness() -> None:
    answers = iter([True, False])
    buffer = SpeechBuffer(
        max_seconds=5, silence_seconds=0.05, threshold=0.5,
        detector=lambda _audio: next(answers),
    )

    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.001, dtype=np.float32)) is None
    assert buffer.size > 0
    # Loud audio that the detector rejects ends the phrase instead of extending
    # it: a fan or music is not speech, whatever its level.
    assert buffer.feed(np.full(SAMPLE_RATE // 10, 0.9, dtype=np.float32)) is not None


def test_open_voice_activity_returns_nothing_without_the_model(monkeypatch) -> None:
    import dotaudio.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_vad_session", None)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", SimpleNamespace())

    assert open_voice_activity() is None


def test_preload_voice_activity_caches_session(monkeypatch) -> None:
    import dotaudio.pipeline as pipeline

    session = object()
    monkeypatch.setattr(pipeline, "_vad_session", None)
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper.vad",
        SimpleNamespace(get_vad_model=lambda: SimpleNamespace(session=session)),
    )

    assert preload_voice_activity() is True
    first = open_voice_activity()
    second = open_voice_activity()
    assert first is not None and second is not None
    assert first.session is session
    assert second.session is session
    # Два детектора делят сессию, но не состояние рекуррентной сети.
    assert first is not second


def test_speech_buffer_marks_phrases_cut_by_the_limit() -> None:
    buffer = SpeechBuffer(max_seconds=1.0, silence_seconds=0.3, threshold=0.1)
    buffer.feed(np.full(int(SAMPLE_RATE * 0.4), 0.4, dtype=np.float32))
    buffer.feed(np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.float32))
    assert buffer.feed(np.full(int(SAMPLE_RATE * 0.5), 0.4, dtype=np.float32)) is not None
    assert buffer.cut_at_limit is True

    # The remainder ends when the speaker pauses: that phrase is whole.
    assert buffer.feed(np.zeros(int(SAMPLE_RATE * 0.4), dtype=np.float32)) is not None
    assert buffer.cut_at_limit is False


def test_live_finals_carry_the_cut_flag_and_condition_on_earlier_text() -> None:
    class Engine:
        def __init__(self) -> None:
            self.contexts: list[tuple[bool, str]] = []
            self.calls = 0

        def transcribe(self, audio, config, _cancel, on_segment, _on_status):
            self.calls += 1
            self.contexts.append((config.live_preview, config.live_context))
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": f"фраза {self.calls}"})
            return []

    engine = Engine()
    finals: list[dict] = []
    partials: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: None, partials.append, catch_up=True,
    )
    session._preview_generation = 1

    # The first window of a session has nothing to condition on.
    session._transcribe_preview(0.0, _speech(1.0), 0.0, 1)
    assert engine.contexts[-1] == (True, "")

    session._transcribe_final(0.0, _speech(2.0), None, True)
    assert finals[-1]["cut"] is True
    assert finals[-1]["text"] == "фраза 2"

    # Every later preview and final reads the finals before it as previous text.
    session._transcribe_preview(2.0, _speech(1.0), 0.0, 1)
    assert engine.contexts[-1] == (True, "фраза 2")
    session._transcribe_final(2.0, _speech(2.0))
    assert engine.contexts[-1] == (False, "фраза 2")
    assert finals[-1]["cut"] is False
    session._transcribe_preview(4.0, _speech(1.0), 0.0, 1)
    assert engine.contexts[-1] == (True, "фраза 2 фраза 4")


def test_short_final_with_lead_audio_does_not_also_read_that_phrase_as_text() -> None:
    contexts: list[str] = []

    class Engine:
        def __init__(self) -> None:
            self.lines = ["первая фраза", "первая фраза и хвост"]
            self.answered = Event()

        def transcribe(self, audio, config, _cancel, on_segment, _on_status):
            contexts.append(config.live_context)
            on_segment({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": self.lines[min(len(contexts), 2) - 1]})
            self.answered.set()
            return []

    engine = Engine()
    completed = Event()
    finals: list[dict] = []
    session = LiveSession(
        engine, RecognitionConfig(), finals.append, lambda _status: None,
        lambda _error, _cancelled: completed.set(), catch_up=True,
    )
    session.start(_Capture())
    session.feed(_speech(2.0))
    session.feed(_silence())
    assert engine.answered.wait(2)
    session.feed(_speech(0.2))
    session.stop()
    assert completed.wait(2)
    # The lead audio already is the previous phrase; giving its text as well
    # would make the decoder read the same speech twice.
    assert contexts == ["", ""]
    assert [final["text"] for final in finals] == ["первая фраза", "и хвост"]
