"""Optional single-worker Whisper service. Keep behind loopback or an SSH tunnel."""

from __future__ import annotations

import argparse
import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

DEFAULT_MODELS = ("tiny", "base", "small", "medium", "large-v3", "turbo", "large-v3-turbo")
DEFAULT_UPLOAD_BYTES = 100 * 1024 * 1024


class InvalidAudio(ValueError):
    """Input cannot be decoded or exceeds the configured duration."""


def decode_audio(data: bytes, duration: float, cancel: threading.Event):
    """Decode incrementally so duration limits apply before allocating full audio."""
    import av
    import numpy as np

    frames = []
    samples = 0
    limit = int(duration * 16000)
    try:
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.audio:
                raise InvalidAudio("The uploaded media has no audio track.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

            def append(frame):
                nonlocal samples
                if cancel.is_set():
                    raise InvalidAudio("Recognition cancelled.")
                samples += frame.samples
                if samples > limit:
                    raise InvalidAudio(f"Audio exceeds the {duration:g} second limit.")
                frames.append(frame.to_ndarray().reshape(-1))

            for frame in container.decode(audio=0):
                if cancel.is_set():
                    raise InvalidAudio("Recognition cancelled.")
                frame.pts = None
                for converted in resampler.resample(frame):
                    append(converted)
            for converted in resampler.resample(None):
                append(converted)
    except InvalidAudio:
        raise
    except Exception as exc:
        raise InvalidAudio("The uploaded media cannot be decoded.") from exc
    if not frames:
        raise InvalidAudio("The uploaded audio is empty.")
    return np.concatenate(frames).astype(np.float32) / 32768.0


@dataclass
class _MultipartUpload:
    """Bounded in-memory multipart receiver, avoiding disk spooling entirely."""

    limit: int
    fields: dict[str, str] = field(default_factory=dict)
    audio: bytearray = field(default_factory=bytearray)
    headers: dict[bytes, bytes] = field(default_factory=dict)
    header_name: bytearray = field(default_factory=bytearray)
    current_header_value: bytearray = field(default_factory=bytearray)
    value: bytearray = field(default_factory=bytearray)
    name: str = ""
    header_size: int = 0
    parts: int = 0
    file_seen: bool = False
    ended: bool = False

    def callbacks(self):
        return {f"on_{name}": getattr(self, name) for name in (
            "part_begin", "header_field", "header_value", "header_end",
            "headers_finished", "part_data", "part_end", "end",
        )}

    def part_begin(self):
        from fastapi import HTTPException

        self.parts += 1
        if self.parts > 4:
            raise HTTPException(400, "Too many multipart fields.")
        self.headers.clear()
        self.value.clear()
        self.header_size = 0
        self.name = ""

    def _header(self, target, data, start, end):
        from fastapi import HTTPException

        self.header_size += end - start
        if self.header_size > 4096:
            raise HTTPException(400, "Multipart headers are too large.")
        target.extend(data[start:end])

    def header_field(self, data, start, end):
        self._header(self.header_name, data, start, end)

    def header_value(self, data, start, end):
        self._header(self.current_header_value, data, start, end)

    def header_end(self):
        self.headers[bytes(self.header_name).lower()] = bytes(self.current_header_value)
        self.header_name.clear()
        self.current_header_value.clear()

    def headers_finished(self):
        from fastapi import HTTPException
        from python_multipart.multipart import parse_options_header

        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        try:
            self.name = options.get(b"name", b"").decode("utf-8")
        except UnicodeError as exc:
            raise HTTPException(400, "Invalid multipart field name.") from exc
        if disposition != b"form-data" or self.name not in {"file", "model", "language", "task"}:
            raise HTTPException(400, "Unexpected multipart field.")
        if self.name == "file":
            if self.file_seen:
                raise HTTPException(400, "Only one media file is accepted.")
            self.file_seen = True
        elif self.name in self.fields:
            raise HTTPException(400, "Duplicate multipart field.")

    def part_data(self, data, start, end):
        from fastapi import HTTPException

        target = self.audio if self.name == "file" else self.value
        limit = self.limit if self.name == "file" else 128
        if len(target) + end - start > limit:
            raise HTTPException(413, "Uploaded file or field exceeds the size limit.")
        target.extend(data[start:end])

    def part_end(self):
        from fastapi import HTTPException

        if self.name != "file":
            try:
                self.fields[self.name] = self.value.decode("utf-8")
            except UnicodeError as exc:
                raise HTTPException(400, "Multipart fields must be UTF-8.") from exc

    def end(self):
        self.ended = True


async def _read_upload(request, limit):
    from fastapi import HTTPException
    from python_multipart import MultipartParser
    from python_multipart.exceptions import MultipartParseError
    from python_multipart.multipart import parse_options_header

    kind, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise HTTPException(400, "Expected multipart/form-data with a valid boundary.")
    body_limit = limit + 16 * 1024
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
            if length < 0:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length.") from exc
        if length > body_limit:
            raise HTTPException(413, "Request exceeds the upload limit.")
    upload = _MultipartUpload(limit)
    parser = MultipartParser(boundary, upload.callbacks())
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > body_limit:
                raise HTTPException(413, "Request exceeds the upload limit.")
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        raise HTTPException(400, "Malformed multipart body.") from exc
    if not upload.ended or not upload.file_seen or not upload.audio:
        raise HTTPException(400, "A complete, non-empty media file is required.")
    return upload


def create_app(*, engine=None, max_upload_bytes=DEFAULT_UPLOAD_BYTES, max_duration_seconds=3600,
               allowed_models=DEFAULT_MODELS, decoder=None):
    from fastapi import FastAPI, HTTPException, Request
    from starlette.requests import ClientDisconnect

    if max_upload_bytes <= 0 or max_duration_seconds <= 0:
        raise ValueError("Upload and duration limits must be positive.")
    models = tuple(allowed_models)
    if not models or any(model not in DEFAULT_MODELS for model in models):
        raise ValueError("Choose at least one supported Whisper model.")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dotaudio-asr")

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="DotAudio", lifespan=lifespan)
    app.state.busy = False
    app.state.engine = engine
    decode = decoder or decode_audio

    @app.get("/health")
    async def health():
        return {"status": "ok", "busy": app.state.busy, "models": models,
                "max_upload_bytes": max_upload_bytes, "max_duration_seconds": max_duration_seconds}

    async def transcribe(request):
        if app.state.busy:
            raise HTTPException(503, "Recognition worker is busy.", headers={"Retry-After": "2"})
        app.state.busy = True
        cancel = threading.Event()
        future = None

        def release(_=None):
            app.state.busy = False
            if future is not None and not future.cancelled():
                future.exception()  # Retrieve abandoned errors after a client disconnect.

        try:
            upload = await _read_upload(request, max_upload_bytes)
            model = upload.fields.get("model", "base" if "base" in models else models[0])
            language = upload.fields.get("language", "auto")
            task = upload.fields.get("task", "transcribe")
            if model not in models:
                raise HTTPException(422, "This Whisper model is not enabled on the server.")
            if task not in {"transcribe", "translate"}:
                raise HTTPException(422, "Task must be transcribe or translate.")
            if language != "auto" and (not language.isascii() or not language.isalpha()
                                       or len(language) not in {2, 3}):
                raise HTTPException(422, "Language must be auto or a Whisper language code.")

            def recognize():
                from dotaudio.engine import Engine, RecognitionConfig

                waveform = decode(bytes(upload.audio), max_duration_seconds, cancel)
                if cancel.is_set():
                    return []
                if app.state.engine is None:
                    app.state.engine = Engine()
                config = RecognitionConfig(model=model, language=language, task=task, backend="local")
                return app.state.engine.transcribe(waveform, config, cancel=cancel)

            future = asyncio.get_running_loop().run_in_executor(executor, recognize)
            while not future.done():
                await asyncio.wait({future}, timeout=0.1)
                if await request.is_disconnected():
                    cancel.set()
                    raise HTTPException(499, "Client disconnected.")
            try:
                segments = future.result()
            except InvalidAudio as exc:
                raise HTTPException(422, str(exc)) from exc
            except Exception as exc:
                raise HTTPException(500, "Recognition failed. Check the model and server configuration.") from exc
            return {"segments": segments}
        except (asyncio.CancelledError, ClientDisconnect):
            cancel.set()
            raise
        finally:
            if future is not None and not future.done():
                cancel.set()
                future.add_done_callback(release)
            else:
                release()

    # Resolve Request explicitly: FastAPI cannot resolve function-local imports in postponed annotations.
    transcribe.__annotations__["request"] = Request
    app.post("/v1/transcribe")(transcribe)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-upload-mib", type=int, default=100)
    parser.add_argument("--max-duration-seconds", type=int, default=3600)
    parser.add_argument("--models", nargs="+", choices=DEFAULT_MODELS, default=["base"])
    args = parser.parse_args()
    if args.max_upload_mib <= 0 or args.max_duration_seconds <= 0:
        parser.error("Upload and duration limits must be positive.")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    import uvicorn

    uvicorn.run(create_app(max_upload_bytes=args.max_upload_mib * 1024 * 1024,
                           max_duration_seconds=args.max_duration_seconds, allowed_models=args.models),
                host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
