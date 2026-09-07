"""Bounded live audio segmentation. Capture never waits for model inference."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable

import numpy as np

from dotaudio.engine import Engine, RecognitionConfig

SAMPLE_RATE = 16000


class SpeechBuffer:
    """Energy endpointing with pre-roll; Whisper VAD filters each utterance again."""

    def __init__(self, max_seconds=4.0, silence_seconds=0.45, threshold=0.004):
        self.limit = int(max_seconds * SAMPLE_RATE)
        self.silence_limit = int(silence_seconds * SAMPLE_RATE)
        self.threshold = threshold
        self.position = 0
        self.start = 0
        self.frames = []
        self.size = 0
        self.quiet = 0
        self.pre = deque()
        self.pre_size = 0

    def feed(self, audio):
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(audio):
            return None
        speaking = float(np.sqrt(np.mean(audio * audio))) >= self.threshold
        if not self.frames and not speaking:
            self.pre.append(audio.copy())
            self.pre_size += len(audio)
            while self.pre and self.pre_size > SAMPLE_RATE // 4:
                self.pre_size -= len(self.pre.popleft())
            self.position += len(audio)
            return None
        if not self.frames:
            self.start = self.position - self.pre_size
            self.frames = list(self.pre)
            self.size = self.pre_size
            self.pre.clear()
            self.pre_size = 0
        self.frames.append(audio.copy())
        self.size += len(audio)
        self.position += len(audio)
        self.quiet = 0 if speaking else self.quiet + len(audio)
        if self.size >= self.limit or self.quiet >= self.silence_limit:
            return self.flush()
        return None

    def flush(self):
        if not self.frames:
            return None
        result = (self.start / SAMPLE_RATE, np.concatenate(self.frames))
        self.frames = []
        self.size = self.quiet = 0
        return result

    def snapshot(self):
        """Return the active utterance without changing endpointing state."""

        if not self.frames:
            return None
        return self.start / SAMPLE_RATE, np.concatenate(self.frames)


class LiveSession:
    """Recognise final utterances and a coalesced preview of the active one.

    ``Engine.transcribe`` is used for both paths.  A preview is a short
    transcription that is never persisted.  There can be one in-flight
    preview and one replacement waiting behind it; final utterances always
    win over that replacement.

    ``catch_up`` is the Live-captions policy: stay near the current sound.
    An old final that has not started decoding is dropped when a newer one
    arrives.  Dictation keeps the strict queue and fails instead of skipping.
    """

    def __init__(
        self,
        engine: Engine,
        config: RecognitionConfig,
        on_segment: Callable[[dict[str, Any]], None],
        on_status: Callable[[str], None],
        on_done: Callable[[str, bool], None],
        on_partial: Callable[[dict[str, Any]], None] | None = None,
        *,
        catch_up: bool = False,
        preview_min_seconds: float = 0.8,
        preview_interval_seconds: float = 0.8,
        preview_window_seconds: float = 1.8,
    ):
        self.engine, self.config = engine, config
        self.on_segment, self.on_status, self.on_done = on_segment, on_status, on_done
        self.on_partial = on_partial
        self.catch_up = catch_up
        self.preview_config = replace(config, live_preview=True, live_stream=False)
        if catch_up:
            # ~1 s captions need a short rolling window, not a 4 s phrase wait.
            # Tiny/base greedy decode of ~1 s audio is the practical budget.
            self.buffer = SpeechBuffer(max_seconds=1.5, silence_seconds=0.24, threshold=0.004)
            preview_min_seconds = min(preview_min_seconds, 0.4)
            preview_interval_seconds = min(preview_interval_seconds, 0.35)
            preview_window_seconds = min(preview_window_seconds, 1.05)
            self.queue = Queue(maxsize=1)
        else:
            self.buffer = SpeechBuffer(max_seconds=4.0, silence_seconds=0.45, threshold=0.004)
            self.queue = Queue(maxsize=2)
        self.cancel = Event()
        self.closed = Event()
        self.failed = ""
        self.capture = None
        self._input_lock = Lock()
        self._preview_lock = Lock()
        self._wake = Event()
        self._preview: tuple[float, np.ndarray, float, int] | None = None
        self._preview_generation = 0
        self._preview_min_samples = max(1, int(preview_min_seconds * SAMPLE_RATE))
        self._preview_interval_samples = max(1, int(preview_interval_seconds * SAMPLE_RATE))
        self._preview_window_samples = max(
            self._preview_min_samples, int(preview_window_seconds * SAMPLE_RATE)
        )
        self._last_preview_position = -self._preview_interval_samples
        self._last_preview_text = ""
        self._worker_started = False
        self._done_emitted = False
        self.thread = Thread(target=self._run, name="dotaudio-recognize", daemon=True)

    def _mark_done(self):
        if self._done_emitted:
            return False
        self._done_emitted = True
        return True

    def start(self, capture):
        with self._input_lock:
            if self.cancel.is_set() or self.closed.is_set():
                self.closed.set()
                emit = self._mark_done()
            else:
                self.capture = capture
                self._worker_started = True
                emit = False
        if emit:
            self.on_done(self.failed, self.cancel.is_set())
            return
        self.thread.start()
        try:
            if self.cancel.is_set() or self.closed.is_set():
                capture.stop()
                self._wake.set()
                return
            capture.start()
            if self.cancel.is_set() or self.closed.is_set():
                capture.stop()
                self._wake.set()
        except Exception:
            self.cancel.set()
            self.closed.set()
            self._clear_preview()
            self._wake.set()
            raise

    def feed(self, audio):
        with self._input_lock:
            if self.closed.is_set():
                return
            chunk = self.buffer.feed(audio)
            if chunk:
                self._last_preview_position = self.buffer.position
                self._enqueue_final(chunk)
            else:
                self._schedule_preview()

    def _enqueue_final(self, chunk):
        # A final result supersedes any preview waiting for the same utterance.
        self._clear_preview()
        if self.catch_up:
            dropped = self._put_or_replace_final(chunk)
            if dropped:
                self.on_status("live_backlog")
        else:
            try:
                self.queue.put_nowait(chunk)
            except Full:
                self.failed = "Модель не успевает за эфиром. Выберите меньшую модель или GPU."
                self.cancel.set()
                self.closed.set()
            else:
                if self.queue.qsize() > 1:
                    self.on_status("live_backlog")
        self._wake.set()

    def _put_or_replace_final(self, chunk):
        """Keep the newest unstarted phrase.  In-flight audio is not dropped."""

        dropped = False
        while True:
            try:
                self.queue.put_nowait(chunk)
                return dropped
            except Full:
                try:
                    self.queue.get_nowait()
                except Empty:
                    continue
                dropped = True

    def _discard_queued_finals(self):
        while True:
            try:
                self.queue.get_nowait()
            except Empty:
                return

    def _schedule_preview(self):
        if self.on_partial is None:
            return
        if not self.queue.empty():
            return
        if self.buffer.size < self._preview_min_samples:
            return
        if self.buffer.position - self._last_preview_position < self._preview_interval_samples:
            return
        snapshot = self.buffer.snapshot()
        if snapshot is None:
            return
        offset, audio = snapshot
        self._last_preview_position = self.buffer.position
        if len(audio) > self._preview_window_samples:
            skip = len(audio) - self._preview_window_samples
            audio = audio[skip:]
            offset += skip / SAMPLE_RATE
        # The audio is copied by SpeechBuffer, but this explicit copy keeps a
        # queued preview independent from all capture-side arrays.
        with self._preview_lock:
            self._preview_generation += 1
            self._preview = (offset, audio.copy(), monotonic(), self._preview_generation)
        self._wake.set()

    def _clear_preview(self):
        with self._preview_lock:
            self._preview_generation += 1
            self._preview = None

    def stop(self, cancel=False):
        if cancel:
            self.cancel.set()
        with self._input_lock:
            capture = self.capture
            if not self.closed.is_set() and not cancel:
                tail = self.buffer.flush()
                if self.catch_up and tail:
                    # The open phrase is the current sound.  Drop unstarted
                    # finals so Stop does not drain a stale backlog.
                    self._discard_queued_finals()
                if tail:
                    self._enqueue_final(tail)
            else:
                self._discard_queued_finals()
            self.closed.set()
            self._clear_preview()
            emit_now = not self._worker_started and self._mark_done()
        if capture is not None:
            capture.stop()
        self._wake.set()
        if emit_now:
            self.on_done(self.failed, self.cancel.is_set())

    def _next_task(self):
        try:
            offset, audio = self.queue.get_nowait()
            return "final", (offset, audio)
        except Empty:
            pass
        with self._preview_lock:
            preview = self._preview
            self._preview = None
        if preview is None:
            return None
        return "preview", preview

    def _has_work(self):
        if not self.queue.empty():
            return True
        with self._preview_lock:
            return self._preview is not None

    def _preview_is_current(self, generation):
        with self._preview_lock:
            return (
                generation == self._preview_generation
                and not self.cancel.is_set()
                and not self.closed.is_set()
            )

    @staticmethod
    def _text(segments):
        return " ".join(
            str(segment.get("text", "")).strip()
            for segment in segments
            if str(segment.get("text", "")).strip()
        )

    @staticmethod
    def _common_word_prefix(previous, current):
        old_words, new_words = previous.split(), current.split()
        count = 0
        for old, new in zip(old_words, new_words):
            if old != new:
                break
            count += 1
        return " ".join(new_words[:count])

    def _transcribe_preview(self, offset, audio, requested_at, generation):
        received: list[dict[str, Any]] = []

        def collect(segment):
            received.append(dict(segment))

        result = self.engine.transcribe(
            audio, self.preview_config, self.cancel, collect, self.on_status
        )
        if not received and result:
            received.extend(dict(segment) for segment in result)
        if not self._preview_is_current(generation):
            return
        text = self._text(received)
        if not text:
            return
        stable_text = self._common_word_prefix(self._last_preview_text, text)
        self._last_preview_text = text
        final_end = offset + len(audio) / SAMPLE_RATE
        try:
            self.on_partial({
                "start": offset,
                "end": final_end,
                "text": text,
                "stable_text": stable_text,
                "latency_ms": round((monotonic() - requested_at) * 1000),
            })
        except Exception:
            # A closed QML object must not stop recording or finalisation.
            return

    def _transcribe_final(self, offset, audio):
        self._last_preview_text = ""

        def emit(segment):
            if not self.cancel.is_set():
                self.on_segment({
                    **segment,
                    "start": segment["start"] + offset,
                    "end": segment["end"] + offset,
                })

        self.engine.transcribe(audio, self.config, self.cancel, emit, self.on_status)

    def _run(self):
        error = ""
        try:
            while not self.cancel.is_set():
                task = self._next_task()
                if task is None:
                    if self.closed.is_set():
                        break
                    self._wake.clear()
                    if not self._has_work() and not self.closed.is_set():
                        self._wake.wait(0.15)
                    continue
                kind, payload = task
                if kind == "final":
                    self._transcribe_final(*payload)
                else:
                    self._transcribe_preview(*payload)
        except Exception as exc:
            error = str(exc)
        finally:
            self.closed.set()
            self._clear_preview()
            if self.capture:
                self.capture.stop()
            with self._input_lock:
                emit = self._mark_done()
            if emit:
                self.on_done(error or self.failed, self.cancel.is_set())
