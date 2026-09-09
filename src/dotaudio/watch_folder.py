"""Poll a directory for newly arrived media files without Qt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread

MEDIA_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".mkv", ".webm", ".aac"}

FileCallback = Callable[[Path], None]
SeenKey = tuple[str, float, int]


class WatchFolder:
    """Report stable media files that appear after watching starts."""

    def __init__(
        self,
        path: Path | str | None = None,
        on_file: FileCallback | None = None,
        *,
        suffixes: set[str] = MEDIA_SUFFIXES,
        poll_seconds: float = 2.0,
    ) -> None:
        if on_file is None:
            raise TypeError("on_file is required")
        self._on_file = on_file
        self._suffixes = {suffix.casefold() for suffix in suffixes}
        self._poll_seconds = poll_seconds
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._path: Path | None = None
        self._seen: set[SeenKey] = set()
        self._pending_sizes: dict[str, int] = {}
        self._initial_scan = True
        self.set_path(path)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="watch-folder", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(self._poll_seconds * 3.0, 1.0))
        with self._lock:
            self._thread = None

    def set_path(self, path: Path | str | None) -> None:
        with self._lock:
            if path is None or not str(path).strip():
                self._path = None
            else:
                self._path = Path(path)
            self._seen.clear()
            self._pending_sizes.clear()
            self._initial_scan = True

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self._poll_seconds)

    def _poll_once(self) -> None:
        with self._lock:
            folder = self._path
            initial_scan = self._initial_scan
            seen = self._seen
            pending_sizes = self._pending_sizes
            suffixes = self._suffixes
            on_file = self._on_file

        if folder is None or not folder.is_dir():
            return

        try:
            entries = list(folder.iterdir())
        except OSError:
            return

        for entry in entries:
            if not self._is_candidate(entry, suffixes):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue

            key = (str(entry), stat.st_mtime, stat.st_size)
            path_key = str(entry)

            if initial_scan:
                seen.add(key)
                pending_sizes[path_key] = stat.st_size
                continue

            if key in seen:
                pending_sizes[path_key] = stat.st_size
                continue

            previous_size = pending_sizes.get(path_key)
            if previous_size is None or previous_size != stat.st_size:
                pending_sizes[path_key] = stat.st_size
                continue

            seen.add(key)
            pending_sizes[path_key] = stat.st_size
            try:
                on_file(entry)
            except Exception:
                pass

        if initial_scan:
            with self._lock:
                self._initial_scan = False

    @staticmethod
    def _is_candidate(entry: Path, suffixes: set[str]) -> bool:
        if entry.name.startswith("."):
            return False
        try:
            if entry.is_dir():
                return False
        except OSError:
            return False
        return entry.suffix.casefold() in suffixes
