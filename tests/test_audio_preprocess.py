from __future__ import annotations

import numpy as np

from dotaudio.audio_preprocess import PreprocessConfig, preprocess_audio


def test_preprocess_is_noop_when_disabled() -> None:
    source = np.array([0.0, 0.2, -0.3], dtype=np.float32)
    result = preprocess_audio(source, PreprocessConfig(enabled=False))
    assert np.array_equal(result, source)
    assert result.dtype == np.float32


def test_preprocess_preserves_length_and_finite_samples() -> None:
    rng = np.random.default_rng(4)
    source = (0.02 * rng.standard_normal(4097)).astype(np.float32)
    source[10] = np.nan
    source[20] = np.inf
    result = preprocess_audio(
        source,
        PreprocessConfig(enabled=True, highpass_hz=80.0),
    )
    assert result.shape == source.shape
    assert result.dtype == np.float32
    assert np.isfinite(result).all()
    assert np.max(np.abs(result)) <= 1.0
