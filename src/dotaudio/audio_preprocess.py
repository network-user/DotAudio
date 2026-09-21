"""Optional, bounded PCM preprocessing for speech recognition.

The module deliberately does not contain voice activity detection.  VAD answers
whether a frame looks like speech; this module changes the samples to reduce a
stationary noise floor before recognition.  It has no mandatory dependency
beyond NumPy and is safe to leave disabled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

DEFAULT_SAMPLE_RATE = 16000
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 96000
MIN_FRAME_MS = 8.0
MAX_FRAME_MS = 64.0
MIN_HOP_MS = 4.0
MAX_NOISE_PROFILE_SECONDS = 5.0


@dataclass(frozen=True)
class PreprocessConfig:
    """Configuration for the optional lightweight preprocessing pass.

    ``enabled`` is false by default because preprocessing is signal-dependent:
    a good microphone can sound worse when an aggressive gate is enabled.
    ``noise_seconds`` is used only when a separate ``noise_audio`` sample is
    not supplied to :func:`preprocess_audio`.
    """

    enabled: bool = False
    sample_rate: int = DEFAULT_SAMPLE_RATE
    frame_ms: float = 20.0
    hop_ms: float = 10.0
    noise_seconds: float = 0.35
    reduction_strength: float = 0.75
    spectral_floor: float = 0.08
    highpass_hz: float = 0.0


@dataclass(frozen=True)
class NoiseProfile:
    """Stationary noise spectrum compatible with one preprocessing config."""

    sample_rate: int
    frame_size: int
    hop_size: int
    magnitude: np.ndarray


def _finite_float(value: float, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def normalise_preprocess_config(config: PreprocessConfig | None) -> PreprocessConfig:
    """Return a safe config without allowing invalid values to reach the FFT."""

    source = config or PreprocessConfig()
    try:
        sample_rate = int(source.sample_rate)
    except (TypeError, ValueError):
        sample_rate = DEFAULT_SAMPLE_RATE
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        sample_rate = DEFAULT_SAMPLE_RATE

    frame_ms = min(
        MAX_FRAME_MS,
        max(MIN_FRAME_MS, _finite_float(source.frame_ms, PreprocessConfig.frame_ms)),
    )
    hop_ms = min(
        frame_ms,
        max(MIN_HOP_MS, _finite_float(source.hop_ms, PreprocessConfig.hop_ms)),
    )
    noise_seconds = min(
        MAX_NOISE_PROFILE_SECONDS,
        max(0.0, _finite_float(source.noise_seconds, PreprocessConfig.noise_seconds)),
    )
    reduction_strength = min(
        1.0,
        max(0.0, _finite_float(source.reduction_strength, PreprocessConfig.reduction_strength)),
    )
    spectral_floor = min(
        1.0,
        max(0.0, _finite_float(source.spectral_floor, PreprocessConfig.spectral_floor)),
    )
    highpass_hz = min(
        sample_rate * 0.45,
        max(0.0, _finite_float(source.highpass_hz, PreprocessConfig.highpass_hz)),
    )
    return PreprocessConfig(
        enabled=bool(source.enabled),
        sample_rate=sample_rate,
        frame_ms=frame_ms,
        hop_ms=hop_ms,
        noise_seconds=noise_seconds,
        reduction_strength=reduction_strength,
        spectral_floor=spectral_floor,
        highpass_hz=highpass_hz,
    )


def _as_mono(audio: np.ndarray) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1, dtype=np.float32)
    if samples.ndim != 1:
        raise ValueError("audio must be a mono 1-D or frame-by-channel 2-D array")
    return np.ascontiguousarray(
        np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0, copy=False),
        dtype=np.float32,
    )


def _frame_parameters(config: PreprocessConfig) -> tuple[int, int]:
    frame_size = max(64, int(round(config.sample_rate * config.frame_ms / 1000.0)))
    hop_size = max(1, int(round(config.sample_rate * config.hop_ms / 1000.0)))
    return frame_size, min(frame_size, hop_size)


def _frame_count(length: int, frame_size: int, hop_size: int) -> int:
    if length <= frame_size:
        return 1
    return 1 + int(math.ceil((length - frame_size) / hop_size))


def _padded_frames(
    audio: np.ndarray,
    frame_size: int,
    hop_size: int,
) -> tuple[np.ndarray, int]:
    count = _frame_count(audio.size, frame_size, hop_size)
    padded = np.zeros((count - 1) * hop_size + frame_size, dtype=np.float32)
    if audio.size:
        padded[: audio.size] = audio
    return padded, count


def _window(frame_size: int) -> np.ndarray:
    # A non-zero end point is useful for one-frame and very short recordings.
    window = np.hanning(frame_size).astype(np.float32)
    window[[0, -1]] = max(float(window.max()) * 1e-3, 1e-6)
    return window


def _spectra(
    audio: np.ndarray,
    frame_size: int,
    hop_size: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    padded, count = _padded_frames(audio, frame_size, hop_size)
    window = _window(frame_size)
    frames = np.empty((count, frame_size), dtype=np.float32)
    for index in range(count):
        start = index * hop_size
        frames[index] = padded[start : start + frame_size] * window
    spectra = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
    energies = np.mean(frames * frames, axis=1, dtype=np.float32)
    return spectra, energies, count


def estimate_noise_profile(
    audio: np.ndarray,
    config: PreprocessConfig | None = None,
    *,
    noise_seconds: float | None = None,
) -> NoiseProfile:
    """Estimate a stationary spectrum from the quietest supplied frames.

    A separate noise-only recording is preferred.  When the caller supplies a
    full recording, selecting the quietest half of its frames makes the default
    less likely to learn a single loud syllable as the noise floor.
    """

    safe = normalise_preprocess_config(config)
    frame_size, hop_size = _frame_parameters(safe)
    samples = _as_mono(audio)
    seconds = safe.noise_seconds if noise_seconds is None else _finite_float(noise_seconds, safe.noise_seconds)
    limit = max(1, int(min(MAX_NOISE_PROFILE_SECONDS, max(0.0, seconds)) * safe.sample_rate))
    if samples.size > limit:
        samples = samples[:limit]
    spectra, energies, _count = _spectra(samples, frame_size, hop_size)
    keep = max(1, int(math.ceil(spectra.shape[0] * 0.5)))
    selected = np.argpartition(energies, keep - 1)[:keep]
    magnitude = np.median(spectra[selected], axis=0).astype(np.float32)
    magnitude.setflags(write=False)
    return NoiseProfile(safe.sample_rate, frame_size, hop_size, magnitude)


def high_pass_filter(audio: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    """Apply a bounded first-order high-pass filter without external DSP libs."""

    samples = _as_mono(audio)
    cutoff = _finite_float(cutoff_hz, 0.0)
    rate = int(sample_rate)
    if not samples.size or cutoff <= 0.0:
        return samples.copy()
    if rate <= 0:
        raise ValueError("sample_rate must be positive")
    cutoff = min(cutoff, rate * 0.45)
    alpha = math.exp(-2.0 * math.pi * cutoff / rate)
    result = np.empty_like(samples)
    result[0] = samples[0]
    for index in range(1, samples.size):
        result[index] = alpha * (result[index - 1] + samples[index] - samples[index - 1])
    return result


def reduce_stationary_noise(
    audio: np.ndarray,
    profile: NoiseProfile,
    *,
    reduction_strength: float = 0.75,
    spectral_floor: float = 0.08,
) -> np.ndarray:
    """Reduce stationary noise with a soft spectral gate and overlap-add."""

    samples = _as_mono(audio)
    if not samples.size:
        return samples.copy()
    if profile.magnitude.ndim != 1 or profile.magnitude.size != profile.frame_size // 2 + 1:
        raise ValueError("noise profile does not match its frame size")
    strength = min(1.0, max(0.0, _finite_float(reduction_strength, 0.75)))
    floor = min(1.0, max(0.0, _finite_float(spectral_floor, 0.08)))
    padded, count = _padded_frames(samples, profile.frame_size, profile.hop_size)
    window = _window(profile.frame_size)
    output = np.zeros_like(padded, dtype=np.float32)
    weights = np.zeros_like(padded, dtype=np.float32)
    noise = np.asarray(profile.magnitude, dtype=np.float32)
    epsilon = np.float32(1e-7)
    for index in range(count):
        start = index * profile.hop_size
        frame = padded[start : start + profile.frame_size] * window
        spectrum = np.fft.rfft(frame)
        magnitude = np.abs(spectrum).astype(np.float32)
        attenuation = noise / np.maximum(magnitude, noise + epsilon)
        gain = np.clip(1.0 - strength * attenuation, floor, 1.0)
        cleaned = np.fft.irfft(spectrum * gain, n=profile.frame_size).real.astype(np.float32)
        output[start : start + profile.frame_size] += cleaned * window
        weights[start : start + profile.frame_size] += window * window
    result = output / np.maximum(weights, 1e-6)
    result = result[: samples.size]
    return np.ascontiguousarray(np.clip(np.nan_to_num(result), -1.0, 1.0), dtype=np.float32)


def preprocess_audio(
    audio: np.ndarray,
    config: PreprocessConfig | None = None,
    *,
    noise_audio: np.ndarray | None = None,
    noise_profile: NoiseProfile | None = None,
) -> np.ndarray:
    """Return processed audio while preserving its length and sample format.

    The operation is opt-in.  ``noise_audio`` should contain a short sample of
    the stationary background without speech; otherwise a quiet prefix of the
    input is used.  A precomputed ``noise_profile`` avoids repeating that work
    for a sequence of bounded live windows.
    """

    safe = normalise_preprocess_config(config)
    samples = _as_mono(audio)
    if not safe.enabled or not samples.size:
        return samples.copy()
    filtered = high_pass_filter(samples, safe.sample_rate, safe.highpass_hz)
    profile = noise_profile
    if profile is None:
        source = filtered if noise_audio is None else high_pass_filter(
            noise_audio, safe.sample_rate, safe.highpass_hz
        )
        profile = estimate_noise_profile(source, safe)
    cleaned = reduce_stationary_noise(
        filtered,
        profile,
        reduction_strength=safe.reduction_strength,
        spectral_floor=safe.spectral_floor,
    )
    return cleaned


__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "NoiseProfile",
    "PreprocessConfig",
    "estimate_noise_profile",
    "high_pass_filter",
    "normalise_preprocess_config",
    "preprocess_audio",
    "reduce_stationary_noise",
]
