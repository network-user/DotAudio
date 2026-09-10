"""Пороги и вспомогательные штуки для многочасовых расшифровок.

Qt-free. Контроллер, движок и диаризация читают одни и те же числа, чтобы
часовой файл не шёл тем же рецептом, что трёхминутный ролик.
"""

from __future__ import annotations

import time

# Дальше этого порога сессия считается длинной: VAD, без пословных таймингов
# караоке, реже тики в QML. Час точно попадает; короткие клипы не трогаем.
LONG_FORM_SECONDS = 12 * 60
# Пословные тайминги нужны караоке и нарезке фразы по смене голоса. На часе
# они удваивают работу Whisper и почти не видны в списке реплик.
WORD_TIMESTAMPS_MAX_SECONDS = 8 * 60
# Полный decode ради waveform на часовом MP3 конкурирует с распознаванием.
PEAKS_DECODE_MAX_SECONDS = 15 * 60
UI_TICK_SECONDS = 0.45
UI_TICK_EVERY_SEGMENTS = 12

# Полный attention Sortformer держит ~6,6 мин. Окно короче этого: на CPU
# streaming часто отдаёт пустую разметку, а `--offline` на часе падает.
DIARIZE_WINDOW_SECONDS = 5 * 60
DIARIZE_OVERLAP_SECONDS = 15.0
DIARIZE_OFFLINE_MAX_SECONDS = 6 * 60


def is_long_form(duration_s: float) -> bool:
    """True, если длительность известна и уже не короткий клип."""

    return float(duration_s or 0.0) >= LONG_FORM_SECONDS


def want_word_timestamps(duration_s: float, *, karaoke: bool = False) -> bool:
    """Слова считаем только для короткого файла или если включено караоке."""

    if karaoke:
        return True
    seconds = float(duration_s or 0.0)
    if seconds <= 0:
        return False
    return seconds < WORD_TIMESTAMPS_MAX_SECONDS


def window_bounds(
    seconds: float,
    window: float = DIARIZE_WINDOW_SECONDS,
    overlap: float = DIARIZE_OVERLAP_SECONDS,
) -> list[tuple[float, float]]:
    """Окна с перекрытием, последнее всегда дотягивает до конца записи."""

    total = max(0.0, float(seconds))
    span = max(1.0, float(window))
    shared = min(max(0.0, float(overlap)), span * 0.49)
    if total <= 0:
        return []
    if total <= span:
        return [(0.0, total)]
    step = span - shared
    bounds: list[tuple[float, float]] = []
    start = 0.0
    while start < total:
        end = min(total, start + span)
        bounds.append((start, end))
        if end >= total:
            break
        start += step
    return bounds


class TickGate:
    """Пропускает первый тик, затем не чаще интервала или каждого N-го."""

    def __init__(
        self,
        interval_s: float = UI_TICK_SECONDS,
        every_n: int = UI_TICK_EVERY_SEGMENTS,
        clock=time.monotonic,
    ) -> None:
        self.interval_s = max(0.05, float(interval_s))
        self.every_n = max(1, int(every_n))
        self._clock = clock
        self._last = 0.0
        self._n = 0

    def allow(self, *, force: bool = False) -> bool:
        self._n += 1
        now = self._clock()
        if force or self._n == 1 or self._n % self.every_n == 0:
            self._last = now
            return True
        if now - self._last >= self.interval_s:
            self._last = now
            return True
        return False


__all__ = [
    "DIARIZE_OFFLINE_MAX_SECONDS",
    "DIARIZE_OVERLAP_SECONDS",
    "DIARIZE_WINDOW_SECONDS",
    "LONG_FORM_SECONDS",
    "PEAKS_DECODE_MAX_SECONDS",
    "TickGate",
    "UI_TICK_EVERY_SEGMENTS",
    "UI_TICK_SECONDS",
    "WORD_TIMESTAMPS_MAX_SECONDS",
    "is_long_form",
    "want_word_timestamps",
    "window_bounds",
]
