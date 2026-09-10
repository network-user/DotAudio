"""Пороги длинных сессий: час не идёт тем же рецептом, что короткий ролик."""

from __future__ import annotations

from dotaudio.longform import (
    LONG_FORM_SECONDS,
    PEAKS_DECODE_MAX_SECONDS,
    WORD_TIMESTAMPS_MAX_SECONDS,
    TickGate,
    is_long_form,
    want_word_timestamps,
    window_bounds,
)


def test_hour_is_long_form_and_skips_word_timings():
    assert is_long_form(3600)
    assert not is_long_form(90)
    assert not want_word_timestamps(3600)
    assert want_word_timestamps(120)
    assert want_word_timestamps(3600, karaoke=True)
    assert not want_word_timestamps(0)
    assert LONG_FORM_SECONDS > WORD_TIMESTAMPS_MAX_SECONDS
    assert PEAKS_DECODE_MAX_SECONDS >= LONG_FORM_SECONDS


def test_window_bounds_cover_an_hour_with_overlap():
    bounds = window_bounds(3600, window=480, overlap=24)
    assert bounds[0] == (0.0, 480.0)
    assert bounds[-1][1] == 3600.0
    for left, right in zip(bounds, bounds[1:]):
        assert left[1] > right[0]
        assert right[0] - left[0] == 456.0


def test_short_clip_is_a_single_window():
    assert window_bounds(90, window=480, overlap=24) == [(0.0, 90.0)]
    assert window_bounds(0) == []


def test_tick_gate_lets_the_first_update_through():
    gate = TickGate(interval_s=30.0, every_n=100)
    assert gate.allow()
    assert not gate.allow()
    assert gate.allow(force=True)


def test_tick_gate_opens_after_interval():
    now = [0.0]

    def clock():
        return now[0]

    gate = TickGate(interval_s=0.05, every_n=1000, clock=clock)
    assert gate.allow()
    assert not gate.allow()
    now[0] = 0.06
    assert gate.allow()
