from pathlib import Path
import ast

p = Path("src/dotaudio/controller.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out: list[str] = []
fixed = 0
i = 0
while i < len(lines):
    line = lines[i]
    if (
        line.strip() == 'self._preview_stable = ""'
        and i > 0
        and i + 1 < len(lines)
        and "self._partial_source" in lines[i - 1]
        and lines[i + 1].lstrip().startswith("self._partial_end")
    ):
        indent = lines[i - 1][: len(lines[i - 1]) - len(lines[i - 1].lstrip())]
        out.append(f'{indent}self._preview_stable = ""\n')
        fixed += 1
        i += 1
        continue
    out.append(line)
    i += 1

text = "".join(out)

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

if "def _sync_watch_folder" not in text:
    anchor = "    @Slot()\n    def pasteLastTranscript(self):\n"
    if anchor not in text:
        raise SystemExit("missing pasteLastTranscript anchor")
    text = text.replace(anchor, helpers + anchor, 1)
    print("helpers inserted")
else:
    print("helpers already present")

p.write_text(text, encoding="utf-8")
ast.parse(text)
print("fixed", fixed, "syntax ok")
