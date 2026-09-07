from dotaudio.capture import next_live_source
from dotaudio.controller import (
    DEFAULTS,
    HOTKEY_OPTIONS,
    MODEL_BY_PROFILE,
    STATUS_LABELS,
    Controller,
)
from dotaudio.engine import Engine


class _Signal:
    def emit(self, *_args) -> None:
        pass


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


def test_disk_status_describes_cache_without_downloading() -> None:
    info = Engine.disk_status("tiny")
    assert info["model"] == "tiny"
    assert info["bytes"] >= 0
    assert "message" in info


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
