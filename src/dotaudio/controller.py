from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from dotaudio.capture import AudioCapture, StreamCapture, list_input_devices
from dotaudio.engine import Engine, RecognitionConfig
from dotaudio.pipeline import LiveSession
from dotaudio.storage import Store
from dotaudio.transcripts import export_transcript, match_keywords

DEFAULTS = {
    "model": "base", "device": "auto", "language": "auto", "task": "transcribe",
    "backend": "local", "server_url": "http://127.0.0.1:8765", "source": "microphone",
    "input_device": "", "auto_paste": True, "keywords": "Whisper, искусственный интеллект",
    "channels": "", "profile": "balanced",
}


class Controller(QObject):
    changed = Signal()
    islandRequested = Signal()
    segmentArrived = Signal(str, object)
    jobFinished = Signal(str, str, bool)
    statusArrived = Signal(str)
    levelArrived = Signal(float)
    devicesArrived = Signal(object)
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
        self._jobs = {}
        self._started = 0
        self._elapsed = "00:00"
        self._closing = False
        self._recording_mode = ""
        self.segmentArrived.connect(self._on_segment)
        self.jobFinished.connect(self._on_finished)
        self.statusArrived.connect(self._set_status)
        self.levelArrived.connect(self._set_level)
        self.devicesArrived.connect(self._set_devices)
        desktop.dictate.connect(self.hotkeyRecord)
        desktop.island.connect(self.islandRequested)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.refreshHistory("")
        self.refreshDevices()

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

    @Property(str, notify=changed)
    def mediaUrl(self): return self._media_url

    @Property(str, notify=changed)
    def text(self): return " ".join(s["text"].strip() for s in self._segments)

    @Property(str, notify=changed)
    def caption(self): return self._segments[-1]["text"] if self._segments else "Здесь появится ваша речь"

    @Property(bool, constant=True)
    def hotkeysAvailable(self): return self.desktop.available

    @Slot(str)
    def selectPage(self, page):
        if page in ("dictation", "live", "media", "monitor", "history", "settings"):
            self._page = page
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
        self.changed.emit()

    def _config(self):
        return RecognitionConfig(**{key: self._settings[key] for key in
                                    ("model", "device", "language", "task", "backend", "server_url")})

    def _set_status(self, value):
        if self._jobs:
            self._status = value
            self.changed.emit()

    def _set_level(self, value):
        self._level = max(0.0, min(1.0, value)) if self.recording else 0.0
        self.changed.emit()

    def _set_devices(self, value):
        self._devices = value
        self.changed.emit()

    @Slot()
    def refreshDevices(self):
        def scan():
            try:
                self.devicesArrived.emit(list_input_devices())
            except Exception:
                self.devicesArrived.emit([])
        threading.Thread(target=scan, daemon=True).start()

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
        mode = self._page if self._page in ("dictation", "live", "monitor") else "dictation"
        self._recording_mode = mode
        self._state = "recording"
        self._status = "Слушаю · модель загрузится при первой фразе"
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
        self._media_url = QUrl.fromLocalFile(str(media.resolve())).toString()
        self._page, self._state = "media", "processing"
        self._status = "Открываем файл и загружаем модель…"
        self._notice = ""
        self._started = time.monotonic()
        cancel = threading.Event()
        self._jobs[sid] = {"cancel": cancel, "mode": "media", "name": media.name}
        config = self._config()
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
        self.store.append_segments(sid, [segment])
        job = self._jobs[sid]
        if sid == self._session_id:
            self._segments = self.store.get_session(sid)["segments"]
        if job["mode"] == "monitor":
            keywords = [w.strip() for w in str(self._settings["keywords"]).split(",") if w.strip()]
            matches = match_keywords(segment["text"], keywords)
            if matches:
                self._hits.insert(0, {**segment, "source": job["name"], "matches": ", ".join(matches), "session_id": sid})
                self._hits = self._hits[:200]
        self._status = "Слушаю" if self.recording else "Распознаём…"
        self.changed.emit()

    def _on_finished(self, sid, error, cancelled):
        job = self._jobs.pop(sid, None)
        if job is None:
            return
        self.store.finish_session(sid, "error" if error else "cancelled" if cancelled else "completed")
        if error:
            self._notice = error
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
            source = session["source"]
            self._media_url = QUrl.fromLocalFile(source).toString() if session["mode"] == "media" and Path(source).is_file() else ""
            self._page = "media"
            self._status = session["title"]
            self.changed.emit()

    @Slot(int, str)
    def editSegment(self, segment_id, text):
        if self._session_id:
            self.store.update_segment(self._session_id, segment_id, text)
            self._segments = self.store.get_session(self._session_id)["segments"]
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
            except OSError as exc:
                self._notice = f"Не удалось сохранить файл: {exc}"
            self.changed.emit()

    @Slot()
    def showIsland(self):
        self.islandRequested.emit()

    def shutdown(self):
        self._closing = True
        self.cancel()
        return not self._jobs
