"""Подписи говорящих для страницы «Транскрибация».

Роли движка (0-based) пользователь видит как 1-based ключи с коротким
русским именем. Оценка пола по pitch/F0 без librosa слишком шумная на
коротких фразах и смешанных дорожках, поэтому по умолчанию всегда
«Голос N», а не «Парень»/«Девушка». Вид можно сменить вручную.
"""

from __future__ import annotations

_KIND_PREFIX = {
    "voice": "Голос",
    "male": "Парень",
    "female": "Девушка",
}


def speaker_label_for_kind(key: int, kind: str) -> str:
    """Подпись по 1-based ключу и виду: voice|male|female."""

    prefix = _KIND_PREFIX.get(str(kind or "voice").strip().lower(), _KIND_PREFIX["voice"])
    return f"{prefix} {int(key)}"


def default_speaker_label(key: int) -> str:
    """Человекочитаемая подпись для 1-based ключа роли."""

    return speaker_label_for_kind(key, "voice")


def is_default_speaker_label(label: str, key: int) -> bool:
    """True, если подпись совпадает с любой из трёх стандартных для ключа."""

    cleaned = " ".join(str(label or "").strip().split())
    if not cleaned:
        return False
    key_i = int(key)
    return cleaned in {
        speaker_label_for_kind(key_i, "voice"),
        speaker_label_for_kind(key_i, "male"),
        speaker_label_for_kind(key_i, "female"),
    }
