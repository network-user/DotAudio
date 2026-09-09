from __future__ import annotations

import time
from pathlib import Path

from dotaudio.watch_folder import MEDIA_SUFFIXES, WatchFolder


def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


def test_initial_scan_does_not_emit_existing_files(tmp_path: Path) -> None:
    existing = tmp_path / "old.wav"
    existing.write_bytes(b"ready")

    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.05)
    watcher.start()
    time.sleep(0.2)
    watcher.stop()

    assert seen == []


def test_emits_new_stable_media_file(tmp_path: Path) -> None:
    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.05)
    watcher.start()
    time.sleep(0.12)

    target = tmp_path / "fresh.mp3"
    target.write_bytes(b"part-one")
    _wait_until(lambda: target in seen, timeout=1.0)

    watcher.stop()
    assert seen == [target]


def test_ignores_growing_file_until_stable(tmp_path: Path) -> None:
    seen: list[Path] = []
    poll = 0.05
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=poll)
    watcher.start()
    time.sleep(poll * 3)

    target = tmp_path / "growing.wav"
    target.write_bytes(b"chunk-1")
    time.sleep(poll)
    target.write_bytes(b"chunk-1-more-data")
    time.sleep(poll)
    assert target not in seen

    _wait_until(lambda: target in seen, timeout=1.0)
    watcher.stop()
    assert seen == [target]


def test_ignores_hidden_and_non_media_files(tmp_path: Path) -> None:
    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.05)
    watcher.start()
    time.sleep(0.12)

    (tmp_path / ".hidden.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "clip.mp3").write_bytes(b"ok")

    _wait_until(lambda: (tmp_path / "clip.mp3") in seen, timeout=1.0)
    watcher.stop()

    assert seen == [tmp_path / "clip.mp3"]


def test_set_path_rebaselines_without_emitting_existing(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "seed.wav").write_bytes(b"seed")
    (second / "seed.wav").write_bytes(b"seed")

    seen: list[Path] = []
    watcher = WatchFolder(first, seen.append, poll_seconds=0.05)
    watcher.start()
    time.sleep(0.12)

    watcher.set_path(second)
    time.sleep(0.12)
    assert seen == []

    new_file = second / "arrival.flac"
    new_file.write_bytes(b"new")
    _wait_until(lambda: new_file in seen, timeout=1.0)

    watcher.stop()
    assert seen == [new_file]


def test_set_path_none_disables_watching(tmp_path: Path) -> None:
    seen: list[Path] = []
    watcher = WatchFolder(tmp_path, seen.append, poll_seconds=0.05)
    watcher.start()
    time.sleep(0.12)

    watcher.set_path(None)
    (tmp_path / "ignored.mp3").write_bytes(b"x")
    time.sleep(0.2)
    watcher.stop()

    assert seen == []


def test_media_suffixes_cover_common_formats() -> None:
    assert {".mp3", ".wav", ".mp4"}.issubset(MEDIA_SUFFIXES)
