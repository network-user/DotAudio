from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dotaudio.capture import (
    AudioCapture,
    StreamCapture,
    describe_capture_error,
    list_input_devices,
    list_loopback_devices,
    list_output_devices,
    mix_audio_blocks,
    next_live_source,
    open_live_capture,
    play_output_tone,
    play_pcm,
    playback_device_for_loopback,
    source_for_mode,
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


def test_level_meter_does_not_evict_audio_blocks_from_capture_queue() -> None:
    received: list[np.ndarray] = []
    gaps: list[int] = []
    capture = AudioCapture(on_audio=received.append, on_gap=gaps.append)

    # Fill the audio queue before starting its consumer. The old shared queue
    # held both audio and meter events, so these 24 blocks lost audio merely
    # because every one also emitted a level update.
    for index in range(24):
        capture._publish_audio(np.full(16, index, dtype=np.float32))
    capture._start_dispatcher()
    time.sleep(0.1)
    capture._stop_dispatcher()

    assert len(received) == 24
    assert gaps == []


def test_capture_reports_audio_gap_when_the_bounded_audio_queue_overflows() -> None:
    received: list[np.ndarray] = []
    gaps: list[int] = []
    capture = AudioCapture(on_audio=received.append, on_gap=gaps.append)

    for index in range(25):
        capture._publish_audio(np.full(16, index, dtype=np.float32))
    capture._start_dispatcher()
    time.sleep(0.1)
    capture._stop_dispatcher()

    assert len(received) == 24
    assert gaps == [1]


def test_list_input_devices_filters_outputs(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Output", "max_input_channels": 0, "hostapi": 0},
                {"name": "Mic", "max_input_channels": 2, "hostapi": 0},
            ],
            query_hostapis=lambda: [{"name": "MME"}],
        ),
    )
    assert list_input_devices() == [{"id": 1, "name": "Mic"}]


def test_list_input_devices_dedupes_hostapi_aliases(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Микрофон (UNA USB audio)", "max_input_channels": 1, "hostapi": 0},
                {"name": "Микрофон (UNA USB audio)", "max_input_channels": 1, "hostapi": 1},
                {"name": "Первичный драйвер записи звука", "max_input_channels": 2, "hostapi": 1},
                {"name": "Микрофон (Steam Streaming Microphone)", "max_input_channels": 1, "hostapi": 0},
            ],
            query_hostapis=lambda: [
                {"name": "MME"},
                {"name": "Windows WDM-KS"},
            ],
        ),
    )
    assert list_input_devices() == [{"id": 1, "name": "Микрофон (UNA USB audio)"}]


def test_resolve_microphone_candidates_prefers_wdm_ks(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [
                {"name": "Mic (USB)", "max_input_channels": 1, "hostapi": 0},
                {"name": "Mic (USB)", "max_input_channels": 1, "hostapi": 1},
            ],
            query_hostapis=lambda: [{"name": "MME"}, {"name": "Windows WDM-KS"}],
            default=SimpleNamespace(device=[0, 1]),
        ),
    )
    from dotaudio.capture import resolve_microphone_candidates

    assert resolve_microphone_candidates(0) == [1, 0]
    assert resolve_microphone_candidates(None) == [1, 0]


def test_resample_to_target_halves_length() -> None:
    from dotaudio.capture import _resample_to_target

    source = np.linspace(-0.5, 0.5, 32, dtype=np.float32)
    out = _resample_to_target(source, 32000, 16000)
    assert 14 <= out.size <= 18


def test_list_input_devices_drops_dead_wdm_only_ghosts(monkeypatch) -> None:
    class DeadStream:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda *args, **kwargs: [
                {"name": "Микрофон (G435)", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
                {"name": "Микрофон (UNA)", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 48000},
            ]
            if not args
            else {
                "name": "Микрофон (G435)",
                "max_input_channels": 1,
                "hostapi": 0,
                "default_samplerate": 48000,
            },
            query_hostapis=lambda: [{"name": "Windows WDM-KS"}, {"name": "MME"}],
            InputStream=DeadStream,
        ),
    )
    monkeypatch.setattr("dotaudio.capture.time.sleep", lambda _seconds: None)
    assert list_input_devices() == [{"id": 1, "name": "Микрофон (UNA)"}]
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


def test_play_pcm_rejects_empty_and_plays_mono(monkeypatch) -> None:
    played: list[tuple] = []

    class FakeSd:
        @staticmethod
        def play(audio, samplerate=16000, device=None, blocking=True):
            played.append((audio.copy(), samplerate, device, blocking))

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSd)

    with pytest.raises(ValueError):
        play_pcm(np.array([], dtype=np.float32))
    play_pcm(np.array([0.5, -0.5, 0.25], dtype=np.float32), device=3, samplerate=16000)
    assert played[0][1] == 16000
    assert played[0][2] == 3
    assert float(np.max(np.abs(played[0][0]))) <= 0.55 + 1e-6


def test_capture_error_explains_how_to_recover() -> None:
    capture = AudioCapture(kind="microphone")
    message = capture._start_error(RuntimeError("driver failed"))
    assert "микрофон" in message.casefold()
    assert "Среде" in message or "Диктовка" in message
    assert "driver failed" in message


def test_capture_error_names_permission_busy_and_missing_device() -> None:
    permission = describe_capture_error("microphone", PermissionError("access is denied"))
    assert "микрофон" in permission.casefold()
    assert any(
        token in permission
        for token in ("Конфиденциальность", "системных настройках", "PipeWire", "права")
    )
    assert "занят" in describe_capture_error("microphone", RuntimeError("device unavailable"))
    assert "недоступен" in describe_capture_error("microphone", RuntimeError("Invalid device"))
    assert "не найден" in describe_capture_error("microphone", RuntimeError("no default input device"))
    assert "наушники" in describe_capture_error("system", RuntimeError("output device not found for loopback"))


def test_start_propagates_microphone_open_failure(monkeypatch) -> None:
    def fail_stream(**_kwargs):
        raise RuntimeError("driver busy")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=fail_stream))
    with pytest.raises(RuntimeError, match="Микрофон занят"):
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


def test_live_defaults_to_system_audio_even_if_legacy_source_is_microphone() -> None:
    import sys

    kind, device = source_for_mode(
        "live",
        {
            "source": "microphone",
            "input_device": "1",
            "loopback_device": "{0.0.0.00000000}.{speaker}",
        },
    )
    if sys.platform == "win32":
        assert kind == "system"
        assert device == "{0.0.0.00000000}.{speaker}"
    else:
        # Without a monitor/BlackHole device the live default is the microphone.
        assert kind in {"system", "microphone"}
        if kind == "system":
            assert device == "{0.0.0.00000000}.{speaker}"
        else:
            assert device == 1


def test_default_live_source_matches_platform() -> None:
    import sys

    from dotaudio.capture import default_live_source

    expected = "system" if sys.platform == "win32" else "microphone"
    assert default_live_source() == expected


def test_dictation_ignores_live_system_source() -> None:
    kind, device = source_for_mode(
        "dictation",
        {"live_source": "system", "input_device": "4", "loopback_device": "headphones"},
    )
    assert kind == "microphone"
    assert device == 4


def test_live_mixed_source_uses_both_devices() -> None:
    kind, device = source_for_mode(
        "live",
        {"live_source": "mixed", "input_device": "2", "loopback_device": "headphones"},
    )
    assert kind == "mixed"
    assert device is None
    capture = open_live_capture("mixed", {"input_device": "2", "loopback_device": "headphones"})
    assert capture._mic.device == 2
    assert capture._sys.device == "headphones"


def test_live_source_cycles_system_mixed_microphone() -> None:
    assert next_live_source("system") == "mixed"
    assert next_live_source("mixed") == "microphone"
    assert next_live_source("microphone") == "system"
    assert next_live_source("unknown") == "mixed"


def test_mix_audio_blocks_sums_and_clips() -> None:
    left = np.array([0.2, 0.8], dtype=np.float32)
    right = np.array([0.3, 0.8], dtype=np.float32)
    mixed = mix_audio_blocks(left, right)
    assert np.allclose(mixed, [0.5, 1.0])
    assert np.allclose(mix_audio_blocks(left, None), left)


def test_live_can_still_use_microphone() -> None:
    kind, device = source_for_mode(
        "live",
        {"live_source": "microphone", "input_device": "", "loopback_device": "ignored"},
    )
    assert kind == "microphone"
    assert device is None


def test_system_loop_records_native_mix_channels(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def record(self, numframes):
            raise RuntimeError("opened")

    class Microphone:
        channels = 2

        def recorder(self, **kwargs):
            recorded.update(kwargs)
            return Recorder()

    capture = AudioCapture(kind="system")
    capture._resolve_loopback_microphone = lambda _soundcard: Microphone()  # type: ignore[method-assign]
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace())
    capture._system_loop()
    assert recorded["channels"] == 2
    assert recorded["samplerate"] == 16000


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
