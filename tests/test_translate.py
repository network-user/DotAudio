"""Speech modes and the local EN→RU translator."""

from __future__ import annotations

from pathlib import Path

from dotaudio.translate import (
    Translator,
    apply_post_translate,
    language_task_for,
    model_ready,
    model_status,
    needs_post_translate,
    next_speech_mode,
    normalize_speech_mode,
    speech_mode_from_language_task,
    speech_mode_label,
    translate_text,
)


def test_speech_mode_cycle_and_labels():
    assert normalize_speech_mode("EN_RU") == "en_ru"
    assert normalize_speech_mode("ru_en") == "en"
    assert normalize_speech_mode("nope") == "ru"
    assert next_speech_mode("ru") == "en"
    assert next_speech_mode("en") == "en_ru"
    assert next_speech_mode("en_ru") == "ru"
    assert speech_mode_label("en_ru") == "EN → RU"
    assert language_task_for("en_ru") == ("en", "transcribe")
    assert needs_post_translate("en_ru")
    assert not needs_post_translate("en")


def test_speech_mode_from_legacy_language_task():
    assert speech_mode_from_language_task("ru", "transcribe") == "ru"
    assert speech_mode_from_language_task("en", "transcribe") == "en"
    # Старый Whisper translate больше не отдельный режим.
    assert speech_mode_from_language_task("ru", "translate") == "en"


def test_translator_caches_and_keeps_source_on_failure():
    calls = {"n": 0}

    def render(text: str, _src: str, _dst: str) -> str:
        calls["n"] += 1
        return "Привет" if text == "Hello" else text

    engine = Translator(translate_fn=render)
    assert engine.translate("Hello", "en", "ru") == "Привет"
    assert engine.translate("Hello", "en", "ru") == "Привет"
    assert calls["n"] == 1

    def boom(_text: str, _src: str, _dst: str) -> str:
        raise RuntimeError("broken")

    failing = Translator(translate_fn=boom)
    assert failing.translate("Hello", "en", "ru") == "Hello"
    assert "broken" in failing.last_error


def test_translator_rejects_non_en_ru_pair():
    engine = Translator(translate_fn=lambda text, *_: "нет")
    assert engine.translate("Hello", "ru", "en") == "Hello"
    assert "EN→RU" in engine.last_error


def test_apply_post_translate_rewrites_text_and_drops_words():
    engine = Translator(translate_fn=lambda text, *_: "Здравствуйте")
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
    untouched = apply_post_translate(segment, "en", translator=engine)
    assert untouched is segment or untouched["text"] == "Hello there"


def test_translate_text_helper_uses_default_engine(monkeypatch):
    from dotaudio import translate as module

    fake = Translator(translate_fn=lambda text, *_: "Мир")
    monkeypatch.setattr(module, "_default", fake)
    assert translate_text("World", "en", "ru") == "Мир"


def test_model_status_without_files(tmp_path: Path):
    status = model_status(tmp_path)
    assert status["ready"] is False
    assert status["phase"] == "missing"
    assert model_ready(tmp_path) is False


def test_legacy_fetch_hook_still_works_for_old_tests():
    engine = Translator(
        fetch=lambda _text: {
            "responseData": {"translatedText": "Мир"},
            "responseStatus": 200,
        }
    )
    assert engine.translate("World", "en", "ru") == "Мир"
