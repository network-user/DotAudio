"""Мост ассистента: контракт свойств, кеш выжимок и разбор потока ответа."""

from __future__ import annotations

from pathlib import Path

from dotaudio.assistant import Digest
from dotaudio.assistant_controller import ACTION_LABELS, AssistantController, StoreDigests
from dotaudio.controller import DEFAULTS
from dotaudio.storage import GENERAL_CHAT_ID, Store


def test_assistant_settings_have_defaults_and_are_validated() -> None:
    assert DEFAULTS["assistant_runtime"] == "auto"
    # Пустая модель значит «ещё не выбрана»: тогда предлагается подходящая
    # этому устройству, а не жёстко прошитая.
    assert DEFAULTS["assistant_model"] == ""


def test_frequent_updates_have_their_own_notify_signals() -> None:
    """Поток токенов не должен пересчитывать каталог моделей и список записей."""

    meta = AssistantController.staticMetaObject
    expected = {
        "messages": "messagesChanged",
        "records": "recordsChanged",
        "chats": "chatsChanged",
        "catalog": "catalogChanged",
        "status": "streamChanged",
        "streaming": "streamChanged",
        "indexState": "streamChanged",
        "pendingReply": "streamChanged",
        "download": "downloadChanged",
        "install": "downloadChanged",
        "hardware": "hardwareChanged",
        "modelReady": "modelChanged",
        "notice": "noticeChanged",
        "recordId": "recordChanged",
        "listMode": "listModeChanged",
    }
    for name, signal in expected.items():
        prop = meta.property(meta.indexOfProperty(name))
        assert prop.isValid(), name
        assert bytes(prop.notifySignal().name()).decode() == signal


def test_selecting_a_model_does_not_block_on_release(tmp_path: Path, monkeypatch) -> None:
    """Выбор модели раньше звал engine.release() на GUI-потоке и замораживал окно."""

    assistant = _controller(tmp_path)
    assistant._catalog = [{"id": "qwen3-1.7b", "ready": True}]
    released: list[str] = []

    monkeypatch.setattr(assistant, "_release_async", lambda: released.append("async"))
    assistant.selectModel("qwen3-1.7b")

    assert assistant.controller.values["assistant_model"] == "qwen3-1.7b"
    assert assistant.modelReady is True
    assert released == ["async"]


def test_token_stream_does_not_rebuild_the_message_list(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._messages = [
        {"role": "user", "content": "Вопрос", "meta": {}, "pending": False},
        {"role": "assistant", "content": "", "pending": True},
    ]
    assistant._busy = True
    rebuilt = []
    assistant.messagesChanged.connect(lambda: rebuilt.append(1))

    assistant._on_token("Часть")
    assistant._on_token(" ответа")

    assert rebuilt == []
    assert assistant.pendingReply == "Часть ответа"
    assistant._token_ui.stop()
    assistant._flush_token_ui()
    assert assistant.pendingReply == "Часть ответа"


def test_actions_are_offered_to_the_interface() -> None:
    meta = AssistantController.staticMetaObject
    assert meta.indexOfProperty("actions") >= 0
    assert set(ACTION_LABELS) == {"summary", "keypoints", "tasks", "topics"}
    for slot in (
        "ask", "runAction", "stop", "selectRecord", "downloadModel", "clearChat",
        "setListMode", "nameRecord", "nameUntitledRecords",
        "createChat", "togglePinRecord", "deleteRecord",
    ):
        assert meta.indexOfMethod(f"{slot}()") >= 0 or any(
            bytes(meta.method(index).name()).decode() == slot
            for index in range(meta.methodCount())
        ), slot


def test_digest_cache_survives_a_restart_through_the_database(tmp_path: Path) -> None:
    store = Store(tmp_path / "dotaudio.sqlite3")
    digests = StoreDigests(store, "qwen3-4b")
    digests.save(
        "rec",
        Digest(index=0, start=0.0, end=60.0, summary="О смете", keywords=("смета",), content_hash="a1"),
    )

    # Новый объект - как после перезапуска программы: выжимка приходит из базы.
    restored = StoreDigests(store, "qwen3-4b").load("rec")

    assert restored[0].summary == "О смете"
    assert restored[0].keywords == ("смета",)
    assert restored[0].content_hash == "a1"

    digests.clear("rec")
    assert StoreDigests(store, "qwen3-4b").load("rec") == {}


class _StubController:
    """Контроллер записи: ассистенту от него нужны только настройки."""

    def __init__(self, **settings) -> None:
        self.values = {**DEFAULTS, **settings}
        self.saved: list[tuple[str, object]] = []

    def setting(self, name, default=None):
        return self.values.get(name, default)

    def setSetting(self, name, value):  # noqa: N802 - имя как в Qt-слоте
        self.values[name] = value
        self.saved.append((name, value))


def _controller(tmp_path: Path, **settings) -> AssistantController:
    store = Store(tmp_path / "dotaudio.sqlite3")
    return AssistantController(tmp_path, store, _StubController(**settings))


def test_saved_model_wins_over_the_recommendation(tmp_path: Path) -> None:
    assistant = _controller(tmp_path, assistant_model="qwen3-1.7b")
    assistant._recommended = "qwen3-8b"

    assert assistant._active_model_id() == "qwen3-1.7b"

    # Неизвестное имя (например, из старых настроек) не должно ломать страницу.
    assistant.controller.values["assistant_model"] = "какая-то-старая"
    assert assistant._active_model_id() == "qwen3-8b"


def test_attachment_is_stored_in_message_meta(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    note = tmp_path / "brief.txt"
    note.write_text("Смета и сроки", encoding="utf-8")

    assistant._load_attachment(note)

    assert assistant.attachment["name"] == "brief.txt"
    assert assistant.attachment["chars"] == len("Смета и сроки")
    assert "text" not in assistant.attachment

    meta = assistant._take_attachment_meta()
    assistant._append("user", "О чём файл?", meta=meta)

    stored = assistant.store.list_chat_messages(GENERAL_CHAT_ID)
    assert stored[0]["content"] == "О чём файл?"
    assert stored[0]["meta"]["attachment"]["text"] == "Смета и сроки"
    assert assistant.attachment == {}


def test_rename_record_updates_title_and_list(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    session_id = assistant.store.create_session("Старое", "live", "mic", "small")
    assistant.store.append_segments(
        session_id, [{"start": 0.0, "end": 1.0, "text": "привет"}]
    )
    assistant._record_id = session_id
    assistant._record = {"id": session_id, "title": "Старое", "displayTitle": "Старое"}
    assistant._records = [{"id": session_id, "title": "Старое", "displayTitle": "Старое"}]

    assistant.renameRecord("  Новое имя ")

    assert assistant.recordTitle == "Новое имя"
    assert assistant._records[0]["title"] == "Новое имя"
    assert assistant._records[0]["needsTitle"] is False
    assert assistant.store.get_session(session_id)["title"] == "Новое имя"


def test_delete_chat_clears_messages_but_keeps_the_record(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    session_id = assistant.store.create_session("Планёрка", "live", "mic", "small")
    assistant.store.append_segments(
        session_id, [{"start": 0.0, "end": 1.0, "text": "привет"}]
    )
    assistant.store.append_chat_message(session_id, "user", "вопрос")
    assistant.store.append_chat_message(session_id, "assistant", "ответ")
    assistant._record_id = session_id
    assistant._messages = [
        {"role": "user", "content": "вопрос"},
        {"role": "assistant", "content": "ответ"},
    ]

    assistant.deleteChat()

    assert assistant.messages == []
    assert assistant.store.list_chat_messages(session_id) == []
    assert assistant.store.get_session(session_id) is not None


def test_create_chat_opens_a_blank_thread(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant.createChat()

    assert assistant.listMode == "chats"
    # id выставляется асинхронно selectRecord; сессия уже в базе.
    chats = [
        row for row in assistant.store.list_sessions() if row.get("mode") == "chat"
    ]
    assert len(chats) == 1
    assert chats[0]["title"].startswith("Новый чат")


def test_pin_and_delete_record_from_assistant(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    session_id = assistant.store.create_session("Смета", "live", "mic", "small")
    assistant.store.append_segments(
        session_id, [{"start": 0.0, "end": 1.0, "text": "текст"}]
    )
    assistant._record_id = session_id
    assistant._record = {"id": session_id, "title": "Смета", "displayTitle": "Смета", "pinned": False}

    assistant.togglePinRecord()
    assert int(assistant.store.get_session(session_id)["pinned"] or 0) == 1
    assert assistant.recordPinned is True

    assistant.deleteRecord()
    assert assistant.store.get_session(session_id) is None
    assert assistant.recordId == ""


def test_open_record_switches_to_records_list(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._list_mode = "chats"
    session_id = assistant.store.create_session("Файл", "transcript", "a.wav", "small")
    assistant.store.append_segments(
        session_id, [{"start": 0.0, "end": 1.0, "text": "текст"}]
    )

    assistant.openRecord(session_id)

    assert assistant.listMode == "records"
    # selectRecord грузит карточку в фоне; id выставляется по приходу сигнала.
    assistant._on_record(assistant._record_request, session_id, {"id": session_id, "title": "Файл"}, [], "ok")
    assert assistant.recordId == session_id


def test_answer_is_assembled_from_tokens_and_saved_once(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._messages = [{"role": "user", "content": "Вопрос", "meta": {}, "pending": False}]
    assistant._messages.append({"role": "assistant", "content": "", "pending": True})
    assistant._busy = True

    assistant._on_token("Ответ")
    assistant._on_token(" готов")
    assistant._on_reply_finished("", "")

    assert assistant._messages[-1]["content"] == "Ответ готов"
    assert assistant._messages[-1]["pending"] is False
    stored = assistant.store.list_chat_messages(GENERAL_CHAT_ID)
    assert [item["content"] for item in stored] == ["Ответ готов"]


def test_empty_reply_is_not_left_hanging_in_the_conversation(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._messages = [{"role": "assistant", "content": "", "pending": True}]
    assistant._busy = True

    assistant._on_reply_finished("", "")

    assert assistant._messages == []
    assert assistant.notice
    assert assistant.store.list_chat_messages(GENERAL_CHAT_ID) == []


def test_stopped_answer_keeps_what_was_already_printed(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._messages = [{"role": "assistant", "content": "", "pending": True}]
    assistant._busy = True
    assistant._on_token("Начало ответа")

    assistant._on_reply_finished("cancelled", "")

    assert assistant._messages[-1]["content"] == "Начало ответа"
    assert assistant.status == "Ответ остановлен"


def test_index_progress_is_reported_in_words(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)

    assistant._on_stage("index_start", {"total": 12})
    assert assistant.indexState["active"] is True
    assistant._on_stage("index_progress", {"done": 5, "total": 12})
    assert "5" in assistant.status and "12" in assistant.status
    assistant._on_stage("index_done", {})
    assert assistant.indexState["active"] is False


def test_asking_without_a_downloaded_model_says_so(tmp_path: Path) -> None:
    assistant = _controller(tmp_path, assistant_model="qwen3-4b", assistant_runtime="llama_cpp")

    assistant.ask("Что в записи?")

    # Ни одной реплики не появилось, зато есть внятная причина.
    assert assistant.messages == []
    assert "не скачана" in assistant.notice.casefold()


def test_actions_require_a_selected_record(tmp_path: Path) -> None:
    assistant = _controller(tmp_path)
    assistant._record_id = ""
    assistant._ready = True

    assistant.runAction("summary")

    assert "выбранной записи" in assistant.notice
