"""Core speech-recognition engine for DotAudio.

The module deliberately has no UI dependencies.  Heavy libraries are imported
only when their corresponding backend is used, keeping application startup
fast on machines that use the remote worker only.
"""

from __future__ import annotations

import json
import mimetypes
import wave
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable
from urllib.parse import urlsplit

import numpy as np

Segment = dict[str, float | str]
SegmentCallback = Callable[[Segment], None]
StatusCallback = Callable[[str], None]


@dataclass(slots=True, frozen=True)
class RecognitionConfig:
    """Options shared by local faster-whisper and the optional worker."""

    model: str = "base"
    device: str = "auto"
    language: str = "auto"
    task: str = "transcribe"
    backend: str = "local"
    server_url: str = "http://127.0.0.1:8765"


class Engine:
    """A bounded, thread-safe recognizer.

    A model can be large enough to evict most application state on modest
    devices.  Keeping exactly one cached model also prevents a switch from a
    quick dictation model to a studio model from retaining both in memory.
    """

    _MAX_REMOTE_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self) -> None:
        self._models: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self._model_lock = Lock()
        self._inference_lock = Lock()

    def transcribe(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None = None,
        on_segment: SegmentCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> list[Segment]:
        """Transcribe a path or a 16 kHz mono float array.

        Cancellation is cooperative.  It stops iteration between emitted
        Whisper segments (or network response chunks) and returns completed
        segments, which lets a live UI retain text already shown to the user.
        """

        self._validate_config(config)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []

        if config.backend == "remote":
            return self._transcribe_remote(
                source, config, cancel, on_segment, on_status
            )
        return self._transcribe_local(
            source, config, cancel, on_segment, on_status
        )

    @staticmethod
    def _validate_config(config: RecognitionConfig) -> None:
        if config.backend not in {"local", "remote"}:
            raise ValueError("backend must be 'local' or 'remote'")
        if config.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be 'auto', 'cpu', or 'cuda'")
        if config.task not in {"transcribe", "translate"}:
            raise ValueError("task must be 'transcribe' or 'translate'")
        if not config.model.strip():
            raise ValueError("model must not be empty")

    @staticmethod
    def _cancelled(cancel: Event | None) -> bool:
        return cancel is not None and cancel.is_set()

    @staticmethod
    def _status(callback: StatusCallback | None, value: str) -> None:
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            # UI callbacks must never break an active transcription.
            return

    @staticmethod
    def _emit_segment(callback: SegmentCallback | None, segment: Segment) -> None:
        if callback is None:
            return
        try:
            callback(segment)
        except Exception:
            return

    def _transcribe_local(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        """Run local inference, retrying once on CPU for CUDA runtime faults."""

        self._status(on_status, "loading_model")
        try:
            return self._run_local(
                source, config, config.device, cancel, on_segment, on_status
            )
        except (RuntimeError, OSError) as exc:
            if config.device != "auto" or not self._is_cuda_error(exc):
                raise
            self._status(on_status, "gpu_unavailable_falling_back_cpu")
            self._drop_model(config.model, "cuda")
            return self._run_local(
                source, config, "cpu", cancel, on_segment, on_status
            )

    def _run_local(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        requested_device: str,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        model, actual_device = self._model_for(config.model, requested_device)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []

        language = None if config.language.strip().lower() == "auto" else config.language
        # These values are a safe general default for spoken audio.  VAD avoids
        # wasting inference on silence, while beam 5 remains usable on CPU.
        kwargs: dict[str, Any] = {
            "task": config.task,
            "language": language,
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 350,
                "min_speech_duration_ms": 120,
            },
            "condition_on_previous_text": False,
        }
        self._status(on_status, f"transcribing_{actual_device}")
        result: list[Segment] = []
        # CTranslate2 / CUDA execution is native and is not safe to run in
        # parallel inside one desktop process.  Model loading remains separate
        # so a second caller can observe the cache while this call is running.
        with self._inference_lock:
            segments, _info = model.transcribe(source, **kwargs)
            for raw in segments:
                if self._cancelled(cancel):
                    self._status(on_status, "cancelled")
                    return result
                text = str(getattr(raw, "text", "")).strip()
                if not text:
                    continue
                segment: Segment = {
                    "start": float(getattr(raw, "start", 0.0)),
                    "end": float(getattr(raw, "end", 0.0)),
                    "text": text,
                }
                result.append(segment)
                self._emit_segment(on_segment, segment)
        self._status(on_status, "completed")
        return result

    def _model_for(self, model_name: str, requested_device: str) -> tuple[Any, str]:
        candidates = ("cuda", "cpu") if requested_device == "auto" else (requested_device,)
        last_error: BaseException | None = None
        for device in candidates:
            try:
                return self._get_or_load_model(model_name, device), device
            except (RuntimeError, OSError) as exc:
                last_error = exc
                if requested_device != "auto" or not self._is_cuda_error(exc):
                    raise
        assert last_error is not None
        raise last_error

    def _get_or_load_model(self, model_name: str, device: str) -> Any:
        key = (model_name, device)
        with self._model_lock:
            cached = self._models.get(key)
            if cached is not None:
                self._models.move_to_end(key)
                return cached
            # Imported here so remote-only installations do not need the
            # local ASR stack at startup.
            from faster_whisper import WhisperModel

            compute_type = "float16" if device == "cuda" else "int8"
            loaded = WhisperModel(
                model_name, device=device, compute_type=compute_type
            )
            self._models.clear()
            self._models[key] = loaded
            return loaded

    def _drop_model(self, model_name: str, device: str) -> None:
        with self._model_lock:
            self._models.pop((model_name, device), None)

    @staticmethod
    def _is_cuda_error(error: BaseException) -> bool:
        text = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in text
            for marker in ("cuda", "cublas", "cudnn", "cudart", "nvrtc")
        )

    def _transcribe_remote(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        self._validate_server_url(config.server_url)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []
        self._status(on_status, "uploading")

        import httpx

        filename, body, content_type = self._remote_file(source)
        try:
            files = {"file": (filename, body, content_type)}
            form = {
                "model": config.model,
                "language": config.language,
                "task": config.task,
            }
            with httpx.Client(timeout=httpx.Timeout(30.0, read=15.0)) as client:
                with client.stream(
                    "POST", config.server_url.rstrip("/") + "/v1/transcribe",
                    files=files,
                    data=form,
                    headers={"Accept": "application/json"},
                ) as response:
                    raw = self._read_bounded_response(response, cancel)
                    if self._cancelled(cancel):
                        self._status(on_status, "cancelled")
                        return []
                    if response.status_code < 200 or response.status_code >= 300:
                        detail = raw.decode("utf-8", errors="replace")[:500]
                        raise RuntimeError(
                            f"remote ASR returned HTTP {response.status_code}: {detail}"
                        )
        finally:
            body.close()

        payload = json.loads(raw.decode("utf-8"))
        raw_segments = payload.get("segments", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_segments, list):
            raise RuntimeError("remote ASR response must contain a segments list")
        result: list[Segment] = []
        for item in raw_segments:
            if self._cancelled(cancel):
                self._status(on_status, "cancelled")
                return result
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            segment: Segment = {
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "text": text,
            }
            result.append(segment)
            self._emit_segment(on_segment, segment)
        self._status(on_status, "completed")
        return result

    def _read_bounded_response(self, response: Any, cancel: Event | None) -> bytes:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            if self._cancelled(cancel):
                break
            size += len(chunk)
            if size > self._MAX_REMOTE_RESPONSE_BYTES:
                raise RuntimeError("remote ASR response exceeds 8 MiB limit")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_server_url(server_url: str) -> None:
        parsed = urlsplit(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("server_url must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("server_url must not contain credentials")

    @staticmethod
    def _remote_file(source: str | np.ndarray) -> tuple[str, BytesIO | Any, str]:
        if isinstance(source, np.ndarray):
            audio = np.asarray(source, dtype=np.float32)
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            if audio.ndim != 1:
                raise ValueError("audio array must be mono or shaped (frames, channels)")
            clipped = np.clip(audio, -1.0, 1.0)
            pcm = (clipped * 32767.0).astype("<i2", copy=False)
            data = BytesIO()
            with wave.open(data, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm.tobytes())
            data.seek(0)
            return "capture.wav", data, "audio/wav"

        path = Path(source).expanduser()
        if not path.is_file():
            raise ValueError("remote backend accepts an existing local media file")
        media = open(path, "rb")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.name, media, content_type


__all__ = ["Engine", "RecognitionConfig", "Segment"]
