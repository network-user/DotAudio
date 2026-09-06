from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from dotaudio.capture import (
    AudioCapture,
    StreamCapture,
    list_input_devices,
    list_output_devices,
    play_output_tone,
)
from dotaudio.engine import Engine, RecognitionConfig
from dotaudio.karaoke import export_ass, render_video
from dotaudio.pipeline import LiveSession
from dotaudio.storage import Store
from dotaudio.transcripts import export_transcript, match_keywords

DEFAULTS = {
    "model": "base", "device": "auto", "language": "ru", "task": "transcribe",
    "backend": "local", "server_url": "http://127.0.0.1:8765", "source": "microphone",
    "input_device": "", "auto_paste": True, "keywords": "Whisper, искусственный интеллект",
    "channels": "", "profile": "balanced", "output_device": "",
    "island_opacity": 0.94, "island_click_through": False, "island_snap": True,
    "island_x": -1, "island_y": 32,
}

STATUS_LABELS = {
    "loading_model": "Загружаем выбранную модель…",
    "transcribing_cpu": "Распознаём на процессоре…",
    "transcribing_cuda": "Распознаём на видеокарте…",
    "gpu_unavailable_falling_back_cpu": "Видеокарта недоступна, продолжаем на процессоре…",
    "uploading": "Отправляем аудио на сервер…",
    "completed": "Расшифровка готова",
    "cancelled": "Обработка отменена",
    "model_ready": "Модель подготовлена",
    "remote_model_managed_by_server": "Модель подготовит удалённый сервер",
}


class Controller(QObject):
    changed = Signal()
    islandRequested = Signal()
    segmentArrived = Signal(str, object)
    jobFinished = Signal(str, str, bool)
    statusArrived = Signal(str)
    levelArrived = Signal(float)
    devicesArrived = Signal(object)
    logArrived = Signal(str, str)
    modelProgressArrived = Signal(str, str)
    modelFinished = Signal(str, str, str)
    outputsArrived = Signal(object)
    deviceTestLevelArrived = Signal(float)
    deviceTestFinished = Signal(str, str)
    renderFinished = Signal(str)
    shutdownReady = Signal()

    def __init__(self, data_dir: Path, desktop):
        super().__init__()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(data_dir / "history.db")
        self.desktop = desktop
        self.engine = Engine()
        self._settings = {**DEFAULTS, **self.store.get_settings()}
        self._page, self._state = "dictation", "idle"
        self._status = "Готов к работе"
        self._notice = ""
        self._level = 0.0
        self._segments, self._history, self._hits, self._devices = [], [], [], []
        self._session_id, self._media_url, self._query = "", "", ""
        self._session_title = ""
        self._session_mode = ""
        self._jobs = {}
        self._started = 0
        self._elapsed = "00:00"
        self._closing = False
        self._recording_mode = ""
        self._logs: list[dict[str, str]] = []
        self._last_status = ""
        self._model_state = {
            "phase": "idle",
            "model": self._settings["model"],
            "message": "Модель ещё не подготовлена",
        }
        self._model_preparing = False
        self._outputs: list[dict[str, str | int]] = []
        self._device_test = {"phase": "idle", "message": "", "level": 0.0}
        self._window = None
        self._testing_device = False
        self._cover_url = ""
        self._rendering = False
        self.segmentArrived.connect(self._on_segment)
        self.jobFinished.connect(self._on_finished)
        self.statusArrived.connect(self._set_status)
        self.levelArrived.connect(self._set_level)
        self.devicesArrived.connect(self._set_devices)
        self.logArrived.connect(self._on_log)
        self.modelProgressArrived.connect(self._on_model_progress)
        self.modelFinished.connect(self._on_model_finished)
        self.outputsArrived.connect(self._set_outputs)
        self.deviceTestLevelArrived.connect(self._on_device_test_level)
        self.deviceTestFinished.connect(self._on_device_test_finished)
        self.renderFinished.connect(self._on_render_finished)
        desktop.dictate.connect(self.hotkeyRecord)
        desktop.island.connect(self.islandRequested)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.refreshHistory("")
        self.refreshDevices()
        self.refreshOutputs()
        self._record_log("system", "DotAudio запущен. Выберите модель или начните работу.")

    @Property(str, notify=changed)
    def page(self): return self._page

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def notice(self): return self._notice

    @Property(str, notify=changed)
    def elapsed(self): return self._elapsed

    @Property(float, notify=changed)
    def level(self): return self._level

    @Property(bool, notify=changed)
    def busy(self): return bool(self._jobs)

    @Property(bool, notify=changed)
    def recording(self): return self._state == "recording"

    @Property("QVariantMap", notify=changed)
    def settings(self): return self._settings

    @Property("QVariantList", notify=changed)
    def segments(self): return self._segments

    @Property("QVariantList", notify=changed)
    def history(self): return self._history

    @Property("QVariantList", notify=changed)
    def hits(self): return self._hits

    @Property("QVariantList", notify=changed)
    def devices(self): return self._devices

    @Property("QVariantList", notify=changed)
    def outputs(self): return self._outputs

    @Property("QVariantMap", notify=changed)
    def deviceTest(self): return self._device_test

    @Property("QVariantList", notify=changed)
    def logs(self): return self._logs

    @Property("QVariantMap", notify=changed)
    def modelState(self): return self._model_state

    @Property(bool, notify=changed)
    def modelPreparing(self): return self._model_preparing

    @Property(str, notify=changed)
    def mediaUrl(self): return self._media_url

    @Property(str, notify=changed)
    def coverUrl(self): return self._cover_url

    @Property(bool, notify=changed)
    def rendering(self): return self._rendering

    @Property(str, notify=changed)
    def sessionTitle(self): return self._session_title

    @Property(str, notify=changed)
    def sessionMode(self): return self._session_mode

    @Property(str, notify=changed)
    def text(self): return " ".join(s["text"].strip() for s in self._segments)

    @Property(str, notify=changed)
    def caption(self): return self._segments[-1]["text"] if self._segments else ""

    @Property(bool, constant=True)
    def hotkeysAvailable(self): return self.desktop.available

    @Slot(str)
    def selectPage(self, page):
        if page in ("dictation", "live", "media", "models", "history", "settings"):
            self._page = page
            self._record_log("info", f"Открыт раздел: {page}")
            self.changed.emit()

    @Slot(str, "QVariant")
    def setSetting(self, name, value):
        if name not in DEFAULTS or self._jobs:
            return
        choices = {
            "model": ("tiny", "base", "small", "medium", "large-v3", "turbo"),
            "device": ("auto", "cpu", "cuda"), "language": ("auto", "ru", "en", "de", "es", "fr", "zh"),
            "task": ("transcribe", "translate"), "backend": ("local", "remote"),
            "source": ("microphone", "system"), "profile": ("fast", "balanced", "quality"),
        }
        if name in choices and value not in choices[name]:
            return
        self._settings[name] = value
        if name == "profile":
            self._settings["model"] = {"fast": "tiny", "balanced": "base", "quality": "large-v3"}[value]
        self.store.save_settings(self._settings)
        if name == "model":
            self._model_state = {
                "phase": "idle",
                "model": str(value),
                "message": "Модель выбрана и ждёт подготовки",
            }
            self._record_log("info", f"Выбрана модель: {value}")
        elif name in ("device", "backend", "source", "language", "task"):
            self._record_log("info", f"Настройка {name}: {value}")
        self.changed.emit()

    def _config(self, media_mode=False):
        values = {key: self._settings[key] for key in
                  ("model", "device", "language", "task", "backend", "server_url", "profile")}
        return RecognitionConfig(**values, media_mode=bool(media_mode))

    def _set_status(self, value):
        if self._jobs:
            label = STATUS_LABELS.get(value, value)
            self._status = label
            if value != self._last_status:
                self._last_status = value
                self._record_log("info", label)
            self.changed.emit()

    def _record_log(self, tone, message):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "tone": str(tone),
            "message": str(message),
        }
        self._logs.insert(0, entry)
        self._logs = self._logs[:120]

    def _on_log(self, tone, message):
        self._record_log(tone, message)
        self.changed.emit()

    def _on_model_progress(self, model, message):
        self._model_state = {
            "phase": "downloading",
            "model": model,
            "message": message,
        }
        self._record_log("info", message)
        self.changed.emit()

    def _on_model_finished(self, model, device, error):
        self._model_preparing = False
        if error:
            self._model_state = {"phase": "error", "model": model, "message": error}
            self._record_log("error", error)
        else:
            placement = "на сервере" if device == "remote" else f"на {device}"
            message = f"Модель {model} готова {placement}."
            self._model_state = {"phase": "ready", "model": model, "message": message}
            self._record_log("success", message)
        self.changed.emit()

    def _set_level(self, value):
        self._level = max(0.0, min(1.0, value)) if self.recording else 0.0
        self.changed.emit()

    def _set_devices(self, value):
        self._devices = value
        self.changed.emit()

    def _set_outputs(self, value):
        self._outputs = value
        self.changed.emit()

    @Slot()
    def refreshDevices(self):
        def scan():
            try:
                devices = list_input_devices()
            except Exception:
                devices = []
            try:
                self.devicesArrived.emit(devices)
            except RuntimeError:
                # The app can close while a slow device driver is enumerated.
                return
        threading.Thread(target=scan, daemon=True).start()

    @Slot()
    def refreshOutputs(self):
        def scan():
            try:
                outputs = list_output_devices()
            except Exception:
                outputs = []
            try:
                self.outputsArrived.emit(outputs)
            except RuntimeError:
                return
        threading.Thread(target=scan, daemon=True).start()

    def set_window(self, window):
        self._window = window

    def _apply_click_through(self, enabled):
        if self._window is None:
            return
        try:
            self.desktop.set_click_through(int(self._window.winId()), bool(enabled))
        except RuntimeError:
            return

    @Slot(bool)
    def setIslandClickThrough(self, enabled):
        if self._jobs:
            return
        self._settings["island_click_through"] = bool(enabled)
        self.store.save_settings(self._settings)
        self._apply_click_through(enabled)
        self._record_log("info", "Остров пропускает клики." if enabled else "Остров принимает клики.")
        self.changed.emit()

    @Slot(bool)
    def applyIslandClickThrough(self, enabled):
        self._apply_click_through(enabled)

    @Slot(float, float)
    def saveIslandPosition(self, x, y):
        if not self._settings["island_snap"]:
            return
        if not all(-10000 < value < 10000 for value in (x, y)):
            return
        self._settings["island_x"] = round(float(x))
        self._settings["island_y"] = round(float(y))
        self.store.save_settings(self._settings)

    def _on_device_test_level(self, level):
        if not self._testing_device:
            return
        self._device_test = {
            "phase": "listening",
            "message": "Получаем уровень с микрофона. Запись не сохраняется.",
            "level": max(0.0, min(1.0, float(level))),
        }
        self.changed.emit()

    def _on_device_test_finished(self, phase, message):
        self._testing_device = False
        self._device_test = {"phase": phase, "message": message, "level": 0.0}
        self._record_log("success" if phase == "ready" else "error", message)
        self.changed.emit()

    @Slot()
    def testMicrophone(self):
        if self._jobs or self._testing_device:
            return
        raw_device = str(self._settings["input_device"])
        device = int(raw_device) if raw_device.isdigit() else None
        self._testing_device = True
        self._device_test = {
            "phase": "starting",
            "message": "Открываем микрофон для короткой проверки…",
            "level": 0.0,
        }
        self._record_log("info", "Запущена проверка микрофона без сохранения записи.")
        self.changed.emit()

        def test():
            errors: list[str] = []
            capture = AudioCapture(
                device=device,
                on_level=lambda level: self.deviceTestLevelArrived.emit(level),
                on_error=errors.append,
            )
            capture.start()
            started = capture.running
            deadline = time.monotonic() + 3.0
            while capture.running and time.monotonic() < deadline:
                time.sleep(0.05)
            capture.stop()
            if errors:
                self.deviceTestFinished.emit("error", errors[-1])
            elif not started:
                self.deviceTestFinished.emit("error", "Микрофон остановился до завершения проверки.")
            else:
                self.deviceTestFinished.emit("ready", "Микрофон отвечает. Тестовая запись не сохранена.")

        threading.Thread(target=test, name="dotaudio-microphone-test", daemon=True).start()

    @Slot()
    def testOutputDevice(self):
        if self._jobs or self._testing_device:
            return
        raw_device = str(self._settings["output_device"])
        device = int(raw_device) if raw_device.isdigit() else None
        self._testing_device = True
        self._device_test = {"phase": "starting", "message": "Воспроизводим короткий тестовый тон…", "level": 0.0}
        self._record_log("info", "Запущена проверка устройства вывода.")
        self.changed.emit()

        def test():
            try:
                play_output_tone(device)
            except Exception as exc:
                self.deviceTestFinished.emit("error", f"Не удалось воспроизвести тон: {exc}")
            else:
                self.deviceTestFinished.emit("ready", "Тестовый тон отправлен на выбранное устройство.")

        threading.Thread(target=test, name="dotaudio-output-test", daemon=True).start()

    @Slot()
    def clearNotice(self):
        self._notice = ""
        self.changed.emit()

    def _tick(self):
        if self._jobs:
            seconds = int(time.monotonic() - self._started)
            self._elapsed = f"{seconds // 60:02}:{seconds % 60:02}"
            self.changed.emit()

    @Slot()
    def prepareSelectedModel(self):
        if self._jobs or self._model_preparing:
            return
        config = self._config()
        model = config.model
        self._model_preparing = True
        self._model_state = {
            "phase": "downloading",
            "model": model,
            "message": "Проверяем кэш и готовим модель…",
        }
        self._record_log("info", f"Подготовка модели {model} начата.")
        self.changed.emit()

        def prepare():
            try:
                self.modelProgressArrived.emit(model, "Загружаем или проверяем файлы модели…")
                device = self.engine.prepare(config, lambda status: self.statusArrived.emit(status))
            except Exception as exc:
                self.modelFinished.emit(model, "", str(exc))
            else:
                self.modelFinished.emit(model, device, "")

        threading.Thread(target=prepare, name="dotaudio-model-prepare", daemon=True).start()

    @Slot()
    def hotkeyRecord(self):
        if not self._jobs:
            self._page = "dictation"
            self.desktop.remember_target()
        self._toggle(True)

    @Slot()
    def toggleRecording(self):
        self._toggle(False)

    def _toggle(self, hotkey):
        if self._state == "recording":
            self._state = "processing"
            self._status = "Завершаем последние фразы…"
            for job in tuple(self._jobs.values()):
                if job.get("live"):
                    threading.Thread(target=job["live"].stop, daemon=True).start()
            self.changed.emit()
            return
        if self._jobs:
            return
        if not hotkey:
            self.desktop.target = 0
        self._notice = ""
        self._segments = []
        self._media_url = ""
        self._hits = []
        self._started = time.monotonic()
        self._elapsed = "00:00"
        mode = self._page if self._page in ("dictation", "live") else "dictation"
        self._recording_mode = mode
        self._session_mode = mode
        self._session_title = {
            "dictation": "Диктовка",
            "live": "Живые субтитры",
            "monitor": "Мониторинг эфира",
        }[mode]
        self._state = "recording"
        self._status = "Слушаю · модель загрузится при первой фразе"
        self._last_status = ""
        self._record_log("info", f"Запущен режим: {mode}.")
        sources = [("Микрофон" if self._settings["source"] == "microphone" else "Звук компьютера", "")]
        if mode == "monitor":
            sources = []
            for line in str(self._settings["channels"]).splitlines():
                if line.strip():
                    name, separator, url = line.partition("|")
                    sources.append((name.strip() if separator else "Эфир", url.strip() if separator else name.strip()))
            if not sources or len(sources) > 4:
                self._state = "idle"
                self._notice = "Добавьте от 1 до 4 прямых HTTP(S)-ссылок на эфир."
                self.changed.emit()
                return
        for name, url in sources:
            sid = self.store.create_session(name, mode, url or self._settings["source"], self._settings["model"])
            self._session_id = sid
            if sid == self._session_id:
                self._session_title = name
            live = LiveSession(self.engine, self._config(),
                               lambda segment, sid=sid: self.segmentArrived.emit(sid, segment),
                               self.statusArrived.emit,
                               lambda error, cancelled, sid=sid: self.jobFinished.emit(sid, error, cancelled))
            self._jobs[sid] = {"live": live, "mode": mode, "name": name, "hotkey": hotkey}
            try:
                def audio_error(error, sid=sid, live=live):
                    live.failed = error
                    threading.Thread(target=live.stop, kwargs={"cancel": True}, daemon=True).start()
                args = {"on_audio": live.feed, "on_level": self.levelArrived.emit, "on_error": audio_error}
                if url:
                    capture = StreamCapture(url, **args)
                else:
                    device = self._settings["input_device"]
                    capture = AudioCapture(kind=self._settings["source"],
                                           device=int(device) if str(device).isdigit() else None, **args)
                # Device startup and WASAPI initialization must not block the QML thread.
                def start(live=live, capture=capture, sid=sid):
                    try:
                        live.start(capture)
                    except Exception as exc:
                        self.jobFinished.emit(sid, str(exc), False)
                threading.Thread(target=start, daemon=True).start()
            except Exception as exc:
                self.jobFinished.emit(sid, str(exc), False)
        self.changed.emit()

    @Slot()
    def cancel(self):
        for job in tuple(self._jobs.values()):
            if job.get("live"):
                threading.Thread(target=job["live"].stop, kwargs={"cancel": True}, daemon=True).start()
            else:
                job["cancel"].set()
        if self._jobs:
            self._state = "processing"
            self._status = "Останавливаем обработку…"
            self.changed.emit()

    @Slot()
    def importFile(self):
        if self._jobs:
            return
        path, _ = QFileDialog.getOpenFileName(None, "Открыть аудио или видео", "",
                                             "Медиа (*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.mp4 *.mkv *.webm *.mov)")
        if path:
            self.transcribePath(path)

    @Slot()
    def chooseCover(self):
        if self._jobs or self._rendering:
            return
        path, _ = QFileDialog.getOpenFileName(
            None, "Выбрать обложку", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self._cover_url = QUrl.fromLocalFile(path).toString()
            self._record_log("info", f"Выбрана обложка: {Path(path).name}")
            self.changed.emit()

    @Slot(str)
    def transcribePath(self, path):
        if self._jobs:
            return
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        media = Path(path)
        if not media.is_file() or media.suffix.lower() not in {
            ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".mp4", ".mkv", ".webm", ".mov"
        }:
            self._notice = "Выберите поддерживаемый аудио- или видеофайл."
            self.changed.emit()
            return
        sid = self.store.create_session(media.name, "media", str(media), self._settings["model"])
        self._session_id = sid
        self._segments = []
        self._session_mode = "media"
        self._session_title = media.name
        self._media_url = QUrl.fromLocalFile(str(media.resolve())).toString()
        self._cover_url = ""
        self._page, self._state = "media", "processing"
        self._status = "Открываем файл и загружаем модель…"
        self._notice = ""
        self._started = time.monotonic()
        cancel = threading.Event()
        self._jobs[sid] = {"cancel": cancel, "mode": "media", "name": media.name}
        config = self._config(media_mode=True)
        def process():
            error = ""
            try:
                self.engine.transcribe(str(media), config, cancel,
                                       lambda segment: self.segmentArrived.emit(sid, segment),
                                       self.statusArrived.emit)
            except Exception as exc:
                error = str(exc)
            self.jobFinished.emit(sid, error, cancel.is_set())
        threading.Thread(target=process, daemon=True).start()
        self.changed.emit()

    def _on_segment(self, sid, segment):
        if sid not in self._jobs:
            return
        identifiers = self.store.append_segments(sid, [segment])
        job = self._jobs[sid]
        if sid == self._session_id:
            self._segments = [*self._segments, {**segment, "id": identifiers[0]}]
        if job["mode"] == "monitor":
            keywords = [w.strip() for w in str(self._settings["keywords"]).split(",") if w.strip()]
            matches = match_keywords(segment["text"], keywords)
            if matches:
                self._hits.insert(0, {**segment, "source": job["name"], "matches": ", ".join(matches), "session_id": sid})
                self._hits = self._hits[:200]
                self._record_log("warning", f"Совпадение в эфире {job['name']}: {', '.join(matches)}")
        elif sid == self._session_id:
            self._record_log("success", f"Добавлен сегмент {len(self._segments)}: {segment['text'][:80]}")
        self._status = "Слушаю" if self.recording else "Распознаём…"
        self.changed.emit()

    def _on_finished(self, sid, error, cancelled):
        job = self._jobs.pop(sid, None)
        if job is None:
            return
        self.store.finish_session(sid, "error" if error else "cancelled" if cancelled else "completed")
        if error:
            self._notice = error
            self._record_log("error", error)
        if job["mode"] == "dictation" and not cancelled and not error:
            session = self.store.get_session(sid)
            text = " ".join(s["text"].strip() for s in session["segments"])
            if text:
                QApplication.clipboard().setText(text)
                self._notice = "Текст скопирован в буфер обмена."
                if self._settings["auto_paste"] and job.get("hotkey"):
                    QTimer.singleShot(250, self._paste)
        if not self._jobs:
            self._state = "idle"
            self._level = 0
            self._status = "Остановлено" if cancelled else "Ошибка обработки" if error else "Готово · история сохранена"
            if not error:
                self._record_log("success", self._status)
        self.refreshHistory(self._query)
        self.changed.emit()
        if self._closing and not self._jobs:
            self.shutdownReady.emit()

    def _paste(self):
        self._notice = "Текст вставлен и сохранён в буфере." if self.desktop.paste() else "Текст в буфере. Нажмите Ctrl+V в нужном поле."
        self.changed.emit()

    @Slot()
    def copyText(self):
        if self.text:
            QApplication.clipboard().setText(self.text)
            self._notice = "Текст скопирован."
            self._record_log("success", "Текст скопирован в буфер обмена.")
            self.changed.emit()

    @Slot(str)
    def refreshHistory(self, query):
        self._query = query
        self._history = self.store.list_sessions(query)
        self.changed.emit()

    @Slot(str)
    def openSession(self, sid):
        if self._jobs:
            self._notice = "Завершите запись, чтобы открыть другую сессию."
            self.changed.emit()
            return
        session = self.store.get_session(sid)
        if session:
            self._session_id = sid
            self._segments = session["segments"]
            self._session_mode = session["mode"]
            self._session_title = session["title"]
            source = session["source"]
            is_media = session["mode"] == "media"
            self._media_url = QUrl.fromLocalFile(source).toString() if is_media and Path(source).is_file() else ""
            if is_media and source and not self._media_url:
                self._notice = "Исходный медиафайл не найден. Расшифровку всё ещё можно редактировать и экспортировать."
            self._page = session["mode"] if session["mode"] in (
                "dictation", "live", "media", "monitor"
            ) else "history"
            self._status = session["title"]
            self.changed.emit()

    @Slot(int, str)
    def editSegment(self, segment_id, text):
        if self._session_id:
            self.store.update_segment(self._session_id, segment_id, text)
            self._segments = self.store.get_session(self._session_id)["segments"]
            self._record_log("info", f"Изменён сегмент {segment_id}.")
            self.changed.emit()

    @Slot(str)
    def exportFile(self, format):
        if not self._segments or format not in ("txt", "srt", "vtt", "json"):
            return
        path, _ = QFileDialog.getSaveFileName(None, "Сохранить расшифровку", f"transcript.{format}",
                                             f"{format.upper()} (*.{format})")
        if path:
            try:
                Path(path).write_text(export_transcript(self._segments, format), encoding="utf-8")
                self._notice = "Расшифровка сохранена."
                self._record_log("success", f"Экспорт: {Path(path).name}")
            except OSError as exc:
                self._notice = f"Не удалось сохранить файл: {exc}"
            self.changed.emit()

    @Slot()
    def exportKaraokeFile(self):
        if not self._segments:
            return
        path, _ = QFileDialog.getSaveFileName(
            None, "Сохранить караоке-субтитры", "karaoke.ass", "ASS subtitles (*.ass)"
        )
        if not path:
            return
        try:
            Path(path).write_text(export_ass(self._segments), encoding="utf-8")
            self._notice = "Караоке-субтитры сохранены. Их можно открыть в FFmpeg, OBS или видеоредакторе."
            self._record_log("success", f"Караоке-экспорт: {Path(path).name}")
        except OSError as exc:
            self._notice = f"Не удалось сохранить ASS: {exc}"
        self.changed.emit()

    @Slot()
    def exportKaraokeVideo(self):
        if not self._segments or not self._media_url or self._rendering:
            return
        source = QUrl(self._media_url).toLocalFile()
        if not source or not Path(source).is_file():
            self._notice = "Исходный медиафайл недоступен для экспорта видео."
            self.changed.emit()
            return
        path, _ = QFileDialog.getSaveFileName(
            None, "Экспортировать караоке-видео", "karaoke.mp4", "MP4 video (*.mp4)"
        )
        if not path:
            return
        cover = QUrl(self._cover_url).toLocalFile() if self._cover_url else None
        self._rendering = True
        self._status = "Собираем караоке-видео в FFmpeg…"
        self._record_log("info", f"Запущен рендер караоке: {Path(path).name}")
        self.changed.emit()

        def render():
            ass_path = str(Path(path).with_suffix(".ass"))
            try:
                Path(ass_path).write_text(export_ass(self._segments), encoding="utf-8")
                render_video(source, ass_path, path, cover)
            except Exception as exc:
                self.renderFinished.emit(str(exc))
            else:
                self.renderFinished.emit("")

        threading.Thread(target=render, name="dotaudio-karaoke-render", daemon=True).start()

    def _on_render_finished(self, error):
        self._rendering = False
        if error:
            self._notice = f"Караоке-видео не создано: {error}"
            self._record_log("error", self._notice)
        else:
            self._notice = "Караоке-видео и ASS-трек сохранены рядом."
            self._record_log("success", self._notice)
        self._status = "Готово" if not error else "Ошибка экспорта"
        self.changed.emit()

    @Slot()
    def showIsland(self):
        self.islandRequested.emit()

    def shutdown(self):
        self._closing = True
        self.cancel()
        return not self._jobs
