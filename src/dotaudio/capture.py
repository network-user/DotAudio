"""Audio capture primitives with no Qt dependency.

The actual device libraries are imported lazily.  Audio callbacks do only
normalisation and a bounded queue put; user callbacks run on a helper thread,
so a slow visualizer cannot cause microphone overflows or block a UI thread.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
from typing import Any
from urllib.parse import urlsplit

import numpy as np

AudioCallback = Callable[[np.ndarray], None]
LevelCallback = Callable[[float], None]
ErrorCallback = Callable[[str], None]
GapCallback = Callable[[int], None]
_QUEUE_LIMIT = 24
_SAMPLE_RATE = 16000
_BLOCK_FRAMES = 1600
LIVE_SOURCES = ("system", "mixed", "microphone")
LIVE_SOURCE_LABELS = {
    "microphone": "Микрофон",
    "system": "Звук системы",
    "mixed": "Авто",
}

# PortAudio exposes the same physical mic through several Windows host APIs.
# MME often opens and stays silent on USB headsets; WDM-KS / WASAPI carry audio.
# Lower number = preferred when deduplicating the device list.
_HOSTAPI_PREFERENCE = {
    "Windows WDM-KS": 0,
    "Windows WASAPI": 1,
    "Windows DirectSound": 2,
    "MME": 3,
}
_SKIP_INPUT_NAME_TOKENS = (
    "первичный",
    "primary",
    "переназначение",
    "sound mapper",
    "mapper",
)


def _mic_privacy_hint() -> str:
    if sys.platform == "darwin":
        return (
            "Системные настройки → Конфиденциальность и безопасность → Микрофон "
            "и разрешите DotAudio."
        )
    if sys.platform.startswith("linux"):
        return "права Flatpak/PipeWire и что микрофон не занят другой программой."
    return "Параметры Windows → Конфиденциальность → Микрофон и разрешите DotAudio."


def describe_capture_error(kind: str, error: Exception | str) -> str:
    """Map driver exceptions to a named recovery hint.  Details stay attached."""

    detail = str(error)
    text = detail.casefold()
    if kind == "microphone":
        if any(token in text for token in ("denied", "permission", "access is denied", "not authorized")):
            return f"Нет доступа к микрофону. Откройте {_mic_privacy_hint()}"
        if any(token in text for token in ("invalid sample rate", "-9997", "unsupported format")):
            return (
                "Микрофон не принял частоту дискретизации. DotAudio откроет "
                "устройство на его родной частоте; выберите другое устройство, "
                "если ошибка повторится."
            )
        if any(token in text for token in ("invalid device", "device not found", "no such device", "-9996")):
            return (
                "Выбранный микрофон недоступен. Подключите его или выберите "
                "другое устройство в «Среде» или на странице «Диктовка»."
            )
        if any(token in text for token in ("busy", "in use", "already open", "device unavailable", "-9985")):
            return (
                "Микрофон занят другой программой или отключён. Закройте "
                "другие приложения со звуком и повторите запись."
            )
        if any(token in text for token in ("no default", "no device", "host error", "no input")):
            return (
                "Микрофон не найден. Подключите устройство входа и проверьте "
                "системные настройки звука."
            )
        return (
            "Не удалось открыть микрофон. Выберите другое устройство в "
            "«Среде» или на странице «Диктовка» и проверьте доступ к микрофону. "
            f"Детали драйвера: {detail}"
        )
    if "unix system audio" in text or "blackhole" in text or "monitor" in text:
        return detail if detail else (
            "Системный звук на этой ОС недоступен. Выберите микрофон или "
            "установите виртуальное устройство захвата (Pulse monitor / BlackHole)."
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


def default_live_source() -> str:
    """Windows defaults to system loopback; other desktops start on the mic."""

    return "system" if sys.platform == "win32" else "microphone"


def system_audio_supported() -> bool:
    """True when Live can open system/mixed audio on this platform."""

    if sys.platform == "win32":
        return True
    return bool(list_loopback_devices())


def system_audio_hint() -> str:
    """Короткая подсказка для мастера/настроек, если системный звук ещё недоступен."""

    if sys.platform == "win32" or system_audio_supported():
        return ""
    if sys.platform == "darwin":
        return (
            "Системный звук Live на macOS: установите BlackHole "
            "(https://existential.audio/blackhole/), добавьте его в Multi-Output "
            "Device вместе с колонками и выберите BlackHole в «Звук системы»."
        )
    return (
        "Системный звук Live на Linux: в списке входов должен появиться "
        "monitor PulseAudio/PipeWire. Без него Live работает с микрофона."
    )


def _coerce_device(raw: Any) -> int | str | None:
    text = "" if raw is None else str(raw)
    if text.isdigit():
        return int(text)
    return text or None


def _normalize_device_name(name: str) -> str:
    """Collapse PortAudio aliases of one physical endpoint to one key."""

    text = " ".join(str(name).split()).casefold()
    for suffix in (
        ", windows wasapi",
        ", windows directsound",
        ", windows wdm-ks",
        ", mme",
        " wave",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip(" -")


def _hostapi_rank(name: str) -> int:
    return _HOSTAPI_PREFERENCE.get(str(name), 50)


def _is_skipped_input_name(name: str) -> bool:
    text = str(name).casefold()
    return any(token in text for token in _SKIP_INPUT_NAME_TOKENS)


def _resample_to_target(audio: np.ndarray, source_rate: int, target_rate: int = _SAMPLE_RATE) -> np.ndarray:
    """Linear-resample mono float32.  Keeps ASR on a fixed 16 kHz clock."""

    if source_rate == target_rate or audio.size == 0:
        return np.ascontiguousarray(audio, dtype=np.float32)
    if source_rate <= 0 or target_rate <= 0:
        return np.empty(0, dtype=np.float32)
    duration = audio.size / float(source_rate)
    target_n = max(1, int(round(duration * target_rate)))
    old_x = np.linspace(0.0, 1.0, num=audio.size, endpoint=False, dtype=np.float64)
    new_x = np.linspace(0.0, 1.0, num=target_n, endpoint=False, dtype=np.float64)
    return np.interp(new_x, old_x, audio.astype(np.float64)).astype(np.float32)


def _same_device_name(left: str, right: str) -> bool:
    a, b = _normalize_device_name(left), _normalize_device_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    # MME truncates long names; accept shared prefix of reasonable length.
    shortest = min(len(a), len(b))
    return shortest >= 12 and (a.startswith(b) or b.startswith(a))


def resolve_microphone_candidates(device: int | str | None) -> list[int | None]:
    """Ordered PortAudio indexes to try for one logical microphone.

    ``None`` means the PortAudio default input.  Same-named aliases across
    host APIs are ordered by :data:`_HOSTAPI_PREFERENCE`.
    """

    try:
        import sounddevice as sd

        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
    except Exception:
        if device is None or device == "":
            return [None]
        if isinstance(device, int) or (isinstance(device, str) and str(device).isdigit()):
            return [int(device)]
        return []

    requested: int | None
    if device is None or device == "":
        default = sd.default.device
        raw_in = None
        if isinstance(default, (list, tuple)):
            raw_in = default[0] if default else None
        else:
            # PortAudio may return a custom pair object with [0]/[1] accessors.
            try:
                raw_in = default[0]  # type: ignore[index]
            except Exception:
                raw_in = default
        try:
            requested = int(raw_in) if raw_in is not None and int(raw_in) >= 0 else None
        except (TypeError, ValueError):
            requested = None
    elif isinstance(device, int) or (isinstance(device, str) and device.isdigit()):
        requested = int(device)
    else:
        requested = None
        target = str(device).casefold()
        for index, item in enumerate(devices):
            if int(item.get("max_input_channels") or 0) <= 0:
                continue
            if target in str(item.get("name", "")).casefold():
                requested = index
                break
        if requested is None:
            return []

    if requested is None:
        return [None]
    if not 0 <= requested < len(devices):
        return [requested]

    seed_name = str(devices[requested].get("name", ""))
    ranked: list[tuple[int, int, int]] = []
    for index, item in enumerate(devices):
        try:
            channels = int(item["max_input_channels"])
            name = str(item["name"])
            host = str(hostapis[int(item["hostapi"])]["name"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if channels <= 0 or _is_skipped_input_name(name):
            continue
        if not _same_device_name(seed_name, name):
            continue
        ranked.append((_hostapi_rank(host), index != requested, index))
    ranked.sort()
    if not ranked:
        return [requested]
    return [index for _rank, _prefer, index in ranked]


def source_for_mode(mode: str, settings: Mapping[str, Any]) -> tuple[str, int | str | None]:
    """Pick capture kind and device for dictation vs live captions.

    Dictation always uses the microphone.  Live defaults to system loopback
    on Windows even when a leftover ``source=microphone`` setting remains
    from older builds; on Linux/macOS the default is the microphone.
    ``mixed`` listens to microphone and system audio together when supported.
    """

    if mode == "live":
        kind = str(settings.get("live_source") or default_live_source())
        if kind not in LIVE_SOURCES:
            kind = default_live_source()
        if kind in {"system", "mixed"} and sys.platform != "win32" and not system_audio_supported():
            # Keep UI choice, but capture must open something that works.
            kind = "microphone"
        if kind == "mixed":
            return kind, None
        raw = settings.get("input_device") if kind == "microphone" else settings.get("loopback_device")
        return kind, _coerce_device(raw)
    return "microphone", _coerce_device(settings.get("input_device"))


def next_live_source(current: str) -> str:
    fallback = default_live_source()
    kind = current if current in LIVE_SOURCES else fallback
    return LIVE_SOURCES[(LIVE_SOURCES.index(kind) + 1) % len(LIVE_SOURCES)]


def live_source_label(kind: str) -> str:
    return LIVE_SOURCE_LABELS.get(kind, LIVE_SOURCE_LABELS[default_live_source()])


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
        on_gap: GapCallback | None = None,
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._on_gap = on_gap
        # Audio must never compete with the cosmetic level meter for queue
        # space. Levels are intentionally coalesced; audio overflow remains
        # bounded but is reported to the consumer instead of disappearing.
        self._audio_events: Queue[np.ndarray | None] = Queue(maxsize=_QUEUE_LIMIT)
        self._error_events: Queue[str] = Queue(maxsize=8)
        self._event_lock = Lock()
        self._latest_level: float | None = None
        self._dropped_audio_blocks = 0
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
        self._put_audio(None)
        if self._dispatch_thread is not None:
            self._dispatch_thread.join(timeout=1.0)
        self._dispatch_thread = None

    def _put_audio(self, audio: np.ndarray | None) -> None:
        try:
            self._audio_events.put_nowait(audio)
            return
        except Full:
            pass
        try:
            self._audio_events.get_nowait()
        except Empty:
            pass
        else:
            if audio is not None:
                with self._event_lock:
                    self._dropped_audio_blocks += 1
        try:
            self._audio_events.put_nowait(audio)
        except Full:
            return

    def _put_level(self, level: float) -> None:
        with self._event_lock:
            self._latest_level = level

    def _put_error(self, message: str) -> None:
        try:
            self._error_events.put_nowait(message)
        except Full:
            try:
                self._error_events.get_nowait()
            except Empty:
                return
            try:
                self._error_events.put_nowait(message)
            except Full:
                return

    def _publish_audio(self, frames: np.ndarray) -> None:
        audio = self._normalise(frames)
        if not audio.size:
            return
        # RMS is stable enough for a 100 ms level meter and is cheap to
        # calculate in the realtime callback.
        level = float(np.sqrt(np.mean(np.square(audio, dtype=np.float32))))
        self._put_audio(audio)
        self._put_level(level)

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
        self._put_error(str(message)[:500])

    def _dispatch_level(self) -> None:
        with self._event_lock:
            level, self._latest_level = self._latest_level, None
        if level is not None and self._on_level is not None:
            try:
                self._on_level(level)
            except Exception:
                return

    def _dispatch_errors(self) -> None:
        while True:
            try:
                message = self._error_events.get_nowait()
            except Empty:
                return
            if self._on_error is None:
                continue
            try:
                self._on_error(message)
            except Exception:
                continue

    def _dispatch_loop(self) -> None:
        while True:
            try:
                audio = self._audio_events.get(timeout=0.05)
            except Empty:
                if self._dispatch_stop.is_set():
                    return
                self._dispatch_level()
                self._dispatch_errors()
                continue
            if audio is None:
                return
            with self._event_lock:
                dropped, self._dropped_audio_blocks = self._dropped_audio_blocks, 0
            if dropped and self._on_gap is not None:
                try:
                    self._on_gap(dropped)
                except Exception:
                    pass
            if self._on_audio is not None:
                try:
                    self._on_audio(audio)
                except Exception:
                    # A consumer error must not kill capture or prevent stop().
                    pass
            self._dispatch_level()
            self._dispatch_errors()


class AudioCapture(_CallbackDispatcher):
    """Capture 16 kHz mono PCM from a microphone or system loopback."""

    def __init__(
        self,
        kind: str = "microphone",
        device: int | str | None = None,
        on_audio: AudioCallback | None = None,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_gap: GapCallback | None = None,
    ) -> None:
        if kind not in {"microphone", "system"}:
            raise ValueError("kind must be 'microphone' or 'system'")
        super().__init__(on_audio, on_level, on_error, on_gap)
        self.kind = kind
        self.device = device
        self._stream: Any = None
        self._stop = Event()
        self._system_thread: Thread | None = None
        self._lock = Lock()
        self._capture_rate = _SAMPLE_RATE
        self._opened_device: int | None = None

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._start_dispatcher()
            try:
                if self.kind == "microphone":
                    self._start_microphone()
                elif sys.platform == "win32":
                    self._start_system_loopback()
                else:
                    self._start_unix_system_capture()
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
        if self.kind == "microphone" or (
            self.kind == "system" and sys.platform != "win32"
        ):
            return self._stream is not None and not self._stop.is_set()
        return self._system_thread is not None and self._system_thread.is_alive()

    def _start_error(self, error: Exception) -> str:
        return describe_capture_error(self.kind, error)

    def _start_unix_system_capture(self) -> None:
        """Capture a Pulse monitor / BlackHole-style input via PortAudio."""

        device = self.device
        if device is None or device == "":
            monitors = list_loopback_devices()
            if not monitors:
                if sys.platform == "darwin":
                    raise RuntimeError(
                        "unix system audio: на macOS нужен виртуальный вход "
                        "(например BlackHole). Без него выберите микрофон."
                    )
                raise RuntimeError(
                    "unix system audio: не найден monitor PulseAudio/PipeWire. "
                    "Выберите микрофон или укажите monitor-устройство в списке."
                )
            device = _coerce_device(monitors[0]["id"])
            self.device = device
        # Reuse the microphone PortAudio path against the virtual capture device.
        self._start_microphone()

    def _start_microphone(self) -> None:
        import sounddevice as sd

        # WDM-KS / WASAPI need COM on the opening thread under Qt.
        _ensure_windows_com()
        candidates = resolve_microphone_candidates(self.device)
        if not candidates:
            candidates = [None]
        errors: list[str] = []
        for candidate in candidates:
            try:
                stream, rate = self._open_microphone_stream(sd, candidate)
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            self._stream = stream
            self._capture_rate = rate
            self._opened_device = candidate if isinstance(candidate, int) else None
            self._stream.start()
            return
        detail = errors[-1] if errors else "no input device"
        raise RuntimeError(detail)

    def _open_microphone_stream(self, sd: Any, device: int | None) -> tuple[Any, int]:
        """Open at a rate the host API accepts; caller resamples to 16 kHz."""

        channels = 1
        native_rate = _SAMPLE_RATE
        host_name = "MME"
        if device is not None:
            info = sd.query_devices(device, "input")
            native_rate = int(float(info.get("default_samplerate") or _SAMPLE_RATE))
            channels = 1 if int(info.get("max_input_channels") or 1) >= 1 else int(info["max_input_channels"])
            try:
                host_name = str(sd.query_hostapis(int(info["hostapi"]))["name"])
            except Exception:
                host_name = "MME"

        extra = None
        if host_name == "Windows WASAPI":
            try:
                # Shared-mode WASAPI rejects 16 kHz unless the mixer converts.
                extra = sd.WasapiSettings(auto_convert=True)
            except Exception:
                extra = None

        # Prefer native rate (WDM-KS often refuses anything else), then 16 kHz
        # with WASAPI auto-convert, then common fallbacks.
        rates: list[int] = []
        for rate in (native_rate, _SAMPLE_RATE, 48000, 44100):
            if rate > 0 and rate not in rates:
                rates.append(rate)

        last_error: Exception | None = None
        for rate in rates:
            kwargs: dict[str, Any] = {
                "samplerate": rate,
                "channels": channels,
                "dtype": "float32",
                "blocksize": max(1, int(round(_BLOCK_FRAMES * rate / _SAMPLE_RATE))),
                "device": device,
                "callback": self._microphone_callback,
            }
            if extra is not None:
                kwargs["extra_settings"] = extra
            try:
                stream = sd.InputStream(**kwargs)
            except Exception as exc:
                last_error = exc
                continue
            return stream, rate
        assert last_error is not None
        raise last_error

    def _microphone_callback(
        self,
        indata: np.ndarray,
        _frames: int,
        _time: Any,
        status: Any,
    ) -> None:
        if status:
            self._error(f"microphone status: {status}")
        if self._stop.is_set():
            return
        audio = self._normalise(indata)
        if self._capture_rate != _SAMPLE_RATE:
            audio = _resample_to_target(audio, self._capture_rate, _SAMPLE_RATE)
        if audio.size:
            self._publish_audio(audio)

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
        on_gap: GapCallback | None = None,
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._on_gap = on_gap
        self._stop = Event()
        self._mic_q: Queue[np.ndarray] = Queue(maxsize=8)
        self._sys_q: Queue[np.ndarray] = Queue(maxsize=8)
        self._mixer: Thread | None = None
        self._mic = AudioCapture(
            kind="microphone",
            device=microphone_device,
            on_audio=lambda audio: self._feed(self._mic_q, audio),
            on_error=lambda message: self._child_error("microphone", message),
            on_gap=lambda dropped: self._gap(dropped),
        )
        self._sys = AudioCapture(
            kind="system",
            device=loopback_device,
            on_audio=lambda audio: self._feed(self._sys_q, audio),
            on_error=lambda message: self._child_error("system", message),
            on_gap=lambda dropped: self._gap(dropped),
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
        else:
            self._gap(1)
        try:
            queue.put_nowait(audio)
        except Full:
            return

    def _gap(self, dropped: int) -> None:
        if dropped > 0 and not self._stop.is_set() and self._on_gap is not None:
            self._on_gap(dropped)

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
    on_gap: GapCallback | None = None,
) -> AudioCapture | MixedCapture:
    """Build the capture object Live should start for ``kind``."""

    callbacks = {"on_audio": on_audio, "on_level": on_level, "on_error": on_error, "on_gap": on_gap}
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
        on_gap: GapCallback | None = None,
    ) -> None:
        super().__init__(on_audio, on_level, on_error, on_gap)
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
        from dotaudio.tools_ffmpeg import resolve_ffmpeg

        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            self._error(
                "FFmpeg не найден. Запустите автонастройку или установите FFmpeg в PATH."
            )
            return
        command = [
            ffmpeg,
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


def _probe_input_alive(sd: Any, device: int, seconds: float = 0.2) -> bool:
    """Return True when the endpoint actually invokes its PortAudio callback."""

    hits = 0

    def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
        nonlocal hits
        hits += 1

    try:
        info = sd.query_devices(device, "input")
        rate = int(float(info.get("default_samplerate") or _SAMPLE_RATE))
        stream = sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            blocksize=0,
            device=device,
            callback=callback,
        )
        stream.start()
        time.sleep(seconds)
        stream.stop()
        stream.close()
    except Exception:
        return False
    return hits > 0


def list_input_devices() -> list[dict[str, str | int]]:
    """Return unique microphones, one entry per physical device.

    PortAudio lists the same mic under MME / DirectSound / WASAPI / WDM-KS.
    Showing every alias hid the working endpoint and made headset mics look
    like duplicates.  Prefer the host API that actually delivers USB audio
    on Windows (see ``_HOSTAPI_PREFERENCE``).
    """

    try:
        import sounddevice as sd

        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
    except Exception:
        return []

    # name-key -> list of (rank, index, name, host)
    groups: dict[str, list[tuple[int, int, str, str]]] = {}
    for index, device in enumerate(devices):
        try:
            channels = int(device["max_input_channels"])
            name = str(device["name"])
            host = str(hostapis[int(device["hostapi"])]["name"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if channels <= 0 or _is_skipped_input_name(name):
            continue
        key = _normalize_device_name(name)
        if not key:
            continue
        steam = "steam streaming" in key
        rank = _hostapi_rank(host) + (100 if steam else 0)
        groups.setdefault(key, []).append((rank, index, name, host))

    best: list[tuple[int, int, str]] = []
    for key, aliases in groups.items():
        aliases.sort()
        rank, index, name, host = aliases[0]
        only_wdm = all(item[3] == "Windows WDM-KS" for item in aliases)
        # Ghost WDM-KS endpoints (seen here: G435) open but never callback.
        if only_wdm and not _probe_input_alive(sd, index):
            continue
        best.append((rank, index, name))

    ordered = sorted(best, key=lambda item: (item[0], item[1]))
    real = [item for item in ordered if "steam streaming" not in _normalize_device_name(item[2])]
    chosen = real or ordered
    return [{"id": index, "name": name} for _rank, index, name in chosen]


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
    """Return playback endpoints (Windows) or monitor/virtual inputs (Unix).

    On Windows SoundCard speakers map to WASAPI loopback. On Linux/macOS we
    expose PortAudio inputs that look like Pulse monitors, BlackHole, Stereo
    Mix and similar virtual capture devices.
    """

    if sys.platform == "win32":
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

    markers = (
        "monitor",
        "loopback",
        "what u hear",
        "stereo mix",
        "blackhole",
        "soundflower",
        "cable",
        "vb-audio",
        "vb cable",
        "multi-output",
        "aggregate",
    )
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for device in list_input_devices():
        name = str(device.get("name") or "")
        folded = name.casefold()
        if not any(token in folded for token in markers):
            continue
        identifier = str(device.get("id", ""))
        if identifier and name and identifier not in seen:
            result.append({"id": identifier, "name": name})
            seen.add(identifier)
    return result


def playback_device_for_loopback(endpoint_id: str | None) -> int | None:
    """Find the SoundDevice playback index for a SoundCard endpoint.

    Windows can expose one physical output through MME, DirectSound, WASAPI
    and WDM-KS at once.  For a loopback probe we must play through an alias of
    the exact endpoint being captured, rather than an arbitrary output index.
    On other platforms the endpoint id is already a PortAudio input index.
    """

    if sys.platform != "win32":
        if endpoint_id is None or endpoint_id == "":
            return None
        text = str(endpoint_id)
        return int(text) if text.isdigit() else None

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


def play_pcm(
    audio: np.ndarray,
    *,
    device: int | str | None = None,
    samplerate: int = _SAMPLE_RATE,
) -> None:
    """Play mono float32 PCM through the selected output device."""

    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim != 1 or not samples.size:
        raise ValueError("audio must be a non-empty mono float32 buffer")
    if not 8000 <= int(samplerate) <= 96000:
        raise ValueError("samplerate out of range")
    import sounddevice as sd

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    # Soften loud mics so the Discord-style check does not blast headphones.
    gain = 0.55 if peak <= 1e-6 else min(0.55, 0.35 / peak)
    faded = samples * gain
    fade = min(int(samplerate * 0.02), faded.size // 4)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        faded[:fade] *= ramp
        faded[-fade:] *= ramp[::-1]
    sd.play(faded, samplerate=int(samplerate), device=device, blocking=True)


__all__ = [
    "AudioCapture",
    "LIVE_SOURCES",
    "MixedCapture",
    "StreamCapture",
    "default_live_source",
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
    "play_pcm",
    "resolve_microphone_candidates",
    "source_for_mode",
    "system_audio_hint",
    "system_audio_supported",
]
