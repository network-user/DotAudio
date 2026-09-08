"""Drop Whisper hallucinations that people did not say.

Whisper was trained on a lot of video subtitles.  In silence or at the end of
a short utterance it completes the most likely "text where nothing was said" —
often translator credits and video outros: «Субтитры создавал…»,
«Продолжение следует…», «Thanks for watching».

Two checks run together:

1. Exact / signature match against known credit phrases (normalised).
2. Confidence: high ``no_speech_prob`` together with a weak ``avg_logprob``.

Live already gates on log probability for music; this module covers the
phrase blacklist for dictation and offline files, and the dual confidence
check when segment metadata is available.
"""

from __future__ import annotations

import re

_EXACT = {
    "продолжение следует",
    "продолжение следует...",
    "спасибо за просмотр",
    "спасибо за внимание",
    "подписывайтесь на канал",
    "подписывайся на канал",
    "ставьте лайки и подписывайтесь на канал",
    "не забудьте подписаться",
    "всем пока",
    "до новых встреч",
    "приятного просмотра",
    "редактор субтитров",
    "субтитры",
    "конец",
    "the end",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "see you next time",
    "bye",
}

_SIGNATURES = (
    "dimatorzok",
    "субтитры создавал",
    "субтитры создал",
    "субтитры сделал",
    "субтитры делал",
    "субтитры подготовил",
    "редактор субтитров",
    "корректор а.",
    "субтитры и перевод",
    "перевод и субтитры",
    "amara.org",
    "subtitles by",
    "subs by",
    "проект «мир",
    "игорь негода",
)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")

_NO_SPEECH = 0.7
_LOW_CONFIDENCE = -0.9


def _normalise(text: str) -> str:
    return _SPACES.sub(" ", _PUNCT.sub("", text.lower())).strip()


def looks_invented(
    text: str,
    no_speech_prob: float = 0.0,
    avg_logprob: float = 0.0,
) -> str:
    """Reason to drop the chunk, or an empty string when it looks real."""

    normalised = _normalise(text)
    if not normalised:
        return "пусто"

    for signature in _SIGNATURES:
        if signature in normalised:
            return f"подпись субтитров: {signature}"

    if normalised in _EXACT:
        return "типовая концовка ролика"

    if no_speech_prob >= _NO_SPEECH and avg_logprob <= _LOW_CONFIDENCE:
        return (
            f"тишина по мнению модели "
            f"(no_speech {no_speech_prob:.2f}, logprob {avg_logprob:.2f})"
        )

    return ""
