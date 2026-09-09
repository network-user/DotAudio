"""Save WAV clips around keyword matches from a PCM ring buffer."""

from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

try:
    from dotaudio import capture as _capture

    SAMPLE_RATE = int(getattr(_capture, "SAMPLE_RATE", getattr(_capture, "_SAMPLE_RATE", 16000)))
except ImportError:
    SAMPLE_RATE = 16000


class PcmRing:
    """Keep last ``seconds`` of float32 mono PCM."""

    def __init__(self, seconds: float = 60.0, sample_rate: int = SAMPLE_RATE) -> None:
        self._sample_rate = int(sample_rate)
        self._capacity = max(1, int(round(seconds * self._sample_rate)))
        self._buffer = np.zeros(self._capacity, dtype=np.float32)
        self._write_pos = 0
        self._total_samples = 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def written_seconds(self) -> float:
        return self._total_samples / float(self._sample_rate)

    def write(self, audio: np.ndarray) -> None:
        chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return

        if chunk.size >= self._capacity:
            self._total_samples += chunk.size
            chunk = chunk[-self._capacity :]
            self._buffer[:] = chunk
            self._write_pos = 0
            return

        first = min(chunk.size, self._capacity - self._write_pos)
        self._buffer[self._write_pos : self._write_pos + first] = chunk[:first]
        remainder = chunk.size - first
        if remainder:
            self._buffer[:remainder] = chunk[first:]
        self._write_pos = (self._write_pos + chunk.size) % self._capacity
        self._total_samples += chunk.size

    def dump(self) -> np.ndarray:
        """Return the samples still held by the ring, oldest first.

        Used by dictation refine: the whole take is re-decoded after Stop, then
        this buffer is dropped so the temporary audio never stays on disk.
        """

        if self._total_samples == 0:
            return np.zeros(0, dtype=np.float32)
        kept = min(self._total_samples, self._capacity)
        if kept < self._capacity:
            return self._buffer[:kept].astype(np.float32, copy=True)
        start = self._write_pos
        return np.concatenate(
            (self._buffer[start:], self._buffer[:start])
        ).astype(np.float32, copy=True)

    def slice(self, start_sec: float, end_sec: float, *, stream_end_sec: float) -> np.ndarray | None:
        if end_sec <= start_sec or self._total_samples == 0:
            return None

        start_sample = int(round(start_sec * self._sample_rate))
        end_sample = int(round(end_sec * self._sample_rate))
        oldest = max(0, self._total_samples - min(self._total_samples, self._capacity))
        stream_limit = int(round(stream_end_sec * self._sample_rate))
        newest = min(self._total_samples, stream_limit)

        start_sample = max(start_sample, oldest)
        end_sample = min(end_sample, newest)
        if start_sample >= end_sample:
            return None

        base = max(0, self._total_samples - min(self._total_samples, self._capacity))
        offsets = np.arange(start_sample, end_sample, dtype=np.int64) - base
        indices = (self._write_pos + offsets) % self._capacity
        return self._buffer[indices].astype(np.float32, copy=True)


class WavStream:
    """Append float32 mono PCM to a PCM16 WAV as the stream arrives.

    Live can last much longer than a dictation take, so the full recording
    lives on disk instead of in a ring buffer. After the quality pass the
    controller deletes this file.
    """

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        self._closed = False
        self._frames = 0
        self._wf = wave.open(str(self.path), "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(self._sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def seconds(self) -> float:
        with self._lock:
            return self._frames / float(self._sample_rate) if self._sample_rate else 0.0

    def write(self, audio: np.ndarray) -> None:
        chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return
        pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
        with self._lock:
            if self._closed:
                return
            self._wf.writeframes(pcm.tobytes())
            self._frames += int(chunk.size)

    def close(self) -> Path:
        with self._lock:
            if not self._closed:
                self._wf.close()
                self._closed = True
        return self.path


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    """Write mono float32 audio as PCM16 WAV."""

    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(sample_rate))
        out.writeframes(pcm.tobytes())
    return path


def extract_match_clip(
    ring: PcmRing,
    *,
    match_start: float,
    match_end: float,
    stream_end: float,
    out_dir: Path,
    pre_seconds: float = 15.0,
    post_seconds: float = 15.0,
    stem: str = "hit",
) -> Path | None:
    """Extract a clip around a keyword match and save it as WAV."""

    clip_start = match_start - pre_seconds
    clip_end = match_end + post_seconds
    audio = ring.slice(clip_start, clip_end, stream_end_sec=stream_end)
    if audio is None or audio.size == 0:
        return None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}.wav"
    suffix = 1
    while target.exists():
        target = out_dir / f"{stem}_{suffix}.wav"
        suffix += 1
    return write_wav(target, audio, sample_rate=ring.sample_rate)
