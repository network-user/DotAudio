"""Controller wiring for features 1-9. Run from repo root."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/dotaudio/controller.py"


def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            print(f"SKIP {label}")
            return text
        raise SystemExit(f"FAIL {label}")
    print(f"OK {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = must_replace(
        text,
        "from dotaudio.engine import Engine, RecognitionConfig\n",
        "from dotaudio.engine import DownloadCancelled, Engine, RecognitionConfig\n"
        "from dotaudio.monitor_clips import PcmRing, extract_match_clip\n",
        "imports engine/clips",
    )
    text = must_replace(
        text,
        "    split_caption_window,\n"
        ")\n"
        "from dotaudio.vosk_engine import VoskEngine\n",
        "    split_caption_window,\n"
        "    text_after_prefix,\n"
        ")\n"
        "from dotaudio.vosk_engine import VoskEngine\n"
        "from dotaudio.watch_folder import WatchFolder\n",
        "imports transcripts/watch",
    )
    text = must_replace(
        text,
        '    "quit_hotkey": "Ctrl+Alt+X",\n',
        '    "quit_hotkey": "Ctrl+Alt+X",\n'
        '    "cancel_hotkey": "Escape",\n'
        '    "watch_folder": "",\n'
        '    "watch_folder_enabled": False,\n'
        '    "history_semantic": True,\n',
        "defaults",
    )

    parse_old = '''def parse_hotkey(value: str) -> Hotkey | None:
    """Разбор свободной комбинации вроде ``Ctrl+Shift+A``.

    Берёт только модификаторы (Ctrl/Alt/Shift/Win/Cmd) и одну клавишу A-Z или
    цифру - безраскладочные и тем самым безопасные для RegisterHotKey. Строит
    Hotkey(MOD_NOREPEAT|модификаторы, VK). Невалидную строку возвращает None,
    не трогая уже установленный биндинг.
    """

    if not value or not isinstance(value, str):
        return None
    mods = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
            "win": MOD_WIN, "cmd": MOD_WIN}
    mod = 0
    key: str | None = None
    for raw in value.replace("+", " ").replace("_", " ").split():
        token = raw.strip()
        if not token:
            continue
        low = token.casefold()
        if low in mods:
            mod |= mods[low]
            continue
        if key is not None or len(token) != 1 or not token.isalnum():
            return None
        key = token.upper()
    if key is None or mod == 0:
        return None
    return Hotkey(MOD_NOREPEAT | mod, ord(key))
'''
    parse_new = '''def parse_hotkey(value: str) -> Hotkey | None:
    """Разбор свободной комбинации вроде ``Ctrl+Shift+A`` или ``Escape``."""

    if not value or not isinstance(value, str):
        return None
    mods = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
            "win": MOD_WIN, "cmd": MOD_WIN}
    special = {"space": 0x20, "escape": 0x1B, "esc": 0x1B}
    mod = 0
    key_code: int | None = None
    for raw in value.replace("+", " ").replace("_", " ").split():
        token = raw.strip()
        if not token:
            continue
        low = token.casefold()
        if low in mods:
            mod |= mods[low]
            continue
        if key_code is not None:
            return None
        if low in special:
            key_code = special[low]
            continue
        if len(token) != 1 or not token.isalnum():
            return None
        key_code = ord(token.upper())
    if key_code is None:
        return None
    if mod == 0 and key_code != 0x1B:
        return None
    return Hotkey(MOD_NOREPEAT | mod, key_code)


def resolve_hotkey(value: str) -> Hotkey | None:
    """Пресет из каталога или свободный разбор строки."""

    name = str(value or "").strip()
    if not name:
        return None
    return (
        HOTKEY_OPTIONS.get(name)
        or QUIT_HOTKEY_OPTIONS.get(name)
        or parse_hotkey(name)
    )
'''
    text = must_replace(text, parse_old, parse_new, "parse/resolve hotkey")

    text = must_replace(
        text,
        '        saved_bindings = {\n'
        '            "dictate": HOTKEY_OPTIONS.get(str(self._settings["dictate_hotkey"])),\n'
        '            "island": HOTKEY_OPTIONS.get(str(self._settings["island_hotkey"])),\n'
        '            "paste_last": HOTKEY_OPTIONS.get(str(self._settings["paste_last_hotkey"])),\n'
        "        }\n"
        "        if (\n"
        "            all(saved_bindings.values())\n"
        "            and len({(item.modifiers, item.key) for item in saved_bindings.values()}) == 3\n"
        "        ):\n"
        "            self.desktop.set_hotkeys(saved_bindings)\n",
        '        saved_bindings = {\n'
        '            "dictate": resolve_hotkey(str(self._settings["dictate_hotkey"])),\n'
        '            "island": resolve_hotkey(str(self._settings["island_hotkey"])),\n'
        '            "paste_last": resolve_hotkey(str(self._settings["paste_last_hotkey"])),\n'
        "        }\n"
        '        cancel_combo = resolve_hotkey(str(self._settings.get("cancel_hotkey") or "Escape"))\n'
        "        if cancel_combo is not None:\n"
        '            saved_bindings["cancel"] = cancel_combo\n'
        "        if (\n"
        '            all(saved_bindings.get(key) for key in ("dictate", "island", "paste_last"))\n'
        "            and len({(item.modifiers, item.key) for item in saved_bindings.values()})\n"
        "            == len(saved_bindings)\n"
        "        ):\n"
        "            self.desktop.set_hotkeys(saved_bindings)\n",
        "saved bindings resolve",
    )

    text = must_replace(
        text,
        "        self._partial_source = \"\"\n"
        "        self._partial_end = 0.0\n",
        "        self._partial_source = \"\"\n"
        "        self._preview_stable = \"\"\n"
        "        self._partial_end = 0.0\n",
        "preview_stable field",
    )

    text = must_replace(
        text,
        "        desktop.paste_last.connect(self.pasteLastTranscript)\n"
        "        self.timer = QTimer(self)\n",
        "        desktop.paste_last.connect(self.pasteLastTranscript)\n"
        "        desktop.cancel_requested.connect(self.cancel)\n"
        "        self.timer = QTimer(self)\n",
        "cancel signal connect",
    )

    text = must_replace(
        text,
        "        self._hold_timer.timeout.connect(self._poll_hold)\n"
        '        self.refreshHistory("")\n'
        "        self.refreshDevices()\n"
        "        self.refreshOutputs()\n"
        "        self.refreshLoopbacks()\n"
        '        self._record_log("system", "DotAudio запущен. Выберите модель или начните работу.")\n',
        "        self._hold_timer.timeout.connect(self._poll_hold)\n"
        "        self._data_dir = Path(data_dir)\n"
        "        self._watch_queue: list[str] = []\n"
        "        self._pcm_rings: dict[str, PcmRing] = {}\n"
        "        self._watch = WatchFolder(None, self._on_watch_file, poll_seconds=2.0)\n"
        '        self.refreshHistory("")\n'
        "        self._hits = self.store.list_keyword_events(limit=200)\n"
        "        self.refreshDevices()\n"
        "        self.refreshOutputs()\n"
        "        self.refreshLoopbacks()\n"
        "        self._sync_watch_folder()\n"
        '        self._record_log("system", "DotAudio запущен. Выберите модель или начните работу.")\n'
        "        recoverable = self.store.list_recoverable_sessions()\n"
        "        if recoverable:\n"
        "            self._record_log(\n"
        '                "warning",\n'
        '                f"Найдено прерванных сессий: {len(recoverable)}. Откройте историю для правки.",\n'
        "            )\n",
        "watch/recovery init",
    )

    # remote dictionary gate
    text = must_replace(
        text,
        '        values["initial_prompt"] = "; ".join(\n'
        '            str(entry.get("term", "")).strip()\n'
        "            for entry in self.dictionary if isinstance(entry, dict)\n"
        "        )\n"
        "        return RecognitionConfig(\n"
        "            **values, media_mode=bool(media_mode), live_stream=bool(live_stream)\n"
        "        )\n",
        '        if str(values.get("backend") or "local") == "remote":\n'
        '            values["initial_prompt"] = ""\n'
        "        else:\n"
        '            values["initial_prompt"] = "; ".join(\n'
        '                str(entry.get("term", "")).strip()\n'
        "                for entry in self.dictionary\n"
        "                if isinstance(entry, dict) and str(entry.get(\"term\", \"\")).strip()\n"
        "            )\n"
        "        return RecognitionConfig(\n"
        "            **values, media_mode=bool(media_mode), live_stream=bool(live_stream)\n"
        "        )\n",
        "dictionary remote gate",
    )

    text = must_replace(
        text,
        "    def _apply_hotkey_bindings(self, dictate: str, island: str, paste_last: str) -> bool:\n"
        "        bindings = {\n"
        '            "dictate": HOTKEY_OPTIONS.get(str(dictate)),\n'
        '            "island": HOTKEY_OPTIONS.get(str(island)),\n'
        '            "paste_last": HOTKEY_OPTIONS.get(str(paste_last)),\n'
        "        }\n"
        "        if None in bindings.values() or len({(item.modifiers, item.key) for item in bindings.values()}) != 3:\n"
        '            self._notice = "Выберите разные поддерживаемые комбинации для диктовки, острова и вставки."\n'
        "            self.changed.emit()\n"
        "            return False\n"
        "        if not self.desktop.set_hotkeys(bindings):\n",
        "    def _apply_hotkey_bindings(self, dictate: str, island: str, paste_last: str) -> bool:\n"
        "        bindings = {\n"
        '            "dictate": resolve_hotkey(str(dictate)),\n'
        '            "island": resolve_hotkey(str(island)),\n'
        '            "paste_last": resolve_hotkey(str(paste_last)),\n'
        "        }\n"
        '        cancel = resolve_hotkey(str(self._settings.get("cancel_hotkey") or "Escape"))\n'
        "        if cancel is not None:\n"
        '            bindings["cancel"] = cancel\n'
        "        if None in (bindings.get(\"dictate\"), bindings.get(\"island\"), bindings.get(\"paste_last\")) or \\\n"
        "                len({(item.modifiers, item.key) for item in bindings.values()}) != len(bindings):\n"
        '            self._notice = "Выберите разные понятные комбинации для диктовки, острова и вставки."\n'
        "            self.changed.emit()\n"
        "            return False\n"
        "        if not self.desktop.set_hotkeys(bindings):\n",
        "apply hotkey resolve",
    )

    # prepare_fn pass cancel
    text = must_replace(
        text,
        "                prepare_fn=lambda on_status, on_progress: engine.prepare(\n"
        "                    self._config(live_stream=True), on_status, on_progress\n"
        "                ),\n",
        "                prepare_fn=lambda on_status, on_progress: engine.prepare(\n"
        "                    self._config(live_stream=True), on_status, on_progress,\n"
        "                    cancel=self._prepare_cancel,\n"
        "                ),\n",
        "vosk prepare cancel",
    )
    text = must_replace(
        text,
        "            prepare_fn=lambda on_status, on_progress: self.engine.prepare(\n"
        "                config, on_status, on_progress\n"
        "            ),\n"
        "            preload_vad=preload_needed,\n"
        "        )\n",
        "            prepare_fn=lambda on_status, on_progress: self.engine.prepare(\n"
        "                config, on_status, on_progress, cancel=self._prepare_cancel,\n"
        "            ),\n"
        "            preload_vad=preload_needed,\n"
        "        )\n",
        "whisper prepare cancel",
    )

    text = must_replace(
        text,
        "                device = prepare_fn(\n"
        "                    lambda status: self.statusArrived.emit(status),\n"
        "                    progress,\n"
        "                )\n"
        "                if self._prepare_cancel.is_set():\n"
        '                    self.modelFinished.emit(model_label, "", "Подготовка отменена")\n'
        "                    return\n"
        "            except Exception as exc:\n"
        '                self.modelFinished.emit(model_label, "", str(exc))\n',
        "                device = prepare_fn(\n"
        "                    lambda status: self.statusArrived.emit(status),\n"
        "                    progress,\n"
        "                )\n"
        "                if self._prepare_cancel.is_set():\n"
        '                    self.modelFinished.emit(model_label, "", "Подготовка отменена")\n'
        "                    return\n"
        "            except DownloadCancelled:\n"
        '                self.modelFinished.emit(model_label, "", "Подготовка отменена")\n'
        "            except Exception as exc:\n"
        '                self.modelFinished.emit(model_label, "", str(exc))\n',
        "prepare DownloadCancelled",
    )

    # stable_text in partial
    text = must_replace(
        text,
        "        text = str(segment.get(\"text\", \"\")).strip()\n"
        "        if not text:\n"
        "            return\n"
        "        self._last_caption_at = time.monotonic()\n"
        "        end = float(segment.get(\"end\", 0.0))\n"
        "        if end < self._partial_end or end <= self._final_end:\n"
        "            return\n"
        "        self._partial_source = text\n"
        "        self._partial_end = end\n",
        "        text = str(segment.get(\"text\", \"\")).strip()\n"
        "        if not text:\n"
        "            return\n"
        "        self._last_caption_at = time.monotonic()\n"
        "        end = float(segment.get(\"end\", 0.0))\n"
        "        if end < self._partial_end or end <= self._final_end:\n"
        "            return\n"
        "        self._partial_source = text\n"
        "        self._preview_stable = str(segment.get(\"stable_text\", \"\")).strip()\n"
        "        self._partial_end = end\n",
        "partial stable_text",
    )

    text = must_replace(
        text,
        '    def _refresh_live_caption(self):\n'
        '        """The live row: one unfinished sentence, clipped to a readable tail."""\n\n'
        '        draft = getattr(self, "_partial_source", "") or ""\n'
        "        if self._open_phrase and self._segments:\n"
        "            last = self._segments[-1]\n"
        "            head, tail = blend_fragments(\n"
        '                str(last.get("text", "")), bool(last.get("cut")), draft\n'
        "            )\n"
        "        else:\n"
        '            head, tail = "", draft\n'
        "        head, tail = split_caption_window(head, tail)\n"
        "        self._confirmed_caption = head\n"
        "        self._partial_caption = tail\n"
        "        self._caption_revision += 1\n"
        "        self.captionChanged.emit()\n",
        '    def _refresh_live_caption(self):\n'
        '        """Live row: LocalAgreement prefix as confirmed, remainder as draft."""\n\n'
        '        draft = getattr(self, "_partial_source", "") or ""\n'
        '        stable = getattr(self, "_preview_stable", "") or ""\n'
        "        if stable and draft:\n"
        "            agreed = stable\n"
        "            rest = text_after_prefix(draft, stable)\n"
        "            if self._open_phrase and self._segments:\n"
        "                last = self._segments[-1]\n"
        "                head, _ = blend_fragments(\n"
        '                    str(last.get("text", "")), bool(last.get("cut")), agreed\n'
        "                )\n"
        "                confirmed, pending = head or agreed, rest\n"
        "            else:\n"
        "                confirmed, pending = agreed, rest\n"
        "        elif self._open_phrase and self._segments:\n"
        "            last = self._segments[-1]\n"
        "            confirmed, pending = blend_fragments(\n"
        '                str(last.get("text", "")), bool(last.get("cut")), draft\n'
        "            )\n"
        "        else:\n"
        '            confirmed, pending = "", draft\n'
        "        confirmed, pending = split_caption_window(confirmed, pending)\n"
        "        self._confirmed_caption = confirmed\n"
        "        self._partial_caption = pending\n"
        "        self._caption_revision += 1\n"
        "        self.captionChanged.emit()\n",
        "refresh live caption stable",
    )

    # monitor hits + clips
    text = must_replace(
        text,
        "            if matches:\n"
        '                self._hits.insert(0, {**segment, "source": job["name"], "matches": ", ".join(matches), "session_id": sid})\n'
        "                self._hits = self._hits[:200]\n"
        '                self._record_log("warning", f"Совпадение в эфире {job[\'name\']}: {\', \'.join(matches)}")\n',
        "            if matches:\n"
        "                clip_path = \"\"\n"
        "                ring = self._pcm_rings.get(sid)\n"
        "                if ring is not None:\n"
        "                    clip = extract_match_clip(\n"
        "                        ring,\n"
        "                        match_start=float(segment.get(\"start\", 0.0)),\n"
        "                        match_end=float(segment.get(\"end\", 0.0)),\n"
        "                        stream_end=float(ring.written_seconds),\n"
        "                        out_dir=self._data_dir / \"clips\",\n"
        "                        stem=f\"{sid[:8]}_{int(float(segment.get('start', 0.0)))}\",\n"
        "                    )\n"
        "                    clip_path = str(clip) if clip is not None else \"\"\n"
        "                for keyword in matches:\n"
        "                    self.store.save_keyword_event(\n"
        "                        sid,\n"
        "                        start=float(segment.get(\"start\", 0.0)),\n"
        "                        end=float(segment.get(\"end\", 0.0)),\n"
        "                        keyword=keyword,\n"
        "                        text=str(segment.get(\"text\", \"\")),\n"
        "                        source=str(job[\"name\"]),\n"
        "                        clip_path=clip_path,\n"
        "                    )\n"
        "                hit = {\n"
        "                    **segment,\n"
        "                    \"source\": job[\"name\"],\n"
        "                    \"matches\": \", \".join(matches),\n"
        "                    \"session_id\": sid,\n"
        "                    \"clip_path\": clip_path,\n"
        "                }\n"
        "                self._hits.insert(0, hit)\n"
        "                self._hits = self._hits[:200]\n"
        '                self._record_log("warning", f"Совпадение в эфире {job[\'name\']}: {\', \'.join(matches)}")\n',
        "monitor clips/events",
    )

    text = must_replace(
        text,
        "    @Slot(str)\n"
        "    def refreshHistory(self, query):\n"
        "        self._query = query\n"
        "        self._history = self.store.list_sessions(query)\n"
        "        self.changed.emit()\n",
        "    @Slot(str)\n"
        "    def refreshHistory(self, query):\n"
        "        self._query = query\n"
        "        semantic = bool(self._settings.get(\"history_semantic\", True))\n"
        "        self._history = self.store.search_sessions(\n"
        "            query, semantic=semantic and bool(str(query or \"\").strip())\n"
        "        )\n"
        "        self.changed.emit()\n",
        "semantic history",
    )

    # Append helper methods before a unique late method if missing
    helpers = '''
    def _on_watch_file(self, path: Path) -> None:
        """Новый файл из watch-folder: очередь, чтобы не стартовать поверх busy."""

        target = str(Path(path))
        if target in self._watch_queue:
            return
        self._watch_queue.append(target)
        QTimer.singleShot(0, self._drain_watch_queue)

    def _drain_watch_queue(self) -> None:
        if self._jobs or self._state != "idle" or not self._watch_queue:
            if self._watch_queue and not self._jobs:
                QTimer.singleShot(1500, self._drain_watch_queue)
            return
        path = self._watch_queue.pop(0)
        self._record_log("info", f"Автоимпорт из папки: {path}")
        try:
            self.transcribePath(path)
        except Exception as exc:
            self._record_log("error", f"Автоимпорт не удался: {exc}")
        if self._watch_queue:
            QTimer.singleShot(1500, self._drain_watch_queue)

    def _sync_watch_folder(self) -> None:
        enabled = bool(self._settings.get("watch_folder_enabled"))
        folder = str(self._settings.get("watch_folder") or "").strip()
        if enabled and folder:
            self._watch.set_path(folder)
            self._watch.start()
        else:
            self._watch.set_path(None)
            self._watch.stop()

    @Slot()
    def chooseWatchFolder(self) -> None:
        path = QFileDialog.getExistingDirectory(None, "Папка автоимпорта медиа", "")
        if not path:
            return
        self._settings["watch_folder"] = path
        self._settings["watch_folder_enabled"] = True
        self.store.save_settings(self._settings)
        self._sync_watch_folder()
        self._notice = f"Следим за папкой: {path}"
        self.changed.emit()

    @Slot(bool)
    def setWatchFolderEnabled(self, enabled: bool) -> None:
        self._settings["watch_folder_enabled"] = bool(enabled)
        self.store.save_settings(self._settings)
        self._sync_watch_folder()
        self.changed.emit()

'''
    if "_sync_watch_folder" not in text:
        anchor = "    @Slot()\n    def pasteLastTranscript(self):\n"
        if anchor not in text:
            raise SystemExit("FAIL helpers anchor")
        text = text.replace(anchor, helpers + anchor, 1)
        print("OK helpers")
    else:
        print("SKIP helpers")

    # setSetting bools for new flags
    if '"watch_folder_enabled"' not in text.split("if name in (")[1][:800]:
        text = must_replace(
            text,
            '"live_greedy_finals", "gpu_hint_dismissed", "setup_completed",\n'
            "        ):\n"
            "            value = bool(value)\n",
            '"live_greedy_finals", "gpu_hint_dismissed", "setup_completed",\n'
            '            "watch_folder_enabled", "history_semantic",\n'
            "        ):\n"
            "            value = bool(value)\n",
            "setSetting bools",
        )

    # LIVE_SETTINGS allow watch while recording? optional - skip

    # Wire pcm ring on monitor audio
    if "self._pcm_rings[sid]" not in text:
        text = must_replace(
            text,
            "                def on_audio(audio, sid=sid, live=live, clock=capture_clock, mode=mode):\n"
            "                    if mode == \"live\" and not clock[\"started\"] and len(audio):\n"
            "                        clock[\"started\"] = True\n"
            "                        self.captureStarted.emit(sid, time.monotonic() - len(audio) / SAMPLE_RATE)\n"
            "                    live.feed(audio)\n",
            "                def on_audio(audio, sid=sid, live=live, clock=capture_clock, mode=mode):\n"
            "                    if mode == \"live\" and not clock[\"started\"] and len(audio):\n"
            "                        clock[\"started\"] = True\n"
            "                        self.captureStarted.emit(sid, time.monotonic() - len(audio) / SAMPLE_RATE)\n"
            "                    if mode == \"monitor\":\n"
            "                        ring = self._pcm_rings.setdefault(sid, PcmRing(seconds=90.0))\n"
            "                        ring.write(audio)\n"
            "                    live.feed(audio)\n",
            "monitor pcm ring",
        )

    # Ensure preview_stable clears alongside partial_source (idempotent)
    while 'self._partial_source = ""\n        self._preview_stable = ""\n        self._preview_stable = ""\n' in text:
        text = text.replace(
            'self._partial_source = ""\n        self._preview_stable = ""\n        self._preview_stable = ""\n',
            'self._partial_source = ""\n        self._preview_stable = ""\n',
        )
    text = text.replace(
        'self._partial_source = ""\n',
        'self._partial_source = ""\n        self._preview_stable = ""\n',
    )
    while 'self._partial_source = ""\n        self._preview_stable = ""\n        self._preview_stable = ""\n' in text:
        text = text.replace(
            'self._partial_source = ""\n        self._preview_stable = ""\n        self._preview_stable = ""\n',
            'self._partial_source = ""\n        self._preview_stable = ""\n',
        )

    PATH.write_text(text, encoding="utf-8")
    print("WROTE controller.py")


if __name__ == "__main__":
    main()
