import asyncio
import io
import threading
import wave

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from dotaudio.server import InvalidAudio, create_app, decode_audio, openai_transcription_payload


class FakeEngine:
    def __init__(self):
        self.calls = []

    def transcribe(self, source, config, cancel=None):
        self.calls.append((source, config, cancel))
        return [{"start": 0.0, "end": 1.0, "text": "Привет"}]


def fake_decode(data, duration, cancel):
    assert data == b"audio"
    return np.zeros(16000, dtype=np.float32)


def test_health_and_transcribe():
    engine = FakeEngine()
    with TestClient(create_app(engine=engine, decoder=fake_decode)) as client:
        assert client.get("/health").json()["busy"] is False
        response = client.post("/v1/transcribe", files={"file": ("clip.wav", b"audio")},
                               data={"model": "base", "language": "ru", "task": "transcribe"})
        assert response.status_code == 200
        assert response.json()["segments"][0]["text"] == "Привет"
        assert engine.calls[0][1].language == "ru"
        assert client.get("/health").json()["busy"] is False


def test_openai_transcriptions_json_and_text():
    engine = FakeEngine()
    with TestClient(create_app(engine=engine, decoder=fake_decode)) as client:
        json_response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("clip.wav", b"audio")},
            data={"model": "base", "language": "ru", "response_format": "json"},
        )
        assert json_response.status_code == 200, json_response.text
        assert json_response.json()["text"] == "Привет"
        text_response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("clip.wav", b"audio")},
            data={"model": "base", "response_format": "text"},
        )
        assert text_response.status_code == 200
        assert text_response.text == "Привет"
        verbose = openai_transcription_payload(
            [{"start": 0.0, "end": 1.2, "text": "Привет"}],
            language="ru",
            response_format="verbose_json",
        )
        assert verbose["duration"] == 1.2
        assert verbose["text"] == "Привет"


@pytest.mark.parametrize("body,content_type", [
    (b"audio", "audio/wav"),
    (b"broken", "multipart/form-data; boundary=x"),
    (b'--x\r\nContent-Disposition: form-data; name="file"\r\n\r\naudio',
     "multipart/form-data; boundary=x"),
])
def test_malformed_request(body, content_type):
    with TestClient(create_app(engine=FakeEngine(), decoder=fake_decode)) as client:
        response = client.post("/v1/transcribe", content=body, headers={"Content-Type": content_type})
        assert response.status_code == 400
        assert client.get("/health").json()["busy"] is False


def test_limits_and_model_restriction():
    engine = FakeEngine()
    with TestClient(create_app(engine=engine, decoder=fake_decode,
                               max_upload_bytes=5, allowed_models=("base",))) as client:
        assert client.post("/v1/transcribe", files={"file": ("clip.wav", b"123456")}).status_code == 413
        assert client.post("/v1/transcribe", files={"file": ("clip.wav", b"audio")},
                           data={"model": "large-v3"}).status_code == 422
        assert client.post("/v1/transcribe", files={"file": ("clip.wav", b"audio")},
                           data={"language": "../../xx"}).status_code == 422
        assert client.post("/v1/transcribe", files={"file": ("clip.wav", b"")}).status_code == 400
        assert not engine.calls


def test_streamed_upload_cap_without_content_length():
    async def scenario():
        app = create_app(engine=FakeEngine(), decoder=fake_decode, max_upload_bytes=5)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def chunks():
                yield b'--x\r\nContent-Disposition: form-data; name="file"\r\n\r\n'
                yield b"123"
                yield b"456"
                yield b"\r\n--x--\r\n"
            response = await client.post("/v1/transcribe", content=chunks(),
                                         headers={"Content-Type": "multipart/form-data; boundary=x"})
            assert response.status_code == 413
    asyncio.run(scenario())


def test_busy_worker_rejects_concurrent_request():
    started, finish = threading.Event(), threading.Event()

    class SlowEngine(FakeEngine):
        def transcribe(self, source, config, cancel=None):
            started.set()
            assert finish.wait(3)
            return super().transcribe(source, config, cancel)

    with TestClient(create_app(engine=SlowEngine(), decoder=fake_decode)) as client:
        result = []
        thread = threading.Thread(target=lambda: result.append(
            client.post("/v1/transcribe", files={"file": ("clip.wav", b"audio")}).status_code))
        thread.start()
        try:
            assert started.wait(3)
            assert client.get("/health").json()["busy"] is True
            response = client.post("/v1/transcribe", files={"file": ("clip.wav", b"audio")})
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "2"
        finally:
            finish.set()
            thread.join(3)
        assert result == [200]


def test_decoder_enforces_duration_and_bad_input():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
    assert decode_audio(buffer.getvalue(), 2, threading.Event()).shape == (16000,)
    with pytest.raises(InvalidAudio, match="exceeds"):
        decode_audio(buffer.getvalue(), 0.5, threading.Event())
    with pytest.raises(InvalidAudio, match="cannot be decoded"):
        decode_audio(b"not media", 2, threading.Event())


def test_decoder_error_releases_worker():
    def fail_decode(*args):
        raise InvalidAudio("Broken audio.")
    with TestClient(create_app(engine=FakeEngine(), decoder=fail_decode)) as client:
        assert client.post("/v1/transcribe", files={"file": ("a.wav", b"x")}).status_code == 422
        assert client.get("/health").json()["busy"] is False


def test_disconnect_cancels_inference_and_holds_worker_until_finished():
    started, finish = threading.Event(), threading.Event()
    cancellation = []

    class SlowEngine(FakeEngine):
        def transcribe(self, source, config, cancel=None):
            cancellation.append(cancel)
            started.set()
            finish.wait(3)
            return []

    async def scenario():
        app = create_app(engine=SlowEngine(), decoder=fake_decode)
        request = httpx.Request("POST", "http://test/v1/transcribe",
                                files={"file": ("clip.wav", b"audio")})
        body = request.read()
        delivered = False
        messages = []

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            if started.is_set():
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/v1/transcribe", "raw_path": b"/v1/transcribe",
                 "query_string": b"", "headers": [(key.lower(), value) for key, value in request.headers.raw],
                 "client": ("127.0.0.1", 1234),
                 "server": ("test", 80), "root_path": ""}
        try:
            await asyncio.wait_for(app(scope, receive, send), timeout=3)
            assert messages[0]["status"] == 499
            assert cancellation[0].is_set()
            assert app.state.busy is True
        finally:
            finish.set()
            for _ in range(100):
                if not app.state.busy:
                    break
                await asyncio.sleep(0.01)
        assert app.state.busy is False

    asyncio.run(scenario())
