from __future__ import annotations

import numpy as np

from dotaudio.karaoke_align import align_words, compute_peaks, energy_times


def _audio(seconds: float = 2.2, rate: int = 16000) -> np.ndarray:
    # Ритмичный «говор»: короткие громкие всплески с паузами-шумом на фоне.
    rng = np.random.default_rng(7)
    x = np.zeros(int(seconds * rate), dtype=np.float32)
    for low, high in ((0.15, 0.55), (1.35, 1.75)):
        x[int(low * rate): int(high * rate)] = 0.5
    x += rng.normal(0.0, 0.02, x.shape).astype(np.float32)
    return np.clip(x, -1.0, 1.0)


def test_energy_times_shape_and_order() -> None:
    x = _audio()
    rms, times = energy_times(x, 16000)
    assert rms.shape == times.shape
    assert times[1] > times[0]
    assert rms.min() >= 0.0


def test_align_words_preserves_text_and_order_and_minimal_duration() -> None:
    words = [
        {"text": "а", "start": 0.2, "end": 0.55},
        {"text": "б", "start": 1.4, "end": 2.0},
    ]
    x = _audio()
    out = align_words(words, x, 16000)
    assert [w["text"] for w in out] == ["а", "б"]
    for i in range(1, len(out)):
        assert out[i]["start"] >= out[i - 1]["end"] - 1e-6
    for w in out:
        assert w["start"] >= 0
        assert w["end"] >= w["start"]
        assert w["end"] - w["start"] >= 0.029


def test_align_finite_on_empty_and_silent_audio() -> None:
    assert align_words([], np.zeros(1600, dtype=np.float32), 16000) == []
    words = [{"text": "а", "start": 0.0, "end": 0.1}, {"text": "б", "start": 0.2, "end": 0.3}]
    silent = np.zeros(16000, dtype=np.float32)
    out = align_words(words, silent, 16000)
    assert all(float(w["start"]) >= 0 for w in out)


def test_align_rejects_unusable_lines_without_error() -> None:
    # Одна точка без второй волны - возвращаем как есть, не падаем.
    x = _audio(0.8)
    out = align_words([{"text": "только", "start": 0.0, "end": 0.1}], x, 16000)
    assert len(out) == 1


def test_align_keeps_texts_intact_after_nudge() -> None:
    words = [
        {"text": "раз", "start": 0.18, "end": 0.6},
        {"text": "два", "start": 1.3, "end": 1.8},
        {"text": "три", "start": 1.8, "end": 2.2},
    ]
    out = align_words(words, _audio(2.4), 16000)
    assert [w["text"] for w in out] == ["раз", "два", "три"]
    # соседняя строка уводит правый край, но не раньше предыдущей
    assert out[1]["start"] >= out[0]["end"] - 1e-6


def test_compute_peaks_normalizes_and_reports_duration() -> None:
    x = _audio(1.0)
    peaks, duration = compute_peaks(x, 16000, buckets=32)
    assert len(peaks) == 32
    assert abs(duration - 1.0) < 0.02
    assert max(peaks) <= 1.0 + 1e-6
    assert min(peaks) >= 0.0
