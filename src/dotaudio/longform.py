"""Пороги и вспомогательные штуки для многочасовых расшифровок.

Qt-free. Контроллер, движок и диаризация читают одни и те же числа, чтобы
часовой файл не шёл тем же рецептом, что трёхминутный ролик.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

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

# Short rolling windows need a separate policy: an overlap close to the whole
# window can otherwise make the consumer repeat almost the same decode forever.
SHORT_WINDOW_MIN_SECONDS = 0.25
SHORT_WINDOW_MAX_SECONDS = 30.0
SHORT_WINDOW_MIN_STEP_SECONDS = 0.05
SHORT_WINDOW_MAX_OVERLAP_RATIO = 0.90


@dataclass(frozen=True)
class WindowPlan:
    """A bounded window and its forward step in seconds."""

    window_seconds: float
    overlap_seconds: float
    step_seconds: float


def _finite_or(value: float, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def bounded_window_parameters(
    window: float,
    overlap: float,
    *,
    min_window: float = 1.0,
    max_window: float | None = None,
    max_overlap_ratio: float = 0.49,
    min_step: float = 0.01,
) -> WindowPlan:
    """Clamp window parameters while guaranteeing forward progress."""

    lower = max(0.01, _finite_or(min_window, 1.0))
    upper = _finite_or(max_window, 0.0) if max_window is not None else None
    if upper is not None:
        upper = max(lower, upper)
    span = max(lower, _finite_or(window, lower))
    if upper is not None:
        span = min(span, upper)
    ratio = min(0.99, max(0.0, _finite_or(max_overlap_ratio, 0.49)))
    step_floor = min(span, max(0.001, _finite_or(min_step, 0.01)))
    shared = min(max(0.0, _finite_or(overlap, 0.0)), span * ratio, span - step_floor)
    return WindowPlan(span, shared, span - shared)


def short_window_plan(
    window: float,
    *,
    overlap: float | None = None,
    interval: float | None = None,
) -> WindowPlan:
    """Return safe parameters for a short rolling recognition window.

    Pass either ``overlap`` or the desired forward ``interval``.  Supplying
    both is ambiguous and rejected.
    """

    if overlap is not None and interval is not None:
        raise ValueError("pass either overlap or interval, not both")
    span = min(
        SHORT_WINDOW_MAX_SECONDS,
        max(SHORT_WINDOW_MIN_SECONDS, _finite_or(window, SHORT_WINDOW_MIN_SECONDS)),
    )
    if interval is not None:
        step = min(
            span,
            max(
                SHORT_WINDOW_MIN_STEP_SECONDS,
                _finite_or(interval, SHORT_WINDOW_MIN_STEP_SECONDS),
            ),
        )
        shared = span - step
    else:
        shared = min(
            span * SHORT_WINDOW_MAX_OVERLAP_RATIO,
            max(0.0, _finite_or(overlap, 0.0)),
            max(0.0, span - SHORT_WINDOW_MIN_STEP_SECONDS),
        )
    return WindowPlan(span, shared, round(span - shared, 10))


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
    *,
    max_overlap_ratio: float = 0.49,
    min_step: float = 0.01,
) -> list[tuple[float, float]]:
    """Окна с перекрытием, последнее всегда дотягивает до конца записи."""

    total = max(0.0, _finite_or(seconds, 0.0))
    # A non-finite window is an unavailable duration hint, not a request for
    # one-second windows.  Keep the legacy and least-surprising behaviour for
    # short media: process the known recording as one bounded window.
    try:
        if not math.isfinite(float(window)):
            window = total
    except (TypeError, ValueError):
        window = total
    plan = bounded_window_parameters(
        window,
        overlap,
        max_overlap_ratio=max_overlap_ratio,
        min_step=min_step,
    )
    span, step = plan.window_seconds, plan.step_seconds
    if total <= 0:
        return []
    if total <= span:
        return [(0.0, total)]
    bounds: list[tuple[float, float]] = []
    start = 0.0
    while start < total:
        end = min(total, start + span)
        bounds.append((start, end))
        if end >= total:
            break
        next_start = start + step
        if next_start <= start:
            break
        start = next_start
    return bounds


def short_window_bounds(
    seconds: float,
    window: float,
    *,
    overlap: float | None = None,
    interval: float | None = None,
) -> list[tuple[float, float]]:
    """Split a short recording into bounded rolling windows."""

    plan = short_window_plan(window, overlap=overlap, interval=interval)
    return window_bounds(
        seconds,
        plan.window_seconds,
        plan.overlap_seconds,
        max_overlap_ratio=SHORT_WINDOW_MAX_OVERLAP_RATIO,
        min_step=SHORT_WINDOW_MIN_STEP_SECONDS,
    )


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
    "SHORT_WINDOW_MAX_OVERLAP_RATIO",
    "SHORT_WINDOW_MAX_SECONDS",
    "SHORT_WINDOW_MIN_SECONDS",
    "SHORT_WINDOW_MIN_STEP_SECONDS",
    "DIARIZE_OFFLINE_MAX_SECONDS",
    "DIARIZE_OVERLAP_SECONDS",
    "DIARIZE_WINDOW_SECONDS",
    "LONG_FORM_SECONDS",
    "PEAKS_DECODE_MAX_SECONDS",
    "TickGate",
    "UI_TICK_EVERY_SEGMENTS",
    "UI_TICK_SECONDS",
    "WORD_TIMESTAMPS_MAX_SECONDS",
    "WindowPlan",
    "bounded_window_parameters",
    "is_long_form",
    "short_window_bounds",
    "short_window_plan",
    "want_word_timestamps",
    "window_bounds",
]
