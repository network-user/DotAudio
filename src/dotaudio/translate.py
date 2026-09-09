"""Speech modes and local EN→RU text translation (CTranslate2 + OPUS-MT).

Whisper cannot emit Russian from English speech. Mode ``en_ru`` recognises
English with Whisper, then this module translates the text on device with a
Marian OPUS-MT model converted to CTranslate2. No network at translate time;
the model zip is downloaded once into the app data directory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

# speech_mode → (language, task) for RecognitionConfig.
# en_ru keeps ASR on English; the controller then runs local MT.
SPEECH_MODES: dict[str, tuple[str, str]] = {
    "ru": ("ru", "transcribe"),
    "en": ("en", "transcribe"),
    "en_ru": ("en", "transcribe"),
}

SPEECH_MODE_ORDER = ("ru", "en", "en_ru")

SPEECH_MODE_LABELS = {
    "ru": "Русский",
    "en": "English",
    "en_ru": "EN → RU",
}

SPEECH_MODE_HINTS = {
    "ru": "Распознавание русской речи как есть",
    "en": "Распознавание английской речи как есть",
    "en_ru": "Английская речь → русский текст (локальный перевод)",
}

POST_TRANSLATE = {
    "en_ru": ("en", "ru"),
}

# Official OPUS-MT Marian package (Helsinki-NLP / CSC). Downloaded once, then
# converted with the ct2-opus-mt-converter that ships with ctranslate2.
OPUS_EN_RU_URL = "https://object.pouta.csc.fi/OPUS-MT-models/en-ru/opus-2020-02-11.zip"
OPUS_EN_RU_SIZE_BYTES = 298_000_000  # approximate; progress still works without exact size
MT_KIND = "mt"
MT_PAIR = "en-ru"


def normalize_speech_mode(value: object) -> str:
    mode = str(value or "ru").strip().lower()
    # Old Whisper-translate mode is gone: fall back to plain English ASR.
    if mode == "ru_en":
        return "en"
    return mode if mode in SPEECH_MODES else "ru"


def speech_mode_label(value: object) -> str:
    return SPEECH_MODE_LABELS[normalize_speech_mode(value)]


def speech_mode_hint(value: object) -> str:
    return SPEECH_MODE_HINTS[normalize_speech_mode(value)]


def next_speech_mode(current: object) -> str:
    mode = normalize_speech_mode(current)
    index = SPEECH_MODE_ORDER.index(mode)
    return SPEECH_MODE_ORDER[(index + 1) % len(SPEECH_MODE_ORDER)]


def language_task_for(mode: object) -> tuple[str, str]:
    return SPEECH_MODES[normalize_speech_mode(mode)]


def speech_mode_from_language_task(language: object, task: object) -> str:
    """Recover speech_mode from older language/task settings."""

    lang = str(language or "ru").strip().lower()
    work = str(task or "transcribe").strip().lower()
    # Whisper translate used to mean RU→EN; that mode is removed.
    if work == "translate":
        return "en"
    if lang == "en":
        return "en"
    if lang == "ru":
        return "ru"
    return "ru"


def needs_post_translate(mode: object) -> bool:
    return normalize_speech_mode(mode) in POST_TRANSLATE


def post_pair(mode: object) -> tuple[str, str] | None:
    return POST_TRANSLATE.get(normalize_speech_mode(mode))


def mt_root(data_dir: Path) -> Path:
    return Path(data_dir) / "models" / MT_KIND / MT_PAIR


def marian_dir(data_dir: Path) -> Path:
    return mt_root(data_dir) / "marian"


def ct2_dir(data_dir: Path) -> Path:
    return mt_root(data_dir) / "ct2"


def source_spm_path(data_dir: Path) -> Path:
    return marian_dir(data_dir) / "source.spm"


def target_spm_path(data_dir: Path) -> Path:
    return marian_dir(data_dir) / "target.spm"


def model_ready(data_dir: Path | None) -> bool:
    if data_dir is None:
        return False
    root = Path(data_dir)
    model = ct2_dir(root)
    return (
        model.is_dir()
        and (model / "model.bin").is_file()
        and source_spm_path(root).is_file()
        and target_spm_path(root).is_file()
    )


def model_status(data_dir: Path | None) -> dict:
    """Disk status for the EN→RU package. No network."""

    if data_dir is None:
        return {"ready": False, "phase": "missing", "message": "Каталог данных не задан"}
    root = Path(data_dir)
    if model_ready(root):
        return {"ready": True, "phase": "ready", "message": "Локальный переводчик готов"}
    zip_path = mt_root(root) / "opus-en-ru.zip"
    if zip_path.is_file():
        return {"ready": False, "phase": "packed", "message": "Архив скачан, ждёт конвертацию"}
    if marian_dir(root).is_dir():
        return {"ready": False, "phase": "marian", "message": "Модель распакована, ждёт конвертацию"}
    return {
        "ready": False,
        "phase": "missing",
        "message": "Нужна однократная загрузка локальной модели перевода (~300 МБ)",
    }


def _find_marian_bundle(extracted: Path) -> Path:
    """Return the directory that contains Marian OPUS files after unzip."""

    if (extracted / "source.spm").is_file() and (extracted / "model.npz").is_file():
        return extracted
    for child in sorted(extracted.rglob("source.spm")):
        parent = child.parent
        if (parent / "model.npz").is_file() or (parent / "decoder.yml").is_file():
            return parent
    raise RuntimeError("в архиве OPUS-MT не найдены source.spm / model.npz")


def _run_ct2_converter(marian: Path, output: Path) -> None:
    """Convert Marian OPUS-MT weights to CTranslate2 on disk."""

    if output.exists():
        shutil.rmtree(output, ignore_errors=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "ctranslate2.converters.opus_mt",
        "--model_dir",
        str(marian),
        "--output_dir",
        str(output),
        "--quantization",
        "int8",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not (output / "model.bin").is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "не удалось конвертировать модель перевода")


def download_and_prepare(
    data_dir: Path,
    *,
    url: str = OPUS_EN_RU_URL,
    on_progress: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download OPUS-MT en-ru once, convert to CT2, return the CT2 directory."""

    root = Path(data_dir)
    if model_ready(root):
        return ct2_dir(root)

    bundle = mt_root(root)
    bundle.mkdir(parents=True, exist_ok=True)
    zip_path = bundle / "opus-en-ru.zip"
    extract_tmp = bundle / "_extract"
    marian = marian_dir(root)
    output = ct2_dir(root)

    if not zip_path.is_file() or zip_path.stat().st_size < 1_000_000:
        _download_file(
            url,
            zip_path,
            on_progress=on_progress,
            cancel=cancel,
            timeout=timeout,
            expected=OPUS_EN_RU_SIZE_BYTES,
        )

    if cancel is not None and cancel.is_set():
        raise RuntimeError("загрузка переводчика отменена")

    if on_progress is not None:
        on_progress({"phase": "extract", "ratio": 0.0, "message": "Распаковываем модель перевода"})

    if extract_tmp.exists():
        shutil.rmtree(extract_tmp, ignore_errors=True)
    extract_tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_tmp)
    found = _find_marian_bundle(extract_tmp)
    if marian.exists():
        shutil.rmtree(marian, ignore_errors=True)
    shutil.move(str(found), str(marian))
    shutil.rmtree(extract_tmp, ignore_errors=True)

    if on_progress is not None:
        on_progress({"phase": "convert", "ratio": 0.0, "message": "Конвертируем модель под локальный движок"})

    _run_ct2_converter(marian, output)
    if not model_ready(root):
        raise RuntimeError("после конвертации модель перевода не готова")
    if on_progress is not None:
        on_progress({"phase": "ready", "ratio": 1.0, "message": "Локальный переводчик готов"})
    return output


def _download_file(
    url: str,
    target: Path,
    *,
    on_progress: Callable[[dict], None] | None,
    cancel: threading.Event | None,
    timeout: float,
    expected: int,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Accept-Encoding": "identity"}
    if done:
        headers["Range"] = f"bytes={done}-"
    name = Path(urlparse(url).path).name or target.name

    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 416 and part.exists():
                part.replace(target)
                return
            if done and response.status_code == 200:
                done = 0
                part.unlink(missing_ok=True)
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            total = expected
            if length and length.isdigit():
                total = done + int(length)
            mode = "ab" if done else "wb"
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    if cancel is not None and cancel.is_set():
                        handle.flush()
                        raise RuntimeError("загрузка переводчика отменена")
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(
                            {
                                "phase": "download",
                                "bytes": done,
                                "total": total,
                                "ratio": (done / total) if total else 0.0,
                                "file": name,
                                "message": "Скачиваем локальную модель перевода",
                            }
                        )
    part.replace(target)


class Translator:
    """Cached local EN→RU translator. Injectable ``translate_fn`` for tests."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        translate_fn: Callable[[str, str, str], str] | None = None,
        # Legacy test hook from the MyMemory prototype.
        fetch: Callable[[str], dict] | None = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._translate_fn = translate_fn
        self._fetch = fetch
        self._cache: dict[tuple[str, str, str], str] = {}
        self._lock = threading.Lock()
        self._ct2 = None
        self._source_spm = None
        self._target_spm = None
        self.last_error = ""

    @property
    def data_dir(self) -> Path | None:
        return self._data_dir

    def set_data_dir(self, data_dir: Path | None) -> None:
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self.release()

    def ready(self) -> bool:
        if self._translate_fn is not None or self._fetch is not None:
            return True
        return model_ready(self._data_dir)

    def status(self) -> dict:
        if self._translate_fn is not None or self._fetch is not None:
            return {"ready": True, "phase": "ready", "message": "Тестовый переводчик"}
        return model_status(self._data_dir)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
        self.last_error = ""

    def release(self) -> None:
        with self._lock:
            self._cache.clear()
            self._ct2 = None
            self._source_spm = None
            self._target_spm = None

    def ensure(self, on_progress=None, cancel: threading.Event | None = None) -> None:
        if self.ready():
            return
        if self._data_dir is None:
            raise RuntimeError("не задан каталог для модели перевода")
        download_and_prepare(self._data_dir, on_progress=on_progress, cancel=cancel)
        self.release()

    def translate(self, text: str, source: str, target: str) -> str:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        src = str(source or "").strip().lower()
        dst = str(target or "").strip().lower()
        if not src or not dst or src == dst:
            return cleaned
        if (src, dst) != ("en", "ru"):
            self.last_error = "поддерживается только перевод EN→RU"
            return cleaned
        key = (cleaned.casefold(), src, dst)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            self.last_error = ""
            return hit
        try:
            rendered = self._request(cleaned, src, dst)
        except Exception as exc:  # noqa: BLE001 - surface load/decode faults
            self.last_error = str(exc) or exc.__class__.__name__
            return cleaned
        if not rendered:
            self.last_error = self.last_error or "пустой ответ переводчика"
            return cleaned
        self.last_error = ""
        with self._lock:
            self._cache[key] = rendered
        return rendered

    def _request(self, text: str, source: str, target: str) -> str:
        if self._translate_fn is not None:
            return str(self._translate_fn(text, source, target) or "").strip()
        if self._fetch is not None:
            payload = self._fetch(text)
            data = payload.get("responseData") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise RuntimeError("переводчик вернул неожиданный ответ")
            return str(data.get("translatedText") or "").strip()
        return self._translate_local(text)

    def _load_engine(self) -> None:
        if self._ct2 is not None:
            return
        if self._data_dir is None or not model_ready(self._data_dir):
            raise RuntimeError("локальная модель перевода ещё не установлена")
        import ctranslate2
        import sentencepiece as spm

        source = spm.SentencePieceProcessor()
        target = spm.SentencePieceProcessor()
        if not source.Load(str(source_spm_path(self._data_dir))):
            raise RuntimeError("не удалось открыть source.spm")
        if not target.Load(str(target_spm_path(self._data_dir))):
            raise RuntimeError("не удалось открыть target.spm")
        self._source_spm = source
        self._target_spm = target
        self._ct2 = ctranslate2.Translator(
            str(ct2_dir(self._data_dir)),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=0,
        )

    def _translate_local(self, text: str) -> str:
        with self._lock:
            self._load_engine()
            source = self._source_spm
            target = self._target_spm
            engine = self._ct2
        assert source is not None and target is not None and engine is not None
        tokens = source.encode(text, out_type=str)
        results = engine.translate_batch([tokens], beam_size=1, max_decoding_length=256)
        hypothesis = results[0].hypotheses[0] if results and results[0].hypotheses else []
        return str(target.decode(hypothesis) or "").strip()


_default = Translator()


def translate_text(text: str, source: str, target: str, *, translator: Translator | None = None) -> str:
    engine = translator or _default
    return engine.translate(text, source, target)


def apply_post_translate(
    segment: dict,
    mode: object,
    *,
    translator: Translator | None = None,
) -> dict:
    """Return a copy with text translated when the speech mode needs it."""

    pair = post_pair(mode)
    if pair is None:
        return segment
    source, target = pair
    original = str(segment.get("text") or "").strip()
    if not original:
        return segment
    rendered = translate_text(original, source, target, translator=translator)
    if rendered == original:
        return segment
    updated = {**segment, "text": rendered, "source_text": original}
    if "words" in updated:
        updated = {**updated, "words": []}
    return updated
