from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dotaudio.capture import AudioCapture, StreamCapture, list_input_devices


def test_audio_capture_normalises_and_dispatches_without_device() -> None:
    received: list[np.ndarray] = []
    levels: list[float] = []
    capture = AudioCapture(on_audio=received.append, on_level=levels.append)
    capture._start_dispatcher()
    capture._publish_audio(np.array([[0.5, -0.5], [1.0, 1.0]], dtype=np.float32))
    time.sleep(0.05)
    capture._stop_dispatcher()
    assert np.allclose(received[0], [0.0, 1.0])
    assert levels[0] > 0


def test_list_input_devices_filters_outputs(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Output", "max_input_channels": 0},
                {"name": "Mic", "max_input_channels": 2},
            ]
        ),
    )
    assert list_input_devices() == [{"id": 1, "name": "Mic"}]


def test_capture_error_explains_how_to_recover() -> None:
    capture = AudioCapture(kind="microphone")
    message = capture._start_error(RuntimeError("driver failed"))
    assert "разрешение Windows" in message
    assert "driver failed" in message


@pytest.mark.parametrize(
    "url",
    ["file:///recording.wav", "https://user:pass@example.com/live", "not a url"],
)
def test_stream_capture_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        StreamCapture(url)
