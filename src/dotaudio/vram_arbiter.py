"""Координация видеопамяти между ASR и локальной LLM.

Qt-free: один процесс, два «владельца» - faster-whisper на CUDA и llama.cpp
с выгрузкой слоёв на GPU. Перед загрузкой второго владелец вытесняет первого
через зарегистрированный callback.
"""

from __future__ import annotations

import threading
from typing import Callable

Owner = str  # "asr" | "llm"
EvictCallback = Callable[[], None]

_VALID_OWNERS = frozenset({"asr", "llm"})
_arbiter: VramArbiter | None = None
_arbiter_lock = threading.Lock()


class VramArbiter:
    """Простой mutex на VRAM: один активный владелец, вытеснение по callback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: Owner | None = None
        self._evict: dict[Owner, list[EvictCallback]] = {}

    def on_evict(self, owner: str, callback: EvictCallback) -> None:
        """Добавить, что освободить у этого владельца при вытеснении.

        Владелец не всегда один объект: у Live две модели Whisper - быстрая
        на черновики и выбранная на финалы. Прежняя одиночная ссылка теряла
        первую из них, и та оставалась в видеопамяти после вытеснения.
        """

        if owner not in _VALID_OWNERS:
            raise ValueError(f"unknown VRAM owner: {owner}")
        with self._lock:
            handlers = self._evict.setdefault(owner, [])
            if callback not in handlers:
                handlers.append(callback)

    def acquire(self, owner: str, *, force: bool = False) -> bool:
        if owner not in _VALID_OWNERS:
            raise ValueError(f"unknown VRAM owner: {owner}")
        with self._lock:
            current = self._owner
            if current == owner and not force:
                return True
            if current is not None and current != owner:
                for evict in tuple(self._evict.get(current, ())):
                    try:
                        evict()
                    except Exception:
                        pass
            self._owner = owner
            return True

    def release(self, owner: str) -> None:
        if owner not in _VALID_OWNERS:
            raise ValueError(f"unknown VRAM owner: {owner}")
        with self._lock:
            if self._owner == owner:
                self._owner = None

    def owner(self) -> Owner | None:
        with self._lock:
            return self._owner


def get_arbiter() -> VramArbiter:
    global _arbiter
    with _arbiter_lock:
        if _arbiter is None:
            _arbiter = VramArbiter()
        return _arbiter
