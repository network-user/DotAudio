"""Regression scenarios for the latest Whisper feedback.

This file is intentionally separate from the established unit-test modules.
It exercises only deterministic public seams and local test doubles: no model
download, microphone, network, or GPU is required.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from dotaudio import nemo_diarize
from dotaudio.adapt import (
    assess_whisper_model_fit,
    whisper_memory_requirements,
)
from dotaudio.audio_preprocess import (
    PreprocessConfig,
    normalise_preprocess_config,
    preprocess_audio,
)
from dotaudio.diag import classify_setup_error, normalise_setup_progress
from dotaudio.model_registry import ModelRegistry, ModelValidationError
from dotaudio.nemo_diarize import diarize_audio
from dotaudio.storage import Store
from dotaudio.watch_folder import WatchFolder


def _ct2_model(path: Path) -> Path:
    path.mkdir()
    (path / "model.bin").write_bytes(b"synthetic-weights")
    (path / "config.json").write_text(
        json.dumps({"model_type": "marian"}),
        encoding="utf-8",
    )
    (path / "source.spm").write_bytes(b"source-tokenizer")
    (path / "target.spm").write_bytes(b"target-tokenizer")
    return path


def _wait_until(predicate, *, timeout: float = 1.5, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition was not met before timeout")


# -- preflight / fit ---------------------------------------------------------


def test_feedback_preflight_rejects_cuda_with_insufficient_free_vram() -> None:
    requirement = whisper_memory_requirements("medium", device="cuda", compute_type="int8")
    report = assess_whisper_model_fit(
        "medium",
        {
            "ram_available_gb": requirement["ram_mb"] / 1024 + 2.0,
            "gpus": [{"vendor": "nvidia", "vramFreeMb": max(0, requirement["vram_mb"] - 1)}],
        },
        device="cuda",
        compute_type="int8",
    )

    assert report["state"] == "insufficient"
    assert report["available_vram_mb"] < report["vram_mb"]
    assert report["ram_state"] == "fit"


def test_feedback_preflight_accepts_model_when_ram_and_vram_have_headroom() -> None:
    requirement = whisper_memory_requirements("small", device="cuda", compute_type="int8")
    report = assess_whisper_model_fit(
        "small",
        {
            "ram_available_gb": requirement["ram_mb"] / 1024 + 1.0,
            "gpus": [{"vendor": "nvidia", "vramFreeMb": requirement["vram_mb"] + 1024}],
        },
        device="cuda",
        compute_type="int8",
    )

    assert report["state"] == "fit"
    assert report["headroom_mb"] >= 1024
    assert report["available_vram_mb"] >= report["vram_mb"]


def test_feedback_preflight_does_not_block_unknown_custom_model_without_telemetry() -> None:
    report = assess_whisper_model_fit(
        "my-local-whisper",
        {},
        device="cuda",
        compute_type="int8",
    )

    assert report["known"] is False
    assert report["state"] == "unknown"
    assert report["available_mb"] is None


# -- noise preprocessing -----------------------------------------------------


def test_feedback_noise_preprocess_disabled_preserves_samples() -> None:
    source = np.array([-0.25, 0.0, 0.5, -0.75], dtype=np.float32)

    result = preprocess_audio(source, PreprocessConfig(enabled=False))

    assert result.dtype == np.float32
    assert np.array_equal(result, source)


def test_feedback_noise_preprocess_sanitises_stereo_and_non_finite_input() -> None:
    source = np.array(
        [[np.nan, 0.2], [np.inf, -0.2], [-np.inf, 0.4]],
        dtype=np.float32,
    )

    result = preprocess_audio(
        source,
        PreprocessConfig(enabled=True, highpass_hz=80.0),
    )

    assert result.shape == (3,)
    assert result.dtype == np.float32
    assert np.isfinite(result).all()
    assert np.max(np.abs(result)) <= 1.0


def test_feedback_noise_preprocess_clamps_untrusted_filter_settings() -> None:
    config = normalise_preprocess_config(
        PreprocessConfig(
            enabled=True,
            sample_rate=1,
            frame_ms=999.0,
            hop_ms=-20.0,
            noise_seconds=99.0,
            reduction_strength=9.0,
            spectral_floor=-1.0,
            highpass_hz=999_999.0,
        )
    )

    assert config.sample_rate == 16_000
    assert config.frame_ms == 64.0
    assert config.hop_ms == 4.0
    assert config.noise_seconds == 5.0
    assert config.reduction_strength == 1.0
    assert config.spectral_floor == 0.0
    assert config.highpass_hz == pytest.approx(7_200.0)


# -- custom translation registry --------------------------------------------


def test_feedback_translation_registry_imports_and_reloads_local_model(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path / "registry")
    model = _ct2_model(tmp_path / "en-ru")

    descriptor = registry.register_local(
        model,
        model_id="meeting-en-ru",
        source_language="en",
        target_language="ru",
        label="Meeting EN → RU",
    )
    reloaded = ModelRegistry(registry.root)

    assert descriptor.pair.code == "en-ru"
    assert reloaded.require("meeting-en-ru").validate().valid
    assert [pair.code for pair in reloaded.translation_pairs()] == ["en-ru"]


def test_feedback_translation_registry_rejects_incomplete_ct2_directory(tmp_path: Path) -> None:
    model = tmp_path / "incomplete"
    model.mkdir()
    (model / "model.bin").write_bytes(b"weights")
    (model / "config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ModelValidationError) as error:
        ModelRegistry(tmp_path / "registry").register_local(
            model,
            model_id="broken-en-ru",
            source_language="en",
            target_language="ru",
        )

    assert error.value.code == "invalid_ctranslate2_model"
    assert "target.spm" in str(error.value)


def test_feedback_translation_registry_rejects_pair_mismatch_and_unknown_fields(
    tmp_path: Path,
) -> None:
    model = _ct2_model(tmp_path / "en-ru")
    registry = ModelRegistry(tmp_path / "registry")
    registry.register_local(
        model,
        model_id="pair-en-ru",
        source_language="en",
        target_language="ru",
    )

    with pytest.raises(ModelValidationError) as mismatch:
        registry.resolve_pair("en", "de", model_id="pair-en-ru")
    assert mismatch.value.code == "model_pair_mismatch"

    with pytest.raises(ModelValidationError) as unknown:
        registry.require("not-registered")
    assert unknown.value.code == "model_not_found"


# -- watch-folder stability --------------------------------------------------


def test_feedback_watch_folder_ignores_files_present_during_initial_scan(tmp_path: Path) -> None:
    existing = tmp_path / "before.wav"
    existing.write_bytes(b"already complete")
    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.01)

    watcher.start()
    try:
        time.sleep(0.08)
    finally:
        watcher.stop()

    assert seen == []


def test_feedback_watch_folder_waits_for_two_stable_polls(tmp_path: Path) -> None:
    seen: list[Path] = []
    poll_seconds = 0.05
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=poll_seconds)
    target = tmp_path / "recording.wav"

    watcher.start()
    try:
        time.sleep(poll_seconds * 4)
        target.write_bytes(b"first chunk")
        # The first observation only arms the stability counter.  This delay
        # is shorter than a poll interval, so a second unchanged observation
        # cannot occur before the file grows again.
        time.sleep(poll_seconds * 0.2)
        assert seen == []
        target.write_bytes(b"first chunk plus second chunk")
        _wait_until(lambda: target in seen)
    finally:
        watcher.stop()

    assert seen == [target]


def test_feedback_watch_folder_can_be_disabled_without_emitting_new_files(tmp_path: Path) -> None:
    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.01)

    watcher.start()
    try:
        time.sleep(0.08)
        watcher.set_path(None)
        (tmp_path / "ignored.mp3").write_bytes(b"not processed")
        time.sleep(0.08)
    finally:
        watcher.stop()

    assert seen == []


# -- diarization fallback and transcript preservation -----------------------


def test_feedback_diarization_retries_on_cpu_after_cuda_failure(monkeypatch) -> None:
    flags: list[str] = []
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")
    monkeypatch.setattr(nemo_diarize, "ensure_model", lambda *args, **kwargs: None)

    def fake_run(command, timeout, cancel=None):
        del timeout, cancel
        flag = command[command.index("--device") + 1] if "--device" in command else ""
        flags.append(flag)
        if flag == "cuda:0":
            return subprocess.CompletedProcess(command, 1, "", "CUDA out of memory")
        target = Path(command[command.index("--output") + 1])
        target.write_text(
            '{"segments": [{"start": 0, "end": 1, "speaker": 1}]}',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(nemo_diarize, "_run", fake_run)

    turns = diarize_audio(np.zeros(16_000, dtype=np.float32), device="cuda")

    assert flags[0] == "cuda:0"
    assert flags.index("cpu") > 0
    assert turns[0].speaker == "1"


def test_feedback_diarization_cpu_path_never_requests_cuda(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")
    monkeypatch.setattr(nemo_diarize, "ensure_model", lambda *args, **kwargs: None)

    def fake_run(command, timeout, cancel=None):
        del timeout, cancel
        commands.append(command)
        target = Path(command[command.index("--output") + 1])
        target.write_text(
            '{"segments": [{"start": 0.2, "end": 0.8, "speaker": 2}]}',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(nemo_diarize, "_run", fake_run)

    turns = diarize_audio(np.zeros(8_000, dtype=np.float32), device="cpu")

    assert len(commands) == 1
    assert commands[0][commands[0].index("--device") + 1] == "cpu"
    # The stitching layer intentionally renumbers the first local speaker to
    # the first global role, regardless of the backend's numeric label.
    assert turns[0].speaker == "1"


def test_feedback_diarization_unavailable_keeps_plain_text_for_storage(tmp_path: Path) -> None:
    rows = [{"start": 0.0, "end": 1.0, "text": "text survives", "words": [], "speaker": ""}]
    diagnostic = classify_setup_error("NeMo diarization runtime is unavailable")
    store = Store(tmp_path / "history.sqlite3")
    session_id = store.create_session("speech.wav", "transcript", "speech.wav", "tiny")
    store.append_segments(session_id, rows)
    saved = store.get_session(session_id)

    assert diagnostic["code"] == "diarization_unavailable"
    assert "continue_without_diarization" in diagnostic["actions"]
    assert saved is not None
    assert saved["segments"][0]["text"] == "text survives"


# -- indeterminate progress payloads ----------------------------------------


def test_feedback_progress_without_backend_percentage_is_indeterminate() -> None:
    payload = normalise_setup_progress(
        {"phase": "model_loading", "message": "Loading model"},
        step_id="whisper",
    )

    assert payload["stepId"] == "whisper"
    assert payload["determinate"] is False
    assert payload["indeterminate"] is True
    assert payload["percent"] is None


def test_feedback_progress_uses_bytes_only_when_total_is_known() -> None:
    payload = normalise_setup_progress(
        {"phase": "download", "bytes": 256, "total": 1024},
    )

    assert payload["determinate"] is True
    assert payload["indeterminate"] is False
    assert payload["percent"] == 25.0
    assert payload["ratio"] == 0.25


def test_feedback_progress_explicit_indeterminate_flag_wins_over_stale_percentage() -> None:
    payload = normalise_setup_progress(
        {"phase": "model_loading", "percent": 55.0, "indeterminate": True},
    )

    assert payload["determinate"] is False
    assert payload["indeterminate"] is True
    assert payload["percent"] is None
