"""Проверки Live на реальном аудио, запускаемые только явно.

Задайте DOTAUDIO_MEDIA_TESTS=1 и DOTAUDIO_MEDIA_DIR с WAV 16 кГц, mono,
PCM16: speech_video.wav, song_2.wav ... song_6.wav, song_lantern.wav.
По умолчанию каталог .local-check/media, модель small из локального кеша;
другая модель задаётся DOTAUDIO_MEDIA_MODEL. Скачивания нет.

DOTAUDIO_LOOPBACK_TEST=1 отдельно разрешает 12 секунд системного звука.
Длительность ограничена DOTAUDIO_LOOPBACK_SECONDS (1..60), устройство можно
задать DOTAUDIO_LOOPBACK_DEVICE. DOTAUDIO_LOOPBACK_PLAY с путём к WAV
заставляет проверку самой играть файл в выход по умолчанию во время захвата:
тогда проверка не зависит от того, играет ли на машине что-то прямо сейчас.
Файл нужен с речью или явным вокалом (например song_4.wav): инструментал
VAD справедливо пропускает, и черновиков не будет. Микрофон эти проверки
не открывают. Музыка без вокала не обязана давать текст; слова песен в
отчёт не выводятся.
"""

from __future__ import annotations

import os
import threading
import wave
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import numpy as np
import pytest

from dotaudio.capture import AudioCapture
from dotaudio.engine import Engine, RecognitionConfig
from dotaudio.pipeline import (
    LIVE_PHRASE_SECONDS,
    LIVE_SILENCE_SECONDS,
    LIVE_SPEECH_THRESHOLD,
    SAMPLE_RATE,
    LiveSession,
    SpeechBuffer,
    open_voice_activity,
)

MEDIA = Path(os.environ.get("DOTAUDIO_MEDIA_DIR", ".local-check/media"))
MODEL = os.environ.get("DOTAUDIO_MEDIA_MODEL", "small")
media_only = pytest.mark.skipif(
    os.environ.get("DOTAUDIO_MEDIA_TESTS") != "1",
    reason="реальные записи: требуется DOTAUDIO_MEDIA_TESTS=1",
)


def _load(name: str) -> np.ndarray:
    path = MEDIA / name
    if not path.exists():
        pytest.skip(f"нет записи {path}; см. docstring модуля")
    with wave.open(str(path), "rb") as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (
            SAMPLE_RATE, 1, 2,
        ), f"{path} должен быть PCM16, 16 кГц, mono"
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


class _Capture:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.fixture(scope="module")
def engine():
    return Engine()


@pytest.fixture(scope="module")
def config():
    from faster_whisper.utils import download_model

    if Path(MODEL).is_dir():
        local_model = MODEL
    else:
        try:
            local_model = download_model(MODEL, local_files_only=True)
        except Exception as error:
            pytest.skip(f"локальная модель {MODEL} недоступна: {type(error).__name__}")
    return RecognitionConfig(model=local_model, device="cpu", language="ru", live_stream=True)


@pytest.fixture(scope="module")
def live(engine, config):
    def recognise(window: np.ndarray) -> str:
        return " ".join(
            segment["text"] for segment in engine.transcribe(window, config)
        )

    return recognise


def _captions(
    engine: Engine, config: RecognitionConfig, audio: np.ndarray,
    *, updates: list[dict] | None = None,
) -> list[str]:
    """Run the whole Live path over a recording and return what it recorded."""

    done = Event()
    finals: list[dict] = []
    completed: list[tuple[str, bool]] = []

    def finish(error: str, cancelled: bool) -> None:
        completed.append((error, cancelled))
        done.set()

    def partial(segment: dict) -> None:
        if updates is not None:
            updates.append(segment)

    engine.prepare(config)
    session = LiveSession(
        engine, config, finals.append, lambda _status: None,
        finish, partial,
        catch_up=True, detector=open_voice_activity(),
    )
    session.start(_Capture())
    started = monotonic()
    try:
        for offset in range(0, len(audio), 1024):
            block = audio[offset : offset + 1024]
            session.feed(block)
            assert not done.is_set(), f"Live завершился до конца аудио: {completed}"
            sleep(max(0, started + (offset + len(block)) / SAMPLE_RATE - monotonic()))
        session.stop()
        assert done.wait(30), "живая сессия не завершилась за 30 с после stop"
        assert completed == [("", False)], f"ошибка завершения Live: {completed}"
        for segment in finals:
            assert 0 <= float(segment["start"]) <= float(segment["end"])
            assert np.isfinite(float(segment["end"]))
    finally:
        if not done.is_set():
            session.stop(cancel=True)
    return [str(final["text"]) for final in finals]


@media_only
def test_live_records_the_whole_sentence_that_was_said(engine, config) -> None:
    audio = _load("speech_video.wav")
    text = " ".join(_captions(engine, config, audio)).casefold().replace("ё", "е")
    # Every part of the clip, including the reply at the very end, which used to
    # be lost: the queue dropped it, Stop dropped it, and the token budget cut
    # the sentence before it.
    for word in ("мед", "тесто", "чак", "вкусненько"):
        assert word in text, f"в расшифровке нет слова {word!r}: {text!r}"


@media_only
def test_live_keeps_emitting_after_repeated_real_speech(engine, config, record_property) -> None:
    clip = _load("speech_video.wav")
    updates: list[dict] = []
    captions = _captions(engine, config, np.tile(clip, 3), updates=updates)
    # One good first caption does not establish a healthy stream. Exercise
    # several final boundaries and require fresh previews beyond the first clip.
    assert len(captions) >= 2, "новые финальные фразы перестали приходить"
    assert any(float(update["start"]) >= len(clip) / SAMPLE_RATE for update in updates), (
        "после первого фрагмента перестали приходить свежие черновики"
    )
    record_property("previews", len(updates))
    record_property("finals", len(captions))


@media_only
def test_music_alone_does_not_become_a_caption(live) -> None:
    audio = _load("song_2.wav")
    spoken = [live(phrase) for phrase in _phrases(audio)]
    # An instrumental track has no words in it.  Before the confidence check
    # the decoder answered a one second fragment of it with "Слышишь?".
    assert not any(spoken), "инструментальный фрагмент распознался как речь"


@media_only
def test_music_is_mostly_rejected_before_it_reaches_the_decoder() -> None:
    audio = _load("song_2.wav")
    passed = sum(len(phrase) for phrase in _phrases(audio)) / SAMPLE_RATE
    # Voice activity is the cheap gate: a track that nobody sings over should
    # not cost a decode every second.
    assert passed < 0.1 * len(audio) / SAMPLE_RATE


@media_only
@pytest.mark.parametrize("name", [f"song_{n}.wav" for n in range(2, 7)] + ["song_lantern.wav"])
def test_song_live_keeps_running_and_stops(engine, config, name, record_property) -> None:
    audio = _load(name)[:20 * SAMPLE_RATE]
    previews: list[dict] = []
    captions = _captions(engine, config, audio, updates=previews)
    record_property("audio_seconds", len(audio) / SAMPLE_RATE)
    record_property("previews", len(previews))
    record_property("finals", len(captions))
    # Singing may yield words; instrumentals may yield none. Neither should
    # terminate capture or hang Stop. A fixed lyric assertion is inappropriate.


def _play_to_default_output(path: Path, stop: Event) -> None:
    """Play a WAV to the default output the way a music player would."""

    import numpy as np
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(path), sampling_rate=48000)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    stereo = np.stack([audio, audio], axis=1).astype(np.float32)
    import soundcard as sc

    speaker = sc.default_speaker()
    with speaker.player(samplerate=48000, channels=2) as player:
        block = 48000
        for offset in range(0, len(stereo), block):
            if stop.is_set():
                return
            player.play(stereo[offset : offset + block])


@pytest.mark.skipif(
    os.environ.get("DOTAUDIO_LOOPBACK_TEST") != "1",
    reason="системный звук: требуется DOTAUDIO_LOOPBACK_TEST=1",
)
def test_current_system_audio_live(engine, config, record_property) -> None:
    seconds = float(os.environ.get("DOTAUDIO_LOOPBACK_SECONDS", "12"))
    assert 1 <= seconds <= 60
    play_path = os.environ.get("DOTAUDIO_LOOPBACK_PLAY") or ""
    stop_play = Event()
    player_thread = None
    if play_path:
        player_thread = threading.Thread(
            target=_play_to_default_output,
            args=(Path(play_path), stop_play),
            daemon=True,
        )
    engine.prepare(config)
    done = Event()
    audio_seen = Event()
    errors: list[str] = []
    completions: list[tuple[str, bool]] = []
    previews: list[dict] = []
    finals: list[dict] = []
    levels: list[float] = []

    def finish(error: str, cancelled: bool) -> None:
        completions.append((error, cancelled))
        done.set()

    session = LiveSession(
        engine, config, finals.append, lambda _status: None, finish,
        previews.append, catch_up=True, detector=open_voice_activity(),
    )

    def feed(audio: np.ndarray) -> None:
        audio_seen.set()
        session.feed(audio)

    capture = AudioCapture(
        kind="system", device=os.environ.get("DOTAUDIO_LOOPBACK_DEVICE") or None,
        on_audio=feed, on_level=levels.append, on_error=errors.append,
    )
    started = monotonic()
    try:
        session.start(capture)
        if player_thread is not None:
            player_thread.start()
        while monotonic() - started < seconds:
            assert not done.wait(0.1), f"Live остановился во время захвата: {completions}"
            assert not errors, f"ошибки захвата: {errors}"
        session.stop()
        assert done.wait(30), "Live завис после остановки системного звука"
        assert completions == [("", False)]
        assert audio_seen.is_set(), "WASAPI не прислал ни одного блока аудио"
        assert not errors, f"ошибки захвата: {errors}"
        peak = max(levels, default=0.0)
        assert not (play_path and peak < 0.001), (
            "loopback не услышал файл, который сами проигрывали в выход по умолчанию"
        )
        if play_path:
            # Вокальный трек обязан дать хотя бы один черновик: тишина здесь
            # означает, что Live не видит звук, а не что трек инструментальный.
            assert previews, "за время проигрывания вокального трека не было ни одного черновика"
        record_property("peak_rms", peak)
        record_property("previews", len(previews))
        record_property("finals", len(finals))
        print(f"loopback: blocks={len(levels)}, peak_rms={peak:.4f}, "
              f"previews={len(previews)}, finals={len(finals)}")
    finally:
        if not done.is_set():
            session.stop(cancel=True)
        capture.stop()
        stop_play.set()
