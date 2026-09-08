import time

from dotaudio.capture import next_live_source
from dotaudio.controller import (
    DEFAULTS,
    HOTKEY_OPTIONS,
    MODEL_BY_PROFILE,
    STATUS_LABELS,
    Controller,
    sensitivity_label,
)
from dotaudio.engine import Engine


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
    assert DEFAULTS["caption_overlay"] is True
    assert DEFAULTS["caption_size"] == "md"
    assert DEFAULTS["caption_contrast"] == "normal"


def test_segments_have_a_dedicated_qt_notify_signal() -> None:
    """Frequent Live status updates must not rebuild the whole transcript list."""
    meta = Controller.staticMetaObject
    prop = meta.property(meta.indexOfProperty("segments"))

    assert bytes(prop.notifySignal().name()).decode() == "segmentsChanged"


def test_engine_statuses_have_russian_labels() -> None:
    assert STATUS_LABELS["loading_model"].startswith("Загружаем")
    assert STATUS_LABELS["transcribing_cpu"].startswith("Распознаём")
    assert STATUS_LABELS["live_backlog"].startswith("Догоняем")


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
    assert DEFAULTS["dictate_hold"] is False
    assert DEFAULTS["paste_last_hotkey"] == "Shift+Alt+Z"
    assert DEFAULTS["caption_position"] == "bottom"
    assert DEFAULTS["caption_locked"] is True
    assert DEFAULTS["caption_autohide"] is False
    assert DEFAULTS["reduce_motion"] is False


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
    assert recommended_model({"threads": 2, "ram_gb": 8.0, "cuda_devices": 0}) == "base"
    assert recommended_model({"threads": 0, "ram_gb": None, "cuda_devices": 0}) == "tiny"


def test_late_live_final_does_not_replace_a_newer_preview() -> None:
    class Store:
        @staticmethod
        def append_segments(_sid, _segments):
            return [1]

    controller = type("ControllerState", (), {})()
    controller._jobs = {"live": {"mode": "live"}}
    controller.store = Store()
    controller._session_id = "live"
    controller._segments = []
    controller.segmentsChanged = _Signal()
    controller._final_end = 0.0
    controller._partial_end = 5.0
    controller._confirmed_caption = "новая фраза"
    controller._partial_caption = "продолжается"
    controller._caption_revision = 3
    controller._started = 0.0
    controller._live_latency_ms = 0.0
    controller._live_phase = "speech"
    controller.captionChanged = _Signal()
    controller.liveStateChanged = _Signal()
    controller.recording = True
    controller._record_log = lambda *_args: None
    controller.changed = _Signal()

    Controller._on_segment(
        controller, "live", {"start": 2.0, "end": 4.0, "text": "старая фраза"}
    )

    assert controller._segments[-1]["text"] == "старая фраза"
    assert controller._confirmed_caption == "новая фраза"
    assert controller._partial_caption == "продолжается"
    assert controller._caption_revision == 3


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

    for _ in range(3):
        Controller._set_status(controller, "transcribing_cpu")
        Controller._set_status(controller, "completed")

    assert controller._live_phase == "listening"
    assert controller._status == "Слушаю"
    assert controller.changed.count == 0
    assert controller.liveStateChanged.count == 6

    Controller._set_status(controller, "live_slow")
    assert controller._live_diagnostic == "live_slow"
    assert controller._status == STATUS_LABELS["live_slow"]
    assert controller.changed.count == 1


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
    controller = type("ControllerState", (), {})()
    controller._jobs = {"live": {"mode": "live"}}
    controller.liveActive = True
    controller.recording = True
    controller._capture_started_at = time.monotonic() - 30
    controller._level = 0.5
    controller._last_signal_at = time.monotonic() - 1
    controller._last_caption_at = time.monotonic() - 30
    controller._live_diagnostic = ""
    controller.displayCaption = "старая фраза"
    controller._confirmed_caption = "старая фраза"
    controller._partial_caption = ""
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
