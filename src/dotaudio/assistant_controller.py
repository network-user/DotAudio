"""Мост между локальной моделью и интерфейсом ассистента.

Живёт рядом с ``Controller``, а не внутри него: у записи и у чата разные
состояния, и складывать их в один объект на две с половиной тысячи строк
означало бы, что каждый токен ответа заставляет интерфейс перечитывать
устройства и настройки записи.

Правила те же, что и у распознавания: тяжёлое - в daemon-потоке, результат
приходит в GUI-поток сигналом, ни один воркер не трогает QML напрямую.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from dotaudio import assistant as core
from dotaudio import hardware, llm, modelhub
from dotaudio.assistant import Digest, TranscriptAssistant, build_chunks
from dotaudio.llm import GenerationOptions
from dotaudio.storage import GENERAL_CHAT_ID

# Модель занимает единицы гигабайт: держать её загруженной после того, как
# разговор кончился, незачем. Порог тот же, что у Whisper.
MODEL_IDLE_RELEASE_MS = 10 * 60 * 1000
# Поток токенов и прогресс загрузки иначе дёргают весь лист на каждый кусок.
TOKEN_UI_MS = 48
DOWNLOAD_UI_MS = 120
# TXT в чат: больше этого режется с предупреждением, чтобы не раздувать контекст.
ATTACHMENT_MAX_CHARS = 120_000

ACTION_LABELS = {
    "summary": "Краткое изложение",
    "keypoints": "Главные мысли",
    "tasks": "Задачи и договорённости",
    "topics": "Темы записи",
}

GENERAL_CHAT_TITLE = "Свободный разговор"


class StoreDigests:
    """Выжимки частей записи, живущие в базе рядом с расшифровкой."""

    def __init__(self, store, model_id: str = "") -> None:
        self.store = store
        self.model_id = model_id
        self._cache: dict[str, dict[int, Digest]] = {}

    def load(self, session_id: str) -> dict[int, Digest]:
        if session_id in self._cache:
            return dict(self._cache[session_id])
        rows = self.store.list_digests(session_id)
        found = {
            int(row["chunk_index"]): Digest(
                index=int(row["chunk_index"]),
                start=float(row["start"]),
                end=float(row["end"]),
                summary=str(row["summary"]),
                keywords=tuple(row.get("keywords") or ()),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        }
        self._cache[session_id] = found
        return dict(found)

    def save(self, session_id: str, digest: Digest) -> None:
        self._cache.setdefault(session_id, {})[digest.index] = digest
        self.store.save_digest(
            session_id,
            digest.index,
            digest.content_hash,
            digest.start,
            digest.end,
            digest.summary,
            digest.keywords,
            self.model_id,
        )

    def clear(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
        self.store.clear_digests(session_id)


class AssistantController(QObject):
    """Состояние страницы «Ассистент» и запуск локальной модели."""

    changed = Signal()
    messagesChanged = Signal()
    recordsChanged = Signal()
    chatsChanged = Signal()
    catalogChanged = Signal()
    streamChanged = Signal()
    # Узкие сигналы: прогресс загрузки и опрос железа не должны
    # пересчитывать карточки модели и список записей.
    hardwareChanged = Signal()
    downloadChanged = Signal()
    noticeChanged = Signal()
    modelChanged = Signal()
    recordChanged = Signal()
    attachmentChanged = Signal()
    listModeChanged = Signal()

    # Сигналы из воркеров в GUI-поток.
    tokenArrived = Signal(str)
    replyFinished = Signal(str, str)
    stageArrived = Signal(str, "QVariantMap")
    recordsArrived = Signal("QVariant", "QVariant", int)
    catalogArrived = Signal("QVariant")
    hardwareArrived = Signal("QVariantMap", "QVariant", "QVariant")
    downloadProgress = Signal("QVariantMap")
    downloadFinished = Signal(str, str)
    installLine = Signal(str)
    installFinished = Signal(str)
    recordArrived = Signal(int, str, "QVariantMap", "QVariant", str)
    titleFinished = Signal(str, str, str)
    namingFinished = Signal(str, int)

    def __init__(self, data_dir: Path, store, controller) -> None:
        super().__init__()
        self.store = store
        self.controller = controller
        self.models_dir = modelhub.models_root(Path(data_dir), "llm")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.engine = llm.ChatEngine(
            self.models_dir,
            preference=str(controller.setting("assistant_runtime", "auto")),
        )
        self._digests = StoreDigests(store)

        self._hardware: dict = {}
        self._accelerators: list = []
        self._runtimes: list = []
        self._catalog: list = []
        self._recommended = ""
        self._ready = False
        self._runtime_label = ""
        self._records: list = []
        self._chats: list = []
        self._untitled_count = 0
        self._list_mode = "records"
        self._record_id = ""
        self._record: dict = {}
        self._messages: list = []
        self._busy = False
        self._streaming = False
        self._naming = False
        self._status = "Выберите запись или спросите что-нибудь"
        self._notice = ""
        self._stage = ""
        self._index = {"active": False, "done": 0, "total": 0}
        self._download = {"active": False, "model": "", "bytes": 0, "total": 0, "ratio": 0.0}
        self._install = {"active": False, "accelerator": "", "log": ""}
        self._cancel = threading.Event()
        self._download_cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._download_pending: dict | None = None
        self._record_request = 0
        self._attachment: dict = {}

        self.tokenArrived.connect(self._on_token)
        self.replyFinished.connect(self._on_reply_finished)
        self.stageArrived.connect(self._on_stage)
        self.recordsArrived.connect(self._on_records)
        self.catalogArrived.connect(self._on_catalog)
        self.hardwareArrived.connect(self._on_hardware)
        self.downloadProgress.connect(self._on_download_progress)
        self.downloadFinished.connect(self._on_download_finished)
        self.installLine.connect(self._on_install_line)
        self.installFinished.connect(self._on_install_finished)
        self.recordArrived.connect(self._on_record)
        self.titleFinished.connect(self._on_title_finished)
        self.namingFinished.connect(self._on_naming_finished)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(MODEL_IDLE_RELEASE_MS)
        self._idle.timeout.connect(self._release_idle)

        self._token_ui = QTimer(self)
        self._token_ui.setSingleShot(True)
        self._token_ui.setInterval(TOKEN_UI_MS)
        self._token_ui.timeout.connect(self._flush_token_ui)

        self._download_ui = QTimer(self)
        self._download_ui.setSingleShot(True)
        self._download_ui.setInterval(DOWNLOAD_UI_MS)
        self._download_ui.timeout.connect(self._flush_download_ui)

        self._messages = self.store.list_chat_messages(GENERAL_CHAT_ID)
        self.refreshHardware()
        self.refreshRecords("")
        # Новые расшифровки и сессии сразу попадают в список слева.
        if hasattr(controller, "transcriptPersisted"):
            controller.transcriptPersisted.connect(lambda *_: self.refreshRecords(""))
        if hasattr(controller, "jobFinished"):
            controller.jobFinished.connect(lambda *_: self.refreshRecords(""))
        if hasattr(controller, "openAssistantWithRecord"):
            controller.openAssistantWithRecord.connect(self.openRecord)

    # -- свойства ----------------------------------------------------------

    def _release_async(self) -> None:
        """Выгрузка GGUF с GUI-потока: close() у большой модели идёт секундами."""

        engine = self.engine

        def work():
            engine.release()

        threading.Thread(target=work, name="dotaudio-llm-release", daemon=True).start()

    def _set_notice(self, text: str) -> None:
        if self._notice == text:
            return
        self._notice = text
        self.noticeChanged.emit()

    @Property("QVariantMap", notify=hardwareChanged)
    def hardware(self):
        return self._hardware

    @Property("QVariant", notify=hardwareChanged)
    def accelerators(self):
        return self._accelerators

    @Property("QVariant", notify=hardwareChanged)
    def runtimes(self):
        return self._runtimes

    @Property("QVariant", notify=catalogChanged)
    def catalog(self):
        return self._catalog

    @Property(str, notify=modelChanged)
    def modelId(self):
        return self._active_model_id()

    @Property(str, notify=modelChanged)
    def modelLabel(self):
        model = self._current_model()
        return "" if model is None else model.label

    @Property(str, notify=modelChanged)
    def recommendedModel(self):
        return self._recommended

    @Property(bool, notify=modelChanged)
    def modelReady(self):
        """Готовность считается в воркере, а не здесь.

        QML читает это свойство в десятке привязок. Спрашивать про диск и про
        службу Ollama на каждое чтение значило бы держать интерфейс в сетевом
        таймауте: страница собиралась двадцать секунд.
        """

        return self._ready

    @Property(str, notify=modelChanged)
    def runtimePreference(self):
        return str(self.controller.setting("assistant_runtime", "auto"))

    @Property(str, notify=modelChanged)
    def activeRuntime(self):
        return self._runtime_label

    @Property("QVariant", notify=recordsChanged)
    def records(self):
        return self._records

    @Property("QVariant", notify=chatsChanged)
    def chats(self):
        return self._chats

    @Property(int, notify=recordsChanged)
    def untitledCount(self):
        return self._untitled_count

    @Property(str, notify=listModeChanged)
    def listMode(self):
        return self._list_mode

    @Property(str, notify=recordChanged)
    def recordId(self):
        return self._record_id

    @Property("QVariantMap", notify=recordChanged)
    def record(self):
        return self._record

    @Property(str, notify=recordChanged)
    def recordTitle(self):
        if not self._record_id:
            return GENERAL_CHAT_TITLE
        return str(
            self._record.get("displayTitle")
            or self._record.get("title")
            or GENERAL_CHAT_TITLE
        )

    @Property(bool, notify=recordChanged)
    def recordNeedsTitle(self):
        return bool(self._record_id) and bool(self._record.get("needsTitle"))

    @Property("QVariant", notify=messagesChanged)
    def messages(self):
        return self._messages

    @Property(bool, notify=streamChanged)
    def busy(self):
        return self._busy or self._naming

    @Property(bool, notify=streamChanged)
    def naming(self):
        return self._naming

    @Property(bool, notify=streamChanged)
    def streaming(self):
        return self._streaming

    @Property(str, notify=streamChanged)
    def status(self):
        return self._status

    @Property(str, notify=streamChanged)
    def stage(self):
        return self._stage

    @Property(str, notify=streamChanged)
    def pendingReply(self):
        """Текст ещё недопечатанного ответа: обновляется чаще списка сообщений."""

        if self._messages and self._messages[-1].get("pending"):
            return str(self._messages[-1].get("content") or "")
        return ""

    @Property("QVariantMap", notify=streamChanged)
    def indexState(self):
        return self._index

    @Property("QVariantMap", notify=downloadChanged)
    def download(self):
        return self._download

    @Property("QVariantMap", notify=downloadChanged)
    def install(self):
        return self._install

    @Property(str, notify=noticeChanged)
    def notice(self):
        return self._notice

    @Property("QVariant", notify=recordChanged)
    def actions(self):
        return [{"id": key, "label": label} for key, label in ACTION_LABELS.items()]

    @Property("QVariantMap", notify=attachmentChanged)
    def attachment(self):
        """Ожидающее вложение: имя и размер; текст в свойстве не отдаём."""

        if not self._attachment:
            return {}
        return {
            "name": str(self._attachment.get("name") or ""),
            "chars": int(self._attachment.get("chars") or 0),
            "truncated": bool(self._attachment.get("truncated")),
        }

    # -- железо, каталог, записи -------------------------------------------

    @Slot()
    def refreshHardware(self):
        """Опрос устройства в фоне: он запускает процесс и читает реестр."""

        def work():
            profile = hardware.probe(refresh=True)
            options = hardware.accelerator_options(profile)
            runtimes = self.engine.status(profile)
            self.hardwareArrived.emit(profile.as_dict(), options, runtimes)
            self.catalogArrived.emit(self._catalog_payload(profile))

        threading.Thread(target=work, name="dotaudio-llm-probe", daemon=True).start()

    @Slot()
    def refreshCatalog(self):
        def work():
            self.catalogArrived.emit(self._catalog_payload(hardware.probe()))

        threading.Thread(target=work, name="dotaudio-llm-catalog", daemon=True).start()

    def _catalog_payload(self, profile) -> dict:
        """Каталог и готовность активной модели - всё, что требует диска и сети.

        Считается в воркере целиком, чтобы свойства контроллера остались
        мгновенными: интерфейс читает их на каждой перерисовке.
        """

        cards = llm.catalog_cards(self.models_dir, profile, self.engine)
        model = self._current_model()
        ready = False
        runtime_label = ""
        if model is not None:
            runtime = self.engine.pick_runtime(model)
            runtime_label = str(runtime.label)
            ready = bool(runtime.available() and runtime.ready(model))
        return {
            "cards": cards,
            "recommended": llm.recommend_model(profile),
            "ready": ready,
            "runtimeLabel": runtime_label,
        }

    @Slot(str)
    def setListMode(self, mode):
        value = str(mode or "")
        if value not in ("records", "chats") or value == self._list_mode:
            return
        self._list_mode = value
        self.listModeChanged.emit()

    @Slot(str)
    def refreshRecords(self, query):
        """Список записей и чатов; чтение базы не на GUI-потоке."""

        text = str(query or "")

        def work():
            rows = self.store.list_sessions(text, limit=200)
            records = []
            chats = []
            untitled = 0
            for row in rows:
                if not int(row.get("segment_count") or 0):
                    continue
                item = core.list_item_from_row(row)
                records.append(item)
                if item.get("needsTitle"):
                    untitled += 1
                if int(item.get("chatCount") or 0) > 0:
                    chats.append(item)
            general_count = self.store.count_chat_messages(GENERAL_CHAT_ID)
            general = {
                "id": "",
                "title": GENERAL_CHAT_TITLE,
                "displayTitle": GENERAL_CHAT_TITLE,
                "subtitle": (
                    f"{general_count} сообщ."
                    if general_count
                    else "Без записи, обычный чат"
                ),
                "mode": "chat",
                "createdAt": "",
                "segments": 0,
                "preview": "",
                "needsTitle": False,
                "chatCount": general_count,
            }
            self.recordsArrived.emit(records, [general, *chats], untitled)

        threading.Thread(target=work, name="dotaudio-llm-records", daemon=True).start()

    def _on_hardware(self, profile, options, runtimes):
        self._hardware = dict(profile)
        self._accelerators = list(options)
        self._runtimes = list(runtimes)
        self.hardwareChanged.emit()

    def _on_catalog(self, payload):
        data = dict(payload)
        self._catalog = list(data.get("cards") or [])
        self._recommended = str(data.get("recommended") or "")
        self._ready = bool(data.get("ready"))
        self._runtime_label = str(data.get("runtimeLabel") or "")
        self.catalogChanged.emit()
        self.modelChanged.emit()

    def _on_records(self, records, chats, untitled):
        self._records = list(records)
        self._chats = list(chats)
        self._untitled_count = int(untitled)
        self.recordsChanged.emit()
        self.chatsChanged.emit()

    def _apply_title(self, session_id: str, title: str) -> None:
        """Обновить заголовок в текущей карточке и обоих списках."""

        patch = {
            "title": title,
            "displayTitle": title,
            "needsTitle": False,
        }
        if self._record_id == session_id:
            self._record = {**self._record, **patch}
            self.recordChanged.emit()
        for index, row in enumerate(self._records):
            if row.get("id") == session_id:
                self._records[index] = {**row, **patch}
                break
        for index, row in enumerate(self._chats):
            if row.get("id") == session_id:
                self._chats[index] = {**row, **patch}
                break
        self._untitled_count = sum(1 for row in self._records if row.get("needsTitle"))
        self.recordsChanged.emit()
        self.chatsChanged.emit()

    # -- выбор модели и записи ---------------------------------------------

    def _active_model_id(self) -> str:
        chosen = str(self.controller.setting("assistant_model", "") or "")
        if chosen and llm.get_model(chosen) is not None:
            return chosen
        return self._recommended or llm.DEFAULT_MODEL_ID

    def _current_model(self) -> llm.ChatModel | None:
        return llm.get_model(self._active_model_id())

    @Slot(str)
    def selectModel(self, model_id):
        if llm.get_model(str(model_id)) is None:
            return
        self.controller.setSetting("assistant_model", str(model_id))
        # Выгрузка прошлой модели - секунды на GUI-потоке; в фоне.
        self._release_async()
        # Готовность новой модели уже известна из каталога: показать её сразу,
        # не дожидаясь воркера, иначе кнопка «Спросить» на миг гаснет.
        for card in self._catalog:
            if card.get("id") == str(model_id):
                self._ready = bool(card.get("ready"))
                break
        self._status = "Выберите запись или спросите что-нибудь"
        self.modelChanged.emit()
        self.streamChanged.emit()
        self.refreshCatalog()

    @Slot(str)
    def setRuntime(self, preference):
        value = str(preference)
        if value not in ("auto", "llama_cpp", "ollama"):
            return
        self.controller.setSetting("assistant_runtime", value)
        self.engine.preference = value
        self.modelChanged.emit()
        self.refreshCatalog()

    @Slot(str)
    def selectRecord(self, session_id):
        """Открыть запись: её переписка и карточка приходят из базы."""

        if self._busy:
            self._set_notice("Дождитесь ответа или остановите его.")
            return
        sid = str(session_id or "")
        self._record_request += 1
        request = self._record_request

        def work():
            if not sid:
                messages = self.store.list_chat_messages(GENERAL_CHAT_ID)
                self.recordArrived.emit(
                    request,
                    "",
                    {},
                    messages,
                    "Свободный разговор без записи",
                )
                return
            session = self.store.get_session(sid)
            if session is None:
                self.recordArrived.emit(request, "", {}, None, "")
                return
            record = core.record_from_session(session)
            messages = self.store.list_chat_messages(sid)
            chunks = len(build_chunks(session.get("segments") or []))
            status = f"{record.get('durationLabel') or '00:00'} записи, частей: {chunks}"
            self.recordArrived.emit(request, sid, record, messages, status)

        threading.Thread(target=work, name="dotaudio-llm-record", daemon=True).start()

    def _on_record(self, request, session_id, record, messages, status):
        if int(request) != self._record_request:
            return
        if messages is None:
            self._record_id = ""
            self._set_notice("Запись не найдена.")
            return
        self._record_id = str(session_id or "")
        self._record = dict(record or {})
        self._messages = list(messages)
        self._status = str(status)
        self._set_notice("")
        self.messagesChanged.emit()
        self.streamChanged.emit()
        self.recordChanged.emit()

    @Slot(str)
    def openRecord(self, session_id):
        """Открыть запись в ассистенте (например, сразу после транскрибации)."""

        sid = str(session_id or "")
        if not sid:
            return
        self.setListMode("records")
        self.selectRecord(sid)
        self.refreshRecords("")

    @Slot()
    def clearChat(self):
        """Удалить переписку по текущему чату. Расшифровку не трогает."""

        self.deleteChat()

    @Slot()
    def deleteChat(self):
        """Удалить текущий открытый чат."""

        self._delete_chat(self._record_id or GENERAL_CHAT_ID)

    @Slot(str)
    def deleteChatId(self, session_id):
        """Удалить чат по id записи (или пустой id - свободный разговор)."""

        self._delete_chat(str(session_id or GENERAL_CHAT_ID))

    def _delete_chat(self, chat_id: str) -> None:
        if self._busy or self._naming:
            self._set_notice("Дождитесь ответа или остановите его.")
            return
        key = chat_id or GENERAL_CHAT_ID
        self.store.clear_chat_messages(key)
        if (self._record_id or GENERAL_CHAT_ID) == key:
            self._messages = []
            self.messagesChanged.emit()
        self.refreshRecords("")
        self._set_notice(
            "Свободный разговор очищен."
            if key == GENERAL_CHAT_ID
            else "Чат удалён. Расшифровка на месте."
        )

    @Slot()
    def rebuildIndex(self):
        """Пересчитать карту записи заново, выбросив прежние выжимки."""

        if self._busy or not self._record_id:
            return
        self._digests.clear(self._record_id)
        self._set_notice("Карта записи будет собрана при следующем вопросе.")

    # -- загрузка модели ---------------------------------------------------

    @Slot(str)
    def downloadModel(self, model_id):
        model = llm.get_model(str(model_id))
        if model is None or self._download.get("active"):
            return
        self._download_cancel = threading.Event()
        self._download = {
            "active": True,
            "model": model.id,
            "label": model.label,
            "bytes": 0,
            "total": model.size_bytes,
            "ratio": 0.0,
        }
        self.downloadChanged.emit()
        cancel = self._download_cancel

        def work():
            error = ""
            try:
                modelhub.download(
                    model.file,
                    self.models_dir,
                    on_progress=lambda payload: self.downloadProgress.emit(
                        {
                            "model": model.id,
                            "bytes": int(payload.get("bytes") or 0),
                            "total": int(payload.get("total") or model.size_bytes),
                            "ratio": float(payload.get("ratio") or 0.0),
                        }
                    ),
                    cancel=cancel,
                )
            except modelhub.DownloadCancelled:
                error = "cancelled"
            except Exception as failure:
                error = str(failure) or failure.__class__.__name__
            self.downloadFinished.emit(model.id, error)

        threading.Thread(target=work, name="dotaudio-llm-download", daemon=True).start()

    @Slot()
    def cancelDownload(self):
        self._download_cancel.set()

    @Slot(str)
    def deleteModel(self, model_id):
        """Убрать файл модели с диска. Вызывается только по подтверждению в интерфейсе."""

        model = llm.get_model(str(model_id))
        if model is None or self._busy:
            return
        if self._active_model_id() == model.id:
            self._release_async()
        removed = modelhub.remove(self.models_dir, model.file)
        self._set_notice("Файл модели удалён." if removed else "На диске этой модели не было.")
        self.refreshCatalog()

    def _on_download_progress(self, payload):
        data = dict(payload)
        if data.get("model") != self._download.get("model"):
            return
        self._download_pending = {
            "bytes": int(data.get("bytes") or 0),
            "total": int(data.get("total") or 0),
            "ratio": float(data.get("ratio") or 0.0),
        }
        if not self._download_ui.isActive():
            self._download_ui.start()

    def _flush_download_ui(self) -> None:
        pending = self._download_pending
        self._download_pending = None
        if not pending or not self._download.get("active"):
            return
        self._download.update(pending)
        self.downloadChanged.emit()

    def _on_download_finished(self, model_id, error):
        self._download_ui.stop()
        self._download_pending = None
        self._download = {"active": False, "model": "", "bytes": 0, "total": 0, "ratio": 0.0}
        if error == "cancelled":
            self._set_notice("Загрузка остановлена. Скачанное сохранено для продолжения.")
        elif error:
            self._set_notice(f"Не удалось скачать модель: {error}")
        else:
            self._set_notice("")
            model = llm.get_model(model_id)
            if model is not None and not str(self.controller.setting("assistant_model", "")):
                self.controller.setSetting("assistant_model", model.id)
                self.modelChanged.emit()
        self.downloadChanged.emit()
        self.refreshCatalog()

    # -- установка ускорения ----------------------------------------------

    @Slot(str)
    def installAccelerator(self, accelerator_id):
        """Поставить сборку llama.cpp под это железо.

        Установка запускается только этим действием: молча менять пакеты в
        окружении пользователя приложение не должно.
        """

        steps = hardware.install_steps(str(accelerator_id))
        if not steps or self._install.get("active"):
            return
        self._install = {"active": True, "accelerator": str(accelerator_id), "log": ""}
        self.downloadChanged.emit()

        def work():
            error = ""
            creation = (
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                if sys.platform == "win32"
                else {}
            )
            # Шагов может быть два: библиотеки CUDA и сама сборка. Первая
            # неудача останавливает установку - продолжать по сломанному пути
            # значит оставить пользователя со сборкой, которая не запускается.
            for args in steps:
                try:
                    process = subprocess.Popen(
                        [sys.executable, *args],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        **creation,
                    )
                    for line in process.stdout or ():
                        stripped = line.strip()
                        if stripped:
                            self.installLine.emit(stripped)
                    code = process.wait()
                    if code != 0:
                        error = f"pip вернул код {code}"
                except Exception as failure:
                    error = str(failure) or failure.__class__.__name__
                if error:
                    break
            self.installFinished.emit(error)

        threading.Thread(target=work, name="dotaudio-llm-install", daemon=True).start()

    def _on_install_line(self, line):
        tail = (self._install.get("log") or "").splitlines()[-8:]
        tail.append(line)
        self._install["log"] = "\n".join(tail[-8:])
        self.downloadChanged.emit()

    def _on_install_finished(self, error):
        self._install["active"] = False
        self._set_notice(
            f"Установка не удалась: {error}"
            if error
            else "Сборка установлена. Перезапустите программу, чтобы она подхватилась."
        )
        self.downloadChanged.emit()
        hardware.reset_cache()
        self.refreshHardware()

    # -- разговор ----------------------------------------------------------

    def _append(self, role: str, content: str, meta: dict | None = None, persist: bool = True):
        item = {"role": role, "content": content, "meta": meta or {}, "pending": False}
        if persist:
            self.store.append_chat_message(
                self._record_id or GENERAL_CHAT_ID,
                role,
                content,
                self._active_model_id(),
                meta or {},
            )
        self._messages = [*self._messages, item]
        self.messagesChanged.emit()
        return item

    def _guard(self) -> bool:
        """Можно ли сейчас спрашивать: модель выбрана, скачана и свободна.

        Готовность берётся из кеша воркера каталога: повторный опрос Ollama
        и импорт llama.cpp на GUI-потоке снова замораживали кнопку «Спросить».
        """

        if self._busy or self._naming:
            self._set_notice("Ответ ещё идёт. Остановите его или подождите.")
            return False
        model = self._current_model()
        if model is None:
            self._set_notice("Сначала выберите модель.")
            return False
        if not self._ready:
            self._set_notice(f"Модель «{model.label}» ещё не скачана.")
            return False
        return True

    @Slot()
    def attachTextFile(self):
        """Прикрепить TXT к следующему вопросу."""

        if self._busy:
            self._set_notice("Дождитесь ответа, прежде чем менять вложение.")
            return
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Прикрепить текстовый файл",
            "",
            "Текст (*.txt);;Все файлы (*.*)",
        )
        if not path:
            return
        self._load_attachment(Path(path))

    @Slot(str)
    def attachTextPath(self, path):
        """Путь из drag-and-drop или поля: только локальный .txt."""

        if self._busy:
            self._set_notice("Дождитесь ответа, прежде чем менять вложение.")
            return
        raw = str(path or "")
        if raw.startswith("file:"):
            from PySide6.QtCore import QUrl

            raw = QUrl(raw).toLocalFile()
        media = Path(raw)
        if not media.is_file() or media.suffix.lower() != ".txt":
            self._set_notice("Прикрепите текстовый файл с расширением .txt.")
            return
        self._load_attachment(media)

    def _load_attachment(self, media: Path) -> None:
        try:
            raw = media.read_bytes()
        except OSError as exc:
            self._set_notice(f"Не удалось прочитать файл: {exc}")
            return
        text = _decode_text_bytes(raw)
        truncated = False
        if len(text) > ATTACHMENT_MAX_CHARS:
            text = text[:ATTACHMENT_MAX_CHARS]
            truncated = True
        text = text.strip()
        if not text:
            self._set_notice("Файл пустой.")
            return
        self._attachment = {
            "name": media.name,
            "text": text,
            "chars": len(text),
            "truncated": truncated,
        }
        self.attachmentChanged.emit()
        if truncated:
            self._set_notice(
                f"Файл большой: взяты первые {ATTACHMENT_MAX_CHARS} символов из «{media.name}»."
            )
        else:
            self._set_notice(f"Прикреплён файл «{media.name}».")

    @Slot()
    def clearAttachment(self):
        if not self._attachment:
            return
        self._attachment = {}
        self.attachmentChanged.emit()

    def _take_attachment_meta(self) -> dict | None:
        """Забрать вложение в meta сообщения и очистить слот."""

        if not self._attachment:
            return None
        payload = {
            "attachment": {
                "name": str(self._attachment.get("name") or "file.txt"),
                "chars": int(self._attachment.get("chars") or 0),
                "text": str(self._attachment.get("text") or ""),
                "truncated": bool(self._attachment.get("truncated")),
            }
        }
        self._attachment = {}
        self.attachmentChanged.emit()
        return payload

    @Slot(str)
    def ask(self, text):
        question = str(text or "").strip()
        has_file = bool(self._attachment)
        if not question and not has_file:
            return
        if not question and has_file:
            question = "Кратко изложи содержание прикреплённого файла."
        if not self._guard():
            return
        meta = self._take_attachment_meta()
        self._append("user", question, meta=meta)
        self._start(question, "", meta)

    @Slot(str)
    def runAction(self, kind):
        """Готовое действие по записи: изложение, тезисы, задачи, темы."""

        action = str(kind or "")
        if action not in ACTION_LABELS or not self._guard():
            return
        if not self._record_id:
            self._set_notice("Эти действия работают по выбранной записи.")
            return
        self._append("user", ACTION_LABELS[action])
        self._start("", action)

    @Slot(str)
    def renameRecord(self, title):
        """Переименовать выбранную запись (и строку в истории)."""

        if not self._record_id:
            self._set_notice("Свободный разговор нельзя переименовать.")
            return
        cleaned = " ".join(str(title or "").strip().split())
        if not cleaned:
            self._set_notice("Заголовок не может быть пустым.")
            return
        rename = getattr(self.controller, "renameSession", None)
        if callable(rename):
            rename(self._record_id, cleaned)
        else:
            try:
                cleaned = self.store.rename_session(self._record_id, cleaned)
            except ValueError:
                self._set_notice("Заголовок не может быть пустым.")
                return
        self._apply_title(self._record_id, cleaned)
        self._set_notice(f"Запись переименована: {cleaned}")

    @Slot()
    def nameRecord(self):
        """Придумать заголовок выбранной записи локальной моделью."""

        if not self._record_id:
            self._set_notice("Сначала выберите запись.")
            return
        if not self._guard():
            return
        self._start_naming([self._record_id])

    @Slot()
    def nameUntitledRecords(self):
        """Проставить заголовки всем записям с типовым именем источника."""

        if not self._guard():
            return
        targets = [str(row["id"]) for row in self._records if row.get("needsTitle")]
        if not targets:
            self._set_notice("Все записи уже с понятными названиями.")
            return
        self._start_naming(targets)

    def _start_naming(self, session_ids: list[str]) -> None:
        self._idle.stop()
        self._cancel = threading.Event()
        self._naming = True
        self._busy = True
        self._stage = "title"
        self._status = (
            "Придумываю название…"
            if len(session_ids) == 1
            else f"Называю записи: 0 из {len(session_ids)}"
        )
        self.streamChanged.emit()
        model = self._current_model()
        cancel = self._cancel
        ids = list(session_ids)

        def work():
            done = 0
            error = ""
            try:
                for session_id in ids:
                    if cancel.is_set():
                        error = "cancelled"
                        break
                    session = self.store.get_session(session_id)
                    if session is None:
                        continue
                    excerpt = " ".join(
                        str(segment.get("text") or "")
                        for segment in (session.get("segments") or [])[:40]
                    )
                    fallback = core.title_from_transcript(session.get("segments") or [])
                    title = ""
                    try:
                        raw = self.engine.complete(
                            core.suggest_title_messages(excerpt or fallback),
                            model,
                            GenerationOptions(temperature=0.2, max_tokens=48),
                            cancel=cancel,
                        )
                        title = core.clean_suggested_title(raw)
                    except llm.GenerationCancelled:
                        error = "cancelled"
                        break
                    except llm.RuntimeUnavailable as failure:
                        error = str(failure)
                        break
                    except Exception as failure:
                        error = str(failure) or failure.__class__.__name__
                        break
                    if not title:
                        title = fallback
                    if not title:
                        continue
                    rename = getattr(self.controller, "renameSession", None)
                    if callable(rename):
                        rename(session_id, title)
                    else:
                        title = self.store.rename_session(session_id, title)
                    done += 1
                    self.titleFinished.emit(session_id, title, "")
                    if len(ids) > 1:
                        self.stageArrived.emit(
                            "title_progress",
                            {"done": done, "total": len(ids)},
                        )
            except Exception as failure:
                error = str(failure) or failure.__class__.__name__
            self.namingFinished.emit(error, done)

        self._worker = threading.Thread(target=work, name="dotaudio-llm-title", daemon=True)
        self._worker.start()

    def _on_title_finished(self, session_id, title, _unused):
        if session_id and title:
            self._apply_title(str(session_id), str(title))

    def _on_naming_finished(self, error, done):
        self._naming = False
        self._busy = False
        self._stage = ""
        count = int(done)
        if error == "cancelled":
            self._status = "Название остановлено"
            if count:
                self._set_notice(f"Успели назвать: {count}")
        elif error:
            self._status = "Ошибка"
            self._set_notice(f"Не удалось назвать: {error}")
        elif count == 1:
            self._status = "Готов к следующему вопросу"
            self._set_notice("Заголовок обновлён.")
        elif count:
            self._status = "Готов к следующему вопросу"
            self._set_notice(f"Названо записей: {count}")
        else:
            self._status = "Готов к следующему вопросу"
            self._set_notice("Нечего называть: в расшифровках мало текста.")
        self._idle.start()
        self.streamChanged.emit()
        self.refreshRecords("")

    def _start(self, question: str, action: str, meta: dict | None = None) -> None:
        self._idle.stop()
        self._cancel = threading.Event()
        self._busy = True
        self._streaming = False
        self._stage = "prepare"
        self._status = "Готовлю ответ…"
        self._index = {"active": False, "done": 0, "total": 0}
        self.streamChanged.emit()
        # Пустая реплика помощника: в неё будет дописываться поток токенов.
        self._messages = [*self._messages, {"role": "assistant", "content": "", "pending": True}]
        self.messagesChanged.emit()

        model = self._current_model()
        record_id = self._record_id
        history = [
            {
                "role": item["role"],
                "content": item["content"],
                "meta": item.get("meta") or {},
            }
            for item in self._messages[:-2]
            if item.get("content") or (item.get("meta") or {}).get("attachment")
        ]
        attachment = (meta or {}).get("attachment") if meta else None
        cancel = self._cancel

        def work():
            error = ""
            try:
                self._run_task(
                    model, record_id, question, action, history, cancel, attachment
                )
            except llm.GenerationCancelled:
                error = "cancelled"
            except llm.RuntimeUnavailable as failure:
                error = str(failure)
            except Exception as failure:
                error = str(failure) or failure.__class__.__name__
            self.replyFinished.emit(error, action)

        self._worker = threading.Thread(target=work, name="dotaudio-llm-answer", daemon=True)
        self._worker.start()

    def _run_task(
        self, model, record_id, question, action, history, cancel, attachment=None
    ) -> None:
        """Тело воркера: ни одного обращения к QML, только сигналы."""

        digests = StoreDigests(self.store, model.id)

        def respond(messages, options: GenerationOptions, on_token):
            return self.engine.complete(
                messages,
                model,
                options,
                cancel=cancel,
                on_token=on_token,
            )

        def emit_token(piece: str) -> None:
            self.tokenArrived.emit(piece)

        session = self.store.get_session(record_id) if record_id else None
        chunks = build_chunks(session.get("segments") or []) if session else []
        helper = TranscriptAssistant(
            respond=respond,
            context_tokens=llm.plan_context(model),
            digests=digests,
            on_stage=lambda name, payload: self.stageArrived.emit(name, dict(payload)),
            cancel=cancel,
        )
        material = ""
        material_name = ""
        if isinstance(attachment, dict):
            material = str(attachment.get("text") or "")
            material_name = str(attachment.get("name") or "")
        if action:
            helper.summarize(record_id, chunks, action, on_token=emit_token)
        elif record_id and chunks:
            # Вложение к вопросу по записи добавляется в сам вопрос: карта
            # записи и выдержки остаются главным источником.
            prompt = question
            if material.strip():
                prompt = (
                    f"Дополнительно прикреплён файл «{material_name or 'файл'}»:\n"
                    f"{material.strip()}\n\nВопрос: {question}"
                )
            helper.answer(prompt, record_id, chunks, history, on_token=emit_token)
        else:
            helper.chat(
                question,
                history,
                on_token=emit_token,
                material=material,
                material_name=material_name,
            )

    def _on_token(self, piece):
        if not self._messages:
            return
        last = self._messages[-1]
        if last.get("role") != "assistant":
            return
        last["content"] = str(last.get("content") or "") + str(piece)
        if not self._streaming:
            self._streaming = True
            self._stage = "answer"
            self._status = "Отвечаю…"
            self.streamChanged.emit()
        # Список сообщений не трогаем: иначе ListView пересобирает пузыри
        # на каждый токен. Текст недопечатанного ответа идёт через pendingReply.
        if not self._token_ui.isActive():
            self._token_ui.start()

    def _flush_token_ui(self) -> None:
        if self._busy:
            self.streamChanged.emit()

    def _on_stage(self, name, payload):
        data = dict(payload)
        if name == "index_start":
            self._index = {"active": True, "done": 0, "total": int(data.get("total") or 0)}
            self._stage = "index"
            self._status = f"Разбираю запись по частям: 0 из {self._index['total']}"
        elif name == "index_progress":
            done = int(data.get("done") or 0)
            total = int(data.get("total") or self._index.get("total") or 0)
            self._index = {"active": True, "done": done, "total": total}
            self._status = f"Разбираю запись по частям: {done} из {total}"
        elif name == "index_done":
            self._index = {"active": False, "done": 0, "total": 0}
            self._status = "Карта записи готова"
        elif name == "fold":
            self._stage = "fold"
            self._status = "Сжимаю описание длинной записи…"
        elif name == "select_start":
            self._stage = "select"
            self._status = "Ищу, в каких частях записи ответ…"
        elif name == "answer_start":
            self._stage = "answer"
            opened = int(data.get("opened") or 0)
            self._status = (
                "Читаю запись целиком…"
                if data.get("mode") == "full"
                else f"Читаю выбранные части: {opened}"
            )
        elif name == "title_progress":
            done = int(data.get("done") or 0)
            total = int(data.get("total") or 0)
            self._status = f"Называю записи: {done} из {total}"
        self.streamChanged.emit()

    def _on_reply_finished(self, error, action):
        if self._naming:
            return
        self._token_ui.stop()
        self._busy = False
        self._streaming = False
        self._stage = ""
        self._index = {"active": False, "done": 0, "total": 0}
        text = ""
        if self._messages and self._messages[-1].get("role") == "assistant":
            last = self._messages[-1]
            last["pending"] = False
            text = str(last.get("content") or "").strip()
            last["content"] = text
        if error == "cancelled":
            if not text:
                self._messages = self._messages[:-1]
            self._status = "Ответ остановлен"
        elif error:
            self._messages = self._messages[:-1]
            self._set_notice(f"Модель не ответила: {error}")
            self._status = "Ошибка"
        elif not text:
            self._messages = self._messages[:-1]
            self._set_notice("Модель вернула пустой ответ. Попробуйте переспросить.")
            self._status = "Пустой ответ"
        else:
            self._status = "Готов к следующему вопросу"
        if text:
            self.store.append_chat_message(
                self._record_id or GENERAL_CHAT_ID,
                "assistant",
                text,
                self._active_model_id(),
                {"action": action} if action else {},
            )
        self._idle.start()
        self.messagesChanged.emit()
        self.streamChanged.emit()

    @Slot()
    def stop(self):
        """Остановить ответ. Уже напечатанное остаётся на экране."""

        self._cancel.set()

    @Slot()
    def unloadModel(self):
        self._release_async()
        self._set_notice("Модель выгружена из памяти.")

    def _release_idle(self) -> None:
        if not self._busy:
            self._release_async()

    @Slot(int)
    def copyMessage(self, index):
        position = int(index)
        if not (0 <= position < len(self._messages)):
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(self._messages[position].get("content") or ""))
            self._set_notice("Ответ скопирован.")

    @Slot()
    def clearNotice(self):
        self._set_notice("")

    def shutdown(self) -> None:
        """Остановить работу перед закрытием окна.

        Выгрузка модели уходит в daemon-поток: на aboutToQuit нельзя ждать
        close() у GGUF - это держит выход приложения на десятки секунд.
        """

        self._cancel.set()
        self._download_cancel.set()
        self._release_async()


def _decode_text_bytes(raw: bytes) -> str:
    """Прочитать TXT с типичными кодировками Windows/UTF."""

    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
