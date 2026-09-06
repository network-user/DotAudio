"""Bounded live audio segmentation. Capture never waits for model inference."""

from collections import deque
from queue import Empty, Full, Queue
from threading import Event, Thread

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


class LiveSession:
    def __init__(self, engine: Engine, config: RecognitionConfig, on_segment, on_status, on_done):
        self.engine, self.config = engine, config
        self.on_segment, self.on_status, self.on_done = on_segment, on_status, on_done
        # Short phrases give subtitles a usable live cadence.  The engine VAD
        # remains a second guard against noise before Whisper runs.
        self.buffer = SpeechBuffer(max_seconds=4.0, silence_seconds=0.45, threshold=0.004)
        self.queue = Queue(maxsize=8)
        self.cancel = Event()
        self.closed = Event()
        self.failed = ""
        self.capture = None
        self.thread = Thread(target=self._run, name="dotaudio-recognize", daemon=True)

    def start(self, capture):
        self.capture = capture
        self.thread.start()
        try:
            capture.start()
        except Exception:
            self.cancel.set()
            self.closed.set()
            raise

    def feed(self, audio):
        if self.closed.is_set():
            return
        chunk = self.buffer.feed(audio)
        if chunk:
            self._enqueue(chunk)

    def _enqueue(self, chunk):
        try:
            self.queue.put_nowait(chunk)
        except Full:
            self.failed = "Модель не успевает за эфиром. Выберите меньшую модель или GPU."
            self.cancel.set()
            self.closed.set()

    def stop(self, cancel=False):
        if cancel:
            self.cancel.set()
        if self.capture:
            self.capture.stop()
        if not self.closed.is_set() and not cancel:
            tail = self.buffer.flush()
            if tail:
                self._enqueue(tail)
        self.closed.set()

    def _run(self):
        error = ""
        try:
            while not self.cancel.is_set():
                try:
                    offset, audio = self.queue.get(timeout=0.15)
                except Empty:
                    if self.closed.is_set():
                        break
                    continue
                def emit(segment, offset=offset):
                    if not self.cancel.is_set():
                        self.on_segment({**segment, "start": segment["start"] + offset,
                                         "end": segment["end"] + offset})
                self.engine.transcribe(audio, self.config, self.cancel, emit, self.on_status)
        except Exception as exc:
            error = str(exc)
        finally:
            self.closed.set()
            if self.capture:
                self.capture.stop()
            self.on_done(error or self.failed, self.cancel.is_set())
