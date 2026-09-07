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

    ``Engine.transcribe`` is intentionally used unchanged for both paths.  A
    preview is therefore an ordinary short transcription whose result is never
    persisted.  There can be one in-flight preview and one replacement waiting
    behind it; final utterances always win over that replacement.
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
        preview_min_seconds: float = 0.8,
        preview_interval_seconds: float = 0.8,
    ):
        self.engine, self.config = engine, config
        self.on_segment, self.on_status, self.on_done = on_segment, on_status, on_done
        self.on_partial = on_partial
        self.preview_config = replace(config, live_preview=True)
        # Short phrases give subtitles a usable live cadence.  The engine VAD
        # remains a second guard against noise before Whisper runs.
        self.buffer = SpeechBuffer(max_seconds=4.0, silence_seconds=0.45, threshold=0.004)
        # A Live result that is more than one phrase behind is no longer live.
        # Finals are never discarded, so a full queue stops with an explicit
        # overload error instead of silently extending delay.
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
        self._last_preview_position = -self._preview_interval_samples
        self._last_preview_text = ""
        self.thread = Thread(target=self._run, name="dotaudio-recognize", daemon=True)

    def start(self, capture):
        self.capture = capture
        self.thread.start()
        try:
            capture.start()
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

    def _schedule_preview(self):
        if self.on_partial is None:
            return
        snapshot = self.buffer.snapshot()
        if snapshot is None:
            return
        offset, audio = snapshot
        position = self.buffer.position
        if len(audio) < self._preview_min_samples:
            return
        if position - self._last_preview_position < self._preview_interval_samples:
            return
        self._last_preview_position = position
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
        if self.capture:
            self.capture.stop()
        with self._input_lock:
            if not self.closed.is_set() and not cancel:
                tail = self.buffer.flush()
                if tail:
                    self._enqueue_final(tail)
            self.closed.set()
            self._clear_preview()
        self._wake.set()

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
            self.on_done(error or self.failed, self.cancel.is_set())
