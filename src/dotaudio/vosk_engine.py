"""Лёгкий vosk-движок живого распознавания для Live-суттитров.

Офлайн Kaldi-модели vosk дают потоковый partial-текст и работают на слабом
CPU без GPU (RTF ~0.14 на записи в замерах docs/STT_METHODS.md). В DotAudio
vosk - это альтернативный "live_engine" для живых субтитров (по умолчанию для
нового профиля), при этом взаимодействие остаётся прежним: ``LiveSession``
зовёт движок через ``transcribe(array, ...)``, UI не знает, какой движок был.

Модуль Qt-free и импортирует vosk лениво: нативный пакет нужен только когда
включён живой путь vosk. Интерфейс повторяет минимальную часть ``Engine``,
которой пользуется pipeline.

Каждый вызов ``transcribe`` соответствует одному речевому окну/фразе (16 кГц
mono float32 - контракт LiveSession). Чтобы вести себя как whisper-окно, а не
как бесконечная речевая сессия, распознаватель строится на каждый вызов и
завершается через ``FinalResult`` (граница фразы). Стабилизация префикса и
финализация в этой точке не трогаются - pipeline как прежде.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

from dotaudio.engine import RecognitionConfig

Segment = dict[str, Any]
SegmentCallback = Callable[[Segment], None]
StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[dict], None]

RATE = 16000
# vosk-малая RU-модель на очень коротком окне даёт фонетику, а не слова.
# Ниже этой границы возвращаем пусто, чтобы не кормить UI бормотанием.
MIN_WINDOW_SECONDS = 0.5


def vosk_model_name(size: str) -> str:
    """Фактическое имя vosk-модели по выбранному логическому размеру.

    Совпадает со значениями настроек "vosk_size" в controller.
    """
    if size == "big":
        return "vosk-model-ru-0.42"
    return "vosk-model-small-ru-0.22"


def _import_vosk() -> Any:
    """Ленивая загрузка нативного пакета vosk с понятной ошибкой."""
    try:
        import vosk  # type: ignore
    except Exception as exc:  # pragma: no cover - зависит от машины
        raise RuntimeError(
            "Для движка Vosk нужен пакет vosk. Установите его или переключитесь на Whisper."
        ) from exc
    return vosk


def _word_conf_text(blob: str) -> tuple[str, list[dict[str, float]], float]:
    """Разбор FinalResult: текст, слова с conf/таймкодами, средняя уверенность.

    vosk с ``SetWords(True)`` кладёт в "result" слова с полями start/end/conf.
    Если conf нет (модель без слов или слова скрыты), средняя уверенность
    недоступна - возвращаем 0.0 и пустой список слов, caller сам решает.
    """
    try:
        data = json.loads(blob)
    except Exception:
        return "", [], 0.0
    text = str((data.get("text") or "") if isinstance(data, dict) else "").strip()
    words: list[dict[str, float]] = []
    confs: list[float] = []
    for item in (data.get("result", []) if isinstance(data, dict) else []) or []:
        word = str(item.get("word", "") or "").strip()
        if not word or word.startswith("["):
            continue
        start = max(0.0, float(item.get("start", 0.0)))
        end = max(start, float(item.get("end", start)))
        conf = float(item.get("conf", 0.0))
        words.append({"text": word, "start": start, "end": end})
        confs.append(conf)
    if words and confs:
        return text, words, sum(confs) / len(confs)
    if not words:
        return text, [], 0.0
    return text, words, 0.0


class VoskEngine:
    """Kaldi-декодер vosk как движок Live, с тем же контрактом, что Engine.

    Кеширует одну ``vosk.Model`` между вызовами. ``transcribe`` создаёт и
    сбрасывает отдельный ``KaldiRecognizer`` на каждый массив, поэтому каждый
    вызов - независимое речевое окно, и pipeline-стабилизация не страдает.
    """

    def __init__(self, model_size: str = "small") -> None:
        self._model = None
        self._vosk = None
        self._target = vosk_model_name(model_size)
        self._model_name = ""

    # --- интерфейс, общей с Engine, для pipeline ---

    @property
    def model_name(self) -> str:
        """Целевое имя модели (не загруженной, а настроенной)."""
        return self._target or ""

    def prepare(
        self,
        config: RecognitionConfig,
        on_status: StatusCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Скачивание/загрузка vosk-модели. Возвращает подпись движка.

        Идемпотентна: если нужная модель уже загружена в этом объекте,
        повторный вызов не трогает сеть, а сразу шлёт ``model_ready``.
        """
        name = self._target or vosk_model_name("small")
        if self._model is not None and self._model_name == name:
            self._signal(on_status, "model_ready")
            return "vosk"
        self._signal(on_status, "loading_model")
        vosk = _import_vosk()
        if on_progress is not None:
            try:
                on_progress({"phase": "download", "model": name, "percent": 0.0, "message": "Готовим vosk-модель…"})
            except Exception:
                pass
        # Model(model_name=...) сам найдёт/скачает и распакует нужную модель.
        model = vosk.Model(model_name=name)
        self._model = model
        self._vosk = vosk
        self._model_name = name
        self._signal(on_status, "model_ready")
        return "vosk"

    def release_cached_model(self) -> bool:
        if self._model is None:
            return False
        self._model = None
        self._vosk = None
        self._model_name = ""
        return True

    @staticmethod
    def _signal(cb: StatusCallback | None, value: str) -> None:
        if cb is None:
            return
        try:
            cb(value)
        except Exception:
            return

    def transcribe(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Any = None,
        on_segment: SegmentCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> list[Segment]:
        """Распознать один массив (окно фразы) и вернуть один сегмент.

        Принимается только ``np.ndarray`` в 16 кГц моно float32. Если передан
        str (путь к файлу) - vosk не используется для файлов, кидаем ясную
        ошибку.
        """
        if not isinstance(source, np.ndarray):
            raise ValueError("vosk движок обрабатывает только потоковое аудио-массив, а не файл")
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            self._signal(on_status, "cancelled")
            return []
        model, vosk = self._require()
        audio = np.ascontiguousarray(np.asarray(source, dtype=np.float32).reshape(-1))
        if len(audio) / RATE < MIN_WINDOW_SECONDS:
            self._signal(on_status, "completed")
            return []

        self._signal(on_status, "transcribing_cpu")
        rec = vosk.KaldiRecognizer(model, RATE)
        try:
            rec.SetWords(True)
        except Exception:
            pass  # маленькие модели не поддерживают слова, потерпим
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype("<i2").tobytes()
        rec.AcceptWaveform(pcm)
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            self._signal(on_status, "cancelled")
            return []
        blob = rec.FinalResult()
        self._signal(on_status, "completed")
        text, words, avg_conf = _word_conf_text(blob)
        if not text:
            return []
        # Чувствительность "Речь": не показываем то, чему vosk не уверен.
        # Если conf нет - не отбрасываем вслепую, но и не подсвечиваем его как
        # обработанное: просто возвращаем, pipeline пусть решает.
        if config.live_sensitivity == "speech" and words and avg_conf < 0.5:
            return []
        seconds = len(audio) / RATE
        segment: Segment = {"start": 0.0, "end": seconds, "text": text}
        if words:
            segment["words"] = [dict(w) for w in words]
        if on_segment is not None:
            try:
                on_segment(dict(segment))
            except Exception:
                pass
        return [segment]

    def disk_status(self, model_name: str) -> dict[str, Any]:
        """Наличие vosk-модели в кеше по фактическому каталогу (без сети)."""
        try:
            _import_vosk()
        except RuntimeError:
            return {"model": model_name, "ready": False, "bytes": 0,
                    "message": "vosk не установлен"}
        import os

        # vosk раскладывает модель в ~/.cache/vosk (или LOCALAPPDATA на Windows)
        bases = [Path(os.path.expanduser("~")) / ".cache" / "vosk",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "vosk"]
        for base in bases:
            folder = Path(base) / model_name
            if not folder.is_dir():
                continue
            size = 0
            for item in folder.rglob("*"):
                if item.is_file():
                    try:
                        size += item.stat().st_size
                    except OSError:
                        continue
            return {"model": model_name, "ready": True, "bytes": size,
                    "message": f"В кеше vosk · {size / (1024 * 1024):.0f} МБ"}
        return {"model": model_name, "ready": False, "bytes": 0,
                "message": "Ещё не скачана · загрузится при подготовке Live"}

    def _require(self):
        if self._model is None or self._vosk is None:
            raise RuntimeError("Vosk-модель не загружена. Подготовьте модель перед Live.")
        return self._model, self._vosk


__all__ = ["VoskEngine", "vosk_model_name"]
