"""Light silence alignment of karaoke word timings (Qt-free).

Whisper word boundaries on music can drift by tens to hundreds of
milliseconds.  A deterministic cheap fix is to snap each word edge to the
quietest moment of the nearby waveform, reproducing the idea behind
stable-ts ``adjust_by_silence`` without a second model or an extra ASR pass.

The module never guesses text and never moves an edge that would cross a
neighbour or shrink below a minimum duration: it nudges toward a local RMS
minimum and then restores a monotonic, ordered timeline.  All timing is in
seconds, the same unit as the recognised ``words``.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from dotaudio.karaoke_edit import sanitize_word

FRAME = 0.030   # окно энергии
HOP = 0.010     # шаг сетки, одновременно сетка-время для границ
MAX_SHIFT = 0.25  # граница слова сдвигается не дальше этого от себя
MIN_DUR = 0.030   # минимальная заметная длительность слова


def energy_times(samples: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """RMS по сетке (FRAME/HOP) и момент времени центра каждого отсчёта."""
    x = np.ascontiguousarray(np.asarray(samples, dtype=np.float32).reshape(-1))
    frame = max(1, int(round(FRAME * rate)))
    hop = max(1, int(round(HOP * rate)))
    if len(x) < frame:
        x = np.pad(x, (0, frame - len(x)))
    n = (len(x) - frame) // hop + 1
    rms = np.empty(n, dtype=np.float32)
    for k in range(n):
        seg = x[k * hop : k * hop + frame]
        rms[k] = float(np.sqrt(np.mean(seg * seg)))
    times = (np.arange(n) * hop + frame / 2) / rate
    return rms, times


def align_words(
    words: Iterable[dict[str, Any]],
    samples: np.ndarray,
    rate: int,
    *,
    max_shift: float = MAX_SHIFT,
) -> list[dict[str, float]]:
    """Snap word edges toward local quiet; return ordered clean words.

    Only a usable line is edited (at least two words and enough audio).  The
    result keeps the same words, each with a non-decreasing timeline and a
    duration of at least MIN_DUR seconds.
    """
    clean: list[dict[str, float]] = []
    for raw in words:
        word = sanitize_word(raw)
        if word is not None:
            clean.append({"text": str(word["text"]), "start": float(word["start"]), "end": float(word["end"])})
    if len(clean) < 2 or samples is None or samples.size == 0:
        return clean
    rms, times = energy_times(samples, int(rate))
    if rms.size < 2:
        return clean

    def snap(time: float) -> float:
        """Вернуть секунду действия тишины вблизи `time` (не дальше зазора)."""
        lower = int(np.searchsorted(times, time - max_shift))
        upper = int(np.searchsorted(times, time + max_shift))
        if lower >= rms.size:
            return time
        upper = min(upper + 1, rms.size)
        window = rms[lower:upper]
        best = lower + int(np.argmin(window))
        return float(times[best])

    for word in clean:
        start_t = float(word["start"])
        end_t = float(word["end"])
        if end_t - start_t < FRAME:
            continue
        new_start = min(snap(start_t), end_t - MIN_DUR)
        new_end = max(snap(end_t), new_start + MIN_DUR)
        word["start"] = round(new_start, 4)
        word["end"] = round(new_end, 4)

    # восстанавливаем строгий порядок и минимальную длительность
    out = sorted(clean, key=lambda w: float(w["start"]))
    prev_end = -1.0
    result: list[dict[str, Any]] = []
    for w in out:
        start = max(prev_end, float(w["start"]))
        end = max(start, float(w["end"]))
        if end - start < MIN_DUR:
            end = start + MIN_DUR
        prev_end = end
        w["start"] = round(start, 4)
        w["end"] = round(end, 4)
        result.append(w)
    return result


def decode_file(path: str, rate: int = 16000) -> np.ndarray:
    """16 кГц моно float32 через faster-whisper (ffmpeg), без второй модели."""
    from faster_whisper.audio import decode_audio

    audio = decode_audio(path, sampling_rate=int(rate))
    arr = np.ascontiguousarray(audio, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    return arr.reshape(-1)


def compute_peaks(
    samples: np.ndarray,
    rate: int,
    buckets: int = 480,
) -> tuple[list[float], float]:
    """Downsample decoded audio to a short peak envelope for the media timeline.

    Runs off the GUI thread. Values are 0..1 (peak abs per bucket). Duration is
    derived from sample count so the QML scrubber matches the file, not the
    player metadata race on open.
    """
    x = np.ascontiguousarray(np.asarray(samples, dtype=np.float32).reshape(-1))
    duration = float(x.size) / float(max(1, int(rate)))
    count = max(1, int(buckets))
    if x.size == 0:
        return [0.0] * count, 0.0
    edges = np.linspace(0, x.size, count + 1, dtype=np.int64)
    peaks = np.empty(count, dtype=np.float32)
    for i in range(count):
        lo = int(edges[i])
        hi = max(lo + 1, int(edges[i + 1]))
        chunk = x[lo:hi]
        peaks[i] = float(np.max(np.abs(chunk))) if chunk.size else 0.0
    peak = float(np.max(peaks)) if peaks.size else 0.0
    if peak > 0:
        peaks = peaks / peak
    return [float(v) for v in peaks], duration
