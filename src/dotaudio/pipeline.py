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
from dotaudio.engine import stem as _stem

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
# Two phrases waiting to be recognised are joined instead of one being thrown
# away, as long as they are the same stretch of sound and the join stays short
# enough to decode in one window.
FINAL_MERGE_GAP_SECONDS = 0.5
FINAL_MERGE_LIMIT_SECONDS = 15.0
# A phrase shorter than this is not enough for the decoder on its own: measured,
# a half second scrap of real speech comes back as "Cutie" and is then rejected
# as a guess.  Such a phrase is recognised together with the end of the phrase
# before it, and the words that repeat are removed afterwards.
SHORT_FINAL_SECONDS = 1.2
PHRASE_CONTEXT_SECONDS = 2.0

_PREVIEW_PUNCTUATION = str.maketrans("", "", ".,!?;:…«»\"“”()[]{}")

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
        heard_speech = self.speaking if not usable else False
        for start in range(0, usable, self.FRAME):
            frame = samples[start : start + self.FRAME].reshape(1, -1)
            batch = np.ascontiguousarray(np.concatenate((self._context, frame), axis=1))
            output, self._h, self._c = self.session.run(
                None, {"input": batch, "h": self._h, "c": self._c}
            )
            self._context = frame[:, -self.CONTEXT :]
            score = float(np.asarray(output).reshape(-1)[0])
            self.speaking = score >= (self.release if self.speaking else self.threshold)
            heard_speech = heard_speech or self.speaking
        # Endpointing consumes a whole capture block. A quiet final frame must
        # not erase speech heard earlier in that same block. The recurrent
        # state still follows the last frame for the next call's hysteresis.
        return heard_speech


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
        self.context_limit = int(PHRASE_CONTEXT_SECONDS * SAMPLE_RATE)
        self.position = 0
        self.start = 0
        self.frames = []
        self.size = 0
        self.quiet = 0
        self.split = 0
        self.pre = deque()
        self.pre_size = 0
        # The end of the phrase emitted before the current one, kept so a short
        # phrase can be recognised with something in front of it.
        self.lead = np.zeros(0, dtype=np.float32)
        self.lead_end = 0.0
        self._context = np.zeros(0, dtype=np.float32)
        self._context_end = 0.0

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
        start, audio = self.start / SAMPLE_RATE, np.concatenate(self.frames)
        self._remember(start, audio)
        self._reset()
        return (start, audio)

    def _remember(self, start, audio):
        """Carry the end of an emitted phrase forward as context."""

        self.lead, self.lead_end = self._context, self._context_end
        self._context = audio[-self.context_limit :].copy()
        self._context_end = start + len(audio) / SAMPLE_RATE

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
        self._remember(start / SAMPLE_RATE, head)
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
        self._last_preview_end = None
        self._last_final_text = ""
        # A final has priority over a queued preview, but an uninterrupted
        # stream can produce another final while that one is decoding.  Always
        # taking finals in that case freezes the visible caption even though a
        # fresh preview is waiting.  Live alternates one fresh preview between
        # finals while capture is still open; stop() keeps draining finals.
        self._last_task = ""
        self._audio_gap_reported = False
        self._slow_reported = False
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

    def note_audio_gap(self, dropped_blocks: int) -> None:
        """Surface capture overload without turning a Live session fatal."""

        if dropped_blocks > 0 and not self.cancel.is_set() and not self._audio_gap_reported:
            self._audio_gap_reported = True
            self.on_status("live_audio_gap")

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
        chunk = (*chunk, self._lead_for(chunk))
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
        """Keep the newest unstarted phrase, joined to the one it displaces.

        A speaker who does not pause produces finals faster than a slow machine
        decodes them, and the phrase that was waiting used to be discarded.
        Measured on a 7.7 s clip, that lost the entire spoken sentence to a half
        second of trailing sound.  Neighbouring phrases are the same utterance
        cut by the length limit, so joining them keeps every word and gives the
        decoder more context than either half had.  Audio is only dropped when
        the join would grow past what one window can decode.
        """

        dropped = False
        while True:
            try:
                self.queue.put_nowait(chunk)
                return dropped
            except Full:
                try:
                    waiting = self.queue.get_nowait()
                except Empty:
                    continue
                merged = self._merge_finals(waiting, chunk)
                if merged is None:
                    dropped = True
                else:
                    chunk = merged

    def _lead_for(self, chunk):
        """Audio to put in front of a phrase too short to recognise alone.

        Only the end of the phrase immediately before qualifies: context from
        somewhere else in the recording would put words in the caption that
        nobody said next to these.
        """

        offset, audio = chunk
        if len(audio) >= int(SHORT_FINAL_SECONDS * SAMPLE_RATE):
            return None
        lead = self.buffer.lead
        if lead is None or not len(lead):
            return None
        if abs(offset - self.buffer.lead_end) > FINAL_MERGE_GAP_SECONDS:
            return None
        return lead

    @staticmethod
    def _merge_finals(waiting, arriving):
        """Join two queued phrases, or return None if they must stay apart."""

        start, audio, lead = waiting
        next_start, next_audio, _next_lead = arriving
        gap = next_start - (start + len(audio) / SAMPLE_RATE)
        if not -FINAL_MERGE_GAP_SECONDS <= gap <= FINAL_MERGE_GAP_SECONDS:
            return None
        joined = len(audio) + len(next_audio)
        if joined > int(FINAL_MERGE_LIMIT_SECONDS * SAMPLE_RATE):
            return None
        if joined >= int(SHORT_FINAL_SECONDS * SAMPLE_RATE):
            # Long enough to stand on its own now, so it no longer needs the
            # phrase before it for context.
            lead = None
        return (start, np.concatenate((audio, next_audio)), lead)

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
        # Every final restarts the phrase clock. An unbounded interval can
        # become longer than a phrase, permanently disabling all previews
        # after one slow decode. Queued snapshots already coalesce, so cap the
        # cadence to leave a refresh opportunity inside each full phrase.
        ceiling = max(self._preview_interval_samples, self.buffer.limit // 2)
        return min(ceiling, max(self._preview_interval_samples, measured))

    def _note_decode(self, seconds, audio_seconds=0.0, *, preview=True):
        """Follow the measured decode time, favouring the recent past.

        A machine that spends longer on a window than the window lasts can
        never catch up: previews thin out and the phrase arrives late.  That is
        worth saying once, from the measurement rather than from a guess about
        the hardware.
        """

        if preview:
            # A merged final can contain 15 seconds of sound. Its cost does
            # not predict the cost of the next short rolling preview.
            if self._decode_seconds <= 0.0:
                self._decode_seconds = seconds
            else:
                self._decode_seconds += (seconds - self._decode_seconds) * 0.3
        if (
            self.catch_up
            and not self._slow_reported
            and audio_seconds > 0.0
            and seconds > audio_seconds
        ):
            self._slow_reported = True
            self.on_status("live_slow")

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
                # Stop means "keep what I said".  A phrase still waiting here is
                # the end of that speech, so the tail joins it instead of
                # replacing it; the queue holds one phrase, so this cannot turn
                # into a long drain.  Cancel still throws the backlog away.
                tail = self.buffer.flush()
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
        # While Live is capturing, let one fresh preview through after a final.
        # This preserves the screen cadence during continuous speech without
        # allowing previews to starve final persistence. Once stop() closes the
        # session, finals drain immediately so the saved transcript is complete.
        if self.catch_up and not self.closed.is_set() and self._last_task == "final":
            preview = self._take_preview()
            if preview is not None:
                self._last_task = "preview"
                return "preview", preview

        # Finals must make progress even while capture keeps replacing previews.
        # Catch-up already bounds this queue to the newest unstarted phrase.
        try:
            task = self.queue.get_nowait()
            self._last_task = "final"
            return "final", task
        except Empty:
            pass
        preview = self._take_preview()
        if preview is None:
            return None
        self._last_task = "preview"
        return "preview", preview

    def _take_preview(self):
        with self._preview_lock:
            preview = self._preview
            self._preview = None
        return preview

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
            # Whisper often settles capitalization and punctuation a decode
            # later.  Those cosmetic corrections must not make already read
            # words flash back into the provisional tail.
            if old.casefold().translate(_PREVIEW_PUNCTUATION) != new.casefold().translate(_PREVIEW_PUNCTUATION):
                break
            count += 1
        return " ".join(new_words[:count])

    @staticmethod
    def _overlapping_word_prefix(previous, current):
        """Return the current prefix that agrees with the old window tail.

        Rolling previews deliberately shift their audio start on long speech.
        Comparing two whole strings then loses agreement at every shift even
        though most of the audible words are shared.  One matching word is too
        weak for Russian filler words, so only a two-word overlap is stable.
        """

        old_words, new_words = previous.split(), current.split()
        for count in range(min(len(old_words), len(new_words)), 1, -1):
            if all(
                old_words[-count + index].casefold().translate(_PREVIEW_PUNCTUATION)
                == new_words[index].casefold().translate(_PREVIEW_PUNCTUATION)
                for index in range(count)
            ):
                return " ".join(new_words[:count])
        return ""

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
        self._note_decode(monotonic() - started, len(audio) / SAMPLE_RATE)
        if not received and result:
            received.extend(dict(segment) for segment in result)
        if not self._preview_can_emit(generation):
            return
        text = self._text(received)
        if not text:
            return
        final_end = offset + len(audio) / SAMPLE_RATE
        if offset == self._last_preview_offset:
            agreed = self._common_word_prefix(self._last_preview_text, text)
        elif self._last_preview_end is not None and offset < self._last_preview_end:
            agreed = self._overlapping_word_prefix(self._last_preview_text, text)
        else:
            agreed = ""
        self._last_preview_text = text
        self._last_preview_offset = offset
        self._last_preview_end = final_end
        # Agreement can grow while the decoder preserves the same words. If
        # it revises them, the old prefix is no longer confirmed: publishing
        # it beside the new hypothesis would splice two different sentences.
        self._stable_prefix = agreed
        stable_text = self._stable_prefix
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

    def _transcribe_final(self, offset, audio, lead=None):
        self._last_preview_text = ""
        self._stable_prefix = ""
        self._last_preview_offset = None
        self._last_preview_end = None
        emitted = False
        end = offset + len(audio) / SAMPLE_RATE

        def emit(segment):
            nonlocal emitted
            if not self.cancel.is_set() and str(segment.get("text", "")).strip():
                emitted = True
                self._last_final_text = str(segment["text"]).strip()
                self.on_segment({
                    **segment,
                    "start": segment["start"] + offset,
                    "end": segment["end"] + offset,
                    "audio_end": end,
                })

        started = monotonic()
        if lead is None:
            self.engine.transcribe(audio, self.config, self.cancel, emit, self.on_status)
        else:
            text = self._drop_lead(self._last_final_text, self._decode(lead, audio))
            if text is None:
                # The two decodes disagree about the shared audio, so which
                # words are new cannot be told.  Ask again about the phrase
                # alone: that is what would have happened without the context,
                # and it cannot repeat text the user is already reading.
                text = self._decode(None, audio)
            if text:
                emit({"start": 0.0, "end": len(audio) / SAMPLE_RATE, "text": text})
        self._note_decode(monotonic() - started, len(audio) / SAMPLE_RATE, preview=False)
        if self.catch_up and not emitted and not self.cancel.is_set():
            self.on_status("live_no_text")

    def _decode(self, lead, audio):
        window = audio if lead is None else np.concatenate((lead, audio))
        collected: list[dict[str, Any]] = []
        result = self.engine.transcribe(
            window, self.config, self.cancel, collected.append, self.on_status
        )
        if not collected and result:
            collected.extend(dict(segment) for segment in result)
        return self._text(collected)

    @staticmethod
    def _drop_lead(previous, text):
        """Remove from ``text`` the words that already ended ``previous``.

        The window was widened with audio that has been recognised once
        already, so its words come back a second time.  They are matched on
        stems, because the same speech decoded inside a longer window comes
        back in a different form often enough: "чак-чак" against "чак чак".

        The phrase before was cut where the speaker paused, which can fall
        inside a word: "чак-чак" ended one caption as "ч".  So the last words of
        ``previous`` are allowed to be missing from the match, and the words
        they stand for are removed from the result as well.

        Returns None when no repetition is found at all, which means the two
        decodes did not agree and the caller must decide what to do.
        """

        words = text.split()
        if not previous or not words:
            return text
        old = [_stem(word) for word in previous.split()]
        new = [_stem(word) for word in words]
        for cut in (0, 1, 2):
            head = old[: len(old) - cut] if cut else old
            floor = 1 if cut == 0 else 2
            for size in range(min(len(head), len(new)), floor - 1, -1):
                if head[-size:] == new[:size]:
                    return " ".join(words[size + cut :]).strip()
        return None

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
