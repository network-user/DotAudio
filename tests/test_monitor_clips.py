from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from dotaudio.monitor_clips import SAMPLE_RATE, PcmRing, extract_match_clip, write_wav


def test_pcm_ring_dump_returns_oldest_first() -> None:
    ring = PcmRing(seconds=1.0, sample_rate=10)
    ring.write(np.arange(15, dtype=np.float32))
    dumped = ring.dump()
    # Capacity 10: keep samples 5..14.
    np.testing.assert_array_equal(dumped, np.arange(5, 15, dtype=np.float32))


def test_pcm_ring_dump_before_wrap() -> None:
    ring = PcmRing(seconds=1.0, sample_rate=10)
    ring.write(np.arange(4, dtype=np.float32))
    np.testing.assert_array_equal(ring.dump(), np.arange(4, dtype=np.float32))


def test_pcm_ring_tracks_written_seconds() -> None:
    ring = PcmRing(seconds=1.0, sample_rate=100)
    ring.write(np.ones(50, dtype=np.float32))
    assert ring.written_seconds == pytest.approx(0.5)


def test_pcm_ring_slice_returns_requested_window() -> None:
    ring = PcmRing(seconds=2.0, sample_rate=10)
    ring.write(np.arange(30, dtype=np.float32))

    clip = ring.slice(1.0, 2.5, stream_end_sec=3.0)
    assert clip is not None
    np.testing.assert_array_equal(clip, np.arange(10, 25, dtype=np.float32))


def test_pcm_ring_keeps_only_last_seconds() -> None:
    ring = PcmRing(seconds=1.0, sample_rate=10)
    ring.write(np.full(10, 1.0, dtype=np.float32))
    ring.write(np.full(10, 2.0, dtype=np.float32))

    clip = ring.slice(0.5, 2.0, stream_end_sec=2.0)
    assert clip is not None
    assert clip.size == 10
    assert np.all(clip == 2.0)


def test_pcm_ring_slice_returns_none_outside_window() -> None:
    ring = PcmRing(seconds=1.0, sample_rate=10)
    ring.write(np.ones(5, dtype=np.float32))

    assert ring.slice(0.0, 0.2, stream_end_sec=0.5) is not None
    assert ring.slice(2.0, 3.0, stream_end_sec=0.5) is None


def test_write_wav_creates_pcm16_mono_file(tmp_path: Path) -> None:
    audio = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    path = write_wav(tmp_path / "clip.wav", audio, sample_rate=16000)

    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        assert len(wav.readframes(wav.getnframes())) == 6


def test_extract_match_clip_saves_context_around_match(tmp_path: Path) -> None:
    ring = PcmRing(seconds=5.0, sample_rate=10)
    ring.write(np.arange(50, dtype=np.float32))

    saved = extract_match_clip(
        ring,
        match_start=2.0,
        match_end=2.5,
        stream_end=5.0,
        out_dir=tmp_path,
        pre_seconds=1.0,
        post_seconds=1.0,
        stem="hit",
    )

    assert saved is not None
    assert saved.name == "hit.wav"
    with wave.open(str(saved), "rb") as wav:
        frames = wav.getnframes()
    assert frames == 25


def test_extract_match_clip_returns_none_without_audio(tmp_path: Path) -> None:
    ring = PcmRing(seconds=1.0, sample_rate=10)
    ring.write(np.ones(5, dtype=np.float32))

    assert (
        extract_match_clip(
            ring,
            match_start=100.0,
            match_end=100.5,
            stream_end=0.5,
            out_dir=tmp_path,
        )
        is None
    )

    empty = PcmRing(seconds=1.0, sample_rate=10)
    assert (
        extract_match_clip(
            empty,
            match_start=0.0,
            match_end=0.1,
            stream_end=0.0,
            out_dir=tmp_path / "empty",
        )
        is None
    )


def test_sample_rate_default_matches_project() -> None:
    assert SAMPLE_RATE == 16000
