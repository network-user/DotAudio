from dotaudio.controller import DEFAULTS, HOTKEY_OPTIONS, STATUS_LABELS, Controller


def test_live_source_defaults_to_system_audio() -> None:
    assert DEFAULTS["live_source"] == "system"
    assert DEFAULTS["source"] == "microphone"


def test_caption_overlay_settings_are_local_and_sized() -> None:
    assert DEFAULTS["caption_overlay"] is False
    assert DEFAULTS["caption_size"] == "md"
    assert DEFAULTS["caption_contrast"] == "normal"


def test_engine_statuses_have_russian_labels() -> None:
    assert STATUS_LABELS["loading_model"].startswith("Загружаем")
    assert STATUS_LABELS["transcribing_cpu"].startswith("Распознаём")


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
