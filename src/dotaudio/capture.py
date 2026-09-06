"""Audio capture primitives with no Qt dependency.

The actual device libraries are imported lazily.  Audio callbacks do only
normalisation and a bounded queue put; user callbacks run on a helper thread,
so a slow visualizer cannot cause microphone overflows or block a UI thread.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
from typing import Any
from urllib.parse import urlsplit

import numpy as np

AudioCallback = Callable[[np.ndarray], None]
LevelCallback = Callable[[float], None]
ErrorCallback = Callable[[str], None]
_QUEUE_LIMIT = 24
_SAMPLE_RATE = 16000
_BLOCK_FRAMES = 1600


class _CallbackDispatcher:
    def __init__(
        self,
        on_audio: AudioCallback | None,
        on_level: LevelCallback | None,
        on_error: ErrorCallback | None,
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._events: Queue[tuple[str, Any] | None] = Queue(maxsize=_QUEUE_LIMIT)
        self._dispatch_stop = Event()
        self._dispatch_thread: Thread | None = None

    def _start_dispatcher(self) -> None:
        if self._dispatch_thread is not None and self._dispatch_thread.is_alive():
            return
        self._dispatch_stop.clear()
        self._dispatch_thread = Thread(
            target=self._dispatch_loop,
            name="DotAudioCallbacks",
            daemon=True,
        )
        self._dispatch_thread.start()

    def _stop_dispatcher(self) -> None:
        self._dispatch_stop.set()
        self._put_event(None)
        if self._dispatch_thread is not None:
            self._dispatch_thread.join(timeout=1.0)
        self._dispatch_thread = None

    def _put_event(self, event: tuple[str, Any] | None) -> None:
        try:
            self._events.put_nowait(event)
            return
        except Full:
            pass
        try:
            self._events.get_nowait()
        except Empty:
            pass
        try:
            self._events.put_nowait(event)
        except Full:
            return

    def _publish_audio(self, frames: np.ndarray) -> None:
        audio = self._normalise(frames)
        if not audio.size:
            return
        # RMS is stable enough for a 100 ms level meter and is cheap to
        # calculate in the realtime callback.
        level = float(np.sqrt(np.mean(np.square(audio, dtype=np.float32))))
        self._put_event(("audio", audio))
        self._put_event(("level", level))

    @staticmethod
    def _normalise(frames: np.ndarray) -> np.ndarray:
        audio = np.asarray(frames, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio.mean(axis=1, dtype=np.float32)
        if audio.ndim != 1:
            return np.empty(0, dtype=np.float32)
        # A copy is necessary because sounddevice/soundcard buffers are reused
        # as soon as their native callback returns.
        return np.ascontiguousarray(audio, dtype=np.float32).copy()

    def _error(self, message: str) -> None:
        self._put_event(("error", str(message)[:500]))

    def _dispatch_loop(self) -> None:
        while True:
            try:
                event = self._events.get(timeout=0.1)
            except Empty:
                if self._dispatch_stop.is_set():
                    return
                continue
            if event is None:
                return
            kind, value = event
            callback: Callable[[Any], None] | None
            if kind == "audio":
                callback = self._on_audio
            elif kind == "level":
                callback = self._on_level
            else:
                callback = self._on_error
            if callback is None:
                continue
            try:
                callback(value)
            except Exception:
                # A consumer error must not kill capture or prevent stop().
                continue


class AudioCapture(_CallbackDispatcher):
    """Capture 16 kHz mono PCM from a microphone or system loopback."""

    def __init__(
        self,
        kind: str = "microphone",
        device: int | str | None = None,
        on_audio: AudioCallback | None = None,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        if kind not in {"microphone", "system"}:
            raise ValueError("kind must be 'microphone' or 'system'")
        super().__init__(on_audio, on_level, on_error)
        self.kind = kind
        self.device = device
        self._stream: Any = None
        self._stop = Event()
        self._system_thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._start_dispatcher()
            try:
                if self.kind == "microphone":
                    self._start_microphone()
                else:
                    self._start_system_loopback()
            except Exception as exc:
                self._stop.set()
                self._stop_dispatcher()
                # The previous implementation only queued an error and then
                # immediately stopped its dispatcher.  A failed microphone
                # could therefore leave Live visually recording forever.
                raise RuntimeError(self._start_error(exc)) from exc

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            stream, self._stream = self._stream, None
            if stream is not None:
                for method in ("stop", "close"):
                    try:
                        getattr(stream, method)()
                    except Exception:
                        continue
            thread, self._system_thread = self._system_thread, None
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)
        self._stop_dispatcher()

    @property
    def running(self) -> bool:
        if self.kind == "microphone":
            return self._stream is not None and not self._stop.is_set()
        return self._system_thread is not None and self._system_thread.is_alive()

    def _start_error(self, error: Exception) -> str:
        if self.kind == "microphone":
            prefix = (
                "Не удалось открыть микрофон. Выберите другое устройство в "
                "разделе «Диктовка» и проверьте разрешение Windows для микрофона."
            )
        else:
            prefix = (
                "Не удалось открыть системный звук. Проверьте устройство вывода "
                "и драйвер, затем попробуйте микрофон."
            )
        return f"{prefix} Детали драйвера: {error}"

    def _start_microphone(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=_BLOCK_FRAMES,
            device=self.device,
            callback=self._microphone_callback,
        )
        self._stream.start()

    def _microphone_callback(
        self,
        indata: np.ndarray,
        _frames: int,
        _time: Any,
        status: Any,
    ) -> None:
        if status:
            self._error(f"microphone status: {status}")
        if not self._stop.is_set():
            self._publish_audio(indata)

    def _start_system_loopback(self) -> None:
        self._system_thread = Thread(
            target=self._system_loop,
            name="DotAudioSystemLoopback",
            daemon=True,
        )
        self._system_thread.start()

    def _system_loop(self) -> None:
        try:
            import soundcard as sc

            speaker = self._resolve_loopback_speaker(sc)
            if speaker is None:
                raise RuntimeError("no system output device available")
            with speaker.recorder(
                samplerate=_SAMPLE_RATE,
                channels=1,
                blocksize=_BLOCK_FRAMES,
            ) as recorder:
                while not self._stop.is_set():
                    self._publish_audio(recorder.record(numframes=_BLOCK_FRAMES))
        except Exception as exc:
            if not self._stop.is_set():
                self._error(f"system loopback failed: {exc}")

    def _resolve_loopback_speaker(self, soundcard: Any) -> Any:
        """Match a UI output-device id to the soundcard loopback endpoint."""

        device = self.device
        if device is None or device == "":
            return soundcard.default_speaker()
        if isinstance(device, int) or (isinstance(device, str) and device.isdigit()):
            try:
                import sounddevice as sd

                device = str(sd.query_devices(int(device), "output")["name"])
            except Exception:
                device = str(device)
        if not isinstance(device, str):
            return device
        try:
            return soundcard.get_speaker(device)
        except Exception:
            target = device.casefold()
            for speaker in soundcard.all_speakers():
                name = str(getattr(speaker, "name", ""))
                if name.casefold() == target or target in name.casefold() or name.casefold() in target:
                    return speaker
            raise RuntimeError(f"output device not found for loopback: {device}")


class StreamCapture(_CallbackDispatcher):
    """Decode an http(s) stream to 16 kHz mono PCM with FFmpeg."""

    def __init__(
        self,
        url: str,
        on_audio: AudioCallback | None = None,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        super().__init__(on_audio, on_level, on_error)
        self.url = self._validate_url(url)
        self._stop = Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._start_dispatcher()
            self._thread = Thread(
                target=self._read_loop,
                name="DotAudioStreamCapture",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            process, self._process = self._process, None
            thread, self._thread = self._thread, None
            if process is not None and process.poll() is None:
                process.terminate()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=3.0)
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        self._stop_dispatcher()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    @staticmethod
    def _validate_url(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("stream URL must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("stream URL must not contain userinfo")
        return url

    def _read_loop(self) -> None:
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rw_timeout",
            "10000000",
            "-i",
            self.url,
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(_SAMPLE_RATE),
            "pipe:1",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._process = process
            assert process.stdout is not None
            carry = b""
            bytes_per_block = _BLOCK_FRAMES * 2
            while not self._stop.is_set():
                chunk = process.stdout.read(bytes_per_block)
                if not chunk:
                    break
                carry += chunk
                while len(carry) >= bytes_per_block:
                    raw, carry = carry[:bytes_per_block], carry[bytes_per_block:]
                    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32)
                    self._publish_audio(audio / 32768.0)
            if not self._stop.is_set():
                self._error("stream ended or FFmpeg could not read the source")
        except Exception as exc:
            if not self._stop.is_set():
                self._error(f"stream capture failed: {exc}")
        finally:
            with self._lock:
                process, self._process = self._process, None
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass


def list_input_devices() -> list[dict[str, str | int]]:
    """Return microphone choices without importing sounddevice at startup."""

    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return []
    result: list[dict[str, str | int]] = []
    for index, device in enumerate(devices):
        try:
            channels = int(device["max_input_channels"])
            name = str(device["name"])
        except (KeyError, TypeError, ValueError):
            continue
        if channels > 0:
            result.append({"id": index, "name": name})
    return result


def list_output_devices() -> list[dict[str, str | int]]:
    """Return playback-device choices for the no-file headphone test."""

    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return []
    result: list[dict[str, str | int]] = []
    for index, device in enumerate(devices):
        try:
            channels = int(device["max_output_channels"])
            name = str(device["name"])
        except (KeyError, TypeError, ValueError):
            continue
        if channels > 0:
            result.append({"id": index, "name": name})
    return result


def play_output_tone(device: int | str | None, duration: float = 0.35) -> None:
    """Play a short low-volume test tone without writing an audio file."""

    if not 0 < duration <= 2:
        raise ValueError("duration must be between 0 and 2 seconds")
    import sounddevice as sd

    details = sd.query_devices(device, "output")
    rate = int(float(details["default_samplerate"]))
    frames = max(1, int(rate * duration))
    time = np.arange(frames, dtype=np.float32) / rate
    # A short fade avoids an audible click at the edges of the test tone.
    fade_frames = min(int(rate * 0.025), frames // 2)
    envelope = np.ones(frames, dtype=np.float32)
    if fade_frames:
        ramp = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
        envelope[:fade_frames] = ramp
        envelope[-fade_frames:] = ramp[::-1]
    tone = (0.12 * envelope * np.sin(2 * np.pi * 440 * time)).astype(np.float32)
    sd.play(tone, samplerate=rate, device=device, blocking=True)


__all__ = [
    "AudioCapture",
    "StreamCapture",
    "list_input_devices",
    "list_output_devices",
    "play_output_tone",
]
