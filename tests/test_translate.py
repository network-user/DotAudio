"""Speech modes and the EN→RU post-ASR translator."""

from __future__ import annotations

from dotaudio.translate import (
    Translator,
    apply_post_translate,
    language_task_for,
    needs_post_translate,
    next_speech_mode,
    normalize_speech_mode,
    speech_mode_from_language_task,
    speech_mode_label,
    translate_text,
)


def test_speech_mode_cycle_and_labels():
    assert normalize_speech_mode("RU_EN") == "ru_en"
    assert normalize_speech_mode("nope") == "ru"
    assert next_speech_mode("ru") == "en"
    assert next_speech_mode("en") == "ru_en"
    assert next_speech_mode("ru_en") == "en_ru"
    assert next_speech_mode("en_ru") == "ru"
    assert speech_mode_label("ru_en") == "RU → EN"
    assert language_task_for("ru_en") == ("ru", "translate")
    assert language_task_for("en_ru") == ("en", "transcribe")
    assert needs_post_translate("en_ru")
    assert not needs_post_translate("ru_en")


def test_speech_mode_from_legacy_language_task():
    assert speech_mode_from_language_task("ru", "transcribe") == "ru"
    assert speech_mode_from_language_task("en", "transcribe") == "en"
    assert speech_mode_from_language_task("ru", "translate") == "ru_en"
    assert speech_mode_from_language_task("auto", "translate") == "ru_en"


def test_translator_caches_and_keeps_source_on_failure():
    calls = {"n": 0}

    def fetch(_text: str) -> dict:
        calls["n"] += 1
        return {"responseData": {"translatedText": "Привет"}, "responseStatus": 200}

    engine = Translator(fetch=fetch)
    assert engine.translate("Hello", "en", "ru") == "Привет"
    assert engine.translate("Hello", "en", "ru") == "Привет"
    assert calls["n"] == 1

    def boom(_text: str) -> dict:
        raise RuntimeError("offline")

    failing = Translator(fetch=boom)
    assert failing.translate("Hello", "en", "ru") == "Hello"
    assert "offline" in failing.last_error


def test_apply_post_translate_rewrites_text_and_drops_words():
    engine = Translator(
        fetch=lambda _text: {
            "responseData": {"translatedText": "Здравствуйте"},
            "responseStatus": 200,
        }
    )
    segment = {
        "start": 0.0,
        "end": 1.2,
        "text": "Hello there",
        "words": [{"text": "Hello", "start": 0.0, "end": 0.4}],
    }
    updated = apply_post_translate(segment, "en_ru", translator=engine)
    assert updated["text"] == "Здравствуйте"
    assert updated["source_text"] == "Hello there"
    assert updated["words"] == []
    untouched = apply_post_translate(segment, "ru_en", translator=engine)
    assert untouched is segment or untouched["text"] == "Hello there"


def test_translate_text_helper_uses_default_engine(monkeypatch):
    from dotaudio import translate as module

    fake = Translator(
        fetch=lambda _text: {
            "responseData": {"translatedText": "Мир"},
            "responseStatus": 200,
        }
    )
    monkeypatch.setattr(module, "_default", fake)
    assert translate_text("World", "en", "ru") == "Мир"
