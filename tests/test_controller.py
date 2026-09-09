import time

from dotaudio.capture import next_live_source
from dotaudio.controller import (
    DEFAULTS,
    EXPORT_SETTING_KEYS,
    HOTKEY_OPTIONS,
    MODEL_BY_PROFILE,
    QUIT_HOTKEY_OPTIONS,
    STATUS_LABELS,
    Controller,
    hotkey_id,
    live_draft_model_for,
    parse_hotkey,
    sensitivity_label,
)
from dotaudio.engine import Engine
from dotaudio.transcript_pro import EXPORT_FORMAT_KEYS, normalise_export_options
from dotaudio.translate import language_task_for


class _Signal:
    def emit(self, *_args) -> None:
        pass


class _Counting:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *_args) -> None:
        self.count += 1


def test_live_source_defaults_to_system_audio() -> None:
    assert DEFAULTS["live_source"] == "system"
    assert DEFAULTS["source"] == "microphone"
    # The default profile and the default model have to agree, and both have
    # to be a model that produces Russian rather than phonetic guesses.
    assert DEFAULTS["model"] == MODEL_BY_PROFILE[DEFAULTS["profile"]] == "small"
    assert next_live_source(DEFAULTS["live_source"]) == "mixed"


def test_caption_overlay_settings_are_local_and_sized() -> None:
    # Live по умолчанию живёт в одном окне (остров превращается в зал);
    # отдельное «окно зала» включается вручную кнопкой, а не спавнится при
    # каждом старте Live.
    assert DEFAULTS["caption_overlay"] is False
    assert DEFAULTS["caption_size"] == "md"
    assert DEFAULTS["caption_contrast"] == "normal"


def test_parse_and_normalise_free_exit_hotkey() -> None:
    combo = parse_hotkey("Ctrl+Alt+K")
    assert combo is not None
    assert combo.key == ord("K")
    assert hotkey_id("ctrl+k+alt") == "Ctrl+Alt+K"
    # Некорректные/двойные клавиши и строки без модификатора не принимаются.
    assert parse_hotkey("Alt") is None
    assert parse_hotkey("Ctrl+A+B") is None
    assert parse_hotkey("") is None


def test_default_exit_combo_is_registered_as_a_normal_option() -> None:
    assert "Ctrl+Alt+X" in QUIT_HOTKEY_OPTIONS
    assert parse_hotkey("Ctrl+Alt+X") == QUIT_HOTKEY_OPTIONS["Ctrl+Alt+X"]


def test_saved_export_settings_survive_the_option_check() -> None:
    """Каждая сохранённая настройка сохранения должна быть валидной опцией.

    Опечатка в DEFAULTS иначе молча заменялась бы значением по умолчанию, и
    окно сохранения открывалось бы не с тем, что человек выбрал в прошлый раз.
    """
    saved = {
        option: DEFAULTS[setting] for setting, option in EXPORT_SETTING_KEYS.items()
    }
    # Таймкоды включены: иначе вид отметки честно схлопывается в «без времени»
    # и сравнивать его с сохранённым «начало и конец» нечестно.
    checked = normalise_export_options({**saved, "include_timestamps": True})
    saved["include_timestamps"] = True
    for option, value in saved.items():
        assert checked[option] == value, option
    assert checked["format"] in EXPORT_FORMAT_KEYS
    # Настройка без опции (и наоборот) означала бы потерянный параметр.
    assert set(EXPORT_SETTING_KEYS) <= set(DEFAULTS)


def test_segments_have_a_dedicated_qt_notify_signal() -> None:
    """Frequent Live status updates must not rebuild the whole transcript list."""
    meta = Controller.staticMetaObject
    prop = meta.property(meta.indexOfProperty("segments"))

    assert bytes(prop.notifySignal().name()).decode() == "segmentsChanged"


def test_engine_statuses_have_russian_labels() -> None:
    assert STATUS_LABELS["loading_model"].startswith("Загружаем")
    assert STATUS_LABELS["transcribing_cpu"].startswith("Распознаём")
    assert STATUS_LABELS["live_backlog"].startswith("Догоняем")
    assert STATUS_LABELS["dictation_refine_1"].startswith("Уточняем")
    assert STATUS_LABELS["dictation_refine_2"].startswith("Уточняем")
    assert STATUS_LABELS["live_process"].startswith("Обрабатываем")


def test_dictation_defaults_enable_auto_paste() -> None:
    assert DEFAULTS["auto_paste"] is True
    assert DEFAULTS["dictate_hotkey"] == "Ctrl+Alt+Space"


def test_dictation_refine_progress_replaces_segments(tmp_path) -> None:
    from dotaudio.storage import Store

    store = Store(tmp_path / "dotaudio.sqlite3")
    sid = store.create_session("Диктовка", "dictation", "mic", "base")
    store.append_segments(sid, [{"start": 0.0, "end": 1.0, "text": "черновик"}])

    controller = Controller.__new__(Controller)
    controller._session_id = sid
    controller.store = store
    controller._segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "черновик"}]
    controller._partial_caption = "черновик"
    controller._partial_source = "черновик"
    controller._preview_stable = ""
    controller._status = ""
    controller._caption_revision = 0
    controller.segmentsChanged = _Counting()
    controller.captionChanged = _Counting()
    controller.statusChanged = _Counting()
    controller.changed = _Counting()

    Controller._on_dictation_refine_progress(
        controller,
        sid,
        [{"start": 0.0, "end": 1.5, "text": "уточнённый текст"}],
        "dictation_refine_2",
    )

    session = store.get_session(sid)
    assert session is not None
    assert [row["text"] for row in session["segments"]] == ["уточнённый текст"]
    assert controller._segments[0]["text"] == "уточнённый текст"
    assert controller._partial_caption == ""
    assert controller._status.startswith("Уточняем")


def test_dictation_rules_preserve_raw_text_until_explicit_final_processing() -> None:
    rules = type(
        "Rules",
        (),
        {
            "dictionary": [{"term": "DotAudio", "misheard": "дот аудио"}],
            "snippets": [{"trigger": "моя подпись", "expansion": "С уважением, Анна"}],
        },
    )()
    assert Controller._apply_dictation_rules(rules, "дот аудио моя подпись") == "DotAudio С уважением, Анна"


def test_hotkey_options_are_valid_and_actions_do_not_overlap() -> None:
    assert HOTKEY_OPTIONS["Ctrl+Alt+Space"] != HOTKEY_OPTIONS["Ctrl+Alt+O"]
    assert HOTKEY_OPTIONS["Shift+Alt+Z"] != HOTKEY_OPTIONS["Ctrl+Alt+Space"]
    assert HOTKEY_OPTIONS["Ctrl+Alt+V"] != HOTKEY_OPTIONS["Shift+Alt+Z"]
    assert HOTKEY_OPTIONS["Escape"].key == 0x1B
    assert DEFAULTS["dictate_hold"] is False
    assert DEFAULTS["paste_last_hotkey"] == "Shift+Alt+Z"
    assert DEFAULTS["dictate_hotkey"] == "Ctrl+Alt+Space"
    assert DEFAULTS["cancel_hotkey"] == "Escape"
    assert DEFAULTS["caption_position"] == "bottom"
    assert DEFAULTS["caption_locked"] is True
    assert DEFAULTS["caption_autohide"] is False
    assert DEFAULTS["reduce_motion"] is False
    from dotaudio.controller import HOTKEY_ACTIONS

    ids = [item["id"] for item in HOTKEY_ACTIONS]
    assert ids == ["dictate", "island", "paste_last", "cancel", "quit"]


def test_set_action_hotkey_updates_cancel() -> None:
    saved: list[dict] = []
    registered: list[dict] = []
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._settings = dict(DEFAULTS)
    controller._notice = ""
    controller.store = type(
        "Store",
        (),
        {"save_settings": staticmethod(lambda settings: saved.append(dict(settings)))},
    )()
    controller.desktop = type(
        "Desktop",
        (),
        {"set_hotkeys": staticmethod(lambda bindings: registered.append(bindings) or True)},
    )()
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    Controller.setActionHotkey(controller, "cancel", "Ctrl+Escape")

    assert controller._settings["cancel_hotkey"] == "Ctrl+Escape"
    assert registered and "cancel" in registered[-1]
    assert saved


def test_paste_hotkey_can_be_rebound() -> None:
    saved: list[dict] = []
    registered: list[dict] = []
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._settings = dict(DEFAULTS)
    controller._notice = ""
    controller.store = type("Store", (), {"save_settings": staticmethod(lambda settings: saved.append(dict(settings)))})()
    controller.desktop = type(
        "Desktop",
        (),
        {"set_hotkeys": staticmethod(lambda bindings: registered.append(bindings) or True)},
    )()
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    Controller.setPasteHotkey(controller, "Ctrl+Alt+V")

    assert controller._settings["paste_last_hotkey"] == "Ctrl+Alt+V"
    assert controller._settings["dictate_hotkey"] == DEFAULTS["dictate_hotkey"]
    assert registered and "paste_last" in registered[0]
    assert saved


def test_mic_check_playing_phase_keeps_test_busy() -> None:
    logs: list[tuple] = []
    controller = Controller.__new__(Controller)
    controller._testing_device = True
    controller._device_test = {"phase": "listening", "message": "", "level": 0.2}
    controller._record_log = lambda kind, message: logs.append((kind, message))
    controller.changed = _Signal()

    Controller._on_device_test_finished(controller, "playing", "Воспроизводим…")
    assert controller._testing_device is True
    assert controller._device_test["phase"] == "playing"
    assert logs == []

    Controller._on_device_test_finished(controller, "ready", "Микрофон работает.")
    assert controller._testing_device is False
    assert logs == [("success", "Микрофон работает.")]


def test_disk_status_describes_cache_without_downloading() -> None:
    info = Engine.disk_status("tiny")
    assert info["model"] == "tiny"
    assert info["bytes"] >= 0
    assert "message" in info


def test_model_fit_compares_memory_with_the_real_machine() -> None:
    from dotaudio.controller import MODEL_CATALOG, model_fit, recommended_model

    known = {"threads": 8, "ram_gb": 4.0, "cuda_devices": 0}
    # Память - факт: large-v3 не влезает в 4 ГБ, и это сказано словами.
    tight = model_fit("large-v3", known)
    assert tight["state"] == "tight"
    assert "4 ГБ" in tight["note"]
    # Скорость - рекомендация, а не замер: тяжёлые модели на CPU помечены.
    rich_cpu = {"threads": 8, "ram_gb": 32.0, "cuda_devices": 0}
    assert model_fit("medium", rich_cpu)["state"] == "slow"
    assert model_fit("small", rich_cpu)["state"] == "ok"
    # Без сведений об ОЗУ оценка по памяти не выдумывается.
    unknown_ram = {"threads": 8, "ram_gb": None, "cuda_devices": 0}
    assert model_fit("large-v3", unknown_ram)["state"] != "tight"
    # Каталог покрывает все карточки страницы, рекомендация существует.
    assert set(MODEL_CATALOG) == {"tiny", "base", "small", "medium", "large-v3", "turbo"}
    assert recommended_model(known) == "small"
    assert recommended_model({"threads": 4, "ram_gb": 16.0, "cuda_devices": 0}) == "base"
    assert recommended_model({"threads": 2, "ram_gb": 8.0, "cuda_devices": 0}) == "base"
    assert recommended_model({"threads": 0, "ram_gb": None, "cuda_devices": 0}) == "tiny"
    assert recommended_model({"threads": 8, "ram_gb": 32.0, "cuda_devices": 1, "gpuVramGb": 8}) == "medium"
    assert model_fit("small", {"threads": 4, "ram_gb": 16.0, "cuda_devices": 0})["state"] == "slow"


def test_show_gpu_hint_for_nvidia_until_dismissed() -> None:
    controller = type("ControllerState", (), {})()
    controller._settings = {"gpu_hint_dismissed": False}
    controller._gpu_setup = {"busy": False}
    controller._hardware = {"computeAdvice": "needs_runtime"}
    assert Controller.showGpuHint.fget(controller) is True
    controller._settings["gpu_hint_dismissed"] = True
    assert Controller.showGpuHint.fget(controller) is False


class _LiveStore:
    """Хранилище без SQLite: помнит, что добавили и что расширили."""

    def __init__(self) -> None:
        self.appended: list[dict] = []
        self.extended: list[tuple[int, float, str]] = []

    def append_segments(self, _sid, segments):
        self.appended.extend(segments)
        return [len(self.appended)]

    def extend_segment(self, _sid, segment_id, end, text):
        self.extended.append((segment_id, end, text))


def _live_controller() -> Controller:
    controller = Controller.__new__(Controller)
    controller._jobs = {"live": {"mode": "live"}}
    controller.store = _LiveStore()
    controller._session_id = "live"
    controller._segments = []
    controller._open_phrase = False
    controller._settled_caption = ""
    controller.segmentsChanged = _Counting()
    controller._final_end = 0.0
    controller._partial_end = 0.0
    controller._confirmed_caption = ""
    controller._partial_caption = ""
    controller._partial_source = ""
    controller._caption_revision = 0
    controller._started = 0.0
    controller._live_latency_ms = 0.0
    controller._live_phase = "speech"
    controller._live_diagnostic = ""
    controller._last_caption_at = 0.0
    controller.captionChanged = _Counting()
    controller.liveStateChanged = _Signal()
    controller._state = "recording"
    controller._record_log = lambda *_args: None
    controller._status = ""
    controller.changed = _Counting()
    controller.statusChanged = _Signal()
    controller.logsChanged = _Signal()
    return controller


def test_late_live_final_does_not_replace_a_newer_preview() -> None:
    controller = _live_controller()
    controller._partial_end = 5.0
    controller._partial_source = "новая фраза продолжается"
    controller._caption_revision = 3

    Controller._on_segment(
        controller, "live", {"start": 2.0, "end": 4.0, "text": "старая фраза"}
    )

    assert controller._segments[-1]["text"] == "старая фраза"
    # Сказанное встало строкой в колонке, а живая строка держит черновик
    # более новой речи: она не подставляет туда уже готовую фразу.
    assert controller._confirmed_caption == ""
    assert controller._partial_caption == "новая фраза продолжается"
    assert controller._partial_source == "новая фраза продолжается"
    assert controller._partial_end == 5.0
    # Готовая фраза не перетряхивает весь интерфейс: настройки, устройства и
    # карточки моделей не перечитываются на каждой реплике говорящего.
    assert controller.changed.count == 0


def test_live_finals_of_one_sentence_are_joined_into_one_row() -> None:
    controller = _live_controller()

    Controller._on_segment(controller, "live", {
        "start": 0.0, "end": 4.0, "audio_end": 4.0, "cut": True,
        "text": "Сегодня мы говорим о распознавании речи в реальном",
    })
    # Предложение не закончено, но строка уже стоит в списке и больше не
    # переписывается: живая строка занята только текущей фразой.
    assert controller._open_phrase is True
    assert controller._confirmed_caption == ""
    assert controller._settled_caption == ""

    Controller._on_partial(controller, "live", {"start": 4.0, "end": 4.9, "text": "времени,"})
    assert Controller.displayCaption.fget(controller) == "времени,"

    Controller._on_segment(controller, "live", {
        "start": 4.0, "end": 5.2, "audio_end": 5.2, "cut": False, "text": "времени.",
    })

    assert len(controller._segments) == 1
    assert controller._segments[0]["text"] == "Сегодня мы говорим о распознавании речи в реальном времени."
    assert controller.store.extended == [(1, 5.2, "Сегодня мы говорим о распознавании речи в реальном времени.")]
    # Предложение закончено: строка ушла в историю, живая строка свободна,
    # а остров и зал держат его как последнее сказанное.
    assert controller._open_phrase is False
    assert Controller.liveOpenPhrase.fget(controller) is False
    assert controller._confirmed_caption == ""
    assert controller._partial_caption == ""
    assert controller._settled_caption == "Сегодня мы говорим о распознавании речи в реальном времени."


def test_live_caption_window_shows_readable_tail_only() -> None:
    controller = _live_controller()
    long_draft = (
        "это очень длинный черновик одной фразы про живые субтитры, "
        "который не должен целиком висеть в живой строке на экране зала"
    )
    Controller._on_partial(
        controller, "live", {"start": 0.0, "end": 4.0, "text": long_draft}
    )
    shown = Controller.displayCaption.fget(controller)
    assert shown.endswith("на экране зала")
    assert len(shown) <= 100
    assert shown in long_draft


def test_live_cut_seam_reads_as_one_sentence() -> None:
    controller = _live_controller()

    Controller._on_segment(controller, "live", {
        "start": 0.0, "end": 4.0, "audio_end": 4.0, "cut": True,
        "text": "Живые субтитры должны появляться почти мгновенно.",
    })
    Controller._on_partial(controller, "live", {"start": 4.0, "end": 5.0, "text": "Даже на слабом"})
    # Живая строка держит только текущую фразу: сказанное читается строкой
    # истории, а не переписывается вместе с черновиком несколько раз в секунду.
    assert Controller.displayCaption.fget(controller) == "Даже на слабом"

    Controller._on_segment(controller, "live", {
        "start": 4.0, "end": 6.5, "audio_end": 6.5, "cut": False,
        "text": "Даже на слабом.",
    })
    assert controller._segments[0]["text"] == (
        "Живые субтитры должны появляться почти мгновенно, даже на слабом."
    )

    # Следующая фраза с заглавной буквы после законченного предложения - новая строка.
    Controller._on_segment(controller, "live", {
        "start": 6.8, "end": 8.0, "audio_end": 8.0, "cut": False, "text": "Это главная задача.",
    })
    assert [segment["text"] for segment in controller._segments][-1] == "Это главная задача."
    assert len(controller._segments) == 2


def test_live_pause_closes_an_open_sentence() -> None:
    controller = _live_controller()
    controller._capture_started_at = time.monotonic() - 30
    controller._level = 0.0
    controller._last_signal_at = time.monotonic() - 5

    Controller._on_segment(controller, "live", {
        "start": 0.0, "end": 3.0, "audio_end": 3.0, "cut": False, "text": "и тогда мы",
    })
    assert controller._open_phrase is True

    Controller._update_live_sound_status(controller)

    # Говорящий замолчал: незаконченная фраза уходит в историю как есть.
    assert controller._open_phrase is False
    assert controller._confirmed_caption == ""
    assert controller._settled_caption == ""
    assert controller._segments[-1]["text"] == "и тогда мы"


def test_live_decode_statuses_do_not_touch_interface_bindings() -> None:
    """A decode pair arrives twice a second; only the phase may react to it."""

    controller = type("ControllerState", (), {})()
    controller._jobs = {"live": {"mode": "live"}}
    controller.liveActive = True
    controller.recording = True
    controller._live_phase = "speech"
    controller._live_diagnostic = ""
    controller._status = "Слушаю"
    controller._last_status = ""
    controller._record_log = lambda *_args: None
    controller.changed = _Counting()
    controller.liveStateChanged = _Counting()
    controller.statusChanged = _Counting()
    controller.logsChanged = _Counting()

    for _ in range(3):
        Controller._set_status(controller, "transcribing_cpu")
        Controller._set_status(controller, "completed")

    assert controller._live_phase == "listening"
    assert controller._status == "Слушаю"
    assert controller.changed.count == 0
    assert controller.statusChanged.count == 0
    assert controller.liveStateChanged.count == 6

    Controller._set_status(controller, "live_slow")
    assert controller._live_diagnostic == "live_slow"
    assert controller._status == STATUS_LABELS["live_slow"]
    # Заметный статус меняет строку состояния и журнал, но не весь интерфейс.
    assert controller.statusChanged.count == 1
    assert controller.changed.count == 0


def test_live_sensitivity_stays_speech_outside_live() -> None:
    controller = type("ControllerState", (), {})()
    controller._settings = {
        key: DEFAULTS[key]
        for key in ("model", "device", "language", "task", "backend", "server_url", "profile", "live_sensitivity")
    }
    controller._settings["live_sensitivity"] = "everything"
    controller.dictionary = []

    live = Controller._config(controller, live_stream=True)
    dictation = Controller._config(controller)

    assert live.live_sensitivity == "everything"
    # Диктовка и медиа не имеют своего «всё подряд»: настройка только для Live.
    assert dictation.live_sensitivity == "speech"


def test_live_draft_model_only_helps_when_the_final_model_is_heavy() -> None:
    # Тяжёлому финалу нужен быстрый черновик: сам он отстаёт от речи.
    assert live_draft_model_for("medium", "auto") == "small"
    assert live_draft_model_for("large-v3", "auto") == "small"
    # Лёгкая модель успевает сама - второй модели в памяти не нужно.
    assert live_draft_model_for("small", "auto") == ""
    assert live_draft_model_for("base", "auto") == ""
    # Явный выбор и явное отключение.
    assert live_draft_model_for("large-v3", "base") == "base"
    assert live_draft_model_for("base", "base") == ""
    assert live_draft_model_for("medium", "off") == ""


def test_live_config_asks_for_a_draft_model_outside_dictation() -> None:
    controller = type("ControllerState", (), {})()
    controller._settings = {
        key: DEFAULTS[key]
        for key in (
            "model", "device", "language", "task", "backend", "server_url",
            "profile", "live_sensitivity", "live_draft_model",
        )
    }
    controller._settings["model"] = "medium"
    controller.dictionary = []

    live = Controller._config(controller, live_stream=True)
    dictation = Controller._config(controller)

    assert live.live_draft_model == "small"
    # Диктовка и медиа идут одной моделью: там читают готовый текст.
    assert dictation.live_draft_model == ""


def test_sensitivity_label_and_toggle_round_trip() -> None:
    # Настоящий класс без __init__: методу toggle нужен self.setSetting.
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._settings = dict(DEFAULTS)
    controller.store = type("Store", (), {"save_settings": staticmethod(lambda _s: None)})()
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    assert sensitivity_label(controller._settings["live_sensitivity"]) == "Речь"
    Controller.toggleLiveSensitivity(controller)
    assert controller._settings["live_sensitivity"] == "everything"
    assert sensitivity_label(controller._settings["live_sensitivity"]) == "Всё"
    Controller.toggleLiveSensitivity(controller)
    assert controller._settings["live_sensitivity"] == "speech"


def test_speech_mode_sets_language_task_and_config() -> None:
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._settings = dict(DEFAULTS)
    controller._translator = type(
        "T",
        (),
        {
            "clear": staticmethod(lambda: None),
            "last_error": "",
            "ready": staticmethod(lambda: True),
        },
    )()
    controller._translate_notice_shown = False
    controller._translate_state = {"ready": True, "phase": "ready", "message": ""}
    controller._warmup_enabled = False
    controller._prepared_model = "small"
    controller.store = type("Store", (), {"save_settings": staticmethod(lambda _s: None)})()
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    assert DEFAULTS["speech_mode"] == "ru"
    Controller.setSetting(controller, "speech_mode", "en")
    assert controller._settings["language"] == "en"
    assert controller._settings["task"] == "transcribe"

    Controller.cycleSpeechMode(controller)
    assert controller._settings["speech_mode"] == "en_ru"
    assert controller._settings["language"] == "en"
    assert controller._settings["task"] == "transcribe"
    assert Controller.speechModeLabel.fget(controller) == "EN → RU"
    language, task = language_task_for(controller._settings["speech_mode"])
    assert (language, task) == ("en", "transcribe")

    from dotaudio.translate import Translator

    controller._translator = Translator(translate_fn=lambda text, *_: "Привет")
    controller.logArrived = _Signal()
    translated = Controller._translate_segment(
        controller,
        {"text": "Hello", "words": [{"text": "Hello"}]},
    )
    assert translated["text"] == "Привет"
    assert translated["source_text"] == "Hello"
    assert translated["words"] == []


def test_reset_caption_position_clears_only_saved_floating_coordinates() -> None:
    controller = Controller.__new__(Controller)
    controller._settings = {**DEFAULTS, "caption_position": "floating", "caption_x": 340, "caption_y": 120}
    saved = []
    controller.store = type("Store", (), {"save_settings": staticmethod(saved.append)})()
    controller._record_log = lambda *_args: None
    controller.changed = _Counting()

    Controller.resetCaptionPosition(controller)

    assert controller._settings["caption_position"] == "bottom"
    assert controller._settings["caption_x"] == controller._settings["caption_y"] == -1
    assert saved == [controller._settings]
    assert controller.changed.count == 1


def test_changing_live_source_clears_a_stale_source_check() -> None:
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._settings = dict(DEFAULTS)
    controller._device_test = {"phase": "ready", "message": "Источник отвечает.", "level": 0.42}
    controller.store = type("Store", (), {"save_settings": staticmethod(lambda _settings: None)})()
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    Controller.setSetting(controller, "live_source", "microphone")

    assert controller._settings["live_source"] == "microphone"
    assert controller._device_test == {"phase": "idle", "message": "", "level": 0.0}

    controller._device_test = {"phase": "ready", "message": "Источник отвечает.", "level": 0.42}
    Controller.setSetting(controller, "caption_size", "lg")
    assert controller._device_test["phase"] == "ready"


def test_unrecognized_sound_is_named_and_silence_clears_captions() -> None:
    controller = Controller.__new__(Controller)
    controller._jobs = {"live": {"mode": "live"}}
    controller._state = "recording"
    controller._segments = []
    controller.segmentsChanged = _Signal()
    controller._capture_started_at = time.monotonic() - 30
    controller._level = 0.5
    controller._last_signal_at = time.monotonic() - 1
    controller._last_caption_at = time.monotonic() - 30
    controller._live_diagnostic = ""
    controller._confirmed_caption = "старая фраза"
    controller._partial_caption = ""
    controller._settled_caption = ""
    controller._open_phrase = False
    controller._partial_end = 9.0
    controller._caption_revision = 0
    controller.captionChanged = _Counting()
    controller.liveStateChanged = _Counting()

    # Громкий звук полминуты без единой распознанной фразы: сказать об этом.
    Controller._update_live_sound_status(controller)
    assert controller._live_diagnostic == "live_unrecognized"
    assert controller.liveStateChanged.count == 1
    assert controller.captionChanged.count == 0

    # Звук кончился: Diagnostic гаснет, а после паузы экран освобождается.
    controller._level = 0.0
    controller._last_signal_at = time.monotonic() - 5
    Controller._update_live_sound_status(controller)
    assert controller._live_diagnostic == ""
    assert controller._confirmed_caption == ""
    assert controller._partial_caption == ""
    assert controller._partial_end == 0.0
    assert controller._caption_revision == 1
    assert controller.captionChanged.count == 1


def test_force_stop_releases_cancelled_jobs_without_waiting_for_timer() -> None:
    class Timer:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    controller = type("ControllerState", (), {})()
    controller._jobs = {"live": object()}
    controller._cancel_release = Timer()
    controller._notice = ""
    events: list[str] = []
    controller._record_log = lambda tone, message: events.append(f"{tone}:{message}")
    controller.cancel = lambda: events.append("cancel")
    controller._release_cancelled_jobs = lambda: events.append("release")

    Controller.forceStop(controller)

    assert controller._cancel_release.stopped
    assert events == ["warning:Запрошена принудительная остановка.", "cancel", "release"]
    assert "Нераспознанный хвост" in controller._notice


def test_abort_emergency_idle_returns_to_idle_and_stops_workers() -> None:
    class IdleRelease:
        def stop(self):
            self.stopped = True

        stopped = False

    release = IdleRelease()
    controller = type("ControllerState", (), {})()
    controller._closing = False
    controller._jobs = {}
    controller._model_preparing = True
    controller._state = "recording"
    controller._level = 0.6
    controller._idle_model_release = release
    events: list[str] = []
    controller.forceStop = lambda: events.append("force")
    controller._arm_idle_model_release = lambda: events.append("arm")

    Controller.abortEmergency(controller)

    assert controller._closing is True
    assert controller._state == "idle"
    assert controller._level == 0.0
    assert controller._model_preparing is False
    assert events == ["arm"]  # без активных работ модель не отжимается принудительно
    assert release.stopped is True


def test_abort_emergency_cancels_running_jobs_when_capture_is_active() -> None:
    class IdleRelease:
        def stop(self):
            self.stopped = True

        stopped = False

    release = IdleRelease()
    controller = type("ControllerState", (), {})()
    controller._closing = False
    controller._jobs = {"live": object()}
    controller._model_preparing = False
    controller._state = "recording"
    controller._level = 0.6
    controller._idle_model_release = release
    events: list[str] = []
    controller.forceStop = lambda: events.append("force")
    controller._arm_idle_model_release = lambda: events.append("arm")

    Controller.abortEmergency(controller)

    assert controller._closing is True
    assert controller._state == "idle"
    assert controller._level == 0.0
    assert events == ["force"]
    assert release.stopped is True


def test_pending_seek_defaults_to_none() -> None:
    controller = Controller.__new__(Controller)
    controller._pending_seek_ms = -1
    controller._media_url = ""
    controller.changed = _Counting()

    assert Controller.pendingSeekMs.fget(controller) == -1

    Controller.seekMediaTo(controller, 12.5)
    assert controller._pending_seek_ms == -1
    assert controller.changed.count == 0

    controller._media_url = "file:///tmp/sample.wav"
    Controller.seekMediaTo(controller, 3.2)
    assert controller._pending_seek_ms == 3200
    assert controller.changed.count == 1

    Controller.clearPendingSeek(controller)
    assert controller._pending_seek_ms == -1
    assert controller.changed.count == 2


def test_open_session_at_sets_page_and_pending_seek(tmp_path) -> None:
    media = tmp_path / "talk.wav"
    media.write_bytes(b"RIFF")
    controller = Controller.__new__(Controller)
    controller._jobs = {}
    controller._session_id = ""
    controller._media_url = ""
    controller._page = "live"
    controller._query = ""
    controller._segments = []
    controller._edit_undo = []
    controller._edit_redo = []
    controller._session_mode = ""
    controller._session_title = ""
    controller._status = ""
    controller._trans_state = {}
    controller._pending_seek_ms = -1
    controller._media_peaks = []
    controller._media_peaks_duration = 0.0
    controller._media_peaks_token = 0
    controller.segmentsChanged = _Signal()
    controller.transcribeChanged = _Signal()
    controller.changed = _Counting()
    controller.mediaPeaksReady = _Signal()
    session_id = "rec-with-media"
    controller.store = type(
        "Store",
        (),
        {
            "get_session": staticmethod(
                lambda sid: {
                    "id": session_id,
                    "title": "Talk",
                    "mode": "transcript",
                    "source": str(media),
                    "segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "hi"}],
                }
                if sid == session_id
                else None
            ),
            "list_sessions": staticmethod(lambda _query: []),
        },
    )()
    controller._open_transcript_session = Controller._open_transcript_session.__get__(
        controller, Controller
    )

    Controller.openSessionAt(controller, session_id, 42.0)

    assert controller._session_id == session_id
    assert controller._page == "transcript"
    assert controller._pending_seek_ms == 42000
    assert controller._media_url.startswith("file:")
