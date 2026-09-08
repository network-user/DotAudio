from __future__ import annotations

import os
import re
import sys
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
    list_loopback_devices,
    list_output_devices,
    live_source_label,
    next_live_source,
    open_live_capture,
    play_output_tone,
    playback_device_for_loopback,
    source_for_mode,
)
from dotaudio.desktop import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, Hotkey
from dotaudio.engine import Engine, RecognitionConfig
from dotaudio.karaoke import export_ass, render_video
from dotaudio.pipeline import (
    LIVE_SPEECH_THRESHOLD,
    SAMPLE_RATE,
    LiveSession,
    open_voice_activity,
)
from dotaudio.storage import Store
from dotaudio.transcripts import (
    apply_keyword_cooldown,
    export_transcript,
    match_keywords,
    regroup_for_subtitles,
)

MODEL_BY_PROFILE = {"fast": "base", "balanced": "small", "quality": "large-v3"}

# Справочные характеристики моделей Whisper из публичной документации
# faster-whisper. Это параметры архитектуры и требования к памяти, а не
# замеры скорости на конкретной машине: скорость без реального прогона
# не заявляется.
MODEL_CATALOG = {
    "tiny":     {"params": "39 млн",  "download_mb": 75,   "ram_gb": 1,  "load": 1},
    "base":     {"params": "74 млн",  "download_mb": 142,  "ram_gb": 1,  "load": 2},
    "small":    {"params": "244 млн", "download_mb": 483,  "ram_gb": 2,  "load": 3},
    "medium":   {"params": "769 млн", "download_mb": 1530, "ram_gb": 5,  "load": 4},
    "large-v3": {"params": "1,55 млрд", "download_mb": 3100, "ram_gb": 10, "load": 5},
    "turbo":    {"params": "809 млн", "download_mb": 1620, "ram_gb": 6,  "load": 4},
}

DEFAULTS = {
    "model": "small", "device": "auto", "language": "ru", "task": "transcribe",
    "backend": "local", "server_url": "http://127.0.0.1:8765", "source": "microphone",
    "live_source": "system",
    "input_device": "", "auto_paste": True, "keywords": "Whisper, искусственный интеллект",
    "channels": "", "profile": "balanced", "output_device": "", "loopback_device": "",
    "island_opacity": 0.94, "island_click_through": False, "island_snap": True,
    "island_x": -1, "island_y": 32,
    "caption_overlay": True, "caption_size": "md", "caption_contrast": "normal",
    "caption_position": "bottom", "caption_x": -1, "caption_y": -1,
    "caption_screen": -1, "caption_autohide": False, "caption_locked": True,
    "reduce_motion": False,
    "live_sensitivity": "speech",
    "dictate_hotkey": "Ctrl+Alt+Space", "island_hotkey": "Ctrl+Alt+O",
    "paste_last_hotkey": "Shift+Alt+Z", "dictate_hold": False,
    # Kept in local settings so terminology and snippets never leave the PC.
    "dictionary": [], "snippets": [],
}

LIVE_SETTINGS = {
    "caption_overlay", "caption_size", "caption_contrast",
    "caption_position", "caption_x", "caption_y", "caption_screen",
    "caption_autohide", "caption_locked", "reduce_motion",
    "island_opacity", "island_snap",
}

HOTKEY_OPTIONS = {
    "Ctrl+Alt+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x20),
    "Ctrl+Shift+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x20),
    "Ctrl+Win+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x20),
    "Ctrl+Alt+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x4F),
    "Ctrl+Shift+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x4F),
    "Ctrl+Win+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x4F),
    "Shift+Alt+Z": Hotkey(MOD_NOREPEAT | MOD_SHIFT | MOD_ALT, 0x5A),
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
    "live_backlog": "Догоняем живой звук…",
    "live_audio_gap": "Пропущена часть аудио из-за перегрузки захвата. Субтитры продолжаются.",
    "live_no_text": "Звук есть, но речь не распознана. Проверьте источник и язык.",
    "live_slow": "Модель считает дольше, чем длится речь. Выберите профиль «Быстро».",
    "live_unrecognized": "Звук есть, но речи не распознаём. Музыка или шум?",
}


MODEL_IDLE_RELEASE_MS = 10 * 60 * 1000

# Бухгалтерия одного окна декода. Live отдаёт такую пару статусов примерно
# дважды в секунду; фазу субтитров они двигают, но не должны перечитывать
# статусную строку, журнал и все привязки общего ``changed``.
LIVE_INTERNAL_STATUSES = {"transcribing_cpu", "transcribing_cuda", "completed", "uploading"}

# Звук без единой распознанной фразы дольше этого - почти наверняка музыка
# или шум, и об этом нужно сказать словами, а не молчаливой заморозкой
# последней фразы.
LIVE_UNRECOGNIZED_SOUND_SECONDS = 8.0
# Сколько тишины означает «говорить перестали»: экран освобождается, старая
# фраза не висит до конца сессии. Паузы внутри речи короче.
LIVE_CLEAR_SILENCE_SECONDS = 3.0


def sensitivity_label(value: str) -> str:
    """Подпись кнопки чувствительности Live в один месте."""

    return {"speech": "Речь", "everything": "Всё"}.get(str(value or ""), "Речь")


def _physical_memory_gb() -> float | None:
    """Реальный объём ОЗУ; вне Windows или при отказе API - неизвестно."""

    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.POINTER(wintypes.ULONGLONG)]
        kb = wintypes.ULONGLONG(0)
        if not kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return None
        return round(kb.value / (1024 * 1024), 1)
    except (OSError, AttributeError):
        return None


def _cuda_device_count() -> int:
    """Сколько CUDA-устройств видит CTranslate2 прямо сейчас.

    Это фактическая проверка текущей сборки: если runtime-библиотеки
    (например cublas) недоступны, вернётся 0 и движок пойдёт на CPU.
    """

    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except Exception:
        return 0


def hardware_summary() -> dict:
    """Фактическая сводка устройства для страницы моделей."""

    threads = os.cpu_count() or 0
    ram = _physical_memory_gb()
    cuda = _cuda_device_count()
    return {
        "threads": threads,
        "ram_gb": ram,
        "cuda_devices": cuda,
        "compute_label": "Видеокарта (CUDA)" if cuda > 0 else "Процессор (CPU)",
    }


def model_fit(model: str, hardware: dict) -> dict:
    """Подходит ли модель этому устройству, по факту памяти и CPU.

    Оценка памяти - факт (сравнение с реальным ОЗУ). Оценка скорости -
    рекомендация по числу потоков, не измерение.
    """

    spec = MODEL_CATALOG.get(model)
    if spec is None:
        return {"state": "unknown", "note": ""}
    ram = hardware.get("ram_gb")
    threads = int(hardware.get("threads") or 0)
    cuda = int(hardware.get("cuda_devices") or 0)
    if ram is not None and float(ram) < float(spec["ram_gb"]):
        return {
            "state": "tight",
            "note": f"Хочет около {spec['ram_gb']} ГБ памяти, у вас {ram:g} ГБ",
        }
    if spec["load"] >= 4 and cuda == 0:
        if threads and threads < 8:
            return {"state": "slow", "note": "На этом CPU Live будет отставать"}
        return {"state": "slow", "note": "Потянет, но Live на CPU заметно медленнее"}
    if threads and threads < 4 and spec["load"] >= 3:
        return {"state": "slow", "note": "Мало потоков CPU: берите «Быстро»"}
    return {"state": "ok", "note": "Подходит этому устройству"}


def recommended_model(hardware: dict) -> str:
    """Модель по умолчанию под это устройство, из факта CPU/GPU.

    «small» на этом языке держит ритм Live начиная примерно с 4 потоков
    CPU (замер итерации скорости Live); слабее - «base». GPU снимает
    вопрос для всех карточек.
    """

    if int(hardware.get("cuda_devices") or 0) > 0:
        return "small"
    threads = int(hardware.get("threads") or 0)
    if threads >= 4:
        return "small"
    if threads >= 2:
        return "base"
    return "tiny"


class Controller(QObject):
    changed = Signal()
    captionChanged = Signal()
    segmentsChanged = Signal()
    levelChanged = Signal()
    liveStateChanged = Signal()
    islandRequested = Signal()
    segmentArrived = Signal(str, object)
    partialArrived = Signal(str, object)
    jobFinished = Signal(str, str, bool)
    statusArrived = Signal(str)
    levelArrived = Signal(float)
    captureStarted = Signal(str, float)
    devicesArrived = Signal(object)
    logArrived = Signal(str, str)
    modelProgressArrived = Signal(str, str)
    modelDownloadProgress = Signal(str, "QVariantMap")
    modelFinished = Signal(str, str, str)
    outputsArrived = Signal(object)
    loopbacksArrived = Signal(object)
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
        saved_bindings = {
            "dictate": HOTKEY_OPTIONS.get(str(self._settings["dictate_hotkey"])),
            "island": HOTKEY_OPTIONS.get(str(self._settings["island_hotkey"])),
            "paste_last": HOTKEY_OPTIONS.get(str(self._settings["paste_last_hotkey"])),
        }
        if (
            all(saved_bindings.values())
            and len({(item.modifiers, item.key) for item in saved_bindings.values()}) == 3
        ):
            self.desktop.set_hotkeys(saved_bindings)
        self._page, self._state = "live", "idle"
        self._status = "Готов к работе"
        self._notice = ""
        self._level = 0.0
        self._last_signal_at = 0.0
        self._last_caption_at = 0.0
        self._input_state = "Ожидает запуска"
        self._segments, self._history, self._hits, self._devices = [], [], [], []
        self._partial_caption = ""
        self._partial_end = 0.0
        self._final_end = 0.0
        self._confirmed_caption = ""
        self._caption_revision = 0
        self._live_phase = "idle"
        self._live_latency_ms = 0.0
        self._live_diagnostic = ""
        self._capture_started_at = None
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
        self._model_download = {}
        self._outputs: list[dict[str, str | int]] = []
        self._loopbacks: list[dict[str, str]] = []
        self._device_test = {"phase": "idle", "message": "", "level": 0.0}
        self._window = None
        self._testing_device = False
        self._cover_url = ""
        self._rendering = False
        self._last_transcript = ""
        self._hold_active = False
        self._keyword_cool: dict[str, float] = {}
        self._prepare_cancel = threading.Event()
        self._model_prepare_done = threading.Event()
        self._prepared_model = ""
        self._model_prepare_error = ""
        self._model_library = [Engine.disk_status(name) for name in ("tiny", "base", "small", "medium", "large-v3", "turbo")]
        # Сводка железа приехает фоном: импорт ctranslate2 для проверки CUDA
        # стоит сотни миллисекунд и не должен задерживать первый кадр окна.
        self._hardware = {"threads": os.cpu_count() or 0, "ram_gb": None, "cuda_devices": 0, "compute_label": ""}
        self._recommended_model = recommended_model(self._hardware)
        threading.Thread(target=self._probe_hardware, daemon=True, name="hardware-probe").start()
        self._edit_undo: list[tuple[int, str, str]] = []
        self._edit_redo: list[tuple[int, str, str]] = []
        self.segmentArrived.connect(self._on_segment)
        self.partialArrived.connect(self._on_partial)
        self.jobFinished.connect(self._on_finished)
        self.statusArrived.connect(self._set_status)
        self.levelArrived.connect(self._set_level)
        self.captureStarted.connect(self._on_capture_started)
        self.devicesArrived.connect(self._set_devices)
        self.logArrived.connect(self._on_log)
        self.modelProgressArrived.connect(self._on_model_progress)
        self.modelDownloadProgress.connect(self._on_model_download_progress)
        self.modelFinished.connect(self._on_model_finished)
        self.outputsArrived.connect(self._set_outputs)
        self.loopbacksArrived.connect(self._set_loopbacks)
        self.deviceTestLevelArrived.connect(self._on_device_test_level)
        self.deviceTestFinished.connect(self._on_device_test_finished)
        self.renderFinished.connect(self._on_render_finished)
        desktop.dictate.connect(self.hotkeyRecord)
        desktop.island.connect(self.islandRequested)
        desktop.paste_last.connect(self.pasteLastTranscript)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._cancel_release = QTimer(self)
        self._cancel_release.setSingleShot(True)
        self._cancel_release.timeout.connect(self._release_cancelled_jobs)
        self._idle_model_release = QTimer(self)
        self._idle_model_release.setSingleShot(True)
        self._idle_model_release.timeout.connect(self._release_idle_model)
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(50)
        self._hold_timer.timeout.connect(self._poll_hold)
        self.refreshHistory("")
        self.refreshDevices()
        self.refreshOutputs()
        self.refreshLoopbacks()
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

    @Property(float, notify=levelChanged)
    def level(self): return self._level

    @Property(str, notify=changed)
    def inputState(self):
        if self._state != "recording":
            return "Ожидает запуска"
        if self._level >= LIVE_SPEECH_THRESHOLD:
            return "Сигнал есть"
        if time.monotonic() - self._last_signal_at < 1.5:
            return "Тишина"
        return "Нет входного сигнала"

    @Property(bool, notify=changed)
    def busy(self): return bool(self._jobs)

    @Property(bool, notify=changed)
    def recording(self): return self._state == "recording"

    @Property("QVariantMap", notify=changed)
    def settings(self): return self._settings

    @Property("QVariantList", notify=segmentsChanged)
    def segments(self): return self._segments

    @Property("QVariantList", notify=changed)
    def history(self): return self._history

    @Property("QVariantList", notify=changed)
    def hits(self): return self._hits

    @Property("QVariantList", notify=changed)
    def devices(self): return self._devices

    @Property("QVariantList", notify=changed)
    def outputs(self): return self._outputs

    @Property("QVariantList", notify=changed)
    def loopbacks(self): return self._loopbacks

    @Property("QVariantMap", notify=changed)
    def deviceTest(self): return self._device_test

    @Property("QVariantList", notify=changed)
    def logs(self): return self._logs

    @Property("QVariantMap", notify=changed)
    def modelState(self): return self._model_state

    @Property("QVariantList", notify=changed)
    def modelLibrary(self): return self._model_library

    @Property(bool, notify=changed)
    def modelPreparing(self): return self._model_preparing

    @Property("QVariantMap", notify=changed)
    def modelDownload(self): return self._model_download

    @Property("QVariantMap", notify=changed)
    def hardware(self): return self._hardware

    @Property(str, notify=changed)
    def recommendedModel(self): return self._recommended_model

    @Property("QVariantMap", constant=True)
    def modelCatalog(self): return MODEL_CATALOG

    @Slot(str, result="QVariantMap")
    def modelFit(self, model):
        """Пригодность модели этому устройству; читается вместе с hardware."""

        return model_fit(str(model), self._hardware)

    def _probe_hardware(self) -> None:
        """Фоновая проба железа: обновляет сводку и рекомендацию."""

        summary = hardware_summary()
        self._hardware = summary
        self._recommended_model = recommended_model(summary)
        self.changed.emit()

    @Property(str, notify=changed)
    def mediaUrl(self): return self._media_url

    @Property(str, notify=changed)
    def coverUrl(self): return self._cover_url

    @Property(bool, notify=changed)
    def rendering(self): return self._rendering

    @Property("QVariantList", notify=changed)
    def dictionary(self): return list(self._settings.get("dictionary", []))

    @Property("QVariantList", notify=changed)
    def snippets(self): return list(self._settings.get("snippets", []))

    @Property(bool, notify=changed)
    def canUndoEdit(self): return bool(self._edit_undo)

    @Property(bool, notify=changed)
    def canRedoEdit(self): return bool(self._edit_redo)

    @Property(str, notify=changed)
    def liveSourceLabel(self):
        return live_source_label(str(self._settings.get("live_source") or "system"))

    @Slot()
    def cycleLiveSource(self):
        if self._jobs:
            return
        self.setSetting("live_source", next_live_source(str(self._settings.get("live_source") or "system")))

    @Property(str, notify=changed)
    def liveSensitivityLabel(self):
        return sensitivity_label(self._settings.get("live_sensitivity"))

    @Slot()
    def toggleLiveSensitivity(self):
        if self._jobs:
            return
        current = str(self._settings.get("live_sensitivity") or "speech")
        self.setSetting("live_sensitivity", "speech" if current == "everything" else "everything")

    @Property(str, notify=changed)
    def sessionTitle(self): return self._session_title

    @Property(str, notify=changed)
    def sessionMode(self): return self._session_mode

    @Property(str, notify=changed)
    def text(self): return " ".join(s["text"].strip() for s in self._segments)

    @Property(str, notify=changed)
    def caption(self):
        if self.liveActive:
            return self.displayCaption
        return self._segments[-1]["text"] if self._segments else ""

    @Property(bool, notify=liveStateChanged)
    def liveActive(self):
        return any(job.get("mode") == "live" for job in self._jobs.values())

    @Property(str, notify=liveStateChanged)
    def livePhase(self): return self._live_phase

    @Property(float, notify=liveStateChanged)
    def liveLatencyMs(self): return self._live_latency_ms

    @Property(str, notify=changed)
    def liveStatusText(self):
        if self._live_phase == "starting":
            return "Готовим модель…"
        if self._live_phase == "stopping":
            return "Завершаем последние фразы…"
        if self._live_diagnostic:
            return STATUS_LABELS[self._live_diagnostic]
        if self._live_phase == "decoding":
            return "Распознаём речь…"
        if self._level >= LIVE_SPEECH_THRESHOLD:
            return "Звук поступает · собираем фразу"
        return "Слушаем · ожидаем речь"

    @Property(str, notify=captionChanged)
    def partialCaption(self): return self._partial_caption

    @Property(str, notify=captionChanged)
    def confirmedCaption(self): return self._confirmed_caption

    @Property(str, notify=captionChanged)
    def displayCaption(self):
        return " ".join(part for part in (self._confirmed_caption, self._partial_caption) if part).strip()

    @Property(int, notify=captionChanged)
    def captionRevision(self): return self._caption_revision

    @Property(bool, constant=True)
    def hotkeysAvailable(self): return self.desktop.available

    @Property(str, notify=changed)
    def lastTranscript(self): return self._last_transcript

    @Slot(str)
    def selectPage(self, page):
        if page in ("dictation", "live", "media", "monitor", "models", "history", "settings"):
            self._page = page
            self._record_log("info", f"Открыт раздел: {page}")
            self.changed.emit()

    @Slot(str, "QVariant")
    def setSetting(self, name, value):
        if name not in DEFAULTS:
            return
        if self._jobs and name not in LIVE_SETTINGS:
            return
        choices = {
            "model": ("tiny", "base", "small", "medium", "large-v3", "turbo"),
            "device": ("auto", "cpu", "cuda"), "language": ("auto", "ru", "en", "de", "es", "fr", "zh"),
            "task": ("transcribe", "translate"), "backend": ("local", "remote"),
            "source": ("microphone", "system"), "live_source": ("microphone", "system", "mixed"),
            "live_sensitivity": ("speech", "everything"),
            "profile": ("fast", "balanced", "quality"),
            "caption_size": ("sm", "md", "lg"),
            "caption_contrast": ("normal", "high"),
            "caption_position": ("top", "bottom", "floating"),
        }
        if name in choices and value not in choices[name]:
            return
        if name in (
            "caption_overlay", "auto_paste", "dictate_hold", "island_click_through",
            "island_snap", "caption_autohide", "caption_locked", "reduce_motion",
        ):
            value = bool(value)
        if name in ("caption_x", "caption_y", "caption_screen"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return
        source_changed = (
            name in {"live_source", "input_device", "loopback_device", "output_device"}
            and self._settings.get(name) != value
        )
        self._settings[name] = value
        if name == "live_source":
            self._settings["source"] = value if value in ("microphone", "system") else "system"
        elif name == "source":
            self._settings["live_source"] = value
        if name == "profile":
            # Measured on this CPU with the live window: base decodes a four
            # second phrase in about 130 ms and small in about 360 ms, so the
            # everyday profile can afford the model that actually writes
            # Russian.  On tiny "русской речи" comes back as "меру с каиричев".
            self._settings["model"] = MODEL_BY_PROFILE[value]
        if source_changed:
            # Проверка относится ровно к тому устройству, которое было открыто.
            # После смены входа старый «готово» нельзя оставлять рядом с кнопкой
            # запуска - пользователь мог выбрать совершенно другой источник.
            self._device_test = {"phase": "idle", "message": "", "level": 0.0}
        self.store.save_settings(self._settings)
        if name == "model":
            self._model_state = {
                "phase": "idle",
                "model": str(value),
                "message": "Модель выбрана и ждёт подготовки",
            }
            self._record_log("info", f"Выбрана модель: {value}")
        elif name in ("device", "backend", "source", "live_source", "language", "task", "live_sensitivity"):
            self._record_log("info", f"Настройка {name}: {value}")
        self.changed.emit()

    @Slot()
    def resetCaptionPosition(self):
        """Return a dragged caption window to the safe bottom placement."""
        self._settings.update({"caption_position": "bottom", "caption_x": -1, "caption_y": -1})
        self.store.save_settings(self._settings)
        self._record_log("info", "Положение субтитров возвращено вниз экрана.")
        self.changed.emit()

    def _config(self, media_mode=False, live_stream=False):
        values = {key: self._settings[key] for key in
                  ("model", "device", "language", "task", "backend", "server_url", "profile")}
        if live_stream:
            values["live_sensitivity"] = str(self._settings["live_sensitivity"])
        values["initial_prompt"] = "; ".join(
            str(entry.get("term", "")).strip()
            for entry in self.dictionary if isinstance(entry, dict)
        )
        return RecognitionConfig(
            **values, media_mode=bool(media_mode), live_stream=bool(live_stream)
        )

    @Slot(str, str)
    def setHotkeys(self, dictate, island):
        if self._jobs:
            return
        paste_last = HOTKEY_OPTIONS.get(str(self._settings.get("paste_last_hotkey") or "Shift+Alt+Z"))
        bindings = {
            "dictate": HOTKEY_OPTIONS.get(str(dictate)),
            "island": HOTKEY_OPTIONS.get(str(island)),
            "paste_last": paste_last,
        }
        if None in bindings.values() or len({(item.modifiers, item.key) for item in bindings.values()}) != 3:
            self._notice = "Выберите две разные поддерживаемые комбинации."
            self.changed.emit()
            return
        if not self.desktop.set_hotkeys(bindings):
            self._notice = "Комбинация занята другой программой. Прежние hotkey сохранены."
            self.changed.emit()
            return
        self._settings["dictate_hotkey"] = str(dictate)
        self._settings["island_hotkey"] = str(island)
        self.store.save_settings(self._settings)
        self._notice = "Горячие клавиши обновлены."
        self._record_log("success", "Горячие клавиши переназначены.")
        self.changed.emit()

    def _save_local_rules(self, key, entries):
        self._settings[key] = entries
        self.store.save_settings(self._settings)
        self.changed.emit()

    @Slot(str, str)
    def addDictionaryEntry(self, term, misheard=""):
        term, misheard = str(term).strip(), str(misheard).strip()
        if not term or len(term) > 80 or len(misheard) > 80:
            self._notice = "Термин и вариант ошибки должны быть короче 80 символов."
            self.changed.emit()
            return
        entries = [item for item in self.dictionary if isinstance(item, dict)]
        if any(str(item.get("term", "")).casefold() == term.casefold() for item in entries):
            self._notice = "Такой термин уже есть в словаре."
            self.changed.emit()
            return
        if len(entries) >= 200:
            self._notice = "Словарь ограничен 200 терминами."
            self.changed.emit()
            return
        entries.append({"term": term, "misheard": misheard})
        self._save_local_rules("dictionary", entries)
        self._notice = "Термин сохранён локально и будет подсказкой для Whisper."
        self._record_log("success", f"Добавлен термин: {term}")

    @Slot(int)
    def removeDictionaryEntry(self, index):
        entries = self.dictionary
        if 0 <= index < len(entries):
            removed = entries.pop(index)
            self._save_local_rules("dictionary", entries)
            self._record_log("info", f"Удалён термин: {removed.get('term', '')}")

    @Slot(str, str)
    def addSnippet(self, trigger, expansion):
        trigger, expansion = str(trigger).strip(), str(expansion).strip()
        if not trigger or not expansion or len(trigger) > 60 or len(expansion) > 4000:
            self._notice = "Для snippet нужны фраза до 60 и текст до 4000 символов."
            self.changed.emit()
            return
        entries = [item for item in self.snippets if isinstance(item, dict)]
        if any(str(item.get("trigger", "")).casefold() == trigger.casefold() for item in entries):
            self._notice = "Такой голосовой trigger уже существует."
            self.changed.emit()
            return
        entries.append({"trigger": trigger, "expansion": expansion})
        self._save_local_rules("snippets", entries)
        self._notice = "Snippet сохранён. Он применяется только к финальному тексту диктовки."
        self._record_log("success", f"Добавлен snippet: {trigger}")

    @Slot(int)
    def removeSnippet(self, index):
        entries = self.snippets
        if 0 <= index < len(entries):
            removed = entries.pop(index)
            self._save_local_rules("snippets", entries)
            self._record_log("info", f"Удалён snippet: {removed.get('trigger', '')}")

    def _apply_dictation_rules(self, text):
        """Apply explicit local substitutions only after raw text is saved."""
        result = text
        for entry in self.dictionary:
            if not isinstance(entry, dict):
                continue
            term, misheard = str(entry.get("term", "")).strip(), str(entry.get("misheard", "")).strip()
            if term and misheard:
                result = re.sub(rf"(?<!\w){re.escape(misheard)}(?!\w)", term, result, flags=re.IGNORECASE)
        for entry in self.snippets:
            if not isinstance(entry, dict):
                continue
            trigger, expansion = str(entry.get("trigger", "")).strip(), str(entry.get("expansion", "")).strip()
            if trigger and expansion:
                result = re.sub(rf"(?<!\w){re.escape(trigger)}(?!\w)", expansion, result, flags=re.IGNORECASE)
        return result

    def _set_status(self, value):
        if self._jobs:
            label = STATUS_LABELS.get(value, value)
            if self.liveActive:
                if value == "loading_model" and self._live_phase in {"idle", "starting"}:
                    self._live_phase = "starting"
                elif value == "model_ready" and self._live_phase == "starting":
                    self._live_phase = "listening"
                elif value.startswith("transcribing_"):
                    self._live_phase = "decoding"
                elif value == "live_backlog":
                    self._live_phase = "backlog"
                    self._live_diagnostic = value
                elif value == "live_audio_gap":
                    self._live_phase = "backlog"
                    self._live_diagnostic = value
                elif value == "live_no_text":
                    self._live_phase = "no_text"
                    self._live_diagnostic = value
                elif value == "live_slow":
                    # Not a phase: captions keep coming, only later. The user
                    # needs to know why, and that a faster profile exists.
                    self._live_diagnostic = value
                elif value == "completed" and self.recording:
                    if not self._live_diagnostic:
                        self._live_phase = "listening"
                self.liveStateChanged.emit()
                if value in LIVE_INTERNAL_STATUSES:
                    return
                self._status = label
                if value != self._last_status:
                    self._last_status = value
                    self._record_log("info", label)
                self.changed.emit()
                return
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

    def _on_model_download_progress(self, model, info):
        # Проценты и скорость считает трекер загрузки в движке по факту
        # полученных байтов; сюда прилетает уже готовый снимок ~3 раза в
        # секунду. Состояние гонки не боится: снимок словарь.
        self._model_download = {"model": str(model), **dict(info or {})}
        self.changed.emit()

    def _on_model_finished(self, model, device, error):
        self._model_preparing = False
        self._model_download = {}
        self._prepared_model = "" if error else model
        self._model_prepare_error = str(error or "")
        self._model_prepare_done.set()
        self._model_library = [Engine.disk_status(name) for name in ("tiny", "base", "small", "medium", "large-v3", "turbo")]
        if error:
            self._model_state = {"phase": "error", "model": model, "message": error}
            self._record_log("error", error)
        else:
            placement = "на сервере" if device == "remote" else f"на {device}"
            message = f"Модель {model} готова {placement}."
            self._model_state = {"phase": "ready", "model": model, "message": message}
            self._record_log("success", message)
            self._arm_idle_model_release()
        self.changed.emit()

    def _set_level(self, value):
        self._level = max(0.0, min(1.0, value)) if self.recording else 0.0
        if self._level >= LIVE_SPEECH_THRESHOLD:
            self._last_signal_at = time.monotonic()
        self.levelChanged.emit()
        # Уровень приходит примерно десять раз в секунду. Общий ``changed``
        # пересчитывал бы все привязки интерфейса на каждый блок звука и
        # заставлял статус мигать между двумя формулировками, поэтому он
        # уходит только когда меняется словесное состояние входа.
        state = self.inputState
        if state != self._input_state:
            self._input_state = state
            self.changed.emit()

    def _on_capture_started(self, sid, started_at):
        job = self._jobs.get(sid)
        if job is None or job.get("mode") != "live" or sid != self._session_id:
            return
        self._capture_started_at = started_at
        self._started = started_at
        self._last_signal_at = started_at
        self._last_caption_at = started_at
        self._elapsed = "00:00"
        self.changed.emit()

    def _set_devices(self, value):
        self._devices = value
        self.changed.emit()

    def _set_outputs(self, value):
        self._outputs = value
        self.changed.emit()

    def _set_loopbacks(self, value):
        self._loopbacks = value
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

    @Slot()
    def refreshLoopbacks(self):
        def scan():
            try:
                devices = list_loopback_devices()
            except Exception:
                devices = []
            try:
                self.loopbacksArrived.emit(devices)
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

    @Slot("QVariant", bool)
    def applyClickThrough(self, window_id, enabled):
        try:
            self.desktop.set_click_through(int(window_id), bool(enabled))
        except (RuntimeError, TypeError, ValueError):
            return

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
        self._test_capture("microphone")

    @Slot()
    def testLiveSource(self):
        """Check exactly the source selected for live captions."""
        kind, _device = source_for_mode("live", self._settings)
        self._test_capture(kind)

    @Slot()
    def testSystemLoopback(self):
        """Play a quiet tone and verify that the selected output loops back."""
        if self._jobs or self._testing_device:
            return
        if self._settings["live_source"] not in {"system", "mixed"}:
            self._notice = "Для проверки loopback выберите «Звук системы» или «Авто» как источник Live."
            self.changed.emit()
            return
        raw_loopback = str(self._settings["loopback_device"])
        loopback_device = raw_loopback or None
        self._testing_device = True
        self._device_test = {
            "phase": "starting",
            "message": "Подаём тихий тестовый тон и проверяем возврат в Live…",
            "level": 0.0,
        }
        self._record_log("info", "Запущена проверка Windows loopback выбранного выхода.")
        self.changed.emit()

        def test():
            errors: list[str] = []
            levels: list[float] = []

            def on_level(level: float) -> None:
                levels.append(float(level))
                self.deviceTestLevelArrived.emit(level)

            capture = AudioCapture(kind="system", device=loopback_device, on_level=on_level, on_error=errors.append)
            try:
                capture.start()
                time.sleep(0.2)
                tone_device = playback_device_for_loopback(loopback_device)
                if tone_device is None:
                    raise RuntimeError("не найден выход Windows для выбранного loopback-устройства")
                play_output_tone(tone_device)
                time.sleep(0.5)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                capture.stop()
            peak = max(levels, default=0.0)
            if errors:
                self.deviceTestFinished.emit("error", errors[-1])
            elif peak < 0.001:
                self.deviceTestFinished.emit(
                    "error", "Loopback не получил тестовый тон. Выберите другой выход или проверьте драйвер Windows."
                )
            else:
                self.deviceTestFinished.emit(
                    "ready", f"Loopback работает. Пик тестового сигнала: {peak:.3f}."
                )

        threading.Thread(target=test, name="dotaudio-loopback-test", daemon=True).start()

    def _test_capture(self, kind: str):
        if self._jobs or self._testing_device:
            return
        source_name = {
            "microphone": "микрофон",
            "system": "звук системы",
            "mixed": "микрофон и звук системы",
        }.get(kind, "источник")
        self._testing_device = True
        self._device_test = {
            "phase": "starting",
            "message": f"Открываем {source_name} для короткой проверки…",
            "level": 0.0,
        }
        self._record_log("info", f"Запущена проверка источника: {source_name}.")
        self.changed.emit()

        def test():
            errors: list[str] = []
            levels: list[float] = []

            def on_level(level: float) -> None:
                levels.append(float(level))
                self.deviceTestLevelArrived.emit(level)

            capture = open_live_capture(
                kind,
                self._settings,
                on_level=on_level,
                on_error=errors.append,
            )
            try:
                capture.start()
                started = capture.running
                deadline = time.monotonic() + 3.0
                while capture.running and time.monotonic() < deadline:
                    time.sleep(0.05)
            except Exception as exc:
                errors.append(str(exc))
                started = False
            finally:
                capture.stop()
            if errors:
                self.deviceTestFinished.emit("error", errors[-1])
            elif not started:
                self.deviceTestFinished.emit("error", f"Источник «{source_name}» остановился до завершения проверки.")
            elif max(levels, default=0.0) < 0.001:
                hint = {
                    "system": "Выберите в списке именно устройство, через которое сейчас играет звук.",
                    "mixed": "Проверьте микрофон и выход, через который играет звук.",
                }.get(kind, "Проверьте разрешение Windows для микрофона и уровень входа.")
                self.deviceTestFinished.emit("silent", f"Источник «{source_name}» открыт, но сигнал нулевой. {hint}")
            else:
                self.deviceTestFinished.emit("ready", f"Источник «{source_name}» отвечает. Тестовая запись не сохранена.")

        threading.Thread(target=test, name="dotaudio-capture-test", daemon=True).start()

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
            if self.liveActive and self._capture_started_at is None:
                return
            seconds = int(time.monotonic() - self._started)
            self._elapsed = f"{seconds // 60:02}:{seconds % 60:02}"
            self._update_live_sound_status()
            self.changed.emit()

    def _update_live_sound_status(self):
        """Say out loud what Live hears instead of freezing the last phrase.

        Music or noise keeps the level high while VAD correctly refuses to
        caption it, so after a while without a single recognised phrase the
        interface says so.  Silence works the other way: after a short pause
        the caption is cleared - an ended utterance must not hang on screen
        until the session ends.
        """

        if not self.liveActive or not self.recording or self._capture_started_at is None:
            return
        now = time.monotonic()
        sound = self._level >= LIVE_SPEECH_THRESHOLD
        if sound:
            if now - max(self._last_caption_at, self._capture_started_at) >= LIVE_UNRECOGNIZED_SOUND_SECONDS:
                if self._live_diagnostic != "live_unrecognized":
                    self._live_diagnostic = "live_unrecognized"
                    self.liveStateChanged.emit()
            return
        if self._live_diagnostic == "live_unrecognized":
            self._live_diagnostic = ""
            self.liveStateChanged.emit()
        if (
            self.displayCaption
            and now - max(self._last_signal_at, self._capture_started_at) >= LIVE_CLEAR_SILENCE_SECONDS
        ):
            self._confirmed_caption = ""
            self._partial_caption = ""
            self._partial_end = 0.0
            self._caption_revision += 1
            self.captionChanged.emit()
            self.liveStateChanged.emit()

    def _arm_idle_model_release(self):
        """Unload the heavy ASR instance after a quiet period, not its files."""

        if not self._jobs and not self._model_preparing:
            self._idle_model_release.start(MODEL_IDLE_RELEASE_MS)

    def _release_idle_model(self):
        if self._jobs or self._model_preparing:
            return
        if not self.engine.release_cached_model():
            return
        self._prepared_model = ""
        self._model_state = {
            "phase": "idle",
            "model": self._settings["model"],
            "message": "Модель выгружена после 10 минут простоя.",
        }
        self._record_log("info", "Модель выгружена из памяти после простоя.")
        self.changed.emit()

    @Slot()
    def prepareSelectedModel(self):
        if self._jobs or self._model_preparing:
            return
        self._idle_model_release.stop()
        # Prepare the model for the first live window as well as for the final
        # decode.  This warms the decoder in the worker before the user starts
        # speaking, so the first caption does not pay the cold-start cost.
        config = self._config(live_stream=True)
        model = config.model
        self._prepare_cancel = threading.Event()
        self._model_prepare_done.clear()
        self._prepared_model = ""
        self._model_prepare_error = ""
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
                if self._prepare_cancel.is_set():
                    self.modelFinished.emit(model, "", "Подготовка отменена")
                    return

                def progress(info):
                    self.modelDownloadProgress.emit(model, info)

                device = self.engine.prepare(
                    config,
                    lambda status: self.statusArrived.emit(status),
                    progress,
                )
                if self._prepare_cancel.is_set():
                    self.modelFinished.emit(model, "", "Подготовка отменена")
                    return
            except Exception as exc:
                self.modelFinished.emit(model, "", str(exc))
            else:
                self.modelFinished.emit(model, device, "")

        threading.Thread(target=prepare, name="dotaudio-model-prepare", daemon=True).start()

    @Slot()
    def cancelModelPrepare(self):
        if not self._model_preparing:
            return
        self._prepare_cancel.set()
        self._model_download = {}
        self._model_state = {
            "phase": "idle",
            "model": self._settings["model"],
            "message": "Отменяем подготовку модели…",
        }
        self._record_log("warning", "Подготовка модели отменена.")
        self.changed.emit()

    @Slot()
    def hotkeyRecord(self):
        if self._hold_active and self._state == "recording":
            return
        if not self._jobs:
            self._page = "dictation"
            self.desktop.remember_target()
        hold = bool(self._settings.get("dictate_hold")) and self.desktop.available
        if hold and self._state != "recording":
            self._hold_active = True
            self._toggle(True)
            self._hold_timer.start()
            return
        self._toggle(True)

    def _poll_hold(self):
        if not self._hold_active:
            self._hold_timer.stop()
            return
        if self._state != "recording":
            self._hold_active = False
            self._hold_timer.stop()
            return
        if self.desktop.combo_held("dictate"):
            return
        self._hold_active = False
        self._hold_timer.stop()
        if self._state == "recording":
            self._toggle(True)

    def _stop_hold(self):
        self._hold_active = False
        self._hold_timer.stop()

    @Slot()
    def toggleRecording(self):
        if self._state == "processing" and self._jobs:
            self.forceStop()
            return
        self._toggle(False)

    def _toggle(self, hotkey):
        if self._state == "recording":
            self._stop_hold()
            self._state = "processing"
            self._status = "Завершаем последние фразы…"
            if any(job.get("mode") == "live" for job in self._jobs.values()):
                self._live_phase = "stopping"
                self.liveStateChanged.emit()
            for job in tuple(self._jobs.values()):
                if job.get("live"):
                    threading.Thread(target=job["live"].stop, daemon=True).start()
            self.changed.emit()
            return
        if self._jobs:
            return
        self._idle_model_release.stop()
        if not hotkey:
            self.desktop.target = 0
        self._notice = ""
        self._segments = []
        self.segmentsChanged.emit()
        self._partial_caption = ""
        self._partial_end = 0.0
        self._final_end = 0.0
        self._confirmed_caption = ""
        self._caption_revision += 1
        self._edit_undo = []
        self._edit_redo = []
        self._media_url = ""
        self._hits = []
        self._started = time.monotonic()
        self._last_signal_at = self._started
        self._last_caption_at = self._started
        self._elapsed = "00:00"
        mode = self._page if self._page in ("dictation", "live", "monitor") else "dictation"
        self._recording_mode = mode
        self._session_mode = mode
        self._session_title = {
            "dictation": "Диктовка",
            "live": "Живые субтитры",
            "monitor": "Мониторинг эфира",
        }[mode]
        if mode == "live":
            # Live is an overlay-first mode.  The user can hide it during a
            # session, but each new Live session starts with captions visible.
            self._settings["caption_overlay"] = True
            self._live_phase = "starting"
            self._live_latency_ms = 0.0
            self._live_diagnostic = ""
            self._capture_started_at = None
        self._state = "recording"
        self._status = "Готовим модель для Live…" if mode == "live" else "Слушаю · модель загрузится при первой фразе"
        self._last_status = ""
        self._record_log("info", f"Запущен режим: {mode}.")
        kind, _device = source_for_mode(mode, self._settings)
        sources = [({
            "microphone": "Микрофон",
            "system": "Звук компьютера",
            "mixed": "Микрофон и звук компьютера",
        }.get(kind, "Микрофон"), "")]
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
            sid = self.store.create_session(name, mode, url or kind, self._settings["model"])
            self._session_id = sid
            if sid == self._session_id:
                self._session_title = name
            config = self._config(live_stream=(mode == "live"))
            live = LiveSession(
                self.engine, config,
                lambda segment, sid=sid: self.segmentArrived.emit(sid, segment),
                self.statusArrived.emit,
                lambda error, cancelled, sid=sid: self.jobFinished.emit(sid, error, cancelled),
                on_partial=(
                    (lambda segment, sid=sid: self.partialArrived.emit(sid, segment))
                    if mode == "live" else None
                ),
                catch_up=(mode == "live"),
            )
            self._jobs[sid] = {"live": live, "mode": mode, "name": name, "hotkey": hotkey}
            try:
                def audio_error(error, sid=sid, live=live):
                    if str(error).startswith("Поток переподключается"):
                        self.logArrived.emit("warning", str(error))
                        return
                    live.failed = error
                    threading.Thread(target=live.stop, kwargs={"cancel": True}, daemon=True).start()
                capture_clock = {"started": False}

                def on_audio(audio, sid=sid, live=live, clock=capture_clock, mode=mode):
                    if mode == "live" and not clock["started"] and len(audio):
                        clock["started"] = True
                        self.captureStarted.emit(sid, time.monotonic() - len(audio) / SAMPLE_RATE)
                    live.feed(audio)

                def on_gap(dropped, sid=sid, live=live):
                    live.note_audio_gap(int(dropped))
                    self.logArrived.emit(
                        "warning", f"Захват Live пропустил {int(dropped)} блок(а) аудио."
                    )

                args = {
                    "on_audio": on_audio,
                    "on_level": self.levelArrived.emit,
                    "on_error": audio_error,
                    "on_gap": on_gap,
                }
                if url:
                    capture = StreamCapture(url, **args)
                else:
                    capture = open_live_capture(kind, self._settings, **args)
                # Device startup and WASAPI initialization must not block the QML thread.
                def start(live=live, capture=capture, sid=sid, config=config, mode=mode):
                    try:
                        if mode == "live":
                            # "Всё подряд" не платит за модель VAD: буфер
                            # остаётся на пороге энергии, и декодер получает
                            # любой звук, включая песни.
                            if config.live_sensitivity == "speech":
                                live.use_detector(open_voice_activity())
                            if self._prepared_model == config.model:
                                self.statusArrived.emit("model_ready")
                            elif self._model_preparing:
                                # Startup preparation owns model loading.  Do
                                # not race it with a second WhisperModel
                                # construction when Live is started early.
                                self._model_prepare_done.wait()
                                if self._model_prepare_error:
                                    raise RuntimeError(self._model_prepare_error)
                                self.statusArrived.emit("model_ready")
                            else:
                                self.engine.prepare(config, self.statusArrived.emit)
                        if live.cancel.is_set() or live.closed.is_set():
                            live.stop(cancel=True)
                            return
                        live.start(capture)
                    except Exception as exc:
                        self.jobFinished.emit(sid, str(exc), live.cancel.is_set())
                threading.Thread(target=start, daemon=True).start()
            except Exception as exc:
                self.jobFinished.emit(sid, str(exc), False)
        self.captionChanged.emit()
        self.liveStateChanged.emit()
        self.changed.emit()

    @Slot()
    def cancel(self):
        self._stop_hold()
        for job in tuple(self._jobs.values()):
            if job.get("live"):
                job["live"].cancel.set()
                threading.Thread(target=job["live"].stop, kwargs={"cancel": True}, daemon=True).start()
            else:
                job["cancel"].set()
        if self._jobs:
            self._state = "processing"
            self._status = "Останавливаем обработку…"
            if any(job.get("live") is not None for job in self._jobs.values()):
                self._cancel_release.start(1500)
            self.changed.emit()

    @Slot()
    def forceStop(self):
        """Stop now, without waiting for a cooperative native decoder."""

        if not self._jobs:
            return
        self._notice = (
            "Обработка остановлена принудительно. "
            "Нераспознанный хвост записи не сохранён."
        )
        self._record_log("warning", "Запрошена принудительная остановка.")
        self.cancel()
        # ``cancel`` gives normal cancellation up to 1.5 seconds for native
        # CTranslate2 code to return.  The explicit emergency action must not
        # keep the island and controls busy for that grace period.  The worker
        # still owns its native call, but its late jobFinished signal is ignored
        # because the session below is already closed in the controller.
        self._cancel_release.stop()
        self._release_cancelled_jobs()

    def _release_cancelled_jobs(self):
        """Unblock the UI when CTranslate2 has not returned after cancel."""

        leftover = [
            sid for sid, job in self._jobs.items()
            if (job.get("live") is not None and job["live"].cancel.is_set())
            or (job.get("cancel") is not None and job["cancel"].is_set())
        ]
        for sid in leftover:
            self._on_finished(sid, "", True)

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
        self._idle_model_release.stop()
        sid = self.store.create_session(media.name, "media", str(media), self._settings["model"])
        self._session_id = sid
        self._segments = []
        self.segmentsChanged.emit()
        self._edit_undo = []
        self._edit_redo = []
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
            self.segmentsChanged.emit()
        if job["mode"] == "live" and sid == self._session_id:
            segment_end = float(segment.get("end", 0.0))
            self._last_caption_at = time.monotonic()
            self._final_end = max(self._final_end, float(segment.get("audio_end", segment_end)))
            self._live_diagnostic = ""
            # The recogniser can finish an older phrase while the pipeline has
            # already shown a preview of the next one.  Persist every final,
            # but never make the visible caption jump backwards in time.
            replaces_preview = self._final_end >= self._partial_end
            if replaces_preview:
                self._confirmed_caption = str(segment.get("text", "")).strip()
                self._partial_caption = ""
                self._partial_end = 0.0
                self._caption_revision += 1
            self._live_latency_ms = max(
                0.0,
                (time.monotonic() - self._started - segment_end) * 1000,
            )
            if replaces_preview:
                self._live_phase = "listening" if self.recording else "stopping"
                self.captionChanged.emit()
            self.liveStateChanged.emit()
        if job["mode"] == "monitor":
            keywords = [w.strip() for w in str(self._settings["keywords"]).split(",") if w.strip()]
            matches = apply_keyword_cooldown(
                match_keywords(segment["text"], keywords),
                self._keyword_cool,
                time.monotonic(),
            )
            if matches:
                self._hits.insert(0, {**segment, "source": job["name"], "matches": ", ".join(matches), "session_id": sid})
                self._hits = self._hits[:200]
                self._record_log("warning", f"Совпадение в эфире {job['name']}: {', '.join(matches)}")
        elif sid == self._session_id:
            self._record_log("success", f"Добавлен сегмент {len(self._segments)}: {segment['text'][:80]}")
        self._status = "Слушаю" if self.recording else "Распознаём…"
        self.changed.emit()

    def _on_partial(self, sid, segment):
        """Accept a disposable Live preview without persisting it.

        The worker emits full phrase snapshots.  A future stabiliser may add a
        ``stable_text`` prefix; until then the complete snapshot is explicitly
        treated as provisional by the QML view.
        """

        job = self._jobs.get(sid)
        if job is None or job.get("mode") != "live" or sid != self._session_id:
            return
        text = str(segment.get("text", "")).strip()
        if not text:
            return
        self._last_caption_at = time.monotonic()
        end = float(segment.get("end", 0.0))
        if end < self._partial_end or end <= self._final_end:
            return
        stable = str(segment.get("stable_text", "")).strip()
        if stable and text.startswith(stable):
            self._confirmed_caption = stable
            self._partial_caption = text[len(stable):].strip()
        else:
            self._confirmed_caption = ""
            self._partial_caption = text
        self._caption_revision += 1
        self._live_diagnostic = ""
        self._live_phase = "speech"
        self._partial_end = end
        self._live_latency_ms = max(0.0, (time.monotonic() - self._started - end) * 1000)
        self.captionChanged.emit()
        self.liveStateChanged.emit()

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
            raw_text = " ".join(s["text"].strip() for s in session["segments"])
            text = self._apply_dictation_rules(raw_text)
            if text:
                QApplication.clipboard().setText(text)
                self._last_transcript = text
                changed = text != raw_text
                self._notice = "Текст скопирован в буфер обмена." + (
                    " Применены ваши локальные правила." if changed else ""
                )
                if self._settings["auto_paste"] and job.get("hotkey"):
                    QTimer.singleShot(250, self._paste)
        if not self._jobs:
            self._state = "idle"
            self._level = 0
            self._input_state = self.inputState
            self.levelChanged.emit()
            if job["mode"] == "live":
                self._partial_caption = ""
                self._partial_end = 0.0
                self._live_phase = "error" if error else "idle"
                self._caption_revision += 1
                self.captionChanged.emit()
                self.liveStateChanged.emit()
            self._status = "Остановлено" if cancelled else "Ошибка обработки" if error else "Готово · история сохранена"
            if not error:
                self._record_log("success", self._status)
            self._arm_idle_model_release()
        self.refreshHistory(self._query)
        self.changed.emit()
        if self._closing and not self._jobs:
            self.shutdownReady.emit()

    def _paste(self):
        inserted = self.desktop.paste()
        if inserted:
            self._notice = "Текст вставлен и сохранён в буфере."
        else:
            shortcut = str(self._settings.get("paste_last_hotkey") or "Shift+Alt+Z")
            self._notice = (
                f"Текст в буфере. Нажмите Ctrl+V в нужном поле или {shortcut}, "
                "чтобы вставить последний текст."
            )
        self.changed.emit()

    @Slot()
    def pasteLastTranscript(self):
        text = self._last_transcript
        if not text:
            self._notice = "Пока нет расшифровки для вставки."
            self.changed.emit()
            return
        QApplication.clipboard().setText(text)
        self.desktop.remember_target()
        if self.desktop.paste():
            self._notice = "Последний текст вставлен. Он также в буфере."
        else:
            self._notice = "Текст в буфере. Нажмите Ctrl+V в нужном поле."
        self._record_log("success", "Запрошена вставка последнего текста.")
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
            self.segmentsChanged.emit()
            self._edit_undo = []
            self._edit_redo = []
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
            before = next((item["text"] for item in self._segments if item["id"] == segment_id), None)
            if before is None or before == text:
                return
            self.store.update_segment(self._session_id, segment_id, text)
            self._segments = self.store.get_session(self._session_id)["segments"]
            self.segmentsChanged.emit()
            self._edit_undo.append((segment_id, before, text))
            self._edit_undo = self._edit_undo[-100:]
            self._edit_redo = []
            self._record_log("info", f"Изменён сегмент {segment_id}.")
            self.changed.emit()

    def _apply_edit(self, change, use_after):
        segment_id, before, after = change
        value = after if use_after else before
        self.store.update_segment(self._session_id, segment_id, value)
        self._segments = self.store.get_session(self._session_id)["segments"]
        self.segmentsChanged.emit()

    @Slot()
    def undoEdit(self):
        if not self._session_id or not self._edit_undo:
            return
        change = self._edit_undo.pop()
        self._apply_edit(change, False)
        self._edit_redo.append(change)
        self._record_log("info", "Отменена правка сегмента.")
        self.changed.emit()

    @Slot()
    def redoEdit(self):
        if not self._session_id or not self._edit_redo:
            return
        change = self._edit_redo.pop()
        self._apply_edit(change, True)
        self._edit_undo.append(change)
        self._record_log("info", "Повторена правка сегмента.")
        self.changed.emit()

    @Slot(str)
    def exportFile(self, format):
        if not self._segments or format not in ("txt", "srt", "vtt", "json"):
            return
        path, _ = QFileDialog.getSaveFileName(None, "Сохранить расшифровку", f"transcript.{format}",
                                             f"{format.upper()} (*.{format})")
        if path:
            try:
                segments = regroup_for_subtitles(self._segments) if format in ("srt", "vtt") else self._segments
                Path(path).write_text(export_transcript(segments, format), encoding="utf-8")
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
