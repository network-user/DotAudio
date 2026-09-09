"""Speech I/O modes and a thin text translator for EN→RU.

Whisper `task=translate` only ever produces English. Russian output from
English speech needs a second step after ASR. For the first test pass that
step talks to the free MyMemory HTTP API (httpx is already a dependency);
offline failure leaves the recogniser text unchanged and reports why.
"""

from __future__ import annotations

import threading
from typing import Callable
from urllib.parse import quote

# speech_mode → (language, task) for RecognitionConfig.
# en_ru keeps ASR on English; the controller then runs translate_text.
SPEECH_MODES: dict[str, tuple[str, str]] = {
    "ru": ("ru", "transcribe"),
    "en": ("en", "transcribe"),
    "ru_en": ("ru", "translate"),
    "en_ru": ("en", "transcribe"),
}

SPEECH_MODE_ORDER = ("ru", "en", "ru_en", "en_ru")

SPEECH_MODE_LABELS = {
    "ru": "Русский",
    "en": "English",
    "ru_en": "RU → EN",
    "en_ru": "EN → RU",
}

SPEECH_MODE_HINTS = {
    "ru": "Распознавание русской речи как есть",
    "en": "Распознавание английской речи как есть",
    "ru_en": "Русская речь → английский текст (Whisper Translate)",
    "en_ru": "Английская речь → русский текст (ASR + сетевой перевод)",
}

# Pair for the post-ASR step. Whisper already covers ru_en.
POST_TRANSLATE = {
    "en_ru": ("en", "ru"),
}

_MYMEMORY = "https://api.mymemory.translated.net/get"


def normalize_speech_mode(value: object) -> str:
    mode = str(value or "ru").strip().lower()
    return mode if mode in SPEECH_MODES else "ru"


def speech_mode_label(value: object) -> str:
    return SPEECH_MODE_LABELS[normalize_speech_mode(value)]


def speech_mode_hint(value: object) -> str:
    return SPEECH_MODE_HINTS[normalize_speech_mode(value)]


def next_speech_mode(current: object) -> str:
    mode = normalize_speech_mode(current)
    index = SPEECH_MODE_ORDER.index(mode)
    return SPEECH_MODE_ORDER[(index + 1) % len(SPEECH_MODE_ORDER)]


def language_task_for(mode: object) -> tuple[str, str]:
    return SPEECH_MODES[normalize_speech_mode(mode)]


def speech_mode_from_language_task(language: object, task: object) -> str:
    """Recover speech_mode from older language/task settings."""

    lang = str(language or "ru").strip().lower()
    work = str(task or "transcribe").strip().lower()
    if work == "translate":
        return "ru_en"
    if lang == "en":
        return "en"
    if lang == "ru":
        return "ru"
    return "ru"


def needs_post_translate(mode: object) -> bool:
    return normalize_speech_mode(mode) in POST_TRANSLATE


def post_pair(mode: object) -> tuple[str, str] | None:
    return POST_TRANSLATE.get(normalize_speech_mode(mode))


class Translator:
    """Cached text translator with an injectable HTTP getter for tests."""

    def __init__(
        self,
        *,
        fetch: Callable[[str], dict] | None = None,
        timeout: float = 4.0,
    ) -> None:
        self._fetch = fetch
        self._timeout = float(timeout)
        self._cache: dict[tuple[str, str, str], str] = {}
        self._lock = threading.Lock()
        self.last_error = ""

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
        self.last_error = ""

    def translate(self, text: str, source: str, target: str) -> str:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        src = str(source or "").strip().lower()
        dst = str(target or "").strip().lower()
        if not src or not dst or src == dst:
            return cleaned
        key = (cleaned.casefold(), src, dst)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            self.last_error = ""
            return hit
        try:
            rendered = self._request(cleaned, src, dst)
        except Exception as exc:  # noqa: BLE001 - surface any network/API fault
            self.last_error = str(exc) or exc.__class__.__name__
            return cleaned
        if not rendered:
            self.last_error = self.last_error or "пустой ответ переводчика"
            return cleaned
        self.last_error = ""
        with self._lock:
            self._cache[key] = rendered
        return rendered

    def _request(self, text: str, source: str, target: str) -> str:
        if self._fetch is not None:
            payload = self._fetch(text)
        else:
            payload = self._fetch_mymemory(text, source, target)
        data = payload.get("responseData") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError("переводчик вернул неожиданный ответ")
        rendered = str(data.get("translatedText") or "").strip()
        # MyMemory echoes "QUERY LENGTH LIMIT EXCEEDED..." as translatedText.
        if rendered.upper().startswith("QUERY LENGTH LIMIT"):
            raise RuntimeError("фраза слишком длинная для тестового переводчика")
        if "MYMEMORY WARNING" in rendered.upper():
            raise RuntimeError("лимит тестового переводчика на сегодня")
        return rendered

    def _fetch_mymemory(self, text: str, source: str, target: str) -> dict:
        import httpx

        url = f"{_MYMEMORY}?q={quote(text)}&langpair={quote(f'{source}|{target}')}"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("переводчик вернул не JSON-объект")
        status = payload.get("responseStatus")
        if status not in (None, 200, "200"):
            detail = str(payload.get("responseDetails") or status)
            raise RuntimeError(f"переводчик отклонил запрос: {detail}")
        return payload


_default = Translator()


def translate_text(text: str, source: str, target: str, *, translator: Translator | None = None) -> str:
    engine = translator or _default
    return engine.translate(text, source, target)


def apply_post_translate(
    segment: dict,
    mode: object,
    *,
    translator: Translator | None = None,
) -> dict:
    """Return a copy with text translated when the speech mode needs it."""

    pair = post_pair(mode)
    if pair is None:
        return segment
    source, target = pair
    original = str(segment.get("text") or "").strip()
    if not original:
        return segment
    rendered = translate_text(original, source, target, translator=translator)
    if rendered == original:
        return segment
    updated = {**segment, "text": rendered, "source_text": original}
    # Word timings belong to the ASR language; after MT they would mislead.
    if "words" in updated:
        updated = {**updated, "words": []}
    return updated
