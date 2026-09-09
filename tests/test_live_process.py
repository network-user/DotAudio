from __future__ import annotations

from pathlib import Path

import numpy as np

from dotaudio.controller import LIVE_PROCESS_MIN_SECONDS, Controller
from dotaudio.monitor_clips import SAMPLE_RATE, write_wav
from dotaudio.storage import Store


class _Signal:
    def emit(self, *_args) -> None:
        pass


def _controller(tmp_path: Path) -> Controller:
    store = Store(tmp_path / "dotaudio.sqlite3")
    controller = Controller.__new__(Controller)
    controller.store = store
    controller._data_dir = tmp_path
    controller._live_wavs = {}
    controller._pcm_rings = {}
    controller._jobs = {}
    controller._session_id = ""
    controller._query = ""
    controller._notice = ""
    controller._status = ""
    controller._state = "recording"
    controller._page = "live"
    controller._segments = []
    controller._partial_caption = ""
    controller._partial_source = ""
    controller._preview_stable = ""
    controller._confirmed_caption = ""
    controller._open_phrase = False
    controller._settled_caption = ""
    controller._partial_end = 0.0
    controller._live_phase = "stopping"
    controller._caption_revision = 0
    controller._trans_cancel = type("Cancel", (), {"clear": lambda self: None, "is_set": lambda self: False})()
    controller._trans_state = {
        "phase": "idle",
        "stage": "",
        "file": "",
        "path": "",
        "error": "",
        "speakers": [],
        "diarization": False,
        "engine": "",
        "engineNote": "",
        "duration": 0.0,
        "segments": [],
        "sessionId": "",
        "progress": 0.0,
        "origin": "",
    }
    controller._settings = {"model": "small", "diarize_engine": "off"}
    controller.changed = _Signal()
    controller.statusChanged = _Signal()
    controller.liveStateChanged = _Signal()
    controller.captionChanged = _Signal()
    controller.segmentsChanged = _Signal()
    controller.transcribeChanged = _Signal()
    controller.transcriptPersisted = _Signal()
    controller._record_log = lambda *_args: None
    controller._maybe_autotitle_session = lambda *_args: None
    controller.refreshHistory = lambda *_args: None
    controller._arm_idle_model_release = lambda: None
    controller._close_open_phrase = lambda: None
    controller._input_state = ""
    controller.levelChanged = _Signal()
    controller._level = 0
    controller._closing = False
    return controller


def _write_ready_wav(path: Path, seconds: float = 1.0) -> Path:
    samples = max(1, int(seconds * SAMPLE_RATE))
    return write_wav(path, np.zeros(samples, dtype=np.float32), sample_rate=SAMPLE_RATE)


def test_live_stop_starts_quality_pass_when_wav_is_ready(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    sid = controller.store.create_session("Живые субтитры", "live", "system", "small")
    controller._session_id = sid
    controller._jobs[sid] = {"mode": "live", "name": "Live"}
    started: list[tuple[str, Path]] = []
    wav = _write_ready_wav(tmp_path / "take.wav")
    controller._close_live_wav = lambda _sid: wav
    controller._live_wav_ready = lambda path: path == wav
    controller._start_live_process = lambda sid, path: started.append((sid, path))

    Controller._on_finished(controller, sid, "", False)

    assert started == [(sid, wav)]
    session = controller.store.get_session(sid)
    assert session is not None
    assert session["status"] == "active"


def test_live_cancel_deletes_wav_and_skips_process(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    sid = controller.store.create_session("Живые субтитры", "live", "system", "small")
    controller._session_id = sid
    controller._jobs[sid] = {"mode": "live", "name": "Live"}
    wav = _write_ready_wav(tmp_path / "live" / f"{sid}.wav")
    controller.store.set_session_audio_path(sid, str(wav))
    started: list[Path] = []
    controller._start_live_process = lambda *_args: started.append(True)

    Controller._on_finished(controller, sid, "", True)

    assert started == []
    assert not wav.is_file()
    session = controller.store.get_session(sid)
    assert session is not None
    assert session["status"] == "cancelled"
    assert session["audio_path"] == ""


def test_live_process_finish_replaces_nothing_but_drops_audio(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    sid = controller.store.create_session("Живые субтитры", "live", "system", "small")
    controller.store.append_segments(
        sid, [{"start": 0.0, "end": 1.0, "text": "черновик Live"}]
    )
    controller._session_id = sid
    controller._jobs[sid] = {"mode": "live_process", "name": "Live"}
    wav = _write_ready_wav(tmp_path / "keep.wav")
    controller.store.set_session_audio_path(sid, str(wav))

    Controller._on_finished(controller, sid, "", False)

    assert not wav.is_file()
    session = controller.store.get_session(sid)
    assert session is not None
    assert session["status"] == "completed"
    assert session["audio_path"] == ""
    assert [row["text"] for row in session["segments"]] == ["черновик Live"]
    assert controller._page == "transcript"
    assert controller._trans_state["origin"] == "live"
    assert controller._trans_state["path"] == ""


def test_open_completed_live_opens_transcript_view(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    sid = controller.store.create_session("Живые субтитры", "live", "system", "small")
    controller.store.append_segments(
        sid,
        [{
            "start": 0.0,
            "end": 2.0,
            "text": "готовая фраза",
            "words": [{"text": "готовая", "start": 0.0, "end": 1.0}],
        }],
    )
    controller.store.finish_session(sid, "completed")
    controller._jobs = {}
    controller._media_url = ""
    controller._edit_undo = []
    controller._edit_redo = []
    controller._session_mode = ""
    controller._session_title = ""
    controller._clear_media_peaks = lambda: None
    controller._schedule_media_peaks = lambda *_args: None

    Controller.openSession(controller, sid)

    assert controller._page == "transcript"
    assert controller._trans_state["origin"] == "live"
    assert controller._trans_state["segments"][0]["text"] == "готовая фраза"
    assert controller._trans_state["path"] == ""


def test_transcript_store_payload_keeps_words_and_speaker() -> None:
    controller = Controller.__new__(Controller)
    controller._store_supports_speaker_column = lambda: True
    rows = Controller._transcript_store_payload(
        controller,
        [{
            "start": 0.0,
            "end": 1.4,
            "text": "привет",
            "speaker": "Голос 1",
            "words": [{"text": "привет", "start": 0.0, "end": 1.4}],
            "confidence": 0.8,
        }],
    )
    assert rows[0]["speaker"] == "Голос 1"
    assert rows[0]["words"][0]["text"] == "привет"
    assert rows[0]["confidence"] == 0.8


def test_live_process_min_seconds_matches_dictation_gate() -> None:
    assert LIVE_PROCESS_MIN_SECONDS == 0.35
