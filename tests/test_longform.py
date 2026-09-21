"""Пороги длинных сессий: час не идёт тем же рецептом, что короткий ролик."""

from __future__ import annotations

from dotaudio.longform import (
    LONG_FORM_SECONDS,
    PEAKS_DECODE_MAX_SECONDS,
    WORD_TIMESTAMPS_MAX_SECONDS,
    TickGate,
    bounded_window_parameters,
    is_long_form,
    short_window_bounds,
    short_window_plan,
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


def test_window_bounds_recover_from_non_finite_inputs():
    assert window_bounds(float("nan"), window=10, overlap=2) == []
    bounds = window_bounds(3, window=float("nan"), overlap=float("nan"))
    assert bounds == [(0.0, 3.0)]


def test_short_window_plan_never_stalls_on_excessive_overlap():
    plan = short_window_plan(2.0, overlap=100.0)

    assert plan.window_seconds == 2.0
    assert plan.step_seconds >= 0.05
    assert plan.overlap_seconds < plan.window_seconds


def test_short_window_plan_accepts_a_forward_interval():
    plan = short_window_plan(2.0, interval=0.2)

    assert plan == type(plan)(2.0, 1.8, 0.2)
    bounds = short_window_bounds(2.5, 2.0, interval=0.2)
    assert bounds[0] == (0.0, 2.0)
    assert bounds[-1][1] == 2.5


def test_bounded_window_parameters_caps_overlap_and_keeps_a_step():
    plan = bounded_window_parameters(10, 100, min_step=0.5)

    assert plan.step_seconds >= 0.5


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
