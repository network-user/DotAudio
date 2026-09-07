"""Live recognition on real recordings, opt-in.

The unit suite must run without a model download or a microphone, so these
checks are skipped unless the audio is present.  Prepare it once with

    .venv\\Scripts\\python.exe .local-bench\\extract.py

or point DOTAUDIO_MEDIA_DIR at a directory holding 16 kHz mono WAV files named
``speech_video.wav`` and ``song_2.wav``.  Nothing here is synthesised: the
speech is a recorded clip with two voices and the music is a released track,
because the failures worth catching only show up on real sound.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import pytest

from dotaudio.engine import Engine, RecognitionConfig
from dotaudio.pipeline import (
    LIVE_PHRASE_SECONDS,
    LIVE_SILENCE_SECONDS,
    LIVE_SPEECH_THRESHOLD,
    SAMPLE_RATE,
    SpeechBuffer,
    open_voice_activity,
)

MEDIA = Path(os.environ.get("DOTAUDIO_MEDIA_DIR", ".local-bench"))
MODEL = os.environ.get("DOTAUDIO_MEDIA_MODEL", "small")


def _load(name: str) -> np.ndarray:
    path = MEDIA / name
    if not path.exists():
        pytest.skip(f"нет записи {path}; см. docstring модуля")
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            pytest.skip(f"{path} не 16 кГц моно")
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def _phrases(audio: np.ndarray) -> list[np.ndarray]:
    """Endpoint the recording exactly as Live does, without any timing."""

    buffer = SpeechBuffer(
        max_seconds=LIVE_PHRASE_SECONDS,
        silence_seconds=LIVE_SILENCE_SECONDS,
        threshold=LIVE_SPEECH_THRESHOLD,
        detector=open_voice_activity(),
    )
    found = []
    for offset in range(0, len(audio), 1024):
        chunk = buffer.feed(audio[offset : offset + 1024])
        if chunk is not None:
            found.append(chunk[1])
    tail = buffer.flush()
    if tail is not None:
        found.append(tail[1])
    return found


@pytest.fixture(scope="module")
def live():
    engine = Engine()
    config = RecognitionConfig(
        model=MODEL, device="cpu", language="ru", live_stream=True
    )

    def recognise(window: np.ndarray) -> str:
        return " ".join(
            segment["text"] for segment in engine.transcribe(window, config)
        )

    return recognise


def test_recorded_speech_is_recognised_as_the_words_that_were_said(live) -> None:
    audio = _load("speech_video.wav")
    phrases = _phrases(audio)
    assert phrases, "детектор речи не нашёл речь в записи"
    # The longest phrase carries the sentence; short scraps around it are the
    # business of the endpointing tests, not of this one.
    text = live(max(phrases, key=len)).casefold().replace("ё", "е")
    for word in ("тесто", "мед", "чак"):
        assert word in text, f"в расшифровке нет слова {word!r}: {text!r}"


def test_music_alone_does_not_become_a_caption(live) -> None:
    audio = _load("song_2.wav")
    spoken = [live(phrase) for phrase in _phrases(audio)]
    # An instrumental track has no words in it.  Before the confidence check
    # the decoder answered a one second fragment of it with "Слышишь?".
    assert not any(spoken), f"музыка распозналась как речь: {spoken!r}"


def test_music_is_mostly_rejected_before_it_reaches_the_decoder() -> None:
    audio = _load("song_2.wav")
    passed = sum(len(phrase) for phrase in _phrases(audio)) / SAMPLE_RATE
    # Voice activity is the cheap gate: a track that nobody sings over should
    # not cost a decode every second.
    assert passed < 0.1 * len(audio) / SAMPLE_RATE
