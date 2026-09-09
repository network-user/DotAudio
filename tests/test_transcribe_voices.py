"""Как контроллер превращает роли движка в говорящих на странице.

Полный Controller здесь не создаётся: нужны ровно те методы, что переводят
разметку голосов в подписи, легенду и честную причину отказа.
"""

from __future__ import annotations

from threading import Event

from dotaudio.controller import DIARIZE_ENGINES, Controller


class _Signal:
    def __init__(self):
        self.sent = []

    def emit(self, *args):
        self.sent.append(args[0] if len(args) == 1 else args)


class _Stub:
    """Минимальный контроллер: только то, чем пользуется разметка голосов."""

    _identify_voices = Controller._identify_voices
    _label_speakers = staticmethod(Controller._label_speakers)
    _speaker_legend = staticmethod(Controller._speaker_legend)

    def __init__(self, engine="off"):
        self._settings = {"diarize_engine": engine}
        self._trans_state = {"stage": ""}
        self._trans_cancel = Event()
        self.transcribeChanged = _Signal()
        self.transcribeStatus = _Signal()
        self.logs = []

    def _trans_stage(self, stage):
        self._trans_state["stage"] = stage

    def _record_log(self, tone, message):
        self.logs.append((tone, message))


def test_engine_names_cover_every_stored_choice():
    assert set(DIARIZE_ENGINES) == {"off", "nemo", "ecapa"}


def test_labels_start_at_one_and_skip_unknown_voices():
    rows = Controller._label_speakers([
        {"text": "раз", "role": 0},
        {"text": "два", "role": 1},
        {"text": "три", "role": None},
    ])
    assert [row["role"] for row in rows] == [1, 2, None]
    assert [row["speaker"] for row in rows] == ["Человек 1", "Человек 2", ""]


def test_legend_counts_phrases_and_speaking_time():
    rows = [
        {"role": 1, "speaker": "Человек 1", "start": 0.0, "end": 2.0},
        {"role": 2, "speaker": "Человек 2", "start": 2.0, "end": 3.5},
        {"role": 1, "speaker": "Человек 1", "start": 4.0, "end": 5.0},
        {"role": None, "speaker": "", "start": 6.0, "end": 7.0},
    ]
    legend = Controller._speaker_legend(rows)
    assert [item["key"] for item in legend] == [1, 2]
    assert legend[0]["count"] == 2
    assert legend[0]["seconds"] == 3.0
    assert legend[1]["seconds"] == 1.5


def test_engine_off_returns_text_without_speakers():
    stub = _Stub("off")
    rows, engine, note = _Stub._identify_voices(stub, "a.wav", [{"text": "раз", "start": 0, "end": 1}])
    assert engine == ""
    assert note == ""
    assert rows[0]["speaker"] == ""
    # Этап «голоса» даже не начинался.
    assert stub._trans_state["stage"] == ""


def test_missing_runtime_keeps_the_transcript_and_names_the_reason():
    stub = _Stub("nemo")

    def explode(path, segments):
        raise RuntimeError("рантайм NeMo не установлен")

    stub._voices_nemo = explode
    rows, engine, note = _Stub._identify_voices(stub, "a.wav", [{"text": "раз", "start": 0, "end": 1}])
    # Расшифровка не теряется из-за того, что голоса определить не удалось.
    assert rows[0]["text"] == "раз"
    assert engine == ""
    assert "рантайм NeMo не установлен" in note
    assert stub.logs and stub.logs[0][0] == "warning"


def test_cancel_during_diarization_is_not_reported_as_a_failure():
    stub = _Stub("nemo")
    stub._trans_cancel.set()

    def explode(path, segments):
        raise RuntimeError("определение голосов отменено")

    stub._voices_nemo = explode
    _rows, engine, note = _Stub._identify_voices(stub, "a.wav", [{"text": "раз", "start": 0, "end": 1}])
    assert engine == ""
    assert note == ""
    assert stub.logs == []


def test_persist_transcript_writes_history_session(tmp_path):
    """Страница транскрибации должна сохранять результат в history.db."""

    from pathlib import Path

    from dotaudio.controller import Controller
    from dotaudio.storage import Store

    class _PersistStub:
        _persist_transcript = Controller._persist_transcript
        _maybe_autotitle_session = Controller._maybe_autotitle_session

        def __init__(self):
            self.store = Store(tmp_path / "history.db")
            self._settings = {"model": "small"}
            self.statuses = []
            self.transcribeStatus = _Signal()
            self._session_id = ""
            self._trans_state = {}

    stub = _PersistStub()
    original_emit = stub.transcribeStatus.emit

    def capture(text):
        stub.statuses.append(text)
        original_emit(text)

    stub.transcribeStatus.emit = capture
    path = Path(tmp_path) / "meeting.wav"
    path.write_bytes(b"")
    rows = [
        {"start": 0.0, "end": 1.5, "text": "привет", "speaker": "Человек 1", "words": []},
        {"start": 1.5, "end": 3.0, "text": "мир", "speaker": "", "words": []},
    ]

    session_id = stub._persist_transcript(str(path), rows)

    session = stub.store.get_session(session_id)
    assert session is not None
    assert session["mode"] == "transcript"
    assert session["title"] == "meeting.wav"
    assert session["segments"][0]["text"] == "[Человек 1] привет"
    assert session["segments"][1]["text"] == "мир"
    assert any("истори" in text.casefold() for text in stub.statuses)


def test_open_transcript_in_assistant_emits_session(tmp_path):
    from dotaudio.controller import Controller
    from dotaudio.storage import Store

    class _Bridge:
        selectPage = Controller.selectPage
        openTranscriptInAssistant = Controller.openTranscriptInAssistant

        def __init__(self):
            self.store = Store(tmp_path / "history.db")
            self._page = "transcript"
            self._trans_state = {"sessionId": ""}
            self.statuses = []
            self.opened = []
            self.transcribeStatus = _Signal()
            self.openAssistantWithRecord = _Signal()
            self.changed = _Signal()
            self.logs = []

        def _record_log(self, tone, message):
            self.logs.append((tone, message))

    bridge = _Bridge()
    bridge.openTranscriptInAssistant()
    assert bridge.openAssistantWithRecord.sent == []
    assert bridge.statuses or bridge.transcribeStatus.sent

    sid = bridge.store.create_session("a.wav", "transcript", "a.wav", "small")
    bridge.store.append_segments(sid, [{"start": 0.0, "end": 1.0, "text": "hi"}])
    bridge._trans_state["sessionId"] = sid
    bridge.transcribeStatus.sent.clear()
    bridge.openTranscriptInAssistant()

    assert bridge._page == "assistant"
    assert bridge.openAssistantWithRecord.sent == [sid]
