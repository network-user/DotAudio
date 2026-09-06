from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dotaudio.capture import (
    AudioCapture,
    StreamCapture,
    list_input_devices,
    list_loopback_devices,
    list_output_devices,
    play_output_tone,
    playback_device_for_loopback,
)


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


def test_list_output_devices_filters_inputs(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Mic", "max_output_channels": 0},
                {"name": "Headphones", "max_output_channels": 2},
            ]
        ),
    )
    assert list_output_devices() == [{"id": 1, "name": "Headphones"}]


def test_list_loopback_devices_keeps_unique_windows_endpoint_ids(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "soundcard",
        SimpleNamespace(
            all_speakers=lambda: [
                SimpleNamespace(id="endpoint-1", name="Headphones"),
                SimpleNamespace(id="endpoint-1", name="Headphones duplicate"),
                SimpleNamespace(id="endpoint-2", name="Monitor"),
            ]
        ),
    )

    assert list_loopback_devices() == [
        {"id": "endpoint-1", "name": "Headphones"},
        {"id": "endpoint-2", "name": "Monitor"},
    ]


def test_playback_device_for_loopback_prefers_wasapi_alias(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "soundcard",
        SimpleNamespace(get_speaker=lambda identifier: SimpleNamespace(name="Headphones")),
    )
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Headphones, Windows DirectSound", "max_output_channels": 2},
                {"name": "Headphones, Windows WASAPI", "max_output_channels": 2},
            ],
            default=SimpleNamespace(device=[0, -1]),
        ),
    )

    assert playback_device_for_loopback("endpoint-1") == 1


def test_output_tone_rejects_unreasonable_duration() -> None:
    with pytest.raises(ValueError):
        play_output_tone(None, duration=0)


def test_capture_error_explains_how_to_recover() -> None:
    capture = AudioCapture(kind="microphone")
    message = capture._start_error(RuntimeError("driver failed"))
    assert "разрешение Windows" in message
    assert "driver failed" in message


def test_start_propagates_microphone_open_failure(monkeypatch) -> None:
    def fail_stream(**_kwargs):
        raise RuntimeError("driver busy")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=fail_stream))
    with pytest.raises(RuntimeError, match="Не удалось открыть микрофон"):
        AudioCapture(kind="microphone").start()


def test_system_capture_resolves_selected_output_index(monkeypatch) -> None:
    selected_speaker = object()
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(query_devices=lambda index, kind: {"name": "Headphones"}),
    )
    soundcard = SimpleNamespace(
        default_speaker=lambda: object(),
        get_speaker=lambda name: selected_speaker if name == "Headphones" else None,
    )

    assert AudioCapture(kind="system", device=4)._resolve_loopback_speaker(soundcard) is selected_speaker


def test_system_capture_uses_loopback_microphone_endpoint() -> None:
    speaker = SimpleNamespace(id="speaker-id")
    microphone = object()
    soundcard = SimpleNamespace(
        default_speaker=lambda: speaker,
        get_microphone=lambda identifier, include_loopback: (
            microphone if identifier == "speaker-id" and include_loopback else None
        ),
    )

    assert AudioCapture(kind="system")._resolve_loopback_microphone(soundcard) is microphone


@pytest.mark.parametrize(
    "url",
    ["file:///recording.wav", "https://user:pass@example.com/live", "not a url"],
)
def test_stream_capture_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        StreamCapture(url)
