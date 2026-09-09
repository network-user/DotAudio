from __future__ import annotations

import inspect
import os
import re
import threading
import time
import wave
from dataclasses import replace
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
    play_pcm,
    playback_device_for_loopback,
    source_for_mode,
)
from dotaudio.desktop import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, Hotkey
from dotaudio.engine import DownloadCancelled, Engine, RecognitionConfig
from dotaudio.karaoke import export_ass, render_video
from dotaudio.karaoke_align import align_words, compute_peaks, decode_file
from dotaudio.karaoke_edit import apply_word, clamp_row, set_word_text, sync_words_to_text
from dotaudio.monitor_clips import PcmRing, extract_match_clip
from dotaudio.pipeline import (
    LIVE_SPEECH_THRESHOLD,
    SAMPLE_RATE,
    LiveSession,
    open_voice_activity,
    preload_voice_activity,
)
from dotaudio.speaker_labels import (
    default_speaker_label,
    is_default_speaker_label,
    speaker_label_for_kind,
)
from dotaudio.storage import Store
from dotaudio.transcripts import (
    apply_keyword_cooldown,
    blend_fragments,
    continues_sentence,
    export_transcript,
    join_fragments,
    match_keywords,
    regroup_for_subtitles,
    sentence_open,
    split_caption_window,
    text_after_prefix,
)
from dotaudio.vosk_engine import VoskEngine
from dotaudio.watch_folder import WatchFolder

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
    "caption_overlay": False, "caption_size": "md", "caption_contrast": "normal",
    "caption_position": "bottom", "caption_x": -1, "caption_y": -1,
    "caption_screen": -1, "caption_autohide": False, "caption_locked": True,
    "reduce_motion": False,
    "live_sensitivity": "speech",
    "live_greedy_finals": False,
    # Живой движок распознавания. Whisper по умолчанию: на замерах этого
    # проекта он даёт WER 8% против 52% у vosk на той же записи, а vosk -
    # необязательный пакет, которого на чистой установке может не быть.
    # "vosk" остаётся явным выбором для очень слабого CPU (docs/STT_METHODS.md).
    "live_engine": "whisper",
    # Размер vosk-модели для Live. "small" - vosk-model-small-ru-0.22 (~44 МБ),
    # "big" - vosk-model-ru-0.42 (~1,8 ГБ, точнее, но тяжелее).
    "vosk_size": "small",
    # Оконная «зал» Live при запуске записи Live: превращать остров в окно
    # автоматически (live_auto_window) и как показывать внутри текст.
    "live_auto_window": True,
    # Таймкод рядом с каждой сказанной фразой в Live-потоке.
    "live_show_times": True,
    "live_locked": False,
    "live_size": "standard",
    "dictate_hotkey": "Ctrl+Alt+Space", "island_hotkey": "Ctrl+Alt+O",
    "paste_last_hotkey": "Shift+Alt+Z", "dictate_hold": False,
    "quit_hotkey": "Ctrl+Alt+X",
    "cancel_hotkey": "Escape",
    "watch_folder": "",
    "watch_folder_enabled": False,
    "history_semantic": True,
    # Движок определения голосов на странице «Транскрибация». "nemo" -
    # нативный рантайм NVIDIA NeMo с моделью Sortformer: он размечает
    # дорожку по времени и потому умеет резать фразу по смене голоса.
    # "ecapa" - прежний путь через SpeechBrain: одна метка на фразу.
    # "off" не грузит ничего. Ни один из движков не входит в базовую
    # установку, и интерфейс показывает, как поставить выбранный.
    "diarize_engine": "nemo",
    # Локальный ассистент. Пустая модель означает «ещё не выбрана»: тогда
    # страница предлагает ту, что подходит этому устройству.
    "assistant_model": "",
    # "auto" отдаёт предпочтение уже запущенному Ollama, если нужная модель
    # есть у него: она уже в памяти, второй копии в нашем процессе не нужно.
    "assistant_runtime": "auto",
    # Kept in local settings so terminology and snippets never leave the PC.
    "dictionary": [], "snippets": [],
    # Баннер про GPU: скрывается по кнопке или после успешной настройки.
    "gpu_hint_dismissed": False,
    # Мастер первого запуска: опрос железа, брифинг и фоновая подготовка.
    "setup_completed": False,
}

# Подписи движков голосов для интерфейса и журнала.
DIARIZE_ENGINES = {
    "off": "Не определять",
    "nemo": "NVIDIA NeMo",
    "ecapa": "Быстрый (ECAPA)",
}

LIVE_SETTINGS = {
    "caption_overlay", "caption_size", "caption_contrast",
    "caption_position", "caption_x", "caption_y", "caption_screen",
    "caption_autohide", "caption_locked", "reduce_motion",
    "island_opacity", "island_snap",
    # Выбор модели ассистента к записи не относится: его можно менять и во
    # время записи, загрузка модели всё равно отдельное действие.
    "assistant_model", "assistant_runtime",
}

# vosk-модели, доступные для живого распознавания, по ключу выбора размера.
# Значения - имена, которые понимает vosk (Model(model_name=...)), размер
# на диске и короткая подпись для интерфейса. Подробнее в docs/STT_METHODS.md.
VOSK_MODEL_BY_SIZE = {
    "small": {
        "name": "vosk-model-small-ru-0.22",
        "download_mb": 44,
        "label": "Малая (vosk)",
        "detail": "Лёгкая русская модель ~44 МБ, для слабого CPU",
    },
    "big": {
        "name": "vosk-model-ru-0.42",
        "download_mb": 1860,
        "label": "Большая (vosk)",
        "detail": "Точная русская модель ~1,8 ГБ, подойдёт не каждому CPU",
    },
}

LIVE_ENGINE_LABELS = {"whisper": "Whisper", "vosk": "Vosk"}
HOTKEY_OPTIONS = {
    "Ctrl+Alt+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x20),
    "Ctrl+Shift+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x20),
    "Ctrl+Win+Space": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x20),
    "Ctrl+Alt+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x4F),
    "Ctrl+Shift+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x4F),
    "Ctrl+Win+O": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x4F),
    "Shift+Alt+Z": Hotkey(MOD_NOREPEAT | MOD_SHIFT | MOD_ALT, 0x5A),
    "Ctrl+Alt+V": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x56),
    "Ctrl+Shift+V": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x56),
}

# Discord-style mic check: listen a few seconds, then play the sample back.
MIC_CHECK_SECONDS = 2.5

# Переназначаемые комбинации аварийного выхода. Не пересекаются с действиями
# из HOTKEY_OPTIONS, чтобы merge в Desktop не ругался на дубликаты.
QUIT_HOTKEY_OPTIONS = {
    "Ctrl+Alt+X": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x58),
    "Ctrl+Alt+C": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x43),
    "Ctrl+Shift+X": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x58),
    "Ctrl+Win+X": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_WIN, 0x58),
    "Ctrl+Alt+Q": Hotkey(MOD_NOREPEAT | MOD_CONTROL | MOD_ALT, 0x51),
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


def parse_hotkey(value: str) -> Hotkey | None:
    """Разбор свободной комбинации вроде ``Ctrl+Shift+A`` или ``Escape``."""

    if not value or not isinstance(value, str):
        return None
    mods = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
            "win": MOD_WIN, "cmd": MOD_WIN}
    special = {"space": 0x20, "escape": 0x1B, "esc": 0x1B}
    mod = 0
    key_code: int | None = None
    for raw in value.replace("+", " ").replace("_", " ").split():
        token = raw.strip()
        if not token:
            continue
        low = token.casefold()
        if low in mods:
            mod |= mods[low]
            continue
        if key_code is not None:
            return None
        if low in special:
            key_code = special[low]
            continue
        if len(token) != 1 or not token.isalnum():
            return None
        key_code = ord(token.upper())
    if key_code is None:
        return None
    if mod == 0 and key_code != 0x1B:
        return None
    return Hotkey(MOD_NOREPEAT | mod, key_code)


def resolve_hotkey(value: str) -> Hotkey | None:
    """Пресет из каталога или свободный разбор строки."""

    name = str(value or "").strip()
    if not name:
        return None
    return (
        HOTKEY_OPTIONS.get(name)
        or QUIT_HOTKEY_OPTIONS.get(name)
        or parse_hotkey(name)
    )


def hotkey_id(value: str) -> str:
    """Нормализованный вид комбинации для хранения и отображения."""

    parts = [p.casefold() for p in value.split("+") if p.strip()]
    parts.sort(key=lambda p: {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}.get(p, 4))
    caps = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    out = [caps.get(p, p) for p in parts]
    if out and len(out[-1]) == 1 and out[-1].isalnum():
        out[-1] = out[-1].upper()
    return "+".join(out)


def live_engine_label(method: str, model: str = "", vosk_size: str = "") -> str:
    """Человекочитаемая подпись активного движка/модели для Live.

    Используется в статусной строке Live и на острове, чтобы было видно,
    какая именно модель сейчас слушает. ``vosk_size``: малая большая.
    """
    way = str(method or "whisper")
    if way == "vosk":
        size = "малая" if str(vosk_size or "small") == "small" else "большая"
        return f"Vosk · {size} RU"
    return f"Whisper · {str(model or 'по умолчанию')}"


def hardware_summary(*, refresh: bool = False) -> dict:
    """Фактическая сводка устройства для страницы моделей и настроек."""

    from dotaudio.cuda_runtime import compute_advice
    from dotaudio.hardware import probe

    profile = probe(refresh=refresh)
    summary = profile.as_dict()
    summary.update(compute_advice(profile))
    return summary


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
    # Surface-класс: 4 потока целиком под small уже тесны для Live.
    if threads and threads <= 4 and cuda == 0 and spec["load"] >= 3:
        return {"state": "slow", "note": "Мало потоков CPU: берите «Быстро» (base)"}
    return {"state": "ok", "note": "Подходит этому устройству"}


def recommended_model(hardware: dict) -> str:
    """Модель по умолчанию под это устройство (см. ``adapt.plan_whisper``)."""

    from dotaudio.adapt import recommended_whisper

    return recommended_whisper(hardware)


class Controller(QObject):
    # ``changed`` - общее уведомление «пересчитать интерфейс». Оно дорогое:
    # по нему перечитываются настройки, журнал, списки устройств и карточки
    # моделей. Часто меняющиеся строки вынесены в отдельные сигналы, чтобы
    # секундный таймер и каждая распознанная фраза не двигали весь UI.
    # ``changed`` по-прежнему подразумевает и их: связи ставятся в __init__.
    changed = Signal()
    statusChanged = Signal()
    elapsedChanged = Signal()
    logsChanged = Signal()
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
    realignReady = Signal(object)
    mediaPeaksReady = Signal(object)
    mediaPeaksChanged = Signal()
    shutdownReady = Signal()
    transcribeChanged = Signal()
    transcribeStatus = Signal(str)
    # Тик прогресса ASR/диаризации: только GUI-поток обновляет _trans_state.
    transcribeTick = Signal(object)
    # Успешная транскрибация записана в историю: GUI обновляет списки.
    transcriptPersisted = Signal(str)
    # Открыть ассистента с уже сохранённой записью транскрибации.
    openAssistantWithRecord = Signal(str)
    diarizeProbed = Signal("QVariantMap")
    gpuSetupProgress = Signal("QVariantMap")
    gpuSetupFinished = Signal("QVariantMap")
    hardwareArrived = Signal(object)

    def __init__(self, data_dir: Path, desktop):
        super().__init__()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(data_dir / "history.db")
        self.desktop = desktop
        self.engine = Engine()
        # vosk-движок для живых субтитров создаётся лениво при первом запуске
        # Live с выбранным размером и кешируется между сессиями.
        self._vosk_engine: VoskEngine | None = None
        self._vosk_size: str = ""
        self._settings = {**DEFAULTS, **self.store.get_settings()}
        saved_bindings = {
            "dictate": resolve_hotkey(str(self._settings["dictate_hotkey"])),
            "island": resolve_hotkey(str(self._settings["island_hotkey"])),
            "paste_last": resolve_hotkey(str(self._settings["paste_last_hotkey"])),
        }
        cancel_combo = resolve_hotkey(str(self._settings.get("cancel_hotkey") or "Escape"))
        if cancel_combo is not None:
            saved_bindings["cancel"] = cancel_combo
        if (
            all(saved_bindings.get(key) for key in ("dictate", "island", "paste_last"))
            and len({(item.modifiers, item.key) for item in saved_bindings.values()})
            == len(saved_bindings)
        ):
            self.desktop.set_hotkeys(saved_bindings)
        # Сохранённая комбинация выхода побеждает значение по умолчанию, которым
        # Desktop собрался на старте. Отложить на один тик: контроллер ещё не
        # успел повесить нужные QTimer-сигналы.
        if self.desktop.available and str(self._settings.get("quit_hotkey")) != "Ctrl+Alt+X":
            QTimer.singleShot(0, self._apply_quit_hotkey)
        self._page, self._state = "live", "idle"
        self._status = "Готов к работе"
        self._notice = ""
        self._level = 0.0
        self._last_signal_at = 0.0
        self._last_caption_at = 0.0
        self._input_state = "Ожидает запуска"
        self._segments, self._history, self._hits, self._devices = [], [], [], []
        self._partial_caption = ""
        # Полный черновик от пайплайна; на экран кладётся окно после split.
        self._partial_source = ""
        self._preview_stable = ""
        self._partial_end = 0.0
        self._final_end = 0.0
        self._confirmed_caption = ""
        # Последняя фраза Live ещё не закончила предложение: она читается в
        # живой строке вместе с черновиком, а не отдельной строкой истории.
        self._open_phrase = False
        # Последнее законченное предложение - для острова и зала, где нет
        # колонки истории: оно остаётся на экране до следующей речи или паузы.
        self._settled_caption = ""
        self._caption_revision = 0
        self._live_phase = "idle"
        self._live_latency_ms = 0.0
        self._live_diagnostic = ""
        self._capture_started_at = None
        self._session_id, self._media_url, self._query = "", "", ""
        self._pending_seek_ms = -1
        self._session_title = ""
        self._session_mode = ""
        self._jobs = {}
        # progress: -1 = неизвестно (анимация indeterminate), 0..1 = доля
        # готового прохода. engine.transcribe не отдаёт проценты по сегментам,
        # поэтому во время работы держим -1 и не выдумываем цифры.
        self._trans_state = {
            "phase": "idle", "stage": "", "file": "", "path": "",
            "error": "", "speakers": [], "diarization": False,
            "engine": "", "engineNote": "", "duration": 0.0,
            "segments": [], "sessionId": "", "progress": 0.0,
        }
        self._trans_cancel = threading.Event()
        # sessionId с воркера до доставки QueuedConnection от transcribeTick.
        self._trans_result_session_id = ""
        # Опрос рантайма NeMo - запуск процесса, поэтому он делается один раз
        # в фоне и кешируется. Пустой словарь значит «ещё не проверяли».
        self._diarize_probe: dict = {}
        self._diarize_probing = False
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
        self._aligning = False
        self._last_transcript = ""
        self._hold_active = False
        self._keyword_cool: dict[str, float] = {}
        self._prepare_cancel = threading.Event()
        self._model_prepare_done = threading.Event()
        self._prepared_model = ""
        self._model_prepare_error = ""
        # Фоновый прогрев (и повтор после смены модели) включается только из
        # app.main: unit-тесты не должны скачивать Whisper при setSetting.
        self._warmup_enabled = False
        self._model_library = [Engine.disk_status(name) for name in ("tiny", "base", "small", "medium", "large-v3", "turbo")]
        # Сводка железа приехает фоном: импорт ctranslate2 для проверки CUDA
        # стоит сотни миллисекунд и не должен задерживать первый кадр окна.
        self._hardware = {
            "threads": os.cpu_count() or 0,
            "ram_gb": None,
            "cuda_devices": 0,
            "compute_label": "",
            "computeAdvice": "",
            "computeHint": "",
            "computeAction": "",
            "nvidiaPresent": False,
            "cudaReady": False,
            "manualSteps": [],
            "installCommand": "",
            "helpUrl": "",
        }
        self._recommended_model = recommended_model(self._hardware)
        self._gpu_setup = {
            "phase": "idle",
            "percent": 0.0,
            "message": "",
            "busy": False,
            "error": "",
            "restartRequired": False,
        }
        self._gpu_setup_cancel = threading.Event()
        threading.Thread(target=self._probe_hardware, daemon=True, name="hardware-probe").start()
        # Each entry is a batch of (segment_id, before, after) snapshots.
        self._edit_undo: list[list[tuple[int, dict, dict]]] = []
        self._edit_redo: list[list[tuple[int, dict, dict]]] = []
        self._media_peaks: list[float] = []
        self._media_peaks_duration = 0.0
        self._media_peaks_token = 0
        # Общий сигнал остаётся надмножеством точечных: код, который уже
        # сообщал об изменении через changed, продолжает работать как прежде.
        self.changed.connect(self.statusChanged)
        self.changed.connect(self.elapsedChanged)
        self.changed.connect(self.logsChanged)
        self.changed.connect(self.captionChanged)
        self.changed.connect(self.liveStateChanged)
        self.segmentArrived.connect(self._on_segment)
        self.partialArrived.connect(self._on_partial)
        self.jobFinished.connect(self._on_finished)
        self.transcriptPersisted.connect(self._on_transcript_persisted)
        self.transcribeTick.connect(self._on_transcribe_tick)
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
        self.realignReady.connect(self._on_realign_ready)
        self.mediaPeaksReady.connect(self._on_media_peaks_ready)
        self.diarizeProbed.connect(self._on_diarize_probed)
        self.gpuSetupProgress.connect(self._on_gpu_setup_progress)
        self.gpuSetupFinished.connect(self._on_gpu_setup_finished)
        self.hardwareArrived.connect(self._on_hardware_arrived)
        desktop.dictate.connect(self.hotkeyRecord)
        desktop.island.connect(self.islandRequested)
        desktop.paste_last.connect(self.pasteLastTranscript)
        desktop.cancel_requested.connect(self.cancel)
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
        self._data_dir = Path(data_dir)
        self._watch_queue: list[str] = []
        self._pcm_rings: dict[str, PcmRing] = {}
        self._watch = WatchFolder(None, self._on_watch_file, poll_seconds=2.0)
        self.refreshHistory("")
        self._hits = self.store.list_keyword_events(limit=200)
        self.refreshDevices()
        self.refreshOutputs()
        self.refreshLoopbacks()
        self._sync_watch_folder()
        self._record_log("system", "DotAudio запущен. Выберите модель или начните работу.")
        recoverable = self.store.list_recoverable_sessions()
        if recoverable:
            self._record_log(
                "warning",
                f"Найдено прерванных сессий: {len(recoverable)}. Откройте историю для правки.",
            )

    @Property(str, notify=changed)
    def page(self): return self._page

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property(str, notify=changed)
    def notice(self): return self._notice

    @Property(str, notify=elapsedChanged)
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

    @Property("QVariantList", notify=logsChanged)
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

        try:
            summary = hardware_summary(refresh=True)
        except Exception:
            summary = {
                "threads": os.cpu_count() or 0,
                "ram_gb": None,
                "cuda_devices": 0,
                "compute_label": "Процессор (CPU)",
                "computeAdvice": "cpu_only",
                "computeHint": "Не удалось опросить устройство.",
                "computeAction": "",
                "nvidiaPresent": False,
                "cudaReady": False,
                "manualSteps": [],
                "installCommand": "",
                "helpUrl": "",
            }
        try:
            self.hardwareArrived.emit(summary)
        except RuntimeError:
            return

    def _on_hardware_arrived(self, summary) -> None:
        self._hardware = dict(summary or {})
        self._recommended_model = recommended_model(self._hardware)
        self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def gpuSetup(self):
        return self._gpu_setup

    @Property(bool, notify=changed)
    def showGpuHint(self):
        """Баннер первого запуска / рекомендации GPU."""

        if bool(self._settings.get("gpu_hint_dismissed")):
            return False
        if self._gpu_setup.get("busy"):
            return True
        advice = str(self._hardware.get("computeAdvice") or "")
        return advice in {"ready", "needs_runtime"}

    @Property(str, notify=changed)
    def gpuHintTitle(self):
        advice = str(self._hardware.get("computeAdvice") or "")
        name = str(self._hardware.get("gpuLabel") or self._hardware.get("gpuName") or "NVIDIA")
        if advice == "needs_runtime":
            return f"Найдена {name}"
        if advice == "ready":
            return f"Видеокарта готова · {name}"
        return "Ускорение на видеокарте"

    @Property(str, notify=changed)
    def gpuHintBody(self):
        if self._gpu_setup.get("busy"):
            return str(self._gpu_setup.get("message") or "Настраиваем GPU…")
        hint = str(self._hardware.get("computeHint") or "")
        if hint:
            return hint
        return "Whisper может работать быстрее на CUDA."

    @Slot()
    def dismissGpuHint(self):
        self._settings["gpu_hint_dismissed"] = True
        self.store.save_settings(self._settings)
        self.changed.emit()

    @Slot(str)
    def selectComputeDevice(self, device):
        """Выбор Авто / CPU / GPU. GPU запускает полную настройку."""

        value = str(device or "")
        if value not in ("auto", "cpu", "cuda"):
            return
        if value == "cuda":
            self.setupGpu()
            return
        self.setSetting("device", value)

    @Slot()
    def setupGpu(self):
        """Скачать CUDA runtime при необходимости, включить GPU и прогреть модель."""

        if self._jobs or self._model_preparing or self._gpu_setup.get("busy"):
            self._notice = "Дождитесь окончания текущей операции, затем настройте GPU."
            self.changed.emit()
            return
        self._gpu_setup_cancel = threading.Event()
        self._gpu_setup = {
            "phase": "check",
            "percent": 0.0,
            "message": "Проверяем видеокарту…",
            "busy": True,
            "error": "",
            "restartRequired": False,
        }
        self._record_log("info", "Настройка GPU для Whisper начата.")
        self.changed.emit()

        def run():
            from dotaudio.cuda_runtime import setup_whisper_cuda
            from dotaudio.hardware import reset_cache

            try:
                def progress(info):
                    # Runtime install - первая половина; подготовка модели - вторая.
                    phase = str(info.get("phase") or "")
                    raw = float(info.get("percent") or 0.0)
                    if phase in {"check", "runtime", "register"}:
                        scaled = min(55.0, raw * 0.55)
                    else:
                        scaled = 55.0 + min(45.0, raw * 0.45)
                    payload = {
                        "phase": phase or "runtime",
                        "percent": scaled,
                        "message": str(info.get("message") or ""),
                        "busy": True,
                        "error": "",
                        "restartRequired": False,
                    }
                    self.gpuSetupProgress.emit(payload)

                result = setup_whisper_cuda(progress, self._gpu_setup_cancel)
                reset_cache()
                summary = hardware_summary(refresh=True)
                self.hardwareArrived.emit(summary)
                if not result.get("ok"):
                    self.gpuSetupFinished.emit(
                        {
                            "ok": False,
                            "message": str(result.get("message") or "GPU недоступна"),
                            "restartRequired": bool(result.get("restart_required")),
                            "prepareModel": False,
                        }
                    )
                    return
                self.gpuSetupFinished.emit(
                    {
                        "ok": True,
                        "message": str(result.get("message") or "CUDA готова"),
                        "restartRequired": False,
                        "prepareModel": True,
                    }
                )
            except Exception as exc:
                self.gpuSetupFinished.emit(
                    {
                        "ok": False,
                        "message": str(exc),
                        "restartRequired": False,
                        "prepareModel": False,
                    }
                )

        threading.Thread(target=run, name="dotaudio-gpu-setup", daemon=True).start()

    def _on_gpu_setup_progress(self, info) -> None:
        payload = dict(info or {})
        if "busy" not in payload:
            payload["busy"] = True
        self._gpu_setup = payload
        self.changed.emit()

    def _on_gpu_setup_finished(self, result) -> None:
        payload = dict(result or {})
        ok = bool(payload.get("ok"))
        message = str(payload.get("message") or "")
        restart = bool(payload.get("restartRequired"))
        self._gpu_setup = {
            "phase": "ready" if ok else "error",
            "percent": 100.0 if ok else float(self._gpu_setup.get("percent") or 0.0),
            "message": message,
            "busy": False,
            "error": "" if ok else message,
            "restartRequired": restart,
        }
        if ok:
            self._settings["device"] = "cuda"
            self._settings["gpu_hint_dismissed"] = True
            # На GPU с запасом VRAM предлагаем более точную модель, но не
            # переключаем large без спроса.
            recommended = recommended_model(self._hardware)
            current = str(self._settings.get("model") or "small")
            rank = ("tiny", "base", "small", "medium", "turbo", "large-v3")
            if current in rank and recommended in rank and rank.index(current) < rank.index(recommended):
                if recommended == "medium" and current in ("tiny", "base", "small"):
                    self._settings["model"] = recommended
                    self._settings["profile"] = "balanced"
                    self._model_state = {
                        "phase": "idle",
                        "model": recommended,
                        "message": f"Для GPU выбрана модель {recommended}",
                    }
                    self._record_log("info", f"Для GPU выбрана модель {recommended}.")
            self.store.save_settings(self._settings)
            self._record_log("success", message or "GPU готова.")
            self._notice = ""
            self.changed.emit()
            if payload.get("prepareModel"):
                # Прогрев модели на CUDA с тем же прогресс-баром загрузки файлов.
                self._continue_gpu_model_prepare()
            return
        self._notice = message
        self._record_log("error", message)
        self.changed.emit()

    def _continue_gpu_model_prepare(self) -> None:
        """После CUDA — скачать/прогреть выбранную Whisper-модель на видеокарте."""

        if self._jobs or self._model_preparing:
            return
        self._idle_model_release.stop()
        config = self._config(live_stream=True)
        # Явно CUDA: настройка только что подтвердила runtime.
        config = replace(config, device="cuda")
        model = config.model
        self._prepare_cancel = threading.Event()
        self._model_prepare_done.clear()
        self._prepared_model = ""
        self._model_prepare_error = ""
        self._model_preparing = True
        self._gpu_setup = {
            "phase": "model",
            "percent": 55.0,
            "message": f"Готовим модель {model} на видеокарте…",
            "busy": True,
            "error": "",
            "restartRequired": False,
        }
        self._model_state = {
            "phase": "downloading",
            "model": model,
            "message": "Проверяем кэш и готовим модель на GPU…",
        }
        self._record_log("info", f"Подготовка модели {model} на CUDA.")
        self.changed.emit()

        def prepare():
            try:
                self.modelProgressArrived.emit(model, "Загружаем или проверяем файлы модели…")

                def progress(info):
                    raw = float((info or {}).get("percent") or 0.0)
                    self.modelDownloadProgress.emit(model, info)
                    self.gpuSetupProgress.emit(
                        {
                            "phase": "model",
                            "percent": 55.0 + min(45.0, raw * 0.45),
                            "message": str((info or {}).get("message") or f"Модель {model}…"),
                            "busy": True,
                            "error": "",
                            "restartRequired": False,
                        }
                    )

                device = self.engine.prepare(
                    config,
                    lambda status: self.statusArrived.emit(status),
                    progress,
                )
                if self._prepare_cancel.is_set():
                    self.modelFinished.emit(model, "", "Подготовка отменена")
                    self.gpuSetupFinished.emit(
                        {
                            "ok": False,
                            "message": "Подготовка модели отменена",
                            "restartRequired": False,
                            "prepareModel": False,
                        }
                    )
                    return
            except Exception as exc:
                self.modelFinished.emit(model, "", str(exc))
                self.gpuSetupFinished.emit(
                    {
                        "ok": False,
                        "message": str(exc),
                        "restartRequired": False,
                        "prepareModel": False,
                    }
                )
            else:
                self.modelFinished.emit(model, device, "")
                self.gpuSetupFinished.emit(
                    {
                        "ok": True,
                        "message": f"Модель {model} готова на {device}",
                        "restartRequired": False,
                        "prepareModel": False,
                    }
                )

        threading.Thread(target=prepare, name="dotaudio-gpu-model", daemon=True).start()

    @Slot()
    def cancelGpuSetup(self):
        if not self._gpu_setup.get("busy"):
            return
        self._gpu_setup_cancel.set()
        self._prepare_cancel.set()
        self._gpu_setup = {
            **self._gpu_setup,
            "message": "Отменяем настройку GPU…",
        }
        self.changed.emit()

    @Slot()
    def copyCudaInstallCommand(self):
        command = str(self._hardware.get("installCommand") or "")
        if not command:
            from dotaudio.cuda_runtime import install_command

            command = install_command()
        QApplication.clipboard().setText(command)
        self._notice = "Команда установки CUDA скопирована."
        self.changed.emit()

    @Slot()
    def openCudaHelp(self):
        url = str(self._hardware.get("helpUrl") or "https://developer.nvidia.com/cuda-downloads")
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    @Property(str, notify=changed)
    def mediaUrl(self): return self._media_url

    @Property(int, notify=changed)
    def pendingSeekMs(self): return self._pending_seek_ms

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

    @Property("QVariantList", notify=mediaPeaksChanged)
    def mediaPeaks(self):
        """Precomputed peak envelope for the media timeline (worker-filled)."""
        return list(self._media_peaks)

    @Property(float, notify=mediaPeaksChanged)
    def mediaPeaksDuration(self):
        return float(self._media_peaks_duration)

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

    @Property(str, notify=segmentsChanged)
    def text(self): return " ".join(s["text"].strip() for s in self._segments)

    @Property(str, notify=captionChanged)
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

    @Property(str, notify=liveStateChanged)
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

    @Property(bool, notify=segmentsChanged)
    def liveOpenPhrase(self):
        """Последний сегмент - незаконченное предложение, показанное в живой строке."""

        return bool(self._open_phrase and self._segments)

    @Property(str, notify=captionChanged)
    def settledCaption(self):
        """Последнее законченное предложение Live, пока не началась новая речь."""

        return self._settled_caption

    @Property(int, notify=captionChanged)
    def captionRevision(self): return self._caption_revision

    @Property(bool, constant=True)
    def hotkeysAvailable(self): return self.desktop.available

    @Property(str, notify=changed)
    def lastTranscript(self): return self._last_transcript

    @Slot(str)
    def selectPage(self, page):
        if page in (
            "dictation", "live", "media", "monitor", "models",
            "history", "settings", "transcript", "assistant",
        ):
            self._page = page
            self._record_log("info", f"Открыт раздел: {page}")
            self.changed.emit()

    def setting(self, name, default=None):
        """Одно значение настроек для соседних контроллеров.

        Настройки лежат одним словарём: писать их в обход контроллера нельзя,
        иначе следующее сохранение затрёт чужую правку.
        """

        return self._settings.get(name, DEFAULTS.get(name, default))

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
            "live_engine": ("vosk", "whisper"),
            "vosk_size": ("small", "big"),
            "diarize_engine": tuple(DIARIZE_ENGINES),
            "profile": ("fast", "balanced", "quality"),
            "caption_size": ("sm", "md", "lg"),
            "caption_contrast": ("normal", "high"),
            "caption_position": ("top", "bottom", "floating"),
            "live_size": ("small", "standard", "wide", "tall"),
            "assistant_runtime": ("auto", "llama_cpp", "llama_inplace", "ollama"),
        }
        if name in choices and value not in choices[name]:
            return
        if name in (
            "caption_overlay", "auto_paste", "dictate_hold", "island_click_through",
            "island_snap", "caption_autohide", "caption_locked", "reduce_motion",
            "live_auto_window", "live_show_times", "live_locked",
            "live_greedy_finals", "gpu_hint_dismissed", "setup_completed",
            "watch_folder_enabled", "history_semantic",
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
            # Не затирать medium (и другие модели того же профиля): мастер
            # выставляет profile=balanced + model=medium, а UI «Баланс» раньше
            # всегда писал small.
            from dotaudio.adapt import PROFILE_FOR_MODEL

            current = str(self._settings.get("model") or "")
            if PROFILE_FOR_MODEL.get(current) != value:
                self._settings["model"] = MODEL_BY_PROFILE[value]
        if source_changed:
            # Проверка относится ровно к тому устройству, которое было открыто.
            # После смены входа старый «готово» нельзя оставлять рядом с кнопкой
            # запуска - пользователь мог выбрать совершенно другой источник.
            self._device_test = {"phase": "idle", "message": "", "level": 0.0}
        self.store.save_settings(self._settings)
        if name == "quit_hotkey":
            self._apply_quit_hotkey()
        if name in ("watch_folder", "watch_folder_enabled"):
            self._sync_watch_folder()
        if name == "history_semantic":
            self.refreshHistory(self._query)
        if name == "model":
            self._model_state = {
                "phase": "idle",
                "model": str(value),
                "message": "Модель выбрана и ждёт подготовки",
            }
            self._record_log("info", f"Выбрана модель: {value}")
        elif name in ("device", "backend", "source", "live_source", "language", "task", "live_sensitivity"):
            self._record_log("info", f"Настройка {name}: {value}")
        # Смена Live-движка или модели - сразу греем в фоне, чтобы кнопка
        # Live не ждала загрузку в момент нажатия. Только в живом приложении.
        if name in ("model", "device", "backend", "profile", "live_engine", "vosk_size", "language", "task"):
            self._prepared_model = ""
            if self._warmup_enabled:
                QTimer.singleShot(0, self.prepareSelectedModel)
        # Настройки ассистента читает только его контроллер: общий changed
        # иначе пересчитывает весь мост (устройства, остров, настройки).
        if name not in ("assistant_model", "assistant_runtime"):
            self.changed.emit()

    @Slot()
    def enableModelWarmup(self):
        """Разрешить фоновую подготовку моделей после старта UI."""

        self._warmup_enabled = True

    def _apply_quit_hotkey(self) -> None:
        """Re-register the exit combo after it changes in Settings."""

        quit_name = str(self._settings.get("quit_hotkey") or "Ctrl+Alt+X")
        combo = resolve_hotkey(quit_name)
        base = {
            "dictate": resolve_hotkey(str(self._settings.get("dictate_hotkey"))),
            "island": resolve_hotkey(str(self._settings.get("island_hotkey"))),
            "paste_last": resolve_hotkey(str(self._settings.get("paste_last_hotkey"))),
        }
        cancel = resolve_hotkey(str(self._settings.get("cancel_hotkey") or "Escape"))
        if cancel is not None:
            base["cancel"] = cancel
        if combo is None or None in base.values() or not self.desktop.available:
            if combo is None:
                self._notice = f"Не понимаю комбинацию «{quit_name}». Формат: Ctrl+Alt+A."
                self.changed.emit()
            return
        if not self.desktop.set_hotkeys({**base, "quit": combo}):
            self._notice = "Комбинация выхода занята. Оставлена прежняя."
            self.changed.emit()
            return
        # Нормализуем строку, чтобы интерфейс и перезапуск видели один вид.
        if quit_name != hotkey_id(quit_name):
            self._settings["quit_hotkey"] = hotkey_id(quit_name)
            self.store.save_settings(self._settings)

    @Slot(str)
    def setQuitHotkey(self, text) -> None:
        """Установить свободную комбинацию выхода с клиента (строкой)."""

        raw = str(text or "").strip()
        if not raw:
            self._notice = "Введите комбинацию, например Ctrl+Alt+G."
            self.changed.emit()
            return
        combo = parse_hotkey(raw)
        if combo is None:
            self._notice = f"Не понимаю «{raw}». Пример: Ctrl+Alt+G."
            self.changed.emit()
            return
        self._settings["quit_hotkey"] = raw
        self.store.save_settings(self._settings)
        self._apply_quit_hotkey()

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
            values["live_greedy_finals"] = bool(self._settings.get("live_greedy_finals", False))
        if str(values.get("backend") or "local") == "remote":
            values["initial_prompt"] = ""
        else:
            values["initial_prompt"] = "; ".join(
                str(entry.get("term", "")).strip()
                for entry in self.dictionary
                if isinstance(entry, dict) and str(entry.get("term", "")).strip()
            )
        return RecognitionConfig(
            **values, media_mode=bool(media_mode), live_stream=bool(live_stream)
        )

    def _vosk_engine_for(self, size: str) -> VoskEngine:
        """Возвращает общий vosk-движок, пересоздавая при смене размера.

        Один объект на процесс обеспечивает кеширование модели vosk между
        Live-сессиями (подобно кешу одной модели у faster-whisper).
        """
        size = size if size in ("small", "big") else "small"
        if self._vosk_engine is None or self._vosk_size != size:
            self._vosk_engine = VoskEngine(model_size=size)
            self._vosk_size = size
        return self._vosk_engine

    @Property(str, notify=changed)
    def liveModelText(self):
        """Какая модель/движок сейчас стоит для Live - видно в статусе/острове."""
        way = str(self._settings.get("live_engine") or "whisper")
        if way == "vosk":
            return live_engine_label("vosk", "", str(self._settings.get("vosk_size") or "small"))
        return live_engine_label("whisper", str(self._settings.get("model") or ""))

    def _apply_hotkey_bindings(self, dictate: str, island: str, paste_last: str) -> bool:
        bindings = {
            "dictate": resolve_hotkey(str(dictate)),
            "island": resolve_hotkey(str(island)),
            "paste_last": resolve_hotkey(str(paste_last)),
        }
        cancel = resolve_hotkey(str(self._settings.get("cancel_hotkey") or "Escape"))
        if cancel is not None:
            bindings["cancel"] = cancel
        if None in (bindings.get("dictate"), bindings.get("island"), bindings.get("paste_last")) or \
                len({(item.modifiers, item.key) for item in bindings.values()}) != len(bindings):
            self._notice = "Выберите разные понятные комбинации для диктовки, острова и вставки."
            self.changed.emit()
            return False
        if not self.desktop.set_hotkeys(bindings):
            self._notice = "Комбинация занята другой программой. Прежние hotkey сохранены."
            self.changed.emit()
            return False
        self._settings["dictate_hotkey"] = str(dictate)
        self._settings["island_hotkey"] = str(island)
        self._settings["paste_last_hotkey"] = str(paste_last)
        self.store.save_settings(self._settings)
        self._notice = "Горячие клавиши обновлены."
        self._record_log("success", "Горячие клавиши переназначены.")
        self.changed.emit()
        return True

    @Slot(str, str)
    def setHotkeys(self, dictate, island):
        if self._jobs:
            return
        paste_last = str(self._settings.get("paste_last_hotkey") or "Shift+Alt+Z")
        self._apply_hotkey_bindings(str(dictate), str(island), paste_last)

    @Slot(str)
    def setPasteHotkey(self, paste_last):
        if self._jobs:
            return
        self._apply_hotkey_bindings(
            str(self._settings.get("dictate_hotkey") or "Ctrl+Alt+Space"),
            str(self._settings.get("island_hotkey") or "Ctrl+Alt+O"),
            str(paste_last),
        )

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
                self.statusChanged.emit()
                self.logsChanged.emit()
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

    @Slot()
    def refreshWindowChrome(self):
        """Re-apply dark native title bar after the HWND is recreated."""
        if self._window is None:
            return
        try:
            from dotaudio.branding import apply_dark_titlebar

            apply_dark_titlebar(int(self._window.winId()))
        except (RuntimeError, TypeError, ValueError):
            return

    @Slot(int, int, int, int, float)
    def setWindowMask(self, x, y, w, h, radius):
        """Hit-test only the island chrome; transparent canvas padding passes clicks."""
        if self._window is None or w <= 0 or h <= 0:
            return
        try:
            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QPainterPath, QRegion

            path = QPainterPath()
            path.addRoundedRect(
                QRectF(float(x), float(y), float(w), float(h)),
                float(radius),
                float(radius),
            )
            region = QRegion(path.toFillPolygon().toPolygon())
            self._window.setMask(region)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return

    @Slot()
    def clearWindowMask(self):
        if self._window is None:
            return
        try:
            from PySide6.QtGui import QRegion

            self._window.setMask(QRegion())
        except (RuntimeError, AttributeError):
            return

    @Slot(result=bool)
    def primaryButtonDown(self) -> bool:
        return bool(self.desktop.primary_button_down())

    @Slot(result="QVariant")
    def cursorScreenPos(self):
        """Cursor in the same coordinate space as QWindow x/y."""
        from PySide6.QtGui import QCursor

        point = QCursor.pos()
        return {"x": float(point.x()), "y": float(point.y())}

    @Slot(result=bool)
    def beginWindowDrag(self) -> bool:
        """Native drag for the main shell window. Returns after mouse release."""
        if self._window is None:
            return False
        try:
            return bool(self.desktop.begin_window_drag(int(self._window.winId())))
        except (RuntimeError, TypeError, ValueError):
            return False

    @Slot("QVariant", result=bool)
    def beginWindowDragId(self, window_id) -> bool:
        """Native drag for a secondary window (caption overlay)."""
        try:
            return bool(self.desktop.begin_window_drag(int(window_id)))
        except (RuntimeError, TypeError, ValueError):
            return False

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
        if self._device_test.get("phase") == "playing":
            return
        self._device_test = {
            "phase": "listening",
            "message": "Получаем уровень с микрофона. Запись не сохраняется.",
            "level": max(0.0, min(1.0, float(level))),
        }
        self.changed.emit()

    def _on_device_test_finished(self, phase, message):
        # «playing» - промежуточный этап Discord-проверки микрофона:
        # запись уже есть, идёт прослушивание, новый тест ещё нельзя.
        self._testing_device = phase == "playing"
        self._device_test = {"phase": phase, "message": message, "level": 0.0}
        if phase != "playing":
            self._record_log("success" if phase == "ready" else "error", message)
        self.changed.emit()

    @Slot()
    def testMicrophone(self):
        """Discord-style mic check: meter while speaking, then hear yourself."""

        if self._jobs or self._testing_device:
            return
        self._testing_device = True
        self._device_test = {
            "phase": "starting",
            "message": "Говорите в микрофон несколько секунд…",
            "level": 0.0,
        }
        self._record_log("info", "Запущена проверка микрофона с прослушиванием.")
        self.changed.emit()

        settings = dict(self._settings)

        def test():
            errors: list[str] = []
            levels: list[float] = []
            chunks: list = []

            def on_level(level: float) -> None:
                levels.append(float(level))
                self.deviceTestLevelArrived.emit(level)

            def on_audio(audio) -> None:
                chunks.append(audio.copy())

            capture = open_live_capture(
                "microphone",
                settings,
                on_audio=on_audio,
                on_level=on_level,
                on_error=errors.append,
            )
            try:
                capture.start()
                started = capture.running
                deadline = time.monotonic() + MIC_CHECK_SECONDS
                while capture.running and time.monotonic() < deadline:
                    time.sleep(0.05)
            except Exception as exc:
                errors.append(str(exc))
                started = False
            finally:
                capture.stop()

            if errors:
                self.deviceTestFinished.emit("error", errors[-1])
                return
            if not started:
                self.deviceTestFinished.emit("error", "Микрофон остановился до завершения проверки.")
                return
            peak = max(levels, default=0.0)
            if peak < 0.001 or not chunks:
                self.deviceTestFinished.emit(
                    "silent",
                    "Микрофон открыт, но сигнал нулевой. Выберите другое устройство "
                    "или разрешите доступ в Параметры Windows → Конфиденциальность → Микрофон.",
                )
                return

            import numpy as np

            sample = np.concatenate(chunks).astype(np.float32, copy=False)
            raw_out = str(settings.get("output_device") or "")
            out_device = int(raw_out) if raw_out.isdigit() else None
            self.deviceTestLevelArrived.emit(0.0)
            try:
                # Сообщение до play: иначе UI не успеет сменить подпись.
                self.deviceTestFinished.emit(
                    "playing",
                    f"Воспроизводим сказанное (пик {peak:.3f})…",
                )
                play_pcm(sample, device=out_device, samplerate=SAMPLE_RATE)
            except Exception as exc:
                self.deviceTestFinished.emit(
                    "ready",
                    f"Микрофон отвечает (пик {peak:.3f}), но прослушать не удалось: {exc}",
                )
                return
            self.deviceTestFinished.emit(
                "ready",
                f"Микрофон работает. Пик {peak:.3f}. Если голос слышен криво - выберите другое устройство.",
            )

        threading.Thread(target=test, name="dotaudio-mic-check", daemon=True).start()

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
            # Раз в секунду меняется только счётчик времени. Общий changed
            # заставлял интерфейс перечитывать настройки, журнал и списки
            # устройств во время записи - каждую секунду, без причины.
            self.elapsedChanged.emit()

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
            (self.displayCaption or self._settled_caption or self._open_phrase)
            and now - max(self._last_signal_at, self._capture_started_at) >= LIVE_CLEAR_SILENCE_SECONDS
        ):
            # A pause this long ends the sentence, whatever punctuation the
            # decoder left on it: the phrase moves into the history column.
            self._close_open_phrase()
            self._confirmed_caption = ""
            self._partial_caption = ""
            self._partial_source = ""
            self._preview_stable = ""
            self._settled_caption = ""
            self._partial_end = 0.0
            self._caption_revision += 1
            self.captionChanged.emit()
            self.liveStateChanged.emit()

    def _acquire_asr_vram(self, config: RecognitionConfig | None = None) -> None:
        """Заранее вытеснить LLM, если Whisper пойдёт на CUDA."""

        config = config or self._config(live_stream=True)
        if config.device == "cpu":
            return
        from dotaudio.vram_arbiter import get_arbiter

        get_arbiter().acquire("asr")

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
        way = str(self._settings.get("live_engine") or "whisper")
        # Silero грузим всегда в фоне: даже при смене движка кнопка Live
        # не должна платить сотни миллисекунд за ONNX.
        preload_needed = str(self._settings.get("live_sensitivity") or "speech") == "speech"

        if way == "vosk":
            size = str(self._settings.get("vosk_size") or "small")
            engine = self._vosk_engine_for(size)
            model = engine.model_name if getattr(engine, "model_name", None) else size
            self._begin_engine_prepare(
                model_label=str(model),
                prepare_fn=lambda on_status, on_progress: engine.prepare(
                    self._config(live_stream=True), on_status, on_progress,
                    cancel=self._prepare_cancel,
                ),
                preload_vad=preload_needed,
            )
            return

        # Prepare the model for the first live window as well as for the final
        # decode.  This warms the decoder in the worker before the user starts
        # speaking, so the first caption does not pay the cold-start cost.
        config = self._config(live_stream=True)
        model = config.model
        if (
            self._prepared_model == model
            and self.engine.has_cached_model(model, config.device)
        ):
            if preload_needed:
                threading.Thread(
                    target=preload_voice_activity,
                    name="dotaudio-vad-preload",
                    daemon=True,
                ).start()
            return
        self._acquire_asr_vram(config)
        self._begin_engine_prepare(
            model_label=model,
            prepare_fn=lambda on_status, on_progress: self.engine.prepare(
                config, on_status, on_progress, cancel=self._prepare_cancel,
            ),
            preload_vad=preload_needed,
        )

    def _begin_engine_prepare(self, model_label: str, prepare_fn, preload_vad: bool) -> None:
        """Общий фон подготовки Whisper/Vosk + опциональный VAD."""

        if self._model_preparing:
            return
        self._prepare_cancel = threading.Event()
        self._model_prepare_done.clear()
        self._prepared_model = ""
        self._model_prepare_error = ""
        self._model_preparing = True
        self._model_state = {
            "phase": "downloading",
            "model": model_label,
            "message": "Проверяем кэш и готовим модель…",
        }
        self._record_log("info", f"Подготовка модели {model_label} начата.")
        self.changed.emit()

        def prepare():
            try:
                if preload_vad:
                    preload_voice_activity()
                self.modelProgressArrived.emit(
                    model_label, "Загружаем или проверяем файлы модели…"
                )
                if self._prepare_cancel.is_set():
                    self.modelFinished.emit(model_label, "", "Подготовка отменена")
                    return

                def progress(info):
                    self.modelDownloadProgress.emit(model_label, info)

                device = prepare_fn(
                    lambda status: self.statusArrived.emit(status),
                    progress,
                )
                if self._prepare_cancel.is_set():
                    self.modelFinished.emit(model_label, "", "Подготовка отменена")
                    return
            except DownloadCancelled:
                self.modelFinished.emit(model_label, "", "Подготовка отменена")
            except Exception as exc:
                self.modelFinished.emit(model_label, "", str(exc))
            else:
                self.modelFinished.emit(model_label, device, "")

        threading.Thread(target=prepare, name="dotaudio-model-prepare", daemon=True).start()

    def _ensure_live_model_loading(self, config: RecognitionConfig, vosk: bool, engine) -> None:
        """Не блокируя захват: догрузить модель, если старт обогнал прогрев."""

        if vosk:
            if self._model_preparing:
                return
            if self._prepared_model:
                return
            self._begin_engine_prepare(
                model_label=getattr(engine, "model_name", "vosk") or "vosk",
                prepare_fn=lambda on_status, on_progress: engine.prepare(
                    config, on_status, on_progress
                ),
                preload_vad=False,
            )
            return
        if self._prepared_model == config.model:
            return
        if self._model_preparing:
            return
        if self.engine.has_cached_model(config.model, config.device):
            self._prepared_model = config.model
            return
        self._begin_engine_prepare(
            model_label=config.model,
            prepare_fn=lambda on_status, on_progress: self.engine.prepare(
                config, on_status, on_progress
            ),
            preload_vad=False,
        )

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
        self._partial_source = ""
        self._preview_stable = ""
        self._partial_end = 0.0
        self._final_end = 0.0
        self._confirmed_caption = ""
        self._open_phrase = False
        self._settled_caption = ""
        self._caption_revision += 1
        self._edit_undo = []
        self._edit_redo = []
        self._media_url = ""
        self._clear_media_peaks()
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
            live_engine = str(self._settings.get("live_engine") or "whisper")
            if live_engine != "vosk":
                self._acquire_asr_vram()
            # Единое Live-окно: отдельное «окно зала» (CaptionOverlay) не
            # дублирует текст поверх, а открывается только кнопкой-оверлеем
            # в самом окне, когда оно нужно отдельным экраном/подчисткой.
            self._live_phase = "starting"
            self._live_latency_ms = 0.0
            self._live_diagnostic = ""
            self._capture_started_at = None
        self._state = "recording"
        live_engine = str(self._settings.get("live_engine") or "whisper")
        if mode == "live":
            model_name = str(self._settings.get("model") or "")
            if live_engine != "vosk" and self._prepared_model == model_name and not self._model_preparing:
                self._status = "Слушаю…"
            elif self._model_preparing:
                self._status = "Открываем захват, модель ещё готовится…"
            else:
                self._status = "Готовим модель для Live…"
        else:
            self._status = "Слушаю · модель загрузится при первой фразе"
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
            config = self._config(live_stream=(mode == "live"))
            use_vosk = mode == "live" and live_engine == "vosk"
            vosk_size = str(self._settings.get("vosk_size") or "small")
            engine_now = (
                self._vosk_engine_for(vosk_size) if use_vosk else self.engine
            )
            # В истории сессии пишем не выбранную whisper-модель из profile, а
            # реально используемый движок/модель: так понятно, чем распознавали.
            if use_vosk:
                try:
                    model_tag = engine_now.model_name or self._settings["model"]
                except Exception:
                    model_tag = self._settings["model"]
            else:
                model_tag = self._settings["model"]
            sid = self.store.create_session(name, mode, url or kind, model_tag)
            self._session_id = sid
            if sid == self._session_id:
                self._session_title = name
            live = LiveSession(
                engine_now, config,
                lambda segment, sid=sid: self.segmentArrived.emit(sid, segment),
                self.statusArrived.emit,
                lambda error, cancelled, sid=sid: self.jobFinished.emit(sid, error, cancelled),
                on_partial=(
                    (lambda segment, sid=sid: self.partialArrived.emit(sid, segment))
                    if mode == "live" else None
                ),
                catch_up=(mode == "live"),
            )
            self._jobs[sid] = {"live": live, "mode": mode, "name": name, "hotkey": hotkey, "engine": engine_now, "vosk": use_vosk}
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
                    if mode == "monitor":
                        ring = self._pcm_rings.setdefault(sid, PcmRing(seconds=90.0))
                        ring.write(audio)
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
                # Модель и захват больше не сериализуем: раньше кнопка Live ждала
                # весь prepare (и Silero), и казалось, что она «не работает».
                def start(live=live, capture=capture, sid=sid, config=config, mode=mode, engine=engine_now, vosk=use_vosk):
                    try:
                        if mode == "live":
                            if config.live_sensitivity == "speech":
                                live.use_detector(open_voice_activity())
                            if self._prepared_model and (
                                vosk or self._prepared_model == config.model
                            ):
                                self.statusArrived.emit("model_ready")
                            else:
                                self.statusArrived.emit("loading_model")
                                self._ensure_live_model_loading(config, vosk, engine)
                            # Захват открываем сразу. Первый декод сам ждёт
                            # model_lock / inference_lock, если прогрев ещё идёт.
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
    def abortEmergency(self):
        """Abort every active job now and bring the UI back to idle.

        This is the exit path for Ctrl+C in the console and for the dedicated
        quit hotkey.  It stops capture and cancels native decoder work as fast
        as possible (the same semantics as the island force-stop), frees the
        model cache afterwards, and never waits for a slow decode to return
        before the process may close.  Workers are daemon threads, so a native
        call still running simply dies with the process.
        """

        self._closing = True
        if self._jobs:
            try:
                self.forceStop()
            except Exception:
                pass
        else:
            self._arm_idle_model_release()
        self._idle_model_release.stop()
        # forceStop() already closed the sessions; the model stays resident in
        # memory until the process exits, which on the emergency path happens
        # a moment later.
        self._model_preparing = False
        self._state = "idle"
        self._level = 0

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
        self._schedule_media_peaks(str(media.resolve()))
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
        job = self._jobs[sid]
        live_here = job["mode"] == "live" and sid == self._session_id
        if not (live_here and self._extends_open_phrase(sid, segment)):
            identifiers = self.store.append_segments(sid, [segment])
            if sid == self._session_id:
                self._segments = [*self._segments, {**segment, "id": identifiers[0]}]
                if live_here:
                    self._open_phrase = sentence_open(
                        str(segment.get("text", "")), bool(segment.get("cut"))
                    )
                self.segmentsChanged.emit()
        if live_here:
            if not self._open_phrase and self._segments:
                self._settled_caption = str(self._segments[-1].get("text", "")).strip()
            segment_end = float(segment.get("end", 0.0))
            self._last_caption_at = time.monotonic()
            self._final_end = max(self._final_end, float(segment.get("audio_end", segment_end)))
            self._live_diagnostic = ""
            # The recogniser can finish an older phrase while the pipeline has
            # already shown a preview of the next one.  Persist every final,
            # but never make the visible caption jump backwards in time: a
            # preview of newer sound stays after the sentence it continues.
            if self._partial_end <= self._final_end:
                self._partial_caption = ""
                self._partial_source = ""
                self._preview_stable = ""
                self._partial_end = 0.0
            self._refresh_live_caption()
            self._live_latency_ms = max(
                0.0,
                (time.monotonic() - self._started - segment_end) * 1000,
            )
            self._live_phase = (
                "speech" if self._partial_source
                else "listening" if self.recording
                else "stopping"
            )
            self.liveStateChanged.emit()
        if job["mode"] == "monitor":
            keywords = [w.strip() for w in str(self._settings["keywords"]).split(",") if w.strip()]
            matches = apply_keyword_cooldown(
                match_keywords(segment["text"], keywords),
                self._keyword_cool,
                time.monotonic(),
            )
            if matches:
                clip_path = ""
                ring = self._pcm_rings.get(sid)
                if ring is not None:
                    clip = extract_match_clip(
                        ring,
                        match_start=float(segment.get("start", 0.0)),
                        match_end=float(segment.get("end", 0.0)),
                        stream_end=float(ring.written_seconds),
                        out_dir=self._data_dir / "clips",
                        stem=f"{sid[:8]}_{int(float(segment.get('start', 0.0)))}",
                    )
                    clip_path = str(clip) if clip is not None else ""
                for keyword in matches:
                    self.store.save_keyword_event(
                        sid,
                        start=float(segment.get("start", 0.0)),
                        end=float(segment.get("end", 0.0)),
                        keyword=keyword,
                        text=str(segment.get("text", "")),
                        source=str(job["name"]),
                        clip_path=clip_path,
                    )
                hit = {
                    **segment,
                    "source": job["name"],
                    "matches": ", ".join(matches),
                    "session_id": sid,
                    "clip_path": clip_path,
                }
                self._hits.insert(0, hit)
                self._hits = self._hits[:200]
                self._record_log("warning", f"Совпадение в эфире {job['name']}: {', '.join(matches)}")
        elif sid == self._session_id:
            self._record_log("success", f"Добавлен сегмент {len(self._segments)}: {segment['text'][:80]}")
        self._status = "Слушаю" if self.recording else "Распознаём…"
        # Готовая фраза меняет строку состояния, журнал и подпись - но не
        # настройки, устройства и карточки моделей. При длинной речи общий
        # changed на каждой фразе перетряхивал весь интерфейс.
        self.statusChanged.emit()
        self.logsChanged.emit()
        self.captionChanged.emit()

    def _extends_open_phrase(self, sid, segment) -> bool:
        """Grow the unfinished sentence with this final instead of adding a row.

        Live cuts speech every few seconds so the caption stays quick; the
        pieces of one sentence come back as separate finals ("…в реальном",
        "времени.").  Read as rows they are scraps.  Joined in place they are
        the sentence, in history as well as on screen.
        """

        if not self._open_phrase or not self._segments:
            return False
        previous = self._segments[-1]
        text = str(segment.get("text", "")).strip()
        gap = float(segment.get("start", 0.0)) - float(previous.get("audio_end", previous.get("end", 0.0)))
        if not continues_sentence(
            str(previous.get("text", "")), bool(previous.get("cut")), text, gap
        ):
            return False
        joined = join_fragments(str(previous.get("text", "")), bool(previous.get("cut")), text)
        end = max(float(previous.get("end", 0.0)), float(segment.get("end", 0.0)))
        merged = {
            **previous,
            "end": end,
            "audio_end": max(
                float(previous.get("audio_end", 0.0)),
                float(segment.get("audio_end", segment.get("end", 0.0))),
            ),
            "text": joined,
            "cut": bool(segment.get("cut")),
        }
        self.store.extend_segment(sid, int(previous["id"]), end, joined)
        self._segments = [*self._segments[:-1], merged]
        self._open_phrase = sentence_open(joined, bool(segment.get("cut")))
        self.segmentsChanged.emit()
        return True

    def _refresh_live_caption(self):
        """Live row: LocalAgreement prefix as confirmed, remainder as draft."""

        draft = getattr(self, "_partial_source", "") or ""
        stable = getattr(self, "_preview_stable", "") or ""
        if stable and draft:
            agreed = stable
            rest = text_after_prefix(draft, stable)
            if self._open_phrase and self._segments:
                last = self._segments[-1]
                head, _ = blend_fragments(
                    str(last.get("text", "")), bool(last.get("cut")), agreed
                )
                confirmed, pending = head or agreed, rest
            else:
                confirmed, pending = agreed, rest
        elif self._open_phrase and self._segments:
            last = self._segments[-1]
            confirmed, pending = blend_fragments(
                str(last.get("text", "")), bool(last.get("cut")), draft
            )
        else:
            confirmed, pending = "", draft
        confirmed, pending = split_caption_window(confirmed, pending)
        self._confirmed_caption = confirmed
        self._partial_caption = pending
        self._caption_revision += 1
        self.captionChanged.emit()

    def _close_open_phrase(self):
        """Let the unfinished sentence stand as it is: the speaker stopped."""

        if not self._open_phrase:
            return
        self._open_phrase = False
        if self._segments:
            self._settled_caption = str(self._segments[-1].get("text", "")).strip()
        self.segmentsChanged.emit()

    def _on_partial(self, sid, segment):
        """Accept a disposable Live preview without persisting it.

        The worker emits full phrase snapshots.  On screen the snapshot follows
        the unfinished sentence from the finals before it, so the reader sees
        one sentence growing rather than a new scrap every few seconds.
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
        self._partial_source = text
        self._preview_stable = str(segment.get("stable_text", "")).strip()
        self._partial_end = end
        self._live_diagnostic = ""
        self._live_phase = "speech"
        self._live_latency_ms = max(0.0, (time.monotonic() - self._started - end) * 1000)
        self._refresh_live_caption()
        self.liveStateChanged.emit()

    def _on_finished(self, sid, error, cancelled):
        job = self._jobs.pop(sid, None)
        if job is None:
            return
        self.store.finish_session(sid, "error" if error else "cancelled" if cancelled else "completed")
        if not error and not cancelled:
            self._maybe_autotitle_session(sid)
        if error:
            self._notice = error
            self._record_log("error", error)
        empty_dictation = False
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
            else:
                # PasteTalk: silent cancel when nothing was said — no clipboard noise.
                empty_dictation = True
                self._notice = ""
                self._record_log("info", "Пустая диктовка: в буфер ничего не записано.")
        if not self._jobs:
            self._state = "idle"
            self._level = 0
            self._input_state = self.inputState
            self.levelChanged.emit()
            if job["mode"] == "live":
                self._close_open_phrase()
                self._confirmed_caption = ""
                self._partial_caption = ""
                self._partial_source = ""
                self._preview_stable = ""
                self._partial_end = 0.0
                self._live_phase = "error" if error else "idle"
                self._caption_revision += 1
                self.captionChanged.emit()
                self.liveStateChanged.emit()
            if empty_dictation:
                self._status = "Ничего не сказано"
            else:
                self._status = (
                    "Остановлено"
                    if cancelled
                    else "Ошибка обработки"
                    if error
                    else "Готово · история сохранена"
                )
            if not error and not empty_dictation:
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
        elif getattr(self.desktop, "last_paste_block", "") == "elevated":
            shortcut = str(self._settings.get("paste_last_hotkey") or "Shift+Alt+Z")
            self._notice = (
                "Целевое окно запущено от имени администратора — вставка "
                f"заблокирована системой. Текст в буфере: Ctrl+V или {shortcut}."
            )
        else:
            shortcut = str(self._settings.get("paste_last_hotkey") or "Shift+Alt+Z")
            self._notice = (
                f"Текст в буфере. Нажмите Ctrl+V в нужном поле или {shortcut}, "
                "чтобы вставить последний текст."
            )
        self.changed.emit()


    def _on_watch_file(self, path: Path) -> None:
        """Новый файл из watch-folder: очередь, чтобы не стартовать поверх busy."""

        target = str(Path(path))
        if target in self._watch_queue:
            return
        self._watch_queue.append(target)
        QTimer.singleShot(0, self._drain_watch_queue)

    def _drain_watch_queue(self) -> None:
        if self._jobs or self._state != "idle" or not self._watch_queue:
            if self._watch_queue and not self._jobs:
                QTimer.singleShot(1500, self._drain_watch_queue)
            return
        path = self._watch_queue.pop(0)
        self._record_log("info", f"Автоимпорт из папки: {path}")
        try:
            self.transcribePath(path)
        except Exception as exc:
            self._record_log("error", f"Автоимпорт не удался: {exc}")
        if self._watch_queue:
            QTimer.singleShot(1500, self._drain_watch_queue)

    def _sync_watch_folder(self) -> None:
        enabled = bool(self._settings.get("watch_folder_enabled"))
        folder = str(self._settings.get("watch_folder") or "").strip()
        if enabled and folder:
            self._watch.set_path(folder)
            self._watch.start()
        else:
            self._watch.set_path(None)
            self._watch.stop()

    @Slot()
    def chooseWatchFolder(self) -> None:
        path = QFileDialog.getExistingDirectory(None, "Папка автоимпорта медиа", "")
        if not path:
            return
        self._settings["watch_folder"] = path
        self._settings["watch_folder_enabled"] = True
        self.store.save_settings(self._settings)
        self._sync_watch_folder()
        self._notice = f"Следим за папкой: {path}"
        self.changed.emit()

    @Slot(bool)
    def setWatchFolderEnabled(self, enabled: bool) -> None:
        self._settings["watch_folder_enabled"] = bool(enabled)
        self.store.save_settings(self._settings)
        self._sync_watch_folder()
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
    def copyPhrase(self, text):
        """Скопировать одну сказанную фразу из живого потока."""

        value = " ".join(str(text or "").split())
        if not value:
            return
        QApplication.clipboard().setText(value)
        self._notice = "Фраза скопирована."
        self._record_log("success", "Фраза скопирована в буфер обмена.")
        self.changed.emit()

    @Slot(str)
    def refreshHistory(self, query):
        self._query = query
        semantic = bool(self._settings.get("history_semantic", True))
        self._history = self.store.search_sessions(
            query, semantic=semantic and bool(str(query or "").strip())
        )
        self.changed.emit()

    def _on_transcript_persisted(self, _session_id: str) -> None:
        """Обновить список истории после сохранения страницы «Транскрибация»."""

        self.refreshHistory(self._query)

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
            is_media = session["mode"] in ("media", "transcript")
            self._media_url = QUrl.fromLocalFile(source).toString() if is_media and Path(source).is_file() else ""
            if is_media and Path(source).is_file():
                self._schedule_media_peaks(source)
            else:
                self._clear_media_peaks()
            if is_media and source and not self._media_url:
                self._notice = "Исходный медиафайл не найден. Расшифровку всё ещё можно редактировать и экспортировать."
            if session["mode"] == "transcript":
                self._open_transcript_session(session)
            else:
                self._page = session["mode"] if session["mode"] in (
                    "dictation", "live", "media", "monitor"
                ) else "history"
            self._status = session["title"]
            self.changed.emit()

    @Slot(str, float)
    def openSessionAt(self, sid: str, seconds: float) -> None:
        """Открыть запись и перейти к нужному моменту в медиа или расшифровке."""

        session = self.store.get_session(str(sid or ""))
        if session is None:
            return
        self.openSession(sid)
        if self._session_id != sid:
            return
        self._page = "media" if self._media_url else "transcript"
        self._pending_seek_ms = max(0, int(float(seconds) * 1000))
        self.changed.emit()

    @Slot(float)
    def seekMediaTo(self, seconds: float) -> None:
        """Перемотать текущее медиа без смены записи."""

        if not self._media_url:
            return
        self._pending_seek_ms = max(0, int(float(seconds) * 1000))
        self.changed.emit()

    @Slot()
    def clearPendingSeek(self) -> None:
        if self._pending_seek_ms < 0:
            return
        self._pending_seek_ms = -1
        self.changed.emit()

    def _open_transcript_session(self, session: dict) -> None:
        """Восстановить страницу «Транскрибация» из сохранённой сессии."""

        source = str(session.get("source") or "")
        rows = []
        for segment in session.get("segments") or []:
            text, speaker = self._split_stored_segment(
                str(segment.get("text") or ""),
                segment.get("speaker"),
            )
            rows.append(
                {
                    "id": segment.get("id"),
                    "start": float(segment.get("start", 0.0)),
                    "end": float(segment.get("end", 0.0)),
                    "text": text,
                    "speaker": speaker,
                    "role": None,
                    "words": segment.get("words") or [],
                }
            )
        self._trans_state.update(
            {
                "phase": "done",
                "stage": "",
                "path": source if Path(source).is_file() else "",
                "file": session.get("title") or Path(source).name,
                "error": "",
                "speakers": [],
                "segments": rows,
                "diarization": any(row.get("speaker") for row in rows),
                "engine": "",
                "engineNote": "Открыто из истории",
                "duration": max((float(row.get("end", 0.0)) for row in rows), default=0.0),
                "sessionId": session.get("id") or "",
                "progress": 1.0,
            }
        )
        # Легенда говорящих из подписей в тексте, без ролей движка.
        legend: dict[str, dict] = {}
        for row in rows:
            label = str(row.get("speaker") or "").strip()
            if not label:
                continue
            entry = legend.setdefault(
                label,
                {"key": len(legend) + 1, "label": label, "count": 0, "seconds": 0.0},
            )
            entry["count"] += 1
            entry["seconds"] += max(
                0.0, float(row.get("end", 0.0)) - float(row.get("start", 0.0))
            )
            row["role"] = entry["key"]
        self._trans_state["speakers"] = [
            {**item, "seconds": round(item["seconds"], 1)}
            for item in sorted(legend.values(), key=lambda item: item["key"])
        ]
        self._page = "transcript"
        self.transcribeChanged.emit()

    @staticmethod
    def _split_stored_segment(text: str, speaker_field) -> tuple[str, str]:
        """Dual-read: колонка speaker, иначе legacy-префикс ``[Имя]`` в тексте."""

        body = str(text or "").strip()
        speaker = str(speaker_field or "").strip() if speaker_field is not None else ""
        if speaker:
            prefix = f"[{speaker}]"
            if body.startswith(prefix):
                body = body[len(prefix):].strip()
            return body, speaker
        if body.startswith("[") and "]" in body:
            label, rest = body[1:].split("]", 1)
            if label.strip():
                return rest.strip(), label.strip()
        return body, ""

    @Slot(str, str)
    def renameSession(self, sid, title):
        """Переименовать сессию в истории и на активной странице."""

        session_id = str(sid or "")
        if not session_id:
            return
        try:
            cleaned = self.store.rename_session(session_id, title)
        except ValueError:
            self._notice = "Заголовок не может быть пустым."
            self.changed.emit()
            return
        if self._session_id == session_id:
            self._session_title = cleaned
            self._status = cleaned
        if self._trans_state.get("sessionId") == session_id:
            self._trans_state["file"] = cleaned
            self.transcribeChanged.emit()
        self.refreshHistory(self._query)
        self.changed.emit()

    @Slot(int, str)
    def editSegment(self, segment_id, text):
        if self._session_id:
            before = next((item for item in self._segments if item["id"] == segment_id), None)
            if before is None or before["text"] == text:
                return
            snapshot = self._row_snapshot(before)
            after = sync_words_to_text(snapshot, text)
            self._apply_row_change(
                segment_id,
                snapshot,
                {**after, "id": segment_id},
                info=f"Изменён текст сегмента {segment_id}.",
            )

    def _row_snapshot(self, segment: dict) -> dict:
        """A reducible copy of everything a user edit may change."""
        return {
            "id": segment["id"],
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment["text"]),
            "words": [dict(w) for w in (segment.get("words") or [])],
        }

    def _apply_row_change(self, segment_id, before, after, *, info):
        """Persist a whole-row before/after pair and record it for undo."""
        after_id = after.pop("id", after.get("id", segment_id))
        self.store.update_segment_edit(self._session_id, segment_id, after)
        self._segments = self.store.get_session(self._session_id)["segments"]
        self.segmentsChanged.emit()
        self._edit_undo.append([(segment_id, before, {**after, "id": after_id})])
        self._edit_undo = self._edit_undo[-100:]
        self._edit_redo = []
        self._record_log("info", info)
        self.changed.emit()

    def _apply_edit_batch(self, batch, *, use_after: bool) -> None:
        for segment_id, before, after in (batch if use_after else reversed(batch)):
            value = after if use_after else before
            row = dict(value)
            row.pop("id", None)
            self.store.update_segment_edit(self._session_id, segment_id, row)
        self._segments = self.store.get_session(self._session_id)["segments"]
        self.segmentsChanged.emit()

    @Slot()
    def undoEdit(self):
        if not self._session_id or not self._edit_undo:
            return
        batch = self._edit_undo.pop()
        self._apply_edit_batch(batch, use_after=False)
        self._edit_redo.append(batch)
        self._record_log("info", "Отменена правка сегмента.")
        self.changed.emit()

    @Slot()
    def redoEdit(self):
        if not self._session_id or not self._edit_redo:
            return
        batch = self._edit_redo.pop()
        self._apply_edit_batch(batch, use_after=True)
        self._edit_undo.append(batch)
        self._record_log("info", "Повторена правка сегмента.")
        self.changed.emit()

    def _seg_row(self, segment_id):
        return next((item for item in self._segments if item["id"] == segment_id), None)

    @Slot(int, float, float)
    def setPhraseWindow(self, segment_id, start, end):
        """Move a phrase's time window (words keep their own edges)."""
        row = self._seg_row(segment_id)
        if row is None or not self._session_id:
            return
        adjusted = clamp_row(self._row_snapshot(row), start=start, end=end)
        notice = "Граница окна фразы выровнена по соседней." if adjusted.pop("clamped", False) else ""
        if row["start"] == adjusted["start"] and row["end"] == adjusted["end"]:
            return
        self._apply_row_change(
            segment_id,
            self._row_snapshot(row),
            {**adjusted, "id": segment_id},
            info=f"Изменены границы фразы {segment_id}.",
        )
        if notice:
            self._record_log("warning", notice)

    @Slot(int, int, str, float)
    def setWordEdge(self, segment_id, word_index, edge, seconds):
        """Move a word start or end, clamped to the phrase and its neighbours."""
        row = self._seg_row(segment_id)
        if row is None or not self._session_id:
            return
        if not row.get("words"):
            return
        words = row["words"]
        if word_index < 0 or word_index >= len(words) or edge not in ("start", "end"):
            return
        before = self._row_snapshot(row)
        changed = apply_word(before, word_index, edge, float(seconds))
        clamped = changed.pop("clamped", False)
        if not changed.pop("changed", False):
            return
        self._apply_row_change(
            segment_id,
            before,
            changed,
            info=f"Изменён таймкод слова {word_index + 1} в сегменте {segment_id}.",
        )
        if clamped:
            self._record_log("warning", "Таймкод ограничен соседним словом или окном фразы.")

    @Slot(int, int, str)
    def editWordText(self, segment_id, word_index, text):
        """Edit one word and keep the assembled phrase consistent for export."""
        row = self._seg_row(segment_id)
        if row is None or not self._session_id or not row.get("words"):
            return
        if word_index < 0 or word_index >= len(row["words"]):
            return
        before = self._row_snapshot(row)
        try:
            changed = set_word_text(before, word_index, text)
        except (ValueError, IndexError):
            return
        if changed.get("words", [{}])[word_index].get("text") == before["words"][word_index]["text"]:
            return
        if changed["text"] == before["text"] and not changed.get("words"):
            return
        self._apply_row_change(
            segment_id,
            before,
            changed,
            info=f"Изменён текст слова {word_index + 1} в сегменте {segment_id}.",
        )

    @Slot()
    def realignKaraoke(self):
        """Snap each media word toward the quiet of the actual audio.

        Whisper word timings on music drift.  This reruns no model: it decodes
        the media once to 16 k mono and nudges every word edge to the closest
        quiet moment.  Results persist row-by-row and re-emit ``segments``, so
        the editor, preview and ASS/MP4 export all follow the refined timing.
        """
        if self._aligning or self._rendering or self._jobs:
            return
        if not self._media_url:
            self._notice = "Сначала откройте аудио или видео."
            self.changed.emit()
            return
        source = QUrl(self._media_url).toLocalFile()
        if not source or not Path(source).is_file():
            self._notice = "Исходный медиафайл недоступен для выравнивания."
            self.changed.emit()
            return
        rows = [r for r in self._segments if (r.get("words") or [])]
        if not rows or not any(len(r["words"]) > 1 for r in rows):
            self._notice = "Пословная разметка не найдена: распознайте трек сначала."
            self.changed.emit()
            return
        self._aligning = True
        self._status = "Выравниваем слова к тишине аудио…"
        self.changed.emit()
        snapshot = [dict(r) for r in rows]

        def work():
            error = ""
            payload: list[dict] = []
            try:
                samples = decode_file(source)
                for row in snapshot:
                    words = align_words(row["words"], samples, 16000)
                    if words != row["words"]:
                        span_start = min(float(row["start"]), min(float(w["start"]) for w in words))
                        span_end = max(float(row["end"]), max(float(w["end"]) for w in words))
                        payload.append({
                            "id": row["id"],
                            "start": span_start,
                            "end": span_end,
                            "text": str(row["text"]),
                            "words": words,
                        })
            except Exception as exc:  # noqa: BLE001 - доставляем причину в UI
                error = str(exc)
            self.realignReady.emit({"error": error, "rows": payload})

        threading.Thread(target=work, name="dotaudio-karaoke-align", daemon=True).start()

    def _on_realign_ready(self, result):
        self._aligning = False
        error = str((result or {}).get("error") or "")
        if error:
            self._notice = f"Не удалось выровнять слова: {error}"
            self._status = "Ошибка выравнивания"
            self._record_log("error", self._notice)
        else:
            rows = list((result or {}).get("rows") or [])
            batch: list[tuple[int, dict, dict]] = []
            if self._session_id:
                for row in rows:
                    current = self._seg_row(row["id"])
                    if current is None:
                        continue
                    before = self._row_snapshot(current)
                    after = {
                        "id": row["id"],
                        "start": float(row["start"]),
                        "end": float(row["end"]),
                        "text": str(row["text"]),
                        "words": [dict(w) for w in (row.get("words") or [])],
                    }
                    self.store.update_segment_edit(self._session_id, row["id"], {
                        "start": after["start"],
                        "end": after["end"],
                        "text": after["text"],
                        "words": after["words"],
                    })
                    batch.append((row["id"], before, after))
                if batch:
                    self._segments = self.store.get_session(self._session_id)["segments"]
                    self.segmentsChanged.emit()
                    self._edit_undo.append(batch)
                    self._edit_undo = self._edit_undo[-100:]
                    self._edit_redo = []
            self._notice = "Слова выровнены к тишине." if batch else "Границы слов уже на тишине."
            self._status = "Готово"
            self._record_log("success", self._notice)
        self.changed.emit()

    def _clear_media_peaks(self) -> None:
        self._media_peaks_token += 1
        self._media_peaks = []
        self._media_peaks_duration = 0.0
        self.mediaPeaksChanged.emit()

    def _schedule_media_peaks(self, path: str) -> None:
        """Decode peaks in a worker; never from a Q_PROPERTY getter."""
        media = Path(path)
        if not media.is_file():
            self._clear_media_peaks()
            return
        self._media_peaks_token += 1
        token = self._media_peaks_token
        source = str(media.resolve())

        def work():
            error = ""
            peaks: list[float] = []
            duration = 0.0
            try:
                samples = decode_file(source)
                peaks, duration = compute_peaks(samples, 16000, buckets=480)
            except Exception as exc:  # noqa: BLE001 - surface in UI notice
                error = str(exc)
            self.mediaPeaksReady.emit({
                "token": token,
                "peaks": peaks,
                "duration": duration,
                "error": error,
            })

        threading.Thread(target=work, name="dotaudio-media-peaks", daemon=True).start()

    def _on_media_peaks_ready(self, result) -> None:
        payload = result or {}
        if int(payload.get("token") or 0) != self._media_peaks_token:
            return
        self._media_peaks = [float(v) for v in (payload.get("peaks") or [])]
        self._media_peaks_duration = float(payload.get("duration") or 0.0)
        error = str(payload.get("error") or "")
        if error:
            self._record_log("warning", f"Волна медиа не построена: {error}")
        self.mediaPeaksChanged.emit()

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
            phrase_only = any(
                str(seg.get("text", "")).strip() and not (seg.get("words") or [])
                for seg in self._segments
            )
            if phrase_only:
                self._notice = (
                    "ASS сохранён: фразы без слов записаны пофразово "
                    "(без karaoke \\k). Для пословного режима нужна разметка слов."
                )
            else:
                self._notice = (
                    "Караоке-субтитры сохранены. Их можно открыть в FFmpeg, "
                    "OBS или видеоредакторе."
                )
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

    # ---- Отдельный режим «Транскрибация»: файл + говорящие, локально.
    # Аудио всегда распознаётся локальным faster-whisper, никогда не уходит
    # на сервер; только необязательные веса речи скачиваются один раз в
    # локальный кеш, если включено определение голосов.

    @Property("QVariantMap", notify=transcribeChanged)
    def transcribeState(self): return self._trans_state

    @Property(str, notify=transcribeChanged)
    def transcribeMediaUrl(self) -> str:
        """file:// URL выбранного медиа для QML MediaPlayer.

        Без проверки существования: путь уже задан pick/clear/историей.
        Пустая строка, если файла ещё нет.
        """

        path = str(self._trans_state.get("path") or "")
        if not path:
            return ""
        return QUrl.fromLocalFile(path).toString()

    @Property("QVariantList", notify=transcribeChanged)
    def transcribeSegments(self): return self._trans_state["segments"]

    @Property("QVariantList", notify=transcribeChanged)
    def diarizeEngines(self):
        return [{"key": key, "label": label} for key, label in DIARIZE_ENGINES.items()]

    @Property("QVariantMap", notify=transcribeChanged)
    def diarizeStatus(self):
        """Готовность выбранного движка голосов и что делать, если его нет."""

        engine = str(self._settings.get("diarize_engine") or "off")
        label = DIARIZE_ENGINES.get(engine, DIARIZE_ENGINES["off"])
        base = {
            "engine": engine, "label": label, "ready": False,
            "checking": False, "message": "", "install": "", "hint": "",
        }
        if engine == "off":
            return {**base, "ready": True,
                    "message": "Голоса не определяются: только текст с таймкодами."}
        if engine == "ecapa":
            # find_spec не импортирует torch: проверка не должна стоить
            # секунд загрузки тяжёлого стека на каждое открытие страницы.
            from importlib.util import find_spec

            ready = find_spec("speechbrain") is not None
            return {
                **base,
                "ready": ready,
                "message": (
                    "SpeechBrain ECAPA готов · одна метка на фразу"
                    if ready
                    else "Не установлен SpeechBrain: движок голосов недоступен."
                ),
                "install": "" if ready else 'pip install -e ".[diarize]"',
                "hint": "" if ready else "Выполните команду в папке проекта и перезапустите приложение.",
            }
        if self._diarize_probing:
            return {**base, "checking": True, "message": "Проверяем рантайм NVIDIA NeMo…"}
        report = self._diarize_probe
        if not report:
            return {**base, "message": "Готовность NeMo ещё не проверена."}
        if report.get("available"):
            return {**base, "ready": True, "message": str(report.get("message") or "NeMo готов")}
        from dotaudio.nemo_diarize import install_command

        hints = {
            "not_installed": "Установите рантайм и нажмите «Проверить снова». "
                             "Модель весом около 140 МБ скачается при первом запуске.",
            "no_diarization": "Переустановите рантайм профилем, включающим диаризацию.",
        }
        reason = str(report.get("reason") or "")
        return {
            **base,
            "message": str(report.get("message") or "Рантайм NeMo недоступен."),
            "install": install_command() if reason == "not_installed" else "",
            "hint": hints.get(reason, "Нажмите «Проверить снова» после устранения причины."),
        }

    @Slot()
    def refreshDiarizeStatus(self):
        """Опросить рантайм NeMo в фоне: это запуск процесса, не импорт."""

        if self._diarize_probing or str(self._settings.get("diarize_engine")) != "nemo":
            return
        self._diarize_probing = True
        self.transcribeChanged.emit()

        def run():
            from dotaudio.nemo_diarize import probe

            try:
                report = probe()
            except Exception as exc:  # noqa: BLE001
                report = {"available": False, "reason": "broken",
                          "message": f"Не удалось проверить NeMo: {exc}"}
            self.diarizeProbed.emit(report)

        threading.Thread(target=run, name="dotaudio-nemo-probe", daemon=True).start()

    def _on_diarize_probed(self, report):
        self._diarize_probing = False
        self._diarize_probe = dict(report)
        self.transcribeChanged.emit()

    @Slot()
    def copyDiarizeInstall(self):
        command = str(self.diarizeStatus.get("install") or "")
        if not command:
            return
        QApplication.clipboard().setText(command)
        self.transcribeStatus.emit("Команда установки скопирована в буфер обмена.")

    @Slot(str)
    def setDiarizeEngine(self, engine):
        self.setSetting("diarize_engine", str(engine))
        self._diarize_probe = {}
        self.refreshDiarizeStatus()
        self.transcribeChanged.emit()

    @Slot()
    def openTranscriptInAssistant(self):
        """После транскрибации сразу открыть ассистента с этой записью."""

        session_id = str(self._trans_state.get("sessionId") or "")
        if not session_id:
            self.transcribeStatus.emit(
                "Сначала выполните транскрибацию - запись появится в истории."
            )
            return
        if self.store.get_session(session_id) is None:
            self.transcribeStatus.emit("Сохранённая запись не найдена.")
            return
        self.selectPage("assistant")
        self.openAssistantWithRecord.emit(session_id)

    @Slot()
    def pickTranscriptFile(self):
        """Раздельный выбор файла именно для транскрибации."""
        if self._jobs:
            return
        path, _ = QFileDialog.getOpenFileName(
            None, "Открыть аудио или видео для транскрибации", "",
            "Медиа (*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.mp4 *.mkv *.webm *.mov *.aac)")
        if not path:
            return
        self.transcribeStatus.emit("Файл выбран. Нажмите «Транскрибировать».")
        self._trans_state.update({"phase": "idle", "stage": "", "path": path,
                                  "file": str(Path(path).name), "error": "", "speakers": [],
                                  "segments": [], "engine": "", "engineNote": "", "duration": 0.0,
                                  "sessionId": "", "progress": 0.0,
                                  "diarization": False})
        self.transcribeChanged.emit()

    @Slot(str)
    def pickTranscriptFilename(self, path):
        """QML drag-and-drop либо путь из поля."""
        path = str(path)
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        media = Path(path)
        if not media.is_file() or media.suffix.lower() not in {
            ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".mp4", ".mkv", ".webm", ".mov", ".aac"}:
            self.transcribeStatus.emit("Выберите поддерживаемый аудио- или видеофайл.")
            self.transcribeChanged.emit()
            return
        self._trans_state.update({"phase": "idle", "stage": "", "path": str(media),
                                  "file": media.name, "error": "", "speakers": [],
                                  "segments": [], "engine": "", "engineNote": "", "duration": 0.0,
                                  "sessionId": "", "progress": 0.0,
                                  "diarization": False})
        self.transcribeChanged.emit()

    @Slot()
    def runTranscript(self):
        """Распознайте выбранный файл локально (+ определите голоса)."""
        if self._jobs or self._trans_state["phase"] == "working":
            return
        path = self._trans_state.get("path", "")
        if not path or not Path(path).is_file():
            self.transcribeStatus.emit("Сначала откройте аудио или видео.")
            self.transcribeChanged.emit()
            return
        self._trans_cancel.clear()
        state = self._trans_state
        state.update({"phase": "working", "stage": "asr", "error": "", "segments": [],
                      "speakers": [], "diarization": False, "engine": "", "engineNote": "",
                      "sessionId": "", "progress": -1.0})
        self._trans_result_session_id = ""
        self._record_log("info", f"Транскрибация (локально): {Path(path).name}")
        self.transcribeChanged.emit()

        def process():
            try:
                text = self._transcribe_local(path)
            except Exception as exc:  # noqa: BLE001
                text = f"Ошибка: {exc}"
                self._record_log("error", str(exc))
            session_id = self._trans_result_session_id
            if self._trans_cancel.is_set():
                self.transcribeTick.emit({"phase": "idle", "progress": 0.0, "stage": ""})
                self.transcribeStatus.emit("Распознавание отменено (частичный результат не сохранён).")
            elif text.startswith("Ошибка"):
                self.transcribeTick.emit({
                    "phase": "idle", "progress": 0.0, "stage": "", "error": text,
                })
            else:
                self.transcribeTick.emit({
                    "phase": "done", "stage": "", "error": "", "progress": 1.0,
                })
                if session_id:
                    self.transcriptPersisted.emit(str(session_id))

        threading.Thread(target=process, name="dotaudio-transcribe", daemon=True).start()
        self.transcribeStatus.emit("Распознаём файл на этом устройстве…")

    def _on_transcribe_tick(self, payload) -> None:
        """Применить снимок прогресса в GUI-потоке и уведомить QML."""

        if isinstance(payload, dict):
            self._trans_state.update(payload)
        self.transcribeChanged.emit()

    def _trans_stage(self, stage: str) -> None:
        """Показать, чем занят проход: словами или голосами."""

        payload: dict = {"stage": stage}
        # ASR закончен, голоса ещё без доли: оставляем indeterminate.
        if stage == "voices":
            payload["progress"] = -1.0
        self.transcribeTick.emit(payload)

    @staticmethod
    def _probe_wav_duration(path: str) -> float:
        """Длительность WAV через stdlib wave; иначе 0 (не выдумываем)."""

        try:
            with wave.open(path, "rb") as handle:
                rate = int(handle.getframerate() or 0)
                frames = int(handle.getnframes() or 0)
            if rate > 0 and frames > 0:
                return frames / float(rate)
        except Exception:  # noqa: BLE001
            return 0.0
        return 0.0

    def _store_supports_speaker_column(self) -> bool:
        """Колонка speaker в Store: смотрим сигнатуру update_segment."""

        try:
            return "speaker" in inspect.signature(self.store.update_segment).parameters
        except (TypeError, ValueError):
            return False

    def _write_segment_to_store(
        self,
        session_id: str,
        segment_id: int,
        text: str,
        speaker: str,
    ) -> None:
        """Обновить сегмент: speaker kwargs, иначе legacy ``[Имя]`` в тексте."""

        body = str(text or "").strip()
        label = str(speaker or "").strip()
        if self._store_supports_speaker_column():
            self.store.update_segment(session_id, segment_id, body, speaker=label)
            return
        stored = f"[{label}] {body}" if label else body
        self.store.update_segment(session_id, segment_id, stored)

    def _transcribe_local(self, path: str) -> str:
        # Параметры движения как в караоке (слова), но backend принудительно
        # «local»: транскрибация никогда не отправляет аудио на сервер.
        config = replace(self._config(media_mode=True), backend="local")
        collected: list[dict] = []
        duration = self._probe_wav_duration(path)
        audio = None
        diarize = str(self._settings.get("diarize_engine") or "off")
        if diarize != "off":
            try:
                from dotaudio.speaker_id import decode_audio

                audio = decode_audio(path)
                if duration <= 0 and audio is not None and len(audio) > 0:
                    duration = float(len(audio)) / float(SAMPLE_RATE)
            except Exception:  # noqa: BLE001
                audio = None
        source = audio if audio is not None else path

        def on_segment(segment):
            row = {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
                "text": str(segment.get("text", "")).strip(),
                "words": segment.get("words", []),
            }
            collected.append(row)
            end = float(row["end"])
            progress = min(0.99, end / duration) if duration > 0 else -1.0
            self.transcribeTick.emit({
                "segments": [dict(item) for item in collected],
                "progress": progress,
                "duration": duration,
                "stage": "asr",
            })

        results = self.engine.transcribe(
            source,
            config,
            self._trans_cancel,
            on_segment,
            lambda s: self.transcribeStatus.emit(s.upper()),
        )
        collected = [item for item in collected if item["text"]] or results
        if self._trans_cancel.is_set():
            return ""
        if duration > 0 and collected:
            end = max(float(item.get("end", 0.0)) for item in collected)
            self.transcribeTick.emit({
                "segments": [dict(item) for item in collected],
                "progress": min(0.99, end / duration),
                "duration": duration,
                "stage": "asr",
            })
        elif collected:
            self.transcribeTick.emit({
                "segments": [dict(item) for item in collected],
                "progress": -1.0,
                "duration": duration,
                "stage": "asr",
            })
        rows, engine, note = self._identify_voices(path, collected, audio=audio)
        if self._trans_cancel.is_set():
            return ""
        legend = self._speaker_legend(rows)
        duration_final = max(
            duration,
            max((float(row.get("end", 0.0)) for row in rows), default=0.0),
        )
        session_id = self._persist_transcript(path, rows)
        self._trans_result_session_id = session_id
        self.transcribeTick.emit({
            "segments": rows,
            "speakers": legend,
            "diarization": bool(legend),
            "engine": engine,
            "engineNote": note,
            "duration": duration_final,
            "sessionId": session_id,
            "progress": 1.0,
            "stage": "",
        })
        return ""

    def _persist_transcript(self, path: str, rows: list[dict]) -> str:
        """Записать результат страницы «Транскрибация» в историю.

        Текст хранится без префикса ``[Имя]``, если Store уже принимает
        колонку speaker. Иначе - совместимый fallback в тексте сегмента.
        """

        media = Path(path)
        use_speaker = self._store_supports_speaker_column()
        payload: list[dict] = []
        kept: list[dict] = []
        for row in rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            speaker = str(row.get("speaker") or "").strip()
            item: dict = {
                "start": float(row.get("start", 0.0)),
                "end": float(row.get("end", 0.0)),
                "text": text if use_speaker else (f"[{speaker}] {text}" if speaker else text),
                "words": row.get("words") or [],
            }
            if use_speaker:
                item["speaker"] = speaker
            payload.append(item)
            kept.append(row)
        if not payload:
            return ""
        session_id = self.store.create_session(
            media.name,
            "transcript",
            str(media),
            str(self._settings.get("model") or "small"),
        )
        identifiers = self.store.append_segments(session_id, payload)
        for row, seg_id in zip(kept, identifiers, strict=False):
            row["id"] = int(seg_id)
        self.store.finish_session(session_id, "completed")
        maybe_title = getattr(self, "_maybe_autotitle_session", None)
        if callable(maybe_title):
            maybe_title(session_id)
        self.transcribeStatus.emit(f"Готово. Сохранено в историю: {media.name}")
        return session_id

    def _maybe_autotitle_session(self, session_id: str) -> None:
        """Если название типовое (Микрофон и т.п.), взять первые слова расшифровки."""

        from dotaudio.assistant import is_generic_title, title_from_transcript

        session = self.store.get_session(session_id)
        if session is None:
            return
        if not is_generic_title(str(session.get("title") or "")):
            return
        suggested = title_from_transcript(session.get("segments") or [])
        if not suggested:
            return
        try:
            cleaned = self.store.rename_session(session_id, suggested)
        except ValueError:
            return
        if self._session_id == session_id:
            self._session_title = cleaned
        if self._trans_state.get("sessionId") == session_id:
            self._trans_state["file"] = cleaned

    def _identify_voices(
        self,
        path: str,
        segments: list[dict],
        audio=None,
    ) -> tuple[list[dict], str, str]:
        """Определить говорящих выбранным движком.

        Неудача диаризации не отменяет расшифровку: текст с таймкодами
        остаётся, а причина уходит в подпись под списком. Отмена во время
        разметки голосов трактуется так же, как отмена распознавания.
        """

        engine = str(self._settings.get("diarize_engine") or "off")
        if engine == "off" or not segments:
            return self._label_speakers(segments), "", ""
        self._trans_stage("voices")
        try:
            rows, note = (
                self._voices_nemo(path, segments, audio=audio)
                if engine == "nemo"
                else self._voices_ecapa(path, segments, audio=audio)
            )
        except Exception as exc:  # noqa: BLE001
            if self._trans_cancel.is_set():
                return self._label_speakers(segments), "", ""
            reason = str(exc).strip() or "движок голосов не ответил"
            self._record_log("warning", f"Голоса не определены: {reason}")
            self.transcribeStatus.emit("Текст готов, голоса не определены.")
            return self._label_speakers(segments), "", f"Без определения голосов: {reason}"
        self.transcribeStatus.emit("Готово: текст и говорящие.")
        return self._label_speakers(rows), engine, note

    def _voices_nemo(self, path: str, segments: list[dict], audio=None) -> tuple[list[dict], str]:
        """Разметка дорожки моделью NVIDIA Sortformer через нативный рантайм."""

        from dotaudio.nemo_diarize import MAX_SPEAKERS, diarize_audio
        from dotaudio.speaker_id import assign_turns, decode_audio

        samples = audio if audio is not None else decode_audio(path)
        # Выбор устройства общий с Whisper: если пользователь увёл всё на
        # процессор, диаризация не должна втихую занимать видеокарту.
        turns = diarize_audio(samples, device=str(self._settings.get("device") or "auto"),
                              cancel=self._trans_cancel,
                              on_status=self.transcribeStatus.emit)
        rows = assign_turns(segments, turns)
        voices = len({row["role"] for row in rows if row.get("role") is not None})
        note = f"NVIDIA NeMo Sortformer · голосов: {voices}"
        split = len(rows) - len(segments)
        if split > 0:
            note += f" · фраз разделено по смене голоса: {split}"
        if voices >= MAX_SPEAKERS:
            note += f" · модель различает не больше {MAX_SPEAKERS}"
        return rows, note

    def _voices_ecapa(self, path: str, segments: list[dict], audio=None) -> tuple[list[dict], str]:
        """Прежний путь: один эмбеддинг на фразу и онлайн-кластеризация."""

        from platformdirs import user_cache_dir

        from dotaudio.speaker_id import apply_roles, decode_audio, diarize_segments

        samples = audio if audio is not None else decode_audio(path)
        roles = diarize_segments(samples, segments, user_cache_dir("dotaudio", "dotcore"))
        rows = apply_roles(segments, roles)
        voices = len({role for role in roles if role is not None})
        return rows, f"SpeechBrain ECAPA · голосов: {voices} · метка на фразу целиком"

    @staticmethod
    def _label_speakers(rows: list[dict]) -> list[dict]:
        """Роль движка с нуля -> номер и подпись, которые видит пользователь."""

        labelled = []
        for row in rows:
            role = row.get("role")
            key = int(role) + 1 if role is not None else None
            labelled.append({
                **row,
                "role": key,
                "speaker": default_speaker_label(key) if key else "",
            })
        return labelled

    @staticmethod
    def _speaker_legend(
        rows: list[dict],
        previous: list[dict] | None = None,
    ) -> list[dict]:
        """Легенда с числом реплик и временем речи каждого голоса."""

        prev_by_key = {
            int(item["key"]): item
            for item in (previous or [])
            if item.get("key") is not None
        }
        legend: dict[int, dict] = {}
        for row in rows:
            key = row.get("role")
            if not key:
                continue
            entry = legend.setdefault(
                int(key),
                {"key": int(key), "label": str(row.get("speaker") or ""), "count": 0, "seconds": 0.0},
            )
            if "kind" not in entry:
                prev = prev_by_key.get(int(key))
                if prev and prev.get("kind"):
                    entry["kind"] = prev["kind"]
            entry["count"] += 1
            entry["seconds"] += max(
                0.0, float(row.get("end", 0.0)) - float(row.get("start", 0.0))
            )
        ordered = sorted(legend.values(), key=lambda item: item["key"])
        return [{**item, "seconds": round(item["seconds"], 1)} for item in ordered]

    @Slot()
    def stopTranscript(self):
        self._trans_cancel.set()

    @Slot()
    def clearTranscript(self):
        if self._jobs or self._trans_state["phase"] == "working":
            return
        self._trans_state.update({"phase": "idle", "stage": "", "file": "", "path": "",
                                  "error": "", "speakers": [], "segments": [],
                                  "diarization": False, "engine": "", "engineNote": "",
                                  "duration": 0.0, "sessionId": "", "progress": 0.0})
        self.transcribeChanged.emit()

    @Slot(int, str)
    def editTranscriptSegment(self, index: int, text: str) -> None:
        """Править текст одной фразы в полной расшифровке."""

        segments = self._trans_state.get("segments") or []
        idx = int(index)
        if idx < 0 or idx >= len(segments):
            return
        cleaned = str(text or "").strip()
        row = segments[idx]
        row["text"] = cleaned
        session_id = str(self._trans_state.get("sessionId") or "")
        seg_id = row.get("id")
        if session_id and seg_id is not None:
            self._write_segment_to_store(
                session_id,
                int(seg_id),
                cleaned,
                str(row.get("speaker") or ""),
            )
        self.transcribeChanged.emit()

    @Slot(int, str)
    def setTranscriptSegmentSpeaker(self, index: int, label: str) -> None:
        """Назначить автора одной фразе; пустая строка снимает метку."""

        segments = self._trans_state.get("segments") or []
        idx = int(index)
        if idx < 0 or idx >= len(segments):
            return
        cleaned = " ".join(str(label or "").strip().split())
        row = segments[idx]
        if not cleaned:
            row["speaker"] = ""
            row["role"] = None
        else:
            found_key = None
            for item in self._trans_state.get("speakers") or []:
                if str(item.get("label") or "") == cleaned:
                    found_key = int(item["key"])
                    break
            if found_key is None:
                keys = [
                    int(item["key"])
                    for item in (self._trans_state.get("speakers") or [])
                    if item.get("key") is not None
                ]
                found_key = (max(keys) if keys else 0) + 1
            row["speaker"] = cleaned
            row["role"] = found_key
        self._trans_state["speakers"] = self._speaker_legend(
            segments,
            previous=self._trans_state.get("speakers"),
        )
        self._trans_state["diarization"] = bool(self._trans_state["speakers"])
        session_id = str(self._trans_state.get("sessionId") or "")
        seg_id = row.get("id")
        if session_id and seg_id is not None:
            self._write_segment_to_store(
                session_id,
                int(seg_id),
                str(row.get("text") or ""),
                str(row.get("speaker") or ""),
            )
        self.transcribeChanged.emit()

    @Slot(int, str)
    def setTranscriptSpeakerKind(self, key: int, kind: str) -> None:
        """Ручной вид роли: voice|male|female → Голос/Парень/Девушка N."""

        role = int(key)
        normalized = str(kind or "voice").strip().lower()
        if normalized not in ("voice", "male", "female"):
            normalized = "voice"
        speakers = self._trans_state.get("speakers") or []
        entry = next((item for item in speakers if int(item.get("key", -1)) == role), None)
        if entry is None:
            return
        entry["kind"] = normalized
        current = str(entry.get("label") or "")
        if is_default_speaker_label(current, role):
            self.renameTranscriptSpeaker(role, speaker_label_for_kind(role, normalized))
            entry["kind"] = normalized
            return
        self.transcribeChanged.emit()

    @Slot(int, str)
    def renameTranscriptSpeaker(self, key, label):
        label = " ".join(str(label or "").strip().split())
        if not label:
            return
        state = self._trans_state
        for sp in state["speakers"]:
            if int(sp["key"]) == int(key):
                sp["label"] = label
        for seg in state["segments"]:
            # Диаризация может пройти частично: у фразы без определённого
            # голоса роли нет, и переименование не должно её трогать.
            if seg.get("role") is None:
                continue
            if int(seg["role"]) == int(key):
                seg["speaker"] = label
        # История хранит говорящего отдельно или в тексте «[Имя] фраза».
        self._persist_transcript_speaker_labels()
        self.transcribeChanged.emit()

    def _persist_transcript_speaker_labels(self) -> None:
        """Переписать подписи говорящих в уже сохранённой transcript-сессии."""

        session_id = str(self._trans_state.get("sessionId") or "")
        if not session_id:
            return
        session = self.store.get_session(session_id)
        if session is None or session.get("mode") != "transcript":
            return
        use_speaker = self._store_supports_speaker_column()
        by_id: dict[int, tuple[str, str]] = {}
        by_span: dict[tuple[float, float], tuple[str, str]] = {}
        for row in self._trans_state.get("segments") or []:
            span = (
                round(float(row.get("start", 0.0)), 3),
                round(float(row.get("end", 0.0)), 3),
            )
            body = str(row.get("text") or "").strip()
            speaker = str(row.get("speaker") or "").strip()
            stored = body if use_speaker else (f"[{speaker}] {body}" if speaker else body)
            by_span[span] = (stored, speaker)
            if row.get("id") is not None:
                by_id[int(row["id"])] = (stored, speaker)
        for item in session.get("segments") or []:
            item_id = int(item["id"])
            if item_id in by_id:
                new_text, speaker = by_id[item_id]
            else:
                span = (round(float(item["start"]), 3), round(float(item["end"]), 3))
                pair = by_span.get(span)
                if pair is None:
                    continue
                new_text, speaker = pair
            if use_speaker:
                old_speaker = str(item.get("speaker") or "").strip()
                if new_text == item.get("text") and speaker == old_speaker:
                    continue
                self.store.update_segment(session_id, item_id, new_text, speaker=speaker)
            else:
                if new_text == item.get("text"):
                    continue
                self.store.update_segment(session_id, item_id, new_text)

    @Slot()
    def transcriptExport(self):
        segments = self._trans_state["segments"]
        if not segments:
            return
        from dotaudio.transcripts import export_transcript
        path, _ = QFileDialog.getSaveFileName(None, "Сохранить транскрибацию",
                                              "transcript.txt", "TXT (*.txt);;SRT (*.srt);;VTT (*.vtt);;JSON (*.json)")
        if not path:
            return
        fmt = Path(path).suffix.lstrip(".") or "txt"
        payload = segments
        if fmt in ("srt", "vtt"):
            from dotaudio.transcripts import regroup_for_subtitles
            payload = regroup_for_subtitles(segments)
        # Говорящий выносим в текст перед экспортом (без права менять из строк).
        rows = []
        for seg in payload:
            speaker = str(seg.get("speaker") or "").strip()
            text = str(seg.get("text") or "").strip()
            rows.append({**seg, "text": f"[{speaker}] {text}".strip() if speaker else text})
        try:
            Path(path).write_text(export_transcript(rows, fmt), encoding="utf-8")
            self.transcribeStatus.emit(f"Сохранено: {Path(path).name}")
        except OSError as exc:
            self.transcribeStatus.emit(f"Не удалось сохранить: {exc}")
        self.transcribeChanged.emit()

    def shutdown(self):
        self._closing = True
        self.cancel()
        return not self._jobs
