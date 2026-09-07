"""Audio capture primitives with no Qt dependency.

The actual device libraries are imported lazily.  Audio callbacks do only
normalisation and a bounded queue put; user callbacks run on a helper thread,
so a slow visualizer cannot cause microphone overflows or block a UI thread.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
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
LIVE_SOURCES = ("system", "mixed", "microphone")
LIVE_SOURCE_LABELS = {
    "microphone": "Микрофон",
    "system": "Звук системы",
    "mixed": "Авто",
}


def describe_capture_error(kind: str, error: Exception | str) -> str:
    """Map driver exceptions to a named recovery hint.  Details stay attached."""

    detail = str(error)
    text = detail.casefold()
    if kind == "microphone":
        if any(token in text for token in ("denied", "permission", "access is denied", "not authorized")):
            return (
                "Нет доступа к микрофону. Откройте Параметры Windows → "
                "Конфиденциальность → Микрофон и разрешите DotAudio."
            )
        if any(token in text for token in ("invalid device", "device not found", "no such device", "-9996")):
            return (
                "Выбранный микрофон недоступен. Подключите его или выберите "
                "другое устройство в разделе «Диктовка»."
            )
        if any(token in text for token in ("busy", "in use", "already open", "device unavailable", "-9985")):
            return (
                "Микрофон занят другой программой или отключён. Закройте "
                "другие приложения со звуком и повторите запись."
            )
        if any(token in text for token in ("no default", "no device", "host error", "no input")):
            return (
                "Микрофон не найден. Подключите устройство входа и проверьте "
                "звук Windows."
            )
        return (
            "Не удалось открыть микрофон. Выберите другое устройство в "
            "разделе «Диктовка» и проверьте разрешение Windows для микрофона. "
            f"Детали драйвера: {detail}"
        )
    if any(token in text for token in ("not found", "invalid", "no speaker", "no output")):
        return (
            "Устройство вывода для системного звука недоступно. Выберите "
            "наушники или колонки в настройках Live."
        )
    return (
        "Не удалось открыть системный звук. Проверьте устройство вывода "
        f"и драйвер, затем попробуйте микрофон. Детали драйвера: {detail}"
    )


def _coerce_device(raw: Any) -> int | str | None:
    text = "" if raw is None else str(raw)
    if text.isdigit():
        return int(text)
    return text or None


def source_for_mode(mode: str, settings: Mapping[str, Any]) -> tuple[str, int | str | None]:
    """Pick capture kind and device for dictation vs live captions.

    Dictation always uses the microphone.  Live defaults to system loopback
    even when a leftover ``source=microphone`` setting remains from older
    builds.  ``mixed`` listens to microphone and system audio together.
    """

    if mode == "live":
        kind = str(settings.get("live_source") or "system")
        if kind not in LIVE_SOURCES:
            kind = "system"
        if kind == "mixed":
            return kind, None
        raw = settings.get("input_device") if kind == "microphone" else settings.get("loopback_device")
        return kind, _coerce_device(raw)
    return "microphone", _coerce_device(settings.get("input_device"))


def next_live_source(current: str) -> str:
    kind = current if current in LIVE_SOURCES else "system"
    return LIVE_SOURCES[(LIVE_SOURCES.index(kind) + 1) % len(LIVE_SOURCES)]


def live_source_label(kind: str) -> str:
    return LIVE_SOURCE_LABELS.get(kind, LIVE_SOURCE_LABELS["system"])


def mix_audio_blocks(left: np.ndarray | None, right: np.ndarray | None) -> np.ndarray:
    """Sum two mono blocks and clip.  A missing side is treated as silence."""

    if left is None and right is None:
        return np.empty(0, dtype=np.float32)
    if left is None:
        return np.ascontiguousarray(right, dtype=np.float32)
    if right is None:
        return np.ascontiguousarray(left, dtype=np.float32)
    left = np.asarray(left, dtype=np.float32).reshape(-1)
    right = np.asarray(right, dtype=np.float32).reshape(-1)
    n = min(left.size, right.size)
    if n == 0:
        return np.empty(0, dtype=np.float32)
    return np.clip(left[:n] + right[:n], -1.0, 1.0).astype(np.float32, copy=False)


def _ensure_windows_com() -> None:
    """WASAPI loopback needs COM on the capture thread, not only at import."""

    if sys.platform != "win32":
        return
    try:
        import ctypes

        # COINIT_MULTITHREADED. S_FALSE and RPC_E_CHANGED_MODE are non-fatal.
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)
    except Exception:
        return


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
        return describe_capture_error(self.kind, error)

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

            # soundcard initialises COM on the importing thread.  The
            # loopback thread still needs its own apartment under Qt.
            _ensure_windows_com()
            microphone = self._resolve_loopback_microphone(sc)
            if microphone is None:
                raise RuntimeError("no system output device available")
            # WASAPI loopback is the mix format of the render endpoint.
            # Forcing mono can open, then return silence on some headsets.
            channels = int(getattr(microphone, "channels", 1) or 1)
            with microphone.recorder(
                samplerate=_SAMPLE_RATE,
                channels=channels,
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

    def _resolve_loopback_microphone(self, soundcard: Any) -> Any:
        """Return the Media Foundation loopback microphone for a speaker.

        In soundcard on Windows, a ``Speaker`` only plays audio.  The capture
        endpoint is exposed separately as a ``Microphone`` with
        ``include_loopback=True`` and the same Windows device id.
        """

        speaker = self._resolve_loopback_speaker(soundcard)
        identifier = getattr(speaker, "id", None)
        if not identifier:
            raise RuntimeError("selected output device has no Windows endpoint id")
        return soundcard.get_microphone(identifier, include_loopback=True)


class MixedCapture:
    """Mix microphone and system loopback into one 16 kHz mono stream.

    If only one side opens, Auto keeps that side instead of aborting Live.
    """

    def __init__(
        self,
        microphone_device: int | str | None = None,
        loopback_device: int | str | None = None,
        on_audio: AudioCallback | None = None,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._stop = Event()
        self._mic_q: Queue[np.ndarray] = Queue(maxsize=8)
        self._sys_q: Queue[np.ndarray] = Queue(maxsize=8)
        self._mixer: Thread | None = None
        self._mic = AudioCapture(
            kind="microphone",
            device=microphone_device,
            on_audio=lambda audio: self._feed(self._mic_q, audio),
            on_error=lambda message: self._child_error("microphone", message),
        )
        self._sys = AudioCapture(
            kind="system",
            device=loopback_device,
            on_audio=lambda audio: self._feed(self._sys_q, audio),
            on_error=lambda message: self._child_error("system", message),
        )

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        errors: list[str] = []
        for capture in (self._mic, self._sys):
            try:
                capture.start()
            except Exception as exc:
                errors.append(str(exc))
        if not self._mic.running and not self._sys.running:
            raise RuntimeError(
                " ".join(errors) or "Не удалось открыть микрофон и системный звук."
            )
        self._mixer = Thread(target=self._mix_loop, name="DotAudioMixedCapture", daemon=True)
        self._mixer.start()

    def stop(self) -> None:
        self._stop.set()
        self._mic.stop()
        self._sys.stop()
        thread, self._mixer = self._mixer, None
        if thread is not None and thread is not current_thread():
            thread.join(timeout=1.5)

    @property
    def running(self) -> bool:
        return (self._mic.running or self._sys.running) and not self._stop.is_set()

    def _feed(self, queue: Queue[np.ndarray], audio: np.ndarray) -> None:
        if self._stop.is_set():
            return
        try:
            queue.put_nowait(audio)
            return
        except Full:
            pass
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(audio)
        except Full:
            return

    def _child_error(self, source: str, message: str) -> None:
        if self._stop.is_set():
            return
        other = self._sys if source == "microphone" else self._mic
        if other.running:
            return
        if self._on_error is not None:
            self._on_error(message)

    def _take(self, queue: Queue[np.ndarray], timeout: float) -> np.ndarray | None:
        try:
            return queue.get(timeout=timeout)
        except Empty:
            return None

    def _publish(self, mixed: np.ndarray) -> None:
        if not mixed.size:
            return
        if self._on_audio is not None:
            self._on_audio(mixed)
        if self._on_level is not None:
            level = float(np.sqrt(np.mean(np.square(mixed, dtype=np.float32))))
            self._on_level(level)

    def _mix_loop(self) -> None:
        mic_hold: np.ndarray | None = None
        sys_hold: np.ndarray | None = None
        waited = 0.0
        while not self._stop.is_set():
            if mic_hold is None:
                mic_hold = self._take(self._mic_q, 0.02)
            if sys_hold is None:
                sys_hold = self._take(self._sys_q, 0.0)
            both = mic_hold is not None and sys_hold is not None
            one = (mic_hold is None) != (sys_hold is None)
            single = not self._mic.running or not self._sys.running
            if both or (one and (single or waited >= 0.08)):
                self._publish(mix_audio_blocks(mic_hold, sys_hold))
                mic_hold = sys_hold = None
                waited = 0.0
                continue
            if one:
                waited += 0.02
            else:
                waited = 0.0


def open_live_capture(
    kind: str,
    settings: Mapping[str, Any],
    *,
    on_audio: AudioCallback | None = None,
    on_level: LevelCallback | None = None,
    on_error: ErrorCallback | None = None,
) -> AudioCapture | MixedCapture:
    """Build the capture object Live should start for ``kind``."""

    callbacks = {"on_audio": on_audio, "on_level": on_level, "on_error": on_error}
    if kind == "mixed":
        return MixedCapture(
            microphone_device=_coerce_device(settings.get("input_device")),
            loopback_device=_coerce_device(settings.get("loopback_device")),
            **callbacks,
        )
    if kind not in {"microphone", "system"}:
        kind = "system"
    device = _coerce_device(
        settings.get("input_device") if kind == "microphone" else settings.get("loopback_device")
    )
    return AudioCapture(kind=kind, device=device, **callbacks)


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
        attempt = 0
        while not self._stop.is_set():
            process = None
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
                attempt = 0 if self._stop.is_set() else attempt + 1
            except Exception:
                attempt += 1
            finally:
                with self._lock:
                    if self._process is process:
                        self._process = None
                if process is not None and process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass
            if self._stop.is_set():
                return
            delay = min(15, 2 ** min(attempt - 1, 4))
            self._error(f"Поток переподключается через {delay} с (попытка {attempt}).")
            # Event.wait makes stop immediate even during a long network backoff.
            self._stop.wait(delay)


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


def list_loopback_devices() -> list[dict[str, str]]:
    """Return Windows playback endpoints that SoundCard can capture exactly.

    SoundDevice indexes are useful for playback, but can be duplicated by
    Windows audio APIs.  A SoundCard speaker id is the Media Foundation
    endpoint id and is the matching key for its loopback microphone.
    """

    try:
        import soundcard as sc

        speakers = sc.all_speakers()
    except Exception:
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for speaker in speakers:
        identifier = str(getattr(speaker, "id", ""))
        name = str(getattr(speaker, "name", ""))
        if identifier and name and identifier not in seen:
            result.append({"id": identifier, "name": name})
            seen.add(identifier)
    return result


def playback_device_for_loopback(endpoint_id: str | None) -> int | None:
    """Find the SoundDevice playback index for a SoundCard endpoint.

    Windows can expose one physical output through MME, DirectSound, WASAPI
    and WDM-KS at once.  For a loopback probe we must play through an alias of
    the exact endpoint being captured, rather than an arbitrary output index.
    """

    try:
        import soundcard as sc
        import sounddevice as sd

        speaker = sc.get_speaker(endpoint_id) if endpoint_id else sc.default_speaker()
        target = str(getattr(speaker, "name", "")).casefold()
        devices = sd.query_devices()
    except Exception:
        return None
    candidates: list[tuple[int, str]] = []
    for index, device in enumerate(devices):
        try:
            name = str(device["name"])
            channels = int(device["max_output_channels"])
        except (KeyError, TypeError, ValueError):
            continue
        folded = name.casefold()
        if channels > 0 and target and (target in folded or folded in target):
            candidates.append((index, folded))
    if not candidates:
        return None
    try:
        default_index = int(sd.default.device[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        default_index = -1
    for index, _ in candidates:
        if index == default_index:
            return index
    for index, name in candidates:
        if "wasapi" in name:
            return index
    return candidates[0][0]


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
    "LIVE_SOURCES",
    "MixedCapture",
    "StreamCapture",
    "describe_capture_error",
    "list_input_devices",
    "list_loopback_devices",
    "list_output_devices",
    "live_source_label",
    "mix_audio_blocks",
    "next_live_source",
    "open_live_capture",
    "playback_device_for_loopback",
    "play_output_tone",
    "source_for_mode",
]
