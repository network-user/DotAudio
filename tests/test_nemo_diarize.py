"""Проверки обёртки над нативным рантаймом NVIDIA NeMo.

Настоящий CLI здесь не запускается (кроме одного теста отмены, которому
нужен живой процесс): проверяется разбор ответа, поиск исполняемого файла
и то, что отсутствие рантайма даёт понятную ошибку, а не падение.
"""

from __future__ import annotations

import subprocess
import sys
import wave
from threading import Event

import numpy as np
import pytest

from dotaudio import nemo_diarize
from dotaudio.nemo_diarize import (
    NemoUnavailable,
    diarize_audio,
    executable,
    install_command,
    parse_turns,
    probe,
    write_wav,
)


def _completed(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["nemo-speech"], code, stdout, "")


def test_parse_turns_reads_the_cli_answer():
    payload = (
        '{"file": "x.wav", "segments": ['
        '{"start": 0.091, "end": 0.959, "speaker": 1},'
        '{"start": 3.291, "end": 6.559, "speaker": 2}]}'
    )
    turns = parse_turns(payload)
    assert [turn.speaker for turn in turns] == ["1", "2"]
    assert turns[0].start == pytest.approx(0.091)
    assert turns[1].end == pytest.approx(6.559)


def test_parse_turns_sorts_by_time_and_drops_empty_rows():
    payload = (
        '{"segments": ['
        '{"start": 5, "end": 6, "speaker": 2},'
        '{"start": 1, "end": 1, "speaker": 1},'
        '{"start": 4, "end": 3, "speaker": 1},'
        '{"start": 2, "end": 3},'
        '{"start": 0, "end": 1, "speaker": 1}]}'
    )
    turns = parse_turns(payload)
    # Нулевая длительность, перевёрнутый отрезок и строка без говорящего
    # не попадают в разметку: по ним нельзя назначить голос.
    assert [(turn.start, turn.speaker) for turn in turns] == [(0.0, "1"), (5.0, "2")]


def test_parse_turns_reports_a_broken_answer():
    with pytest.raises(RuntimeError):
        parse_turns("это не json")
    with pytest.raises(RuntimeError):
        parse_turns('{"file": "x.wav"}')


def test_write_wav_keeps_length_and_rate(tmp_path):
    audio = np.sin(np.linspace(0, 40, 16000, dtype=np.float32))
    target = tmp_path / "voice.wav"
    write_wav(audio, target)
    with wave.open(str(target), "rb") as saved:
        assert saved.getnchannels() == 1
        assert saved.getsampwidth() == 2
        assert saved.getframerate() == 16000
        assert saved.getnframes() == 16000


def test_executable_prefers_the_one_on_path(monkeypatch):
    monkeypatch.setattr(nemo_diarize.shutil, "which", lambda name: r"C:\nemo\nemo-speech.exe")
    assert executable() == r"C:\nemo\nemo-speech.exe"


def test_executable_falls_back_to_the_installer_prefix(monkeypatch, tmp_path):
    # Установщик дописывает каталог в PATH, но уже запущенный процесс об этом
    # не узнает: без запасного пути рантайм считался бы отсутствующим.
    binary = tmp_path / "nemo-speech.exe"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(nemo_diarize.shutil, "which", lambda name: None)
    monkeypatch.setattr(nemo_diarize, "_candidate_paths", lambda: [binary])
    assert executable() == str(binary)


def test_probe_reports_a_missing_runtime(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "")
    report = probe()
    assert report["available"] is False
    assert report["reason"] == "not_installed"
    assert report["message"]


def test_probe_reports_a_build_without_diarization(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")
    monkeypatch.setattr(
        nemo_diarize, "_run",
        lambda *a, **k: _completed('{"version": "0.1.0", "features": {"diarization": false}}'),
    )
    report = probe()
    assert report["available"] is False
    assert report["reason"] == "no_diarization"
    assert report["version"] == "0.1.0"


def test_probe_accepts_a_working_runtime(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")
    monkeypatch.setattr(
        nemo_diarize, "_run",
        lambda *a, **k: _completed(
            '{"version": "0.1.0", "accelerator_available": false,'
            ' "features": {"diarization": true},'
            ' "devices": [{"description": "Intel CPU", "name": "CPU"}]}'
        ),
    )
    report = probe()
    assert report["available"] is True
    assert "0.1.0" in report["message"]
    assert report["device"] == "Intel CPU"


def test_probe_survives_a_runtime_that_does_not_answer(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")

    def explode(*args, **kwargs):
        raise RuntimeError("NeMo не ответил за 60 с и был остановлен")

    monkeypatch.setattr(nemo_diarize, "_run", explode)
    report = probe()
    assert report["available"] is False
    assert report["reason"] == "broken"


def test_diarize_without_the_runtime_names_the_reason(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "")
    with pytest.raises(NemoUnavailable):
        diarize_audio(np.zeros(16000, dtype=np.float32))


def test_install_runtime_skips_when_already_available(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: r"C:\nemo\nemo-speech.exe")
    monkeypatch.setattr(
        nemo_diarize,
        "probe",
        lambda cancel=None: {
            "available": True,
            "message": "NeMo 0.1.0 · CPU",
            "path": r"C:\nemo\nemo-speech.exe",
        },
    )
    result = nemo_diarize.install_runtime()
    assert result["ok"] is True
    assert result["installed"] is False


def test_install_runtime_refuses_non_windows(monkeypatch):
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "")
    monkeypatch.setattr(nemo_diarize.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        nemo_diarize.install_runtime()


def test_download_keeps_part_on_cancel(tmp_path, monkeypatch):
    """Отмена оставляет .part в кеше, а не в tempfile."""

    from threading import Event

    calls = {"n": 0}

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": "20"}

        def raise_for_status(self):
            return None

        def iter_bytes(self, size):
            yield b"1234567890"
            calls["n"] += 1
            if calls["n"] >= 1:
                cancel.set()
            yield b"abcdefghij"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, *a, **k):
            return FakeResponse()

    cancel = Event()
    monkeypatch.setattr(nemo_diarize.httpx, "Client", FakeClient)
    monkeypatch.setattr(nemo_diarize, "download_cache_dir", lambda: tmp_path)
    target = tmp_path / "nemo.zip"
    with pytest.raises(nemo_diarize.InstallCancelled):
        nemo_diarize._download_file("https://example.test/nemo.zip", target, cancel=cancel)
    assert target.with_suffix(".zip.part").exists() or (tmp_path / "nemo.zip.part").exists()


@pytest.mark.parametrize(
    "device, expected",
    [("", False), ("auto", False), ("cpu", True), ("cuda", True)],
)
def test_device_choice_reaches_the_runtime(monkeypatch, device, expected):
    """"auto" оставляет выбор рантайму, явное устройство передаётся ему."""

    seen: list[list[str]] = []
    monkeypatch.setattr(nemo_diarize, "executable", lambda: "nemo-speech")
    monkeypatch.setattr(nemo_diarize, "ensure_model", lambda *a, **k: None)

    def fake_run(command, timeout, cancel=None):
        seen.append(command)
        target = command[command.index("--output") + 1]
        with open(target, "w", encoding="utf-8") as out:
            out.write('{"segments": [{"start": 0, "end": 1, "speaker": 1}]}')
        return _completed()

    monkeypatch.setattr(nemo_diarize, "_run", fake_run)
    turns = diarize_audio(np.zeros(16000, dtype=np.float32), device=device)
    assert len(turns) == 1
    assert ("--device" in seen[0]) is expected
    if expected:
        assert seen[0][seen[0].index("--device") + 1] == device


def test_install_command_is_offered_for_this_platform():
    command = install_command()
    assert "NeMo-Speech.cpp" in command
    assert command.startswith("irm" if sys.platform == "win32" else "curl")


def test_cancel_kills_the_running_process():
    """Отмена диаризации настоящая: процесс убивается, а не дожидается.

    Это отличает её от кооперативной отмены нативного декодера Whisper.
    """

    cancel = Event()
    cancel.set()
    with pytest.raises(RuntimeError, match="отменено"):
        nemo_diarize._run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30.0,
            cancel=cancel,
        )
