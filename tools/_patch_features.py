"""One-shot patch for features 1-9 wiring. Run from repo root."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new.strip() and new in text:
            print(f"SKIP {label}: already applied")
            return
        raise SystemExit(f"FAIL {label}: old block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"OK {label}")


def patch_desktop() -> None:
    path = ROOT / "src/dotaudio/desktop.py"
    replace_once(
        path,
        '_HOTKEY_IDS = {"dictate": 41, "island": 42, "paste_last": 43, "quit": 44}',
        '_HOTKEY_IDS = {\n'
        '    "dictate": 41,\n'
        '    "island": 42,\n'
        '    "paste_last": 43,\n'
        '    "quit": 44,\n'
        '    "cancel": 45,\n'
        "}\n"
        "VK_ESCAPE = 0x1B",
        "desktop hotkey ids",
    )
    text = path.read_text(encoding="utf-8")
    if "cancel_requested = Signal()" not in text:
        text = text.replace(
            "quit_requested = Signal()\n",
            "quit_requested = Signal()\n    cancel_requested = Signal()\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK desktop cancel signal")
    text = path.read_text(encoding="utf-8")
    if "_cancel_hotkey" not in text:
        text = text.replace(
            "self._quit_hotkey = Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x58)\n",
            "self._quit_hotkey = Hotkey(MOD_NOREPEAT | MOD_ALT | MOD_CONTROL, 0x58)\n"
            "        self._cancel_hotkey = Hotkey(MOD_NOREPEAT, VK_ESCAPE)\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK desktop cancel default")
    text = path.read_text(encoding="utf-8")
    if '"cancel": self._cancel_hotkey' not in text:
        text = text.replace(
            '"quit": self._quit_hotkey,\n'
            "                }\n"
            "            )",
            '"quit": self._quit_hotkey,\n'
            '                    "cancel": self._cancel_hotkey,\n'
            "                }\n"
            "            )",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK desktop startup cancel binding")
    text = path.read_text(encoding="utf-8")
    if 'merged.setdefault("cancel"' not in text:
        text = text.replace(
            'merged.setdefault("quit", self._quit_hotkey)\n'
            "        bindings = merged",
            'merged.setdefault("quit", self._quit_hotkey)\n'
            '        if "cancel" in bindings and isinstance(bindings["cancel"], Hotkey):\n'
            "            self._cancel_hotkey = bindings[\"cancel\"]\n"
            '        merged.setdefault("cancel", self._cancel_hotkey)\n'
            "        bindings = merged",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK desktop merge cancel")
    text = path.read_text(encoding="utf-8")
    if "msg.wParam == 45" not in text:
        text = text.replace(
            "elif msg.wParam == 44:\n"
            "                    self.quit_requested.emit()\n",
            "elif msg.wParam == 44:\n"
            "                    self.quit_requested.emit()\n"
            "                elif msg.wParam == 45:\n"
            "                    self.cancel_requested.emit()\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK desktop cancel event")


def patch_engine() -> None:
    path = ROOT / "src/dotaudio/engine.py"
    text = path.read_text(encoding="utf-8")
    if "class DownloadCancelled" not in text:
        text = text.replace(
            "class DownloadTracker:",
            "class DownloadCancelled(RuntimeError):\n"
            '    """Загрузка модели остановлена по просьбе пользователя."""\n'
            "\n"
            "\n"
            "class DownloadTracker:",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK engine DownloadCancelled")
    text = path.read_text(encoding="utf-8")
    if "cancel: Event | None = None,\n    ) -> None:\n        self._emit = emit" not in text and "self._cancel = cancel" not in text:
        text = text.replace(
            "def __init__(self, emit: ProgressCallback, interval: float = 0.3, silent: bool = False) -> None:\n"
            "        self._emit = emit\n"
            "        self._interval = interval\n"
            "        self._silent = silent\n"
            "        self._lock = Lock()\n",
            "def __init__(\n"
            "        self,\n"
            "        emit: ProgressCallback,\n"
            "        interval: float = 0.3,\n"
            "        silent: bool = False,\n"
            "        cancel: Event | None = None,\n"
            "    ) -> None:\n"
            "        self._emit = emit\n"
            "        self._interval = interval\n"
            "        self._silent = silent\n"
            "        self._cancel = cancel\n"
            "        self._lock = Lock()\n",
            1,
        )
        # insert raise_if_cancelled after __init__ block ends at _last_emit
        text = text.replace(
            "        self._last_emit = 0.0\n\n"
            "    def _snapshot(self) -> dict:",
            "        self._last_emit = 0.0\n\n"
            "    def raise_if_cancelled(self) -> None:\n"
            "        if self._cancel is not None and self._cancel.is_set():\n"
            '            raise DownloadCancelled("model download cancelled")\n\n'
            "    def _snapshot(self) -> dict:",
            1,
        )
        text = text.replace(
            "    def _push(self, force: bool = False) -> None:\n"
            "        now = time.monotonic()\n",
            "    def _push(self, force: bool = False) -> None:\n"
            "        self.raise_if_cancelled()\n"
            "        now = time.monotonic()\n",
            1,
        )
        text = text.replace(
            "    def register(self, total: int | None, initial: int) -> None:\n"
            "        with self._lock:\n",
            "    def register(self, total: int | None, initial: int) -> None:\n"
            "        self.raise_if_cancelled()\n"
            "        with self._lock:\n",
            1,
        )
        text = text.replace(
            "    def add(self, delta: int) -> None:\n"
            "        with self._lock:\n",
            "    def add(self, delta: int) -> None:\n"
            "        self.raise_if_cancelled()\n"
            "        with self._lock:\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK engine tracker cancel")
    text = path.read_text(encoding="utf-8")
    if "cancel: Event | None = None,\n    ) -> str:" not in text:
        text = text.replace(
            "        on_progress: ProgressCallback | None = None,\n"
            "    ) -> str:\n"
            '        """Download and initialise a local model before the user starts recording.',
            "        on_progress: ProgressCallback | None = None,\n"
            "        cancel: Event | None = None,\n"
            "    ) -> str:\n"
            '        """Download and initialise a local model before the user starts recording.',
            1,
        )
        text = text.replace(
            '            return "remote"\n'
            '        self._status(on_status, "loading_model")\n'
            "        self._ensure_model_files(config.model, on_progress)\n",
            '            return "remote"\n'
            "        if self._cancelled(cancel):\n"
            '            self._status(on_status, "cancelled")\n'
            '            raise DownloadCancelled("model prepare cancelled")\n'
            '        self._status(on_status, "loading_model")\n'
            "        self._ensure_model_files(config.model, on_progress, cancel=cancel)\n"
            "        if self._cancelled(cancel):\n"
            '            self._status(on_status, "cancelled")\n'
            '            raise DownloadCancelled("model prepare cancelled")\n',
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK engine prepare cancel")
    text = path.read_text(encoding="utf-8")
    if "cancel: Event | None = None,\n    ) -> None:\n        \"\"\"Pre-fetch model files" not in text and "cancel=cancel" in text:
        # maybe ensure already patched via prepare call; still need signature
        pass
    if "def _ensure_model_files(self, model_name: str, on_progress: ProgressCallback | None) -> None:" in text:
        text = text.replace(
            "def _ensure_model_files(self, model_name: str, on_progress: ProgressCallback | None) -> None:",
            "def _ensure_model_files(\n"
            "        self,\n"
            "        model_name: str,\n"
            "        on_progress: ProgressCallback | None,\n"
            "        cancel: Event | None = None,\n"
            "    ) -> None:",
            1,
        )
        text = text.replace(
            '        if Engine.disk_status(model_name)["ready"]:\n'
            "            return\n"
            "        repo = None\n",
            '        if Engine.disk_status(model_name)["ready"]:\n'
            "            return\n"
            "        if self._cancelled(cancel):\n"
            '            raise DownloadCancelled("model download cancelled")\n'
            "        repo = None\n",
            1,
        )
        text = text.replace(
            "        tracker = DownloadTracker(\n"
            "            lambda info: Engine._emit_progress(on_progress, info),\n"
            "            silent=on_progress is None,\n"
            "        )\n"
            "        try:\n"
            "            snapshot_download(\n"
            "                repo_id=repo,\n"
            "                allow_patterns=list(MODEL_FILE_PATTERNS),\n"
            "                tqdm_class=progress_tqdm_class(tracker),\n"
            "            )\n"
            "        except Exception:\n",
            "        tracker = DownloadTracker(\n"
            "            lambda info: Engine._emit_progress(on_progress, info),\n"
            "            silent=on_progress is None,\n"
            "            cancel=cancel,\n"
            "        )\n"
            "        try:\n"
            "            snapshot_download(\n"
            "                repo_id=repo,\n"
            "                allow_patterns=list(MODEL_FILE_PATTERNS),\n"
            "                tqdm_class=progress_tqdm_class(tracker),\n"
            "            )\n"
            "        except DownloadCancelled:\n"
            "            raise\n"
            "        except Exception:\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
        print("OK engine ensure cancel")


def patch_pipeline() -> None:
    path = ROOT / "src/dotaudio/pipeline.py"
    text = path.read_text(encoding="utf-8")
    if "_dropped_audio_blocks" not in text:
        text = text.replace(
            "        self._audio_gap_reported = False\n",
            "        self._audio_gap_reported = False\n"
            "        self._dropped_audio_blocks = 0\n",
            1,
        )
        path.write_text(text, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    old = (
        "    def note_audio_gap(self, dropped_blocks: int) -> None:\n"
        '        """Surface capture overload without turning a Live session fatal."""\n\n'
        "        if dropped_blocks > 0 and not self.cancel.is_set() and not self._audio_gap_reported:\n"
        "            self._audio_gap_reported = True\n"
        '            self.on_status("live_audio_gap")\n'
    )
    new = (
        "    def note_audio_gap(self, dropped_blocks: int) -> None:\n"
        '        """Surface capture overload without turning a Live session fatal."""\n\n'
        "        dropped = int(dropped_blocks)\n"
        "        if dropped <= 0 or self.cancel.is_set():\n"
        "            return\n"
        "        self._dropped_audio_blocks += dropped\n"
        '        self.on_status("live_audio_gap")\n'
        "        self._audio_gap_reported = True\n"
        "        if self.catch_up:\n"
        "            self._clear_preview()\n"
        "            self._last_preview_position = self.buffer.position\n\n"
        "    def dropped_audio_blocks(self) -> int:\n"
        '        """Сколько блоков захвата вытеснено с начала сессии."""\n\n'
        "        return int(self._dropped_audio_blocks)\n"
    )
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        print("OK pipeline note_audio_gap")
    elif "dropped_audio_blocks(self)" in text:
        print("SKIP pipeline note_audio_gap")
    else:
        raise SystemExit("FAIL pipeline note_audio_gap")
    text = path.read_text(encoding="utf-8")
    marker = (
        "        if not self.catch_up and not self.queue.empty():\n"
        "            return\n"
        "        if self.buffer.size < self._preview_min_samples:\n"
    )
    insert = (
        "        if not self.catch_up and not self.queue.empty():\n"
        "            return\n"
        "        if self.catch_up and not self.queue.empty() and self._decode_seconds > 0.8:\n"
        "            return\n"
        "        if self.buffer.size < self._preview_min_samples:\n"
    )
    if insert in text:
        print("SKIP pipeline schedule preview")
    elif marker in text:
        path.write_text(text.replace(marker, insert, 1), encoding="utf-8")
        print("OK pipeline schedule preview")
    else:
        raise SystemExit("FAIL pipeline schedule preview")


def patch_transcripts() -> None:
    path = ROOT / "src/dotaudio/transcripts.py"
    old = (
        "def text_after_prefix(text: str, prefix: str) -> str:\n"
        '    """Return text with a leading confirmed prefix removed when it matches."""\n\n'
        "    body = str(text).strip()\n"
        "    head = str(prefix).strip()\n"
        "    if not head or not body.startswith(head):\n"
        "        return body\n"
        "    return body[len(head):].lstrip()\n"
    )
    new = (
        "def text_after_prefix(text: str, prefix: str) -> str:\n"
        '    """Хвост после согласованного префикса: точное или пословное совпадение."""\n\n'
        '    body = str(text or "").strip()\n'
        '    head = str(prefix or "").strip()\n'
        "    if not head:\n"
        "        return body\n"
        "    if not body:\n"
        '        return ""\n'
        "    if body.startswith(head):\n"
        "        return body[len(head):].lstrip()\n"
        "    body_words = body.split()\n"
        "    head_words = head.split()\n"
        "    index = 0\n"
        "    while (\n"
        "        index < len(head_words)\n"
        "        and index < len(body_words)\n"
        "        and body_words[index].casefold() == head_words[index].casefold()\n"
        "    ):\n"
        "        index += 1\n"
        '    return " ".join(body_words[index:])\n'
    )
    replace_once(path, old, new, "transcripts text_after_prefix")


def patch_app_tray() -> None:
    path = ROOT / "src/dotaudio/app.py"
    text = path.read_text(encoding="utf-8")
    if "tray.activated.connect" in text:
        print("SKIP app tray activated")
        return
    needle = "        tray.setToolTip(\"DotAudio\")\n        tray.setIcon(app_icon)\n        tray.show()\n"
    insert = (
        "        tray.setToolTip(\"DotAudio\")\n"
        "        tray.setIcon(app_icon)\n"
        "        def on_tray_activated(reason):\n"
        "            # ЛКМ по иконке возвращает окно, ПКМ оставляет меню.\n"
        "            if int(reason) == int(QSystemTrayIcon.ActivationReason.Trigger):\n"
        "                show_app_shell()\n"
        "                window.show()\n"
        "                window.raise_()\n"
        "                window.requestActivate()\n"
        "        tray.activated.connect(on_tray_activated)\n"
        "        tray.show()\n"
    )
    if needle not in text:
        raise SystemExit("FAIL app tray")
    path.write_text(text.replace(needle, insert, 1), encoding="utf-8")
    print("OK app tray activated")


if __name__ == "__main__":
    patch_desktop()
    patch_engine()
    patch_pipeline()
    patch_transcripts()
    patch_app_tray()
    print("DONE core patches")
