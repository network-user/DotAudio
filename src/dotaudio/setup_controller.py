"""Мастер первой настройки: опрос, брифинг и фоновая подготовка.

Тяжёлые шаги (pip CUDA, скачивание Whisper/LLM) идут в daemon-потоке.
В QML уходит только состояние через сигналы. Не трогает объекты интерфейса
из воркера.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from dotaudio import modelhub
from dotaudio import setup as plan
from dotaudio.controller import hardware_summary
from dotaudio.engine import Engine
from dotaudio.llm import get_model

PROGRESS_UI_MS = 100


def _empty_briefing() -> dict:
    return {
        "whisperModel": "small",
        "whisperLabel": "Whisper Small",
        "whisperMb": 0,
        "whisperReady": False,
        "profile": "balanced",
        "device": "auto",
        "deviceLabel": "Авто",
        "useGpu": False,
        "cudaNeeded": False,
        "cudaMb": 0,
        "llmId": "",
        "llmLabel": "",
        "llmMb": 0,
        "llmReady": False,
        "downloadLlm": True,
        "downloadWhisper": True,
        "nemoReady": False,
        "downloadNemo": True,
        "nemoMb": 0,
        "nemoPreferCuda": False,
        "ffmpegReady": False,
        "downloadFfmpeg": True,
        "ffmpegMb": 0,
        "totalMb": 0,
        "computeHint": "",
        "gpuLabel": "",
        "technologies": [],
    }


class SetupController(QObject):
    """Оркестратор первого запуска поверх Controller и AssistantController."""

    changed = Signal()
    progressChanged = Signal()
    # Воркеры → GUI.
    scanFinished = Signal(object, "QVariantMap")
    stepProgress = Signal(str, float, str)
    stepFinished = Signal(str, bool, str)
    runFinished = Signal(bool, str)

    def __init__(self, data_dir: Path, controller, assistant) -> None:
        super().__init__()
        self.controller = controller
        self.assistant = assistant
        self.data_dir = Path(data_dir)
        self.models_dir = modelhub.models_root(self.data_dir, "llm")
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self._needed = not bool(controller.setting("setup_completed", False))
        self._force = False
        self._phase = "idle"
        self._hardware: dict = {}
        self._briefing = _empty_briefing()
        self._steps: list[dict] = []
        self._overall = 0.0
        self._message = ""
        self._error = ""
        self._busy = False
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._progress_pending: tuple[str, float, str] | None = None

        self.scanFinished.connect(self._on_scan_finished)
        self.stepProgress.connect(self._on_step_progress)
        self.stepFinished.connect(self._on_step_finished)
        self.runFinished.connect(self._on_run_finished)

        self._progress_ui = QTimer(self)
        self._progress_ui.setSingleShot(True)
        self._progress_ui.setInterval(PROGRESS_UI_MS)
        self._progress_ui.timeout.connect(self._flush_progress_ui)

    # -- свойства ----------------------------------------------------------

    @Property(bool, notify=changed)
    def needed(self) -> bool:
        return self._needed

    @Property(bool, notify=changed)
    def visible(self) -> bool:
        return self._phase in {"scan", "brief", "run", "done"}

    @Property(str, notify=changed)
    def phase(self) -> str:
        return self._phase

    @Property("QVariantMap", notify=changed)
    def hardware(self) -> dict:
        return dict(self._hardware)

    @Property("QVariantMap", notify=changed)
    def briefing(self) -> dict:
        return dict(self._briefing)

    @Property("QVariantList", notify=progressChanged)
    def steps(self) -> list:
        return list(self._steps)

    @Property(float, notify=progressChanged)
    def overallPercent(self) -> float:
        return float(self._overall)

    @Property(str, notify=progressChanged)
    def message(self) -> str:
        return self._message

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    # -- запуск ------------------------------------------------------------

    @Slot()
    def begin(self) -> None:
        """Старт опроса. Вызывать только если needed и не smoke-тест."""

        self.beginForced(False)

    @Slot(bool)
    def beginForced(self, force) -> None:
        """``force`` - всегда показать мастер (повтор из настроек)."""

        if self._busy and self._phase == "run":
            return
        self._force = bool(force)
        if not self._needed and self._phase == "idle":
            self._needed = True
        self._phase = "scan"
        self._busy = True
        self._error = ""
        self._message = "Смотрим, что есть на этом компьютере…"
        self._overall = 0.0
        self._steps = []
        self.changed.emit()
        self.progressChanged.emit()

        data_dir = self.data_dir

        def work():
            try:
                summary = hardware_summary(refresh=True)
            except Exception as exc:
                summary = {
                    "threads": 0,
                    "ram_gb": None,
                    "cuda_devices": 0,
                    "computeAdvice": "cpu_only",
                    "computeHint": str(exc),
                    "gpus": [],
                }
            from dotaudio import nemo_diarize
            from dotaudio.setup import recommended_whisper
            from dotaudio.tools_ffmpeg import ffmpeg_available

            model_name = recommended_whisper(summary)
            whisper_ready = bool(Engine.disk_status(model_name).get("ready"))
            llm_id = plan.recommend_llm_id(summary)
            llm = get_model(llm_id)
            llm_ready = False
            if llm is not None:
                status = modelhub.disk_status(self.models_dir, llm.file)
                llm_ready = bool(status.get("ready"))
            try:
                nemo_ready = bool(nemo_diarize.probe().get("available"))
            except Exception:
                nemo_ready = False
            readiness = {
                "whisperReady": whisper_ready,
                "llmReady": llm_ready,
                "nemoReady": nemo_ready,
                "ffmpegReady": ffmpeg_available(data_dir),
            }
            try:
                from dotaudio.capture import system_audio_supported

                readiness["systemAudioReady"] = bool(system_audio_supported())
            except Exception:
                readiness["systemAudioReady"] = False
            self.scanFinished.emit(summary, readiness)

        threading.Thread(target=work, name="dotaudio-setup-scan", daemon=True).start()

    def _on_scan_finished(self, summary, readiness) -> None:
        self._hardware = dict(summary or {})
        ready = dict(readiness or {})
        try:
            self.controller.hardwareArrived.emit(self._hardware)
        except RuntimeError:
            pass
        self._briefing = plan.build_briefing(
            self._hardware,
            whisper_ready=bool(ready.get("whisperReady")),
            llm_ready=bool(ready.get("llmReady")),
            nemo_ready=bool(ready.get("nemoReady")),
            ffmpeg_ready=bool(ready.get("ffmpegReady")),
            system_audio_ready=ready.get("systemAudioReady"),
        )
        # Всё уже на диске и это не ручной повтор - тихо закрываем мастер.
        if not self._force and plan.can_skip_setup(self._briefing):
            self._apply_settings(self._briefing)
            self._mark_completed()
            self._phase = "idle"
            self._busy = False
            self._message = ""
            self._error = ""
            self.changed.emit()
            self.progressChanged.emit()
            try:
                self.controller.enableModelWarmup()
                QTimer.singleShot(0, self.controller.prepareSelectedModel)
            except Exception:
                pass
            return
        self._phase = "brief"
        self._busy = False
        self._message = "Краткий план под это устройство"
        self.changed.emit()
        self.progressChanged.emit()

    @Slot("QVariantMap")
    def updateBriefing(self, overrides) -> None:
        if self._phase != "brief" or self._busy:
            return
        self._briefing = plan.merge_briefing(self._briefing, dict(overrides or {}))
        self.changed.emit()

    @Slot()
    def confirm(self) -> None:
        """Применить брифинг и запустить фоновую подготовку."""

        if self._phase not in {"brief", "done"} or self._busy:
            return
        self._cancel = threading.Event()
        self._briefing = plan.merge_briefing(self._briefing, {})
        # Настройки только из GUI-потока: setSetting трогает QObject.
        self._apply_settings(self._briefing)
        raw_steps = plan.build_steps(self._briefing)
        # Шаг settings уже выполнен выше - в воркере остаётся отметка.
        self._steps = [
            {
                **step,
                "status": "done" if step["id"] == "settings" else "pending",
                "percent": 100.0 if step["id"] == "settings" else 0.0,
                "message": "Готово" if step["id"] == "settings" else "",
            }
            for step in raw_steps
        ]
        self._phase = "run"
        self._busy = True
        self._error = ""
        self._overall = self._compute_overall()
        self._message = "Готовим окружение…"
        self.changed.emit()
        self.progressChanged.emit()

        briefing = dict(self._briefing)
        cancel = self._cancel
        work_steps = [step for step in raw_steps if step["id"] != "settings"]

        def work():
            ok = True
            last_error = ""
            for step in work_steps:
                if cancel.is_set():
                    ok = False
                    last_error = "Настройка остановлена"
                    break
                step_id = str(step["id"])
                self.stepProgress.emit(step_id, 0.0, str(step.get("detail") or ""))
                try:
                    if step_id == "cuda":
                        self._run_cuda(cancel)
                    elif step_id == "whisper":
                        self._run_whisper(briefing, cancel)
                    elif step_id == "nemo":
                        self._run_nemo(briefing, cancel)
                    elif step_id == "llm":
                        self._run_llm(briefing, cancel)
                    elif step_id == "ffmpeg":
                        self._run_ffmpeg(cancel)
                    else:
                        continue
                except Exception as exc:
                    ok = False
                    last_error = str(exc) or exc.__class__.__name__
                    self.stepFinished.emit(step_id, False, last_error)
                    continue
                self.stepFinished.emit(step_id, True, "")
            self.runFinished.emit(ok and not cancel.is_set(), last_error)

        self._worker = threading.Thread(target=work, name="dotaudio-setup-run", daemon=True)
        self._worker.start()

    def _apply_settings(self, briefing: dict) -> None:
        model = str(briefing.get("whisperModel") or "small")
        device = str(briefing.get("device") or "auto")
        profile = str(briefing.get("profile") or "balanced")
        llm_id = str(briefing.get("llmId") or "")
        # Сначала профиль, потом модель: иначе setSetting(profile) мог
        # переписать medium на small (см. PROFILE_FOR_MODEL).
        self.controller.setSetting("profile", profile)
        self.controller.setSetting("model", model)
        self.controller.setSetting("device", device)
        self.controller.setSetting(
            "live_greedy_finals", bool(briefing.get("liveGreedyFinals"))
        )
        if llm_id:
            self.controller.setSetting("assistant_model", llm_id)
        if briefing.get("downloadNemo") or briefing.get("nemoReady"):
            self.controller.setSetting("diarize_engine", "nemo")
        self.controller.setSetting("gpu_hint_dismissed", True)

    def _run_cuda(self, cancel: threading.Event) -> None:
        from dotaudio.cuda_runtime import setup_whisper_cuda
        from dotaudio.hardware import reset_cache

        def progress(info):
            raw = float((info or {}).get("percent") or 0.0)
            message = str((info or {}).get("message") or "CUDA…")
            self.stepProgress.emit("cuda", raw, message)

        result = setup_whisper_cuda(progress, cancel)
        if cancel.is_set():
            raise RuntimeError("Настройка CUDA отменена")
        if not result.get("ok"):
            raise RuntimeError(str(result.get("message") or "CUDA недоступна"))
        reset_cache()
        try:
            summary = hardware_summary(refresh=True)
            self.controller.hardwareArrived.emit(summary)
        except Exception:
            pass
        # device=cuda пишем после успеха через finished на GUI.
        self.stepProgress.emit("cuda", 100.0, str(result.get("message") or "CUDA готова"))

    def _run_whisper(self, briefing: dict, cancel: threading.Event) -> None:
        from dotaudio.engine import RecognitionConfig

        model = str(briefing.get("whisperModel") or "small")
        # Читаем актуальный device без записи настроек из воркера.
        device = str(briefing.get("device") or "auto")
        if briefing.get("useGpu") and not briefing.get("cudaNeeded"):
            device = "cuda"
        language = "ru"
        task = "transcribe"
        profile = str(briefing.get("profile") or "balanced")
        config = RecognitionConfig(
            model=model,
            device=device,
            language=language,
            task=task,
            backend="local",
            profile=profile,
            live_stream=True,
        )

        def progress(info):
            raw = float((info or {}).get("percent") or 0.0)
            message = str((info or {}).get("message") or f"Модель {model}…")
            self.stepProgress.emit("whisper", raw, message)
            try:
                self.controller.modelDownloadProgress.emit(model, dict(info or {}))
            except RuntimeError:
                pass

        if cancel.is_set():
            raise RuntimeError("Подготовка Whisper отменена")
        device_used = self.controller.engine.prepare(config, None, progress)
        if cancel.is_set():
            raise RuntimeError("Подготовка Whisper отменена")
        self.stepProgress.emit("whisper", 100.0, f"Готово · {device_used}")

    def _run_nemo(self, briefing: dict, cancel: threading.Event) -> None:
        from dotaudio import nemo_diarize

        prefer_cuda = bool(briefing.get("nemoPreferCuda"))

        def progress(info):
            raw = float((info or {}).get("percent") or 0.0)
            # Установка рантайма - до 55%, pull модели - вторая половина.
            message = str((info or {}).get("message") or "NeMo…")
            self.stepProgress.emit("nemo", min(55.0, raw * 0.55), message)

        if not nemo_diarize.executable():
            result = nemo_diarize.install_runtime(
                backend="auto",
                prefer_cuda=prefer_cuda,
                cancel=cancel,
                on_progress=progress,
            )
            if cancel.is_set():
                raise RuntimeError("Установка NeMo отменена")
            if not result.get("ok"):
                raise RuntimeError(str(result.get("message") or "NeMo не установился"))
        else:
            self.stepProgress.emit("nemo", 40.0, "Рантайм уже на диске")

        def status(message: str) -> None:
            self.stepProgress.emit("nemo", 85.0, str(message or "Модель Sortformer…"))

        self.stepProgress.emit("nemo", 60.0, "Скачиваем модель Sortformer…")
        nemo_diarize.ensure_model(cancel=cancel, on_status=status)
        if cancel.is_set():
            raise RuntimeError("Загрузка модели NeMo отменена")
        report = nemo_diarize.probe(cancel)
        if not report.get("available"):
            raise RuntimeError(str(report.get("message") or "NeMo не готов после установки"))
        self.stepProgress.emit("nemo", 100.0, str(report.get("message") or "NeMo готов"))

    def _run_llm(self, briefing: dict, cancel: threading.Event) -> None:
        llm_id = str(briefing.get("llmId") or "")
        model = get_model(llm_id)
        if model is None:
            raise RuntimeError("Модель ассистента не найдена в каталоге")
        status = modelhub.disk_status(self.models_dir, model.file)
        if status.get("ready"):
            self.stepProgress.emit("llm", 100.0, "Уже на диске")
            return

        def progress(payload):
            ratio = float(payload.get("ratio") or 0.0)
            received = int(payload.get("bytes") or 0)
            total = int(payload.get("total") or model.size_bytes or 0)
            if total > 0:
                mb = received / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                message = f"{mb:.0f} / {total_mb:.0f} МБ"
            else:
                message = f"{received / (1024 * 1024):.0f} МБ"
            self.stepProgress.emit("llm", ratio * 100.0, message)

        modelhub.download(
            model.file,
            self.models_dir,
            on_progress=progress,
            cancel=cancel,
        )
        if cancel.is_set():
            raise RuntimeError("Загрузка языковой модели отменена")
        self.stepProgress.emit("llm", 100.0, "Файл на диске")

    def _run_ffmpeg(self, cancel: threading.Event) -> None:
        from dotaudio.tools_ffmpeg import FfmpegCancelled, ensure_ffmpeg

        def progress(info):
            raw = float((info or {}).get("percent") or 0.0)
            message = str((info or {}).get("message") or "FFmpeg…")
            self.stepProgress.emit("ffmpeg", raw, message)

        try:
            path = ensure_ffmpeg(self.data_dir, cancel=cancel, on_progress=progress)
        except FfmpegCancelled as exc:
            raise RuntimeError(str(exc) or "Загрузка FFmpeg остановлена") from exc
        if cancel.is_set():
            raise RuntimeError("Загрузка FFmpeg остановлена")
        self.stepProgress.emit("ffmpeg", 100.0, path)

    # -- прогресс UI -------------------------------------------------------

    def _on_step_progress(self, step_id: str, percent: float, message: str) -> None:
        self._progress_pending = (str(step_id), float(percent), str(message or ""))
        if not self._progress_ui.isActive():
            self._progress_ui.start()

    def _flush_progress_ui(self) -> None:
        pending = self._progress_pending
        self._progress_pending = None
        if not pending:
            return
        step_id, percent, message = pending
        found = False
        for step in self._steps:
            if step.get("id") == step_id:
                step["status"] = "active"
                step["percent"] = max(0.0, min(100.0, percent))
                step["message"] = message
                found = True
            elif step.get("status") == "active" and step.get("id") != step_id:
                # Предыдущий активный без finish ещё ждёт - не трогаем.
                pass
        if found:
            self._message = message or self._message
            self._overall = self._compute_overall()
            self.progressChanged.emit()

    def _on_step_finished(self, step_id: str, ok: bool, error: str) -> None:
        for step in self._steps:
            if step.get("id") != step_id:
                continue
            step["status"] = "done" if ok else "error"
            step["percent"] = 100.0 if ok else float(step.get("percent") or 0.0)
            if error:
                step["message"] = error
            break
        if error and not ok:
            self._error = error
        self._overall = self._compute_overall()
        self.progressChanged.emit()
        self.changed.emit()

    def _compute_overall(self) -> float:
        if not self._steps:
            return 0.0
        total_w = sum(float(step.get("weight") or 1) for step in self._steps) or 1.0
        done = 0.0
        for step in self._steps:
            weight = float(step.get("weight") or 1)
            status = str(step.get("status") or "pending")
            if status == "done":
                done += weight
            elif status == "active":
                done += weight * (float(step.get("percent") or 0.0) / 100.0)
            elif status == "error":
                done += weight * (float(step.get("percent") or 0.0) / 100.0)
        return max(0.0, min(100.0, 100.0 * done / total_w))

    def _on_run_finished(self, ok: bool, error: str) -> None:
        self._busy = False
        self._overall = 100.0 if ok else self._compute_overall()
        # После успешной CUDA - включить GPU из GUI-потока.
        if any(step.get("id") == "cuda" and step.get("status") == "done" for step in self._steps):
            self.controller.setSetting("device", "cuda")
        if ok:
            self._phase = "done"
            self._message = "Всё готово к работе"
            self._error = ""
            self._mark_completed()
        else:
            self._phase = "done"
            self._message = error or "Настройка завершилась с ошибками"
            self._error = error or self._error
            self._mark_completed()
        self.changed.emit()
        self.progressChanged.emit()
        try:
            self.controller.enableModelWarmup()
            QTimer.singleShot(0, self.controller.prepareSelectedModel)
        except Exception:
            pass
        try:
            self.assistant.refreshCatalog()
            self.assistant.refreshHardware()
        except Exception:
            pass
        try:
            if hasattr(self.controller, "refreshDiarizeStatus"):
                self.controller.refreshDiarizeStatus()
        except Exception:
            pass

    def _mark_completed(self) -> None:
        self.controller.setSetting("setup_completed", True)
        self.controller.setSetting("gpu_hint_dismissed", True)
        self._needed = False

    @Slot()
    def skip(self) -> None:
        """Отложить настройку: не качаем, но больше не блокируем старт."""

        if self._busy and self._phase == "run":
            self._cancel.set()
            return
        self._mark_completed()
        self._phase = "idle"
        self._busy = False
        self._message = ""
        self.changed.emit()
        try:
            self.controller.enableModelWarmup()
            QTimer.singleShot(0, self.controller.prepareSelectedModel)
        except Exception:
            pass

    @Slot()
    def cancel(self) -> None:
        if self._phase == "run" and self._busy:
            self._cancel.set()
            self._message = "Останавливаем…"
            self.progressChanged.emit()
            return
        self.skip()

    @Slot()
    def finish(self) -> None:
        """Закрыть экран «готово»."""

        self._phase = "idle"
        self._needed = False
        self.changed.emit()

    @Slot()
    def reopen(self) -> None:
        """Повторный запуск из настроек."""

        if self._busy:
            return
        self._needed = True
        self.controller.setSetting("setup_completed", False)
        self._phase = "idle"
        self.beginForced(True)
