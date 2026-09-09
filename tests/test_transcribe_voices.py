"""Как контроллер превращает роли движка в говорящих на странице.

Полный Controller здесь не создаётся: нужны ровно те методы, что переводят
разметку голосов в подписи, легенду и честную причину отказа.
"""

from __future__ import annotations

import inspect
from threading import Event

from dotaudio.controller import DIARIZE_ENGINES, Controller
from dotaudio.speaker_labels import (
    default_speaker_label,
    is_default_speaker_label,
    speaker_label_for_kind,
)


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
        self._trans_state = {"stage": "", "progress": 0.0}
        self._trans_cancel = Event()
        self.transcribeChanged = _Signal()
        self.transcribeStatus = _Signal()
        self.transcribeTick = _Signal()
        self.logs = []

    def _trans_stage(self, stage):
        self._trans_state["stage"] = stage
        if stage == "voices":
            self._trans_state["progress"] = -1.0

    def _record_log(self, tone, message):
        self.logs.append((tone, message))


def _store_has_speaker() -> bool:
    from dotaudio.storage import Store

    return "speaker" in inspect.signature(Store.update_segment).parameters


def test_engine_names_cover_every_stored_choice():
    assert set(DIARIZE_ENGINES) == {"off", "nemo", "ecapa"}


def test_default_speaker_label_is_voice_numbered_from_one():
    assert default_speaker_label(1) == "Голос 1"
    assert default_speaker_label(2) == "Голос 2"


def test_speaker_label_for_kind_variants():
    assert speaker_label_for_kind(1, "voice") == "Голос 1"
    assert speaker_label_for_kind(2, "male") == "Парень 2"
    assert speaker_label_for_kind(3, "female") == "Девушка 3"
    assert is_default_speaker_label("Голос 1", 1)
    assert is_default_speaker_label("Парень 1", 1)
    assert is_default_speaker_label("Девушка 1", 1)
    assert not is_default_speaker_label("Анна", 1)
    assert not is_default_speaker_label("Голос 2", 1)


def test_labels_start_at_one_and_skip_unknown_voices():
    rows = Controller._label_speakers([
        {"text": "раз", "role": 0},
        {"text": "два", "role": 1},
        {"text": "три", "role": None},
    ])
    assert [row["role"] for row in rows] == [1, 2, None]
    assert [row["speaker"] for row in rows] == ["Голос 1", "Голос 2", ""]


def test_legend_counts_phrases_and_speaking_time():
    rows = [
        {"role": 1, "speaker": "Голос 1", "start": 0.0, "end": 2.0},
        {"role": 2, "speaker": "Голос 2", "start": 2.0, "end": 3.5},
        {"role": 1, "speaker": "Голос 1", "start": 4.0, "end": 5.0},
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

    def explode(path, segments, audio=None):
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

    def explode(path, segments, audio=None):
        raise RuntimeError("определение голосов отменено")

    stub._voices_nemo = explode
    _rows, engine, note = _Stub._identify_voices(stub, "a.wav", [{"text": "раз", "start": 0, "end": 1}])
    assert engine == ""
    assert note == ""
    assert stub.logs == []


def test_persist_transcript_writes_history_session(tmp_path):
    """Страница транскрибации должна сохранять результат в history.db."""

    from pathlib import Path

    from dotaudio.storage import Store

    class _PersistStub:
        _persist_transcript = Controller._persist_transcript
        _transcript_store_payload = Controller._transcript_store_payload
        _maybe_autotitle_session = Controller._maybe_autotitle_session
        _store_supports_speaker_column = Controller._store_supports_speaker_column

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
        {"start": 0.0, "end": 1.5, "text": "привет", "speaker": "Голос 1", "words": []},
        {"start": 1.5, "end": 3.0, "text": "мир", "speaker": "", "words": []},
    ]

    session_id = stub._persist_transcript(str(path), rows)

    session = stub.store.get_session(session_id)
    assert session is not None
    assert session["mode"] == "transcript"
    assert session["title"] == "meeting.wav"
    assert rows[0].get("id") is not None
    assert rows[1].get("id") is not None
    seg0, seg1 = session["segments"]
    if _store_has_speaker():
        assert seg0["text"] == "привет"
        assert seg0.get("speaker") == "Голос 1"
        assert seg1["text"] == "мир"
        assert not seg1.get("speaker")
    else:
        assert seg0["text"] == "[Голос 1] привет"
        assert seg1["text"] == "мир"
    assert any("истори" in text.casefold() for text in stub.statuses)


def test_open_transcript_session_dual_read():
    """Колонка speaker и legacy-префикс читаются одинаково."""

    class _Open:
        _open_transcript_session = Controller._open_transcript_session
        _split_stored_segment = staticmethod(Controller._split_stored_segment)

        def __init__(self):
            self._trans_state = {
                "phase": "idle", "stage": "", "path": "", "file": "",
                "error": "", "speakers": [], "segments": [],
                "diarization": False, "engine": "", "engineNote": "",
                "duration": 0.0, "sessionId": "", "progress": 0.0,
            }
            self._page = "history"
            self.transcribeChanged = _Signal()

    stub = _Open()
    stub._open_transcript_session({
        "id": "s1",
        "title": "call.wav",
        "source": "",
        "segments": [
            {"id": 1, "start": 0.0, "end": 1.0, "text": "привет", "speaker": "Анна"},
            {"id": 2, "start": 1.0, "end": 2.0, "text": "[Голос 2] мир"},
            {"id": 3, "start": 2.0, "end": 3.0, "text": "без метки"},
        ],
    })
    rows = stub._trans_state["segments"]
    assert rows[0]["text"] == "привет"
    assert rows[0]["speaker"] == "Анна"
    assert rows[1]["text"] == "мир"
    assert rows[1]["speaker"] == "Голос 2"
    assert rows[2]["speaker"] == ""
    assert stub._trans_state["diarization"] is True
    assert stub._page == "transcript"


def test_rename_transcript_speaker_updates_segments_and_legend():
    class _Rename:
        renameTranscriptSpeaker = Controller.renameTranscriptSpeaker
        _persist_transcript_speaker_labels = Controller._persist_transcript_speaker_labels

        def __init__(self):
            self.store = None
            self._trans_state = {
                "sessionId": "",
                "speakers": [
                    {"key": 1, "label": "Голос 1", "count": 1, "seconds": 1.0},
                    {"key": 2, "label": "Голос 2", "count": 1, "seconds": 1.0},
                ],
                "segments": [
                    {"role": 1, "speaker": "Голос 1", "text": "раз", "start": 0.0, "end": 1.0},
                    {"role": 2, "speaker": "Голос 2", "text": "два", "start": 1.0, "end": 2.0},
                    {"role": None, "speaker": "", "text": "три", "start": 2.0, "end": 3.0},
                ],
            }
            self.transcribeChanged = _Signal()

    stub = _Rename()
    stub.renameTranscriptSpeaker(1, "Анна")
    assert stub._trans_state["speakers"][0]["label"] == "Анна"
    assert stub._trans_state["segments"][0]["speaker"] == "Анна"
    assert stub._trans_state["segments"][1]["speaker"] == "Голос 2"
    assert stub._trans_state["segments"][2]["speaker"] == ""
    assert stub.transcribeChanged.sent


def test_rename_transcript_speaker_rewrites_history(tmp_path):
    """Новое имя должно попасть в SQLite, иначе история откроет старое."""

    from pathlib import Path

    from dotaudio.storage import Store

    class _RenamePersist:
        renameTranscriptSpeaker = Controller.renameTranscriptSpeaker
        _persist_transcript_speaker_labels = Controller._persist_transcript_speaker_labels
        _persist_transcript = Controller._persist_transcript
        _transcript_store_payload = Controller._transcript_store_payload
        _maybe_autotitle_session = Controller._maybe_autotitle_session
        _store_supports_speaker_column = Controller._store_supports_speaker_column
        _write_segment_to_store = Controller._write_segment_to_store

        def __init__(self):
            self.store = Store(tmp_path / "history.db")
            self._settings = {"model": "small"}
            self.transcribeStatus = _Signal()
            self._session_id = ""
            self._trans_state = {"speakers": [], "segments": [], "sessionId": ""}
            self.transcribeChanged = _Signal()

    stub = _RenamePersist()
    path = Path(tmp_path) / "call.wav"
    path.write_bytes(b"")
    rows = [
        {"start": 0.0, "end": 1.0, "text": "раз", "speaker": "Голос 1", "role": 1, "words": []},
        {"start": 1.0, "end": 2.0, "text": "два", "speaker": "Голос 2", "role": 2, "words": []},
    ]
    session_id = stub._persist_transcript(str(path), rows)
    stub._trans_state.update({
        "sessionId": session_id,
        "speakers": [
            {"key": 1, "label": "Голос 1", "count": 1, "seconds": 1.0},
            {"key": 2, "label": "Голос 2", "count": 1, "seconds": 1.0},
        ],
        "segments": rows,
    })

    stub.renameTranscriptSpeaker(1, "Анна")

    session = stub.store.get_session(session_id)
    seg0, seg1 = session["segments"]
    if _store_has_speaker():
        assert seg0["text"] == "раз"
        assert seg0.get("speaker") == "Анна"
        assert seg1["text"] == "два"
        assert seg1.get("speaker") == "Голос 2"
    else:
        assert seg0["text"] == "[Анна] раз"
        assert seg1["text"] == "[Голос 2] два"


def test_edit_transcript_segment_updates_text_and_store(tmp_path):
    from pathlib import Path

    from dotaudio.storage import Store

    class _Edit:
        editTranscriptSegment = Controller.editTranscriptSegment
        _persist_transcript = Controller._persist_transcript
        _transcript_store_payload = Controller._transcript_store_payload
        _maybe_autotitle_session = Controller._maybe_autotitle_session
        _store_supports_speaker_column = Controller._store_supports_speaker_column
        _write_segment_to_store = Controller._write_segment_to_store
        _trans_push_undo = Controller._trans_push_undo

        def __init__(self):
            self.store = Store(tmp_path / "history.db")
            self._settings = {"model": "small"}
            self.transcribeStatus = _Signal()
            self._session_id = ""
            self._trans_state = {"speakers": [], "segments": [], "sessionId": ""}
            self.transcribeChanged = _Signal()
            self._trans_edit_undo = []
            self._trans_edit_redo = []

    stub = _Edit()
    path = Path(tmp_path) / "edit.wav"
    path.write_bytes(b"")
    rows = [
        {"start": 0.0, "end": 1.0, "text": "старое", "speaker": "Голос 1", "role": 1, "words": []},
    ]
    session_id = stub._persist_transcript(str(path), rows)
    stub._trans_state.update({"sessionId": session_id, "segments": rows})

    stub.editTranscriptSegment(0, "новое")

    assert stub._trans_state["segments"][0]["text"] == "новое"
    session = stub.store.get_session(session_id)
    body = session["segments"][0]["text"]
    if _store_has_speaker():
        assert body == "новое"
        assert session["segments"][0].get("speaker") == "Голос 1"
    else:
        assert body == "[Голос 1] новое"


def test_set_transcript_segment_speaker_assigns_role(tmp_path):
    from pathlib import Path

    from dotaudio.storage import Store

    class _Set:
        setTranscriptSegmentSpeaker = Controller.setTranscriptSegmentSpeaker
        _speaker_legend = staticmethod(Controller._speaker_legend)
        _persist_transcript = Controller._persist_transcript
        _transcript_store_payload = Controller._transcript_store_payload
        _maybe_autotitle_session = Controller._maybe_autotitle_session
        _store_supports_speaker_column = Controller._store_supports_speaker_column
        _write_segment_to_store = Controller._write_segment_to_store

        def __init__(self):
            self.store = Store(tmp_path / "history.db")
            self._settings = {"model": "small"}
            self.transcribeStatus = _Signal()
            self._session_id = ""
            self._trans_state = {
                "sessionId": "",
                "speakers": [{"key": 1, "label": "Голос 1", "count": 1, "seconds": 1.0}],
                "segments": [],
            }
            self.transcribeChanged = _Signal()

    stub = _Set()
    path = Path(tmp_path) / "spk.wav"
    path.write_bytes(b"")
    rows = [
        {"start": 0.0, "end": 1.0, "text": "раз", "speaker": "", "role": None, "words": []},
        {"start": 1.0, "end": 2.0, "text": "два", "speaker": "Голос 1", "role": 1, "words": []},
    ]
    session_id = stub._persist_transcript(str(path), rows)
    stub._trans_state.update({
        "sessionId": session_id,
        "segments": rows,
        "speakers": [{"key": 1, "label": "Голос 1", "count": 1, "seconds": 1.0}],
    })

    stub.setTranscriptSegmentSpeaker(0, "Анна")
    assert rows[0]["speaker"] == "Анна"
    assert rows[0]["role"] == 2
    assert any(item["label"] == "Анна" for item in stub._trans_state["speakers"])

    stub.setTranscriptSegmentSpeaker(0, "")
    assert rows[0]["speaker"] == ""
    assert rows[0]["role"] is None


def test_set_transcript_speaker_kind_renames_default_only():
    class _Kind:
        setTranscriptSpeakerKind = Controller.setTranscriptSpeakerKind
        renameTranscriptSpeaker = Controller.renameTranscriptSpeaker
        _persist_transcript_speaker_labels = Controller._persist_transcript_speaker_labels

        def __init__(self):
            self.store = None
            self._trans_state = {
                "sessionId": "",
                "speakers": [
                    {"key": 1, "label": "Голос 1", "count": 1, "seconds": 1.0},
                    {"key": 2, "label": "Анна", "count": 1, "seconds": 1.0},
                ],
                "segments": [
                    {"role": 1, "speaker": "Голос 1", "text": "раз", "start": 0.0, "end": 1.0},
                    {"role": 2, "speaker": "Анна", "text": "два", "start": 1.0, "end": 2.0},
                ],
            }
            self.transcribeChanged = _Signal()

    stub = _Kind()
    stub.setTranscriptSpeakerKind(1, "female")
    assert stub._trans_state["speakers"][0]["kind"] == "female"
    assert stub._trans_state["speakers"][0]["label"] == "Девушка 1"
    assert stub._trans_state["segments"][0]["speaker"] == "Девушка 1"

    stub.setTranscriptSpeakerKind(2, "male")
    assert stub._trans_state["speakers"][1]["kind"] == "male"
    assert stub._trans_state["speakers"][1]["label"] == "Анна"
    assert stub._trans_state["segments"][1]["speaker"] == "Анна"


def test_transcribe_local_emits_streaming_ticks(tmp_path):
    """on_segment должен отдавать копию сегментов и честный progress."""

    class _Engine:
        def transcribe(self, source, config, cancel, on_segment, on_status):
            on_segment({"start": 0.0, "end": 1.0, "text": "раз", "words": []})
            on_segment({"start": 1.0, "end": 2.0, "text": "два", "words": []})
            return []

    class _Stream:
        _transcribe_local = Controller._transcribe_local
        _recognize_file = Controller._recognize_file
        _probe_wav_duration = staticmethod(Controller._probe_wav_duration)
        _identify_voices = Controller._identify_voices
        _label_speakers = staticmethod(Controller._label_speakers)
        _speaker_legend = staticmethod(Controller._speaker_legend)
        _persist_transcript = Controller._persist_transcript
        _transcript_store_payload = Controller._transcript_store_payload
        _store_supports_speaker_column = Controller._store_supports_speaker_column
        _maybe_autotitle_session = Controller._maybe_autotitle_session

        def __init__(self, root):
            from dotaudio.storage import Store

            self.store = Store(root / "history.db")
            self.engine = _Engine()
            self._settings = {
                "model": "tiny",
                "diarize_engine": "off",
                "device": "cpu",
                "speech_mode": "ru",
            }
            self._trans_cancel = Event()
            self._trans_result_session_id = ""
            self._trans_state = {
                "phase": "working", "stage": "asr", "segments": [], "speakers": [],
                "progress": -1.0, "duration": 0.0, "sessionId": "",
            }
            self.transcribeTick = _Signal()
            self.transcribeStatus = _Signal()
            self.transcribeChanged = _Signal()

        def _translate_segment(self, segment):
            return segment

        def _config(self, media_mode=False):
            from dotaudio.engine import RecognitionConfig

            return RecognitionConfig(
                model="tiny", device="cpu", language="ru", task="transcribe",
                backend="local", server_url="", media_mode=media_mode,
            )

        def _on_transcribe_tick(self, payload):
            if isinstance(payload, dict):
                self._trans_state.update(payload)

    import wave
    from pathlib import Path

    wav = Path(tmp_path) / "tick.wav"
    # 2 секунды тишины 16-bit mono 16 kHz.
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 32000)

    stub = _Stream(Path(tmp_path))

    def deliver(payload):
        stub.transcribeTick.sent.append(payload)
        stub._on_transcribe_tick(payload)

    stub.transcribeTick.emit = deliver

    stub._transcribe_local(str(wav))

    assert stub.transcribeTick.sent
    mid = [tick for tick in stub.transcribeTick.sent if tick.get("stage") == "asr"]
    assert mid
    assert mid[0]["progress"] == 0.5  # end=1 / duration=2
    assert len(mid[0]["segments"]) == 1
    assert mid[1]["progress"] == min(0.99, 2.0 / 2.0)
    final = stub.transcribeTick.sent[-1]
    assert final["progress"] == 1.0
    assert final.get("sessionId")
    assert len(final["segments"]) == 2


def test_transcribe_media_url_from_path():
    class _Url:
        transcribeMediaUrl = Controller.transcribeMediaUrl.fget

        def __init__(self, path=""):
            self._trans_state = {"path": path}

    assert _Url("").transcribeMediaUrl() == ""
    url = _Url(r"C:\media\talk.wav").transcribeMediaUrl()
    assert url.startswith("file:")
    assert "talk.wav" in url.replace("\\", "/")


def test_clear_transcript_resets_path_and_progress():
    class _Clear:
        clearTranscript = Controller.clearTranscript

        def __init__(self):
            self._jobs = {}
            self._trans_state = {
                "phase": "done", "stage": "asr", "file": "a.wav", "path": r"C:\a.wav",
                "error": "x", "speakers": [1], "segments": [1],
                "diarization": True, "engine": "nemo", "engineNote": "ok",
                "duration": 3.0, "sessionId": "s1", "progress": 1.0,
            }
            self.transcribeChanged = _Signal()

        def _clear_media_peaks(self):
            return None

    stub = _Clear()
    stub.clearTranscript()
    assert stub._trans_state["path"] == ""
    assert stub._trans_state["file"] == ""
    assert stub._trans_state["progress"] == 0.0
    assert stub._trans_state["phase"] == "idle"
    assert stub._trans_state["segments"] == []
    assert stub.transcribeChanged.sent


def test_open_transcript_in_assistant_emits_session(tmp_path):
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
