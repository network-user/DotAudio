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
LIVE_SPEECH_THRESHOLD = 0.0015

# Live endpointing.  A phrase is allowed to run longer than it used to: the
# rolling preview already shows the text, and Whisper reads a whole phrase far
# better than a 1.5 s fragment of one.
LIVE_PHRASE_SECONDS = 7.0
LIVE_SILENCE_SECONDS = 0.5
# Below roughly two seconds of audio Whisper returns phonetic guesses, so an
# earlier preview would only flash wrong words at the user.
LIVE_PREVIEW_MIN_SECONDS = 1.2
LIVE_PREVIEW_INTERVAL_SECONDS = 0.5
LIVE_PREVIEW_WINDOW_SECONDS = 6.0
# Previews may not use the whole machine.  Asking for a new one before the
# previous decode has had time to finish only grows the backlog, so the
# interval follows the measured decode time on slower hardware.
LIVE_PREVIEW_DUTY = 1.5
# A pause at least this long is treated as a place where a phrase may be cut.
PHRASE_SPLIT_SECONDS = 0.12

DICTATION_PREVIEW_MIN_SECONDS = 0.8
DICTATION_PREVIEW_INTERVAL_SECONDS = 0.8
DICTATION_PREVIEW_WINDOW_SECONDS = 1.8


class VoiceActivity:
    """Streaming Silero VAD: one speech decision per 32 ms frame.

    A loudness threshold cannot answer the question Live actually asks.
    Measured on this machine, speech through WASAPI loopback sits near RMS
    0.0006 while fan and white noise reach 0.02, so any single threshold either
    drops the speech or accepts the noise.  The model separates them, and at
    ~0.09 ms per frame it costs a fraction of a percent of one core.

    The recurrent state is carried between calls, so a long utterance is scored
    as one stream rather than as unrelated chunks.
    """

    FRAME = 512
    CONTEXT = 64

    def __init__(self, session, threshold=0.5, release=0.35):
        self.session = session
        self.threshold = threshold
        # Speech dips below the trigger between words.  Releasing at a lower
        # score keeps one phrase together instead of cutting it into pieces.
        self.release = release
        self.speaking = False
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def __call__(self, audio):
        """Return whether the chunk carries speech.

        A chunk shorter than one frame keeps the previous answer: capture block
        sizes are a device detail and must not toggle endpointing on their own.
        """

        samples = np.concatenate((self._pending, np.asarray(audio, dtype=np.float32).reshape(-1)))
        usable = len(samples) - len(samples) % self.FRAME
        self._pending = samples[usable:]
        for start in range(0, usable, self.FRAME):
            frame = samples[start : start + self.FRAME].reshape(1, -1)
            batch = np.ascontiguousarray(np.concatenate((self._context, frame), axis=1))
            output, self._h, self._c = self.session.run(
                None, {"input": batch, "h": self._h, "c": self._c}
            )
            self._context = frame[:, -self.CONTEXT :]
            score = float(np.asarray(output).reshape(-1)[0])
            self.speaking = score >= (self.release if self.speaking else self.threshold)
        return self.speaking


def open_voice_activity():
    """Build the streaming detector, or ``None`` when the model is unavailable.

    The ONNX model ships with faster-whisper, so this never reaches the network.
    """

    try:
        from faster_whisper.vad import get_vad_model

        return VoiceActivity(get_vad_model().session)
    except Exception:
        # Live must still start with energy endpointing on a machine where
        # onnxruntime cannot load.
        return None


class SpeechBuffer:
    """Endpointing with pre-roll; Whisper VAD filters each utterance again."""

    def __init__(
        self,
        max_seconds=4.0,
        silence_seconds=0.45,
        threshold=0.004,
        hold_threshold=None,
        detector=None,
    ):
        self.limit = int(max_seconds * SAMPLE_RATE)
        self.silence_limit = int(silence_seconds * SAMPLE_RATE)
        self.threshold = threshold
        self.hold_threshold = threshold * 0.55 if hold_threshold is None else hold_threshold
        self.detector = detector
        # A phrase that reaches the length limit is cut back to the last pause
        # instead of in the middle of a word.  Without this the caption ends on
        # "без видеокар" and the next one opens with the leftover syllable.
        self.split_limit = int(PHRASE_SPLIT_SECONDS * SAMPLE_RATE)
        self.position = 0
        self.start = 0
        self.frames = []
        self.size = 0
        self.quiet = 0
        self.split = 0
        self.pre = deque()
        self.pre_size = 0

    def feed(self, audio):
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(audio):
            return None
        if self.detector is not None:
            speaking = self.detector(audio)
        else:
            rms = float(np.sqrt(np.mean(audio * audio)))
            gate = self.threshold if not self.frames else self.hold_threshold
            speaking = rms >= gate
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
        if speaking:
            self.quiet = 0
        else:
            self.quiet += len(audio)
            if self.quiet >= self.split_limit:
                self.split = self.size - self.quiet
        if self.quiet >= self.silence_limit:
            return self.flush()
        if self.size >= self.limit:
            return self.flush_at_limit()
        return None

    def flush(self):
        if not self.frames:
            return None
        result = (self.start / SAMPLE_RATE, np.concatenate(self.frames))
        self._reset()
        return result

    def flush_at_limit(self):
        """Emit up to the last pause and keep the rest as the next phrase.

        Speech that runs past the phrase limit is normal: the limit exists to
        bound memory and latency, not because the speaker stopped.  Cutting at
        the last pause keeps whole words on both sides of the boundary.
        """

        if not self.frames:
            return None
        audio = np.concatenate(self.frames)
        split = self.split
        if not 0 < split < len(audio):
            return self.flush()
        head, tail = audio[:split], audio[split:]
        start = self.start
        quiet = self.quiet
        self._reset()
        # The trailing pause belongs to the audio that is kept, so the next
        # phrase is still endpointed by the silence the speaker is making now.
        self.start = start + split
        self.frames = [tail]
        self.size = len(tail)
        self.quiet = min(quiet, len(tail))
        return (start / SAMPLE_RATE, head)

    def _reset(self):
        self.frames = []
        self.size = self.quiet = self.split = 0

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
        detector: Callable[[np.ndarray], bool] | None = None,
        preview_min_seconds: float | None = None,
        preview_interval_seconds: float | None = None,
        preview_window_seconds: float | None = None,
    ):
        self.engine, self.config = engine, config
        self.on_segment, self.on_status, self.on_done = on_segment, on_status, on_done
        self.on_partial = on_partial
        self.catch_up = catch_up
        self.preview_config = replace(config, live_preview=True, live_stream=False)
        if catch_up:
            # Whisper reads a whole phrase much better than a fragment of one,
            # and the rolling preview covers the wait.  The energy threshold
            # stays as the fallback for machines without the VAD model; it is
            # kept in sync with the UI signal threshold, so the interface no
            # longer claims to hear audio that endpointing then discards.
            self.buffer = SpeechBuffer(
                max_seconds=LIVE_PHRASE_SECONDS,
                silence_seconds=LIVE_SILENCE_SECONDS,
                threshold=LIVE_SPEECH_THRESHOLD,
                detector=detector,
            )
            preview_min_seconds = preview_min_seconds or LIVE_PREVIEW_MIN_SECONDS
            preview_interval_seconds = preview_interval_seconds or LIVE_PREVIEW_INTERVAL_SECONDS
            preview_window_seconds = preview_window_seconds or LIVE_PREVIEW_WINDOW_SECONDS
            self.queue = Queue(maxsize=1)
        else:
            self.buffer = SpeechBuffer(max_seconds=4.0, silence_seconds=0.45, threshold=0.004)
            preview_min_seconds = preview_min_seconds or DICTATION_PREVIEW_MIN_SECONDS
            preview_interval_seconds = (
                preview_interval_seconds or DICTATION_PREVIEW_INTERVAL_SECONDS
            )
            preview_window_seconds = preview_window_seconds or DICTATION_PREVIEW_WINDOW_SECONDS
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
        self._preview_invalidated_through = 0
        self._preview_min_samples = max(1, int(preview_min_seconds * SAMPLE_RATE))
        self._preview_interval_samples = max(1, int(preview_interval_seconds * SAMPLE_RATE))
        self._preview_window_samples = max(
            self._preview_min_samples, int(preview_window_seconds * SAMPLE_RATE)
        )
        self._last_preview_position = -self._preview_interval_samples
        # How long this machine actually needs per window.  Written by the
        # worker thread and read by capture as a single float, which is enough
        # to pace previews without another lock on the audio callback.
        self._decode_seconds = 0.0
        self._last_preview_text = ""
        self._stable_prefix = ""
        self._last_preview_offset = None
        self._worker_started = False
        self._done_emitted = False
        self.thread = Thread(target=self._run, name="dotaudio-recognize", daemon=True)

    def use_detector(self, detector):
        """Attach voice activity before capture starts.

        Loading the VAD model costs a few hundred milliseconds, so the caller
        does it on the thread that prepares the model rather than on the UI
        thread.  After ``start`` the buffer is owned by the audio callback.
        """

        with self._input_lock:
            if self.capture is None:
                self.buffer.detector = detector

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
        # A queued final has not produced text yet. In Live retain a result
        # already decoding across this boundary, or slow inference can emit
        # nothing indefinitely. Stop/cancel still invalidate in-flight work.
        self._clear_preview(invalidate=not self.catch_up)
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
        # In Live mode a queued final is persistence work, not a reason to
        # stop refreshing the caption.  If decoding falls behind, the user
        # must still see the newest rolling window instead of a frozen phrase.
        if not self.catch_up and not self.queue.empty():
            return
        if self.buffer.size < self._preview_min_samples:
            return
        if self.buffer.position - self._last_preview_position < self._preview_interval():
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

    def _preview_interval(self):
        """Space previews by the configured cadence or by the machine's speed.

        On hardware that decodes a window in well under the interval this is
        the configured value.  Where a window takes longer, asking at the same
        rate would queue work that is stale before it starts.
        """

        if not self.catch_up:
            return self._preview_interval_samples
        measured = int(self._decode_seconds * LIVE_PREVIEW_DUTY * SAMPLE_RATE)
        return max(self._preview_interval_samples, measured)

    def _note_decode(self, seconds):
        """Follow the measured decode time, favouring the recent past."""

        if self._decode_seconds <= 0.0:
            self._decode_seconds = seconds
        else:
            self._decode_seconds += (seconds - self._decode_seconds) * 0.3

    def _clear_preview(self, *, invalidate=True):
        with self._preview_lock:
            self._preview_generation += 1
            if invalidate:
                self._preview_invalidated_through = self._preview_generation
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
        # Finals must make progress even while capture keeps replacing previews.
        # Catch-up already bounds this queue to the newest unstarted phrase.
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
        return self._has_preview()

    def _has_preview(self):
        with self._preview_lock:
            return self._preview is not None

    def _preview_is_current(self, generation):
        with self._preview_lock:
            return (
                generation == self._preview_generation
                and not self.cancel.is_set()
                and not self.closed.is_set()
            )

    def _preview_can_emit(self, generation):
        """Allow an in-flight preview to finish when only a newer one arrived.

        A rolling replacement should affect the next decoder turn, not erase
        useful text from a decode that already started. Stop and cancel
        explicitly invalidate all older generations.
        """

        with self._preview_lock:
            return (
                generation > self._preview_invalidated_through
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
        # A capture callback can replace the snapshot after _next_task() has
        # selected it but before native inference starts.  Do not spend a
        # decoder turn on that already obsolete window: the latest snapshot is
        # what keeps the on-screen caption close to the current sound.
        if not self._preview_is_current(generation):
            return
        received: list[dict[str, Any]] = []

        def collect(segment):
            received.append(dict(segment))

        started = monotonic()
        result = self.engine.transcribe(
            audio, self.preview_config, self.cancel, collect, self.on_status
        )
        self._note_decode(monotonic() - started)
        if not received and result:
            received.extend(dict(segment) for segment in result)
        if not self._preview_can_emit(generation):
            return
        text = self._text(received)
        if not text:
            return
        if offset != self._last_preview_offset:
            self._last_preview_text = ""
            self._stable_prefix = ""
            self._last_preview_offset = offset
        agreed = self._common_word_prefix(self._last_preview_text, text)
        self._last_preview_text = text
        if agreed.startswith(self._stable_prefix):
            self._stable_prefix = agreed
        stable_text = self._stable_prefix
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
        self._stable_prefix = ""
        self._last_preview_offset = None
        emitted = False

        def emit(segment):
            nonlocal emitted
            if not self.cancel.is_set():
                emitted = True
                self.on_segment({
                    **segment,
                    "start": segment["start"] + offset,
                    "end": segment["end"] + offset,
                    "audio_end": offset + len(audio) / SAMPLE_RATE,
                })

        started = monotonic()
        self.engine.transcribe(audio, self.config, self.cancel, emit, self.on_status)
        self._note_decode(monotonic() - started)
        if self.catch_up and not emitted and not self.cancel.is_set():
            self.on_status("live_no_text")

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
