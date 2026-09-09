"""Локальная языковая модель: каталог, подбор под железо и генерация.

Модуль Qt-free. Он не знает ни про расшифровки, ни про интерфейс - только
про то, как загрузить модель на этой машине и получить от неё поток текста.
Работа с записями лежит в ``assistant.py``, а мост к QML - в
``assistant_controller.py``.

Рантайм выбирается из реестра. Сейчас их два: встроенный llama.cpp (модель
одним файлом GGUF рядом с историей) и уже запущенный Ollama по HTTP. Новый
рантайм добавляется классом с теми же четырьмя методами, каталог и интерфейс
при этом не меняются.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from dotaudio import hardware, modelhub
from dotaudio.hardware import HardwareProfile
from dotaudio.modelhub import ModelFile

OLLAMA_URL = os.environ.get("DOTAUDIO_OLLAMA_URL", "http://127.0.0.1:11434")

# Ступени каталога. Пользователю показывается ровно это: насколько модель
# тяжела для машины, а не внутреннее имя семейства.
TIER_LABELS = {
    "light": "Лёгкая",
    "balanced": "Обычная",
    "quality": "Точная",
    "heavy": "Тяжёлая",
}


@dataclass(frozen=True)
class ChatModel:
    """Чат-модель в каталоге: файл, требования и подписи.

    ``ram_gb`` и ``vram_gb`` - требования к памяти, посчитанные от размера
    файла плюс запас на контекст. Это оценка требований, а не замер скорости:
    скорость зависит от машины и заявляется только после прогона.
    """

    id: str
    label: str
    detail: str
    repo: str
    filename: str
    size_bytes: int
    params: str
    context: int
    layers: int
    ram_gb: float
    vram_gb: float
    tier: str
    family: str
    # Модели с режимом размышления печатают служебный блок перед ответом.
    # Для работы с расшифровкой он не нужен и отключается в запросе.
    thinking: bool = False
    # Gemma (и дообучения вроде Vikhr) в chat-шаблоне не принимают роль
    # system: шаблон падает с «System role not supported». Тогда инструкцию
    # переносим в первое user-сообщение в shape_messages.
    system_role: bool = True
    ollama: str = ""
    license: str = ""

    @property
    def file(self) -> ModelFile:
        return ModelFile(repo=self.repo, filename=self.filename, size_bytes=self.size_bytes)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1024**3, 2)

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier)


# Каталог. Ступени сделаны по памяти устройства: лёгкая идёт на слабой машине,
# обычная - выбор по умолчанию для типичного ноутбука с дискретной картой,
# точная и тяжёлая просят соответственно больше. Размеры файлов взяты из
# метаданных репозиториев, а не оценены.
CHAT_MODELS: tuple[ChatModel, ...] = (
    ChatModel(
        id="qwen3-1.7b",
        label="Qwen3 1.7B",
        detail="Лёгкая, отвечает и на слабом процессоре",
        repo="unsloth/Qwen3-1.7B-GGUF",
        filename="Qwen3-1.7B-Q4_K_M.gguf",
        size_bytes=1107409472,
        params="1,7 млрд",
        context=8192,
        layers=28,
        ram_gb=3.0,
        vram_gb=2.5,
        tier="light",
        family="Qwen3",
        thinking=True,
        ollama="qwen3:1.7b",
        license="Apache 2.0",
    ),
    ChatModel(
        id="vikhr-gemma-2b",
        label="Vikhr Gemma 2B",
        detail="Дообучена на русском, без режима размышления",
        repo="Vikhrmodels/Vikhr-Gemma-2B-instruct-GGUF",
        filename="Vikhr-Gemma-2B-instruct-Q4_K_M.gguf",
        size_bytes=1708582848,
        params="2,6 млрд",
        context=8192,
        layers=26,
        ram_gb=4.0,
        vram_gb=3.0,
        tier="light",
        family="Gemma 2",
        system_role=False,
        ollama="",
        license="Gemma",
    ),
    ChatModel(
        id="qwen3-4b",
        label="Qwen3 4B",
        detail="Обычная: держит длинный контекст и русский",
        repo="Qwen/Qwen3-4B-GGUF",
        filename="Qwen3-4B-Q4_K_M.gguf",
        size_bytes=2497280256,
        params="4 млрд",
        context=16384,
        layers=36,
        ram_gb=6.0,
        vram_gb=4.0,
        tier="balanced",
        family="Qwen3",
        thinking=True,
        ollama="qwen3:4b",
        license="Apache 2.0",
    ),
    ChatModel(
        id="gemma-3-4b",
        label="Gemma 3 4B",
        detail="Обычная, без размышления: короче и предсказуемее",
        repo="unsloth/gemma-3-4b-it-GGUF",
        filename="gemma-3-4b-it-Q4_K_M.gguf",
        size_bytes=2489894016,
        params="4,3 млрд",
        context=8192,
        layers=34,
        ram_gb=6.0,
        vram_gb=4.0,
        tier="balanced",
        family="Gemma 3",
        system_role=False,
        ollama="gemma3:4b",
        license="Gemma",
    ),
    ChatModel(
        id="qwen3-8b",
        label="Qwen3 8B",
        detail="Точная: заметно лучше в разборе длинных разговоров",
        repo="Qwen/Qwen3-8B-GGUF",
        filename="Qwen3-8B-Q4_K_M.gguf",
        size_bytes=5027783488,
        params="8 млрд",
        context=16384,
        layers=36,
        ram_gb=10.0,
        vram_gb=7.0,
        tier="quality",
        family="Qwen3",
        thinking=True,
        ollama="qwen3:8b",
        license="Apache 2.0",
    ),
    ChatModel(
        id="qwen3-14b",
        label="Qwen3 14B",
        detail="Тяжёлая: для машины с большой видеопамятью",
        repo="Qwen/Qwen3-14B-GGUF",
        filename="Qwen3-14B-Q4_K_M.gguf",
        size_bytes=9001752960,
        params="14 млрд",
        context=16384,
        layers=40,
        ram_gb=16.0,
        vram_gb=11.0,
        tier="heavy",
        family="Qwen3",
        thinking=True,
        ollama="qwen3:14b",
        license="Apache 2.0",
    ),
)

MODELS_BY_ID = {model.id: model for model in CHAT_MODELS}
DEFAULT_MODEL_ID = "qwen3-1.7b"

# Запас видеопамяти поверх веса модели: под контекст, буферы вычислений и то,
# что уже занял рабочий стол. Без него «влезает ровно» превращается в отказ
# драйвера на середине ответа.
VRAM_HEADROOM_GB = 1.4


def get_model(model_id: str) -> ChatModel | None:
    return MODELS_BY_ID.get(str(model_id or ""))


def usable_vram_gb(profile: HardwareProfile) -> float:
    """Видеопамять, на которую действительно можно рассчитывать.

    Ноль означает «считаем на процессоре»: или карты нет, или установленная
    сборка llama.cpp не умеет выгружать слои. Второе - самый частый случай,
    и он не должен выглядеть как отсутствие видеокарты.
    """

    if not profile.llama_gpu_offload:
        return 0.0
    gpu = profile.best_gpu
    if gpu is None or gpu.integrated or gpu.vram_mb is None:
        return 0.0
    return round(gpu.vram_mb / 1024, 2)


def recommend_model(profile: HardwareProfile | None = None) -> str:
    """Модель под это устройство: сначала по видеопамяти, иначе лёгкая на CPU.

    Без GPU-offload llama.cpp на 4B уже даёт единицы токенов в секунду.
    Поэтому на процессоре советуем light-ступень; тяжёлую пользователь
    выбирает сам, если готов ждать.
    """

    profile = profile or hardware.probe()
    vram = usable_vram_gb(profile)
    if vram:
        for model in ("qwen3-14b", "qwen3-8b", "qwen3-4b", "qwen3-1.7b"):
            if vram >= MODELS_BY_ID[model].vram_gb + VRAM_HEADROOM_GB:
                return model
    return "qwen3-1.7b"


def model_fit(model: ChatModel, profile: HardwareProfile | None = None) -> dict:
    """Пойдёт ли модель на этой машине, по факту памяти.

    Оценка памяти - сравнение с измеренным ОЗУ и видеопамятью. Оценка
    скорости - предупреждение по числу потоков, не замер.
    """

    profile = profile or hardware.probe()
    vram = usable_vram_gb(profile)
    if vram and vram >= model.vram_gb + VRAM_HEADROOM_GB:
        return {"state": "ok", "note": f"Целиком поместится в видеопамять ({vram:g} ГБ)"}
    ram = profile.ram_gb
    threads = int(profile.threads or 0)
    if ram is not None and ram < model.ram_gb:
        return {
            "state": "tight",
            "note": f"Просит около {model.ram_gb:g} ГБ памяти, у вас {ram:g} ГБ",
        }
    if vram:
        return {
            "state": "slow",
            "note": "В видеопамять целиком не влезет: часть слоёв останется на процессоре",
        }
    if threads and threads < 4 and model.tier != "light":
        return {"state": "slow", "note": "Мало потоков процессора: возьмите лёгкую модель"}
    if model.tier in ("quality", "heavy") and not vram:
        return {"state": "slow", "note": "На процессоре ответ будет идти долго"}
    if model.tier not in ("light",) and not vram:
        return {
            "state": "slow",
            "note": "На процессоре быстрее лёгкая модель (1.7B / Vikhr 2B)",
        }
    return {"state": "ok", "note": "Подходит этому устройству"}


def plan_gpu_layers(model: ChatModel, profile: HardwareProfile | None = None) -> int:
    """Сколько слоёв модели отдать видеокарте.

    Ноль - весь расчёт на процессоре. Число больше числа слоёв llama.cpp
    сама приводит к максимуму, поэтому полная выгрузка передаётся с запасом.
    """

    profile = profile or hardware.probe()
    vram = usable_vram_gb(profile)
    if vram <= 0:
        return 0
    if vram >= model.vram_gb + VRAM_HEADROOM_GB:
        return model.layers + 8
    budget = vram - VRAM_HEADROOM_GB
    if budget <= 0:
        return 0
    share = budget / model.vram_gb
    return max(0, min(model.layers, int(model.layers * share)))


def plan_threads(profile: HardwareProfile | None = None) -> int:
    """Потоки llama.cpp: почти все ядра, одно оставляем интерфейсу."""

    profile = profile or hardware.probe()
    available = max(1, int(profile.threads or 4))
    if available <= 2:
        return available
    return available - 1


def plan_batch(profile: HardwareProfile | None = None) -> int:
    """Размер батча промпта: на CPU меньше, чтобы не раздувать ОЗУ."""

    profile = profile or hardware.probe()
    if usable_vram_gb(profile) > 0:
        return 512
    return 256


def plan_context(model: ChatModel, profile: HardwareProfile | None = None) -> int:
    """Окно контекста под доступную память.

    Полное окно самой модели на слабой машине занимает столько же памяти,
    сколько её вес, поэтому на маленьком ОЗУ оно урезается. Без GPU
    длинный контекст ещё и сильно тормозит прогон промпта - держим 4K.
    """

    profile = profile or hardware.probe()
    if usable_vram_gb(profile) <= 0:
        return min(model.context, 4096)
    ram = profile.ram_gb
    if ram is not None and ram < model.ram_gb + 2:
        return min(model.context, 4096)
    return model.context


@dataclass
class GenerationOptions:
    """Параметры одного ответа."""

    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 900
    # Размышляющие модели по умолчанию печатают служебный блок. Для разбора
    # расшифровки он только тратит время, поэтому выключен.
    thinking: bool = False


class GenerationCancelled(RuntimeError):
    """Ответ остановлен пользователем."""


class RuntimeUnavailable(RuntimeError):
    """Рантайм не установлен или модель не загружена."""


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

# Мягкий переключатель Qwen3: модель понимает его прямо в тексте запроса и не
# пишет служебный блок размышления. Без него она сначала рассуждает - в разборе
# расшифровки это чистая потеря времени, потому что рассуждение мы выбрасываем.
NO_THINK_SWITCH = "/no_think"


def _fold_system_into_user(messages: list[dict]) -> list[dict]:
    """Склеить system-инструкции с первым user-ходом.

    Нужно моделям без роли system в шаблоне чата (Gemma и дообучения).
    Несколько system подряд объединяются; если user ещё нет - создаётся.
    """

    systems: list[str] = []
    rest: list[dict] = []
    for item in messages:
        if item.get("role") == "system":
            content = str(item.get("content") or "").strip()
            if content:
                systems.append(content)
            continue
        rest.append(item)
    if not systems:
        return rest
    instruction = "\n\n".join(systems)
    for item in rest:
        if item.get("role") == "user":
            body = str(item.get("content") or "")
            item["content"] = f"{instruction}\n\n{body}" if body else instruction
            return rest
    return [{"role": "user", "content": instruction}, *rest]


def _coalesce_turns(messages: list[dict]) -> list[dict]:
    """Слить соседние сообщения с одной ролью.

    Шаблон Gemma требует строгое чередование user/assistant. Два user подряд
    (файл + вопрос, оборванная история) дают TemplateError. Для Qwen склейка
    тоже безопасна и не меняет смысл.
    """

    out: list[dict] = []
    for item in messages:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role not in ("system", "user", "assistant") or not content.strip():
            continue
        if out and out[-1].get("role") == role:
            prev = str(out[-1].get("content") or "")
            out[-1]["content"] = f"{prev}\n\n{content}" if prev else content
            continue
        out.append({"role": role, "content": content})
    return out


def _ensure_user_first(messages: list[dict]) -> list[dict]:
    """После снятия system диалог должен начинаться с user (Gemma)."""

    if not messages:
        return messages
    if messages[0].get("role") == "user":
        return messages
    if messages[0].get("role") == "system":
        return messages
    # История без вопроса: редкий случай, но шаблон иначе падает.
    return [{"role": "user", "content": "."}, *messages]


def shape_messages(
    messages: Sequence[dict],
    model: ChatModel,
    options: GenerationOptions,
) -> list[dict]:
    """Подготовить сообщения под особенности модели из каталога.

    - Gemma 2/3 (и Vikhr): нет роли system, строгое чередование ходов.
    - Qwen3: system оставляем; по умолчанию гасим размышление через /no_think.
    """

    payload = [dict(item) for item in messages]
    if not model.system_role:
        payload = _fold_system_into_user(payload)
    payload = _coalesce_turns(payload)
    if not model.system_role:
        payload = _ensure_user_first(payload)
    if model.thinking and not options.thinking:
        for item in reversed(payload):
            if item.get("role") == "user":
                content = str(item.get("content") or "")
                if NO_THINK_SWITCH not in content:
                    item["content"] = f"{content}\n\n{NO_THINK_SWITCH}"
                break
    return payload


def strip_thinking(text: str) -> str:
    """Убрать служебный блок размышления из готового ответа."""

    return _THINK_BLOCK.sub("", text).strip()


class _ThinkFilter:
    """Отсекает блок ``<think>`` из потока токенов.

    Модель отдаёт текст по частям, поэтому тег может быть разрезан между
    двумя кусками. Фильтр держит хвост, который ещё может оказаться началом
    тега, и не пропускает его дальше, пока не станет ясно.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        out: list[str] = []
        while self._buffer:
            if self._inside:
                end = self._buffer.find(self.CLOSE)
                if end < 0:
                    keep = len(self.CLOSE) - 1
                    self._buffer = self._buffer[-keep:] if keep else ""
                    return "".join(out)
                self._buffer = self._buffer[end + len(self.CLOSE):]
                self._inside = False
                continue
            start = self._buffer.find(self.OPEN)
            if start >= 0:
                out.append(self._buffer[:start])
                self._buffer = self._buffer[start + len(self.OPEN):]
                self._inside = True
                continue
            # Возможное начало тега на границе куска оставляем в буфере.
            hold = 0
            for size in range(1, min(len(self.OPEN), len(self._buffer)) + 1):
                if self.OPEN.startswith(self._buffer[-size:]):
                    hold = size
            if hold:
                out.append(self._buffer[:-hold])
                self._buffer = self._buffer[-hold:]
            else:
                out.append(self._buffer)
                self._buffer = ""
            return "".join(out)
        return "".join(out)

    def flush(self) -> str:
        tail = "" if self._inside else self._buffer
        self._buffer = ""
        return tail


class LlamaCppRuntime:
    """Встроенный llama.cpp: модель одним файлом GGUF рядом с историей."""

    id = "llama_cpp"
    label = "Встроенный (llama.cpp)"

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._lock = threading.RLock()
        self._loaded = None
        self._loaded_key: tuple | None = None

    def available(self) -> bool:
        return hardware.import_llama_cpp() is not None

    def version(self) -> str:
        module = hardware.import_llama_cpp()
        return "" if module is None else str(getattr(module, "__version__", ""))

    def status(self, profile: HardwareProfile | None = None) -> dict:
        profile = profile or hardware.probe()
        installed = self.available()
        return {
            "id": self.id,
            "label": self.label,
            "installed": installed,
            "version": self.version(),
            "gpu": bool(profile.llama_gpu_offload) if installed else False,
            "detail": (
                "Не установлен: чат без него не запустится"
                if not installed
                else (
                    "Сборка с ускорением на видеокарте"
                    if profile.llama_gpu_offload
                    else "Сборка без ускорения: расчёт на процессоре"
                )
            ),
        }

    def model_path(self, model: ChatModel) -> Path:
        return modelhub.local_path(self.models_dir, model.file)

    def ready(self, model: ChatModel) -> bool:
        return bool(modelhub.disk_status(self.models_dir, model.file)["ready"])

    def load(self, model: ChatModel, profile: HardwareProfile | None = None):
        """Загрузить модель в память, переиспользуя уже загруженную."""

        module = hardware.import_llama_cpp()
        if module is None:
            raise RuntimeUnavailable("llama-cpp-python не установлен или не загрузился")
        profile = profile or hardware.probe()
        path = self.model_path(model)
        if not path.exists():
            raise RuntimeUnavailable(f"Файл модели не скачан: {path.name}")
        layers = plan_gpu_layers(model, profile)
        context = plan_context(model, profile)
        threads = plan_threads(profile)
        batch = plan_batch(profile)
        key = (str(path), context, layers, threads, batch)
        with self._lock:
            if self._loaded is not None and self._loaded_key == key:
                return self._loaded
            self.release()
            if layers > 0:
                from dotaudio.vram_arbiter import get_arbiter

                get_arbiter().acquire("llm")
            try:
                self._loaded = module.Llama(
                    model_path=str(path),
                    n_ctx=context,
                    n_threads=threads,
                    n_gpu_layers=layers,
                    n_batch=batch,
                    verbose=False,
                )
            except OSError as error:
                # Готовая сборка llama.cpp может требовать инструкций, которых
                # у этого процессора нет: библиотека импортируется, а падает
                # уже при создании контекста. Проверено на этой машине с
                # CUDA-сборкой из публичного индекса. Сказать словами, что
                # делать, иначе пользователь видит только код ошибки Windows.
                self._loaded_key = None
                if layers > 0:
                    from dotaudio.vram_arbiter import get_arbiter

                    get_arbiter().release("llm")
                raise RuntimeUnavailable(
                    "Установленная сборка llama.cpp не запускается на этом процессоре. "
                    "Выберите сборку «Процессор» в каталоге моделей."
                ) from error
            self._loaded_key = key
            return self._loaded

    def release(self) -> None:
        """Выгрузить модель из памяти."""

        with self._lock:
            model = self._loaded
            key = self._loaded_key
            self._loaded = None
            self._loaded_key = None
        if key is not None and key[2] > 0:
            from dotaudio.vram_arbiter import get_arbiter

            get_arbiter().release("llm")
        if model is not None:
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def loaded(self) -> bool:
        with self._lock:
            return self._loaded is not None

    def stream(
        self,
        messages: Sequence[dict],
        model: ChatModel,
        options: GenerationOptions,
        cancel: threading.Event | None = None,
        profile: HardwareProfile | None = None,
    ) -> Iterator[str]:
        instance = self.load(model, profile)
        payload = shape_messages(messages, model, options)
        with self._lock:
            stream = instance.create_chat_completion(
                messages=payload,
                temperature=options.temperature,
                top_p=options.top_p,
                max_tokens=options.max_tokens,
                stream=True,
            )
            think = _ThinkFilter()
            for chunk in stream:
                if cancel is not None and cancel.is_set():
                    raise GenerationCancelled()
                for choice in chunk.get("choices", ()):
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if not piece:
                        continue
                    visible = think.feed(piece)
                    if visible:
                        yield visible
            tail = think.flush()
            if tail:
                yield tail


_WORKER_CRASH_HINT = (
    "Изолированный воркер языковой модели завершился неожиданно. "
    "Попробуйте сборку «Процессор», режим Ollama или перезапустите приложение."
)


class SubprocessLlamaRuntime:
    """llama.cpp в отдельном процессе: сбой CUDA не роняет интерфейс."""

    id = "llama_cpp"
    label = "Встроенный (llama.cpp, изолированно)"

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._io_lock = threading.Lock()
        self._loaded_key: tuple | None = None

    @staticmethod
    def _worker_env() -> dict[str, str]:
        env = os.environ.copy()
        try:
            import dotaudio

            root = str(Path(dotaudio.__file__).resolve().parent.parent)
            prefix = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = root if not prefix else root + os.pathsep + prefix
        except Exception:
            pass
        return env

    def _worker_command(self) -> list[str]:
        return [sys.executable, "-m", "dotaudio.llm_worker"]

    def _stop_worker(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass

    def _read_event(self) -> dict:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeUnavailable(_WORKER_CRASH_HINT)
        line = proc.stdout.readline()
        if not line:
            code = proc.poll()
            self._stop_worker()
            detail = f" (код {code})" if code is not None else ""
            raise RuntimeUnavailable(f"{_WORKER_CRASH_HINT}{detail}")
        try:
            return json.loads(line)
        except ValueError as error:
            self._stop_worker()
            raise RuntimeUnavailable(_WORKER_CRASH_HINT) from error

    def _ensure_worker(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._stop_worker()
        try:
            self._proc = subprocess.Popen(
                self._worker_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=self._worker_env(),
            )
        except OSError as error:
            raise RuntimeUnavailable(
                "Не удалось запустить изолированный воркер llama.cpp. "
                "Попробуйте режим «В процессе» или Ollama."
            ) from error
        self._write({"cmd": "ping"})
        event = self._read_event()
        if event.get("type") == "error":
            self._stop_worker()
            raise RuntimeUnavailable(str(event.get("message") or _WORKER_CRASH_HINT))

    def _write(self, payload: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeUnavailable(_WORKER_CRASH_HINT)
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _request(self, payload: dict) -> dict:
        with self._io_lock:
            self._ensure_worker()
            self._write(payload)
            event = self._read_event()
            if event.get("type") == "error":
                raise RuntimeUnavailable(str(event.get("message") or _WORKER_CRASH_HINT))
            return event

    def available(self) -> bool:
        return hardware.import_llama_cpp() is not None

    def version(self) -> str:
        module = hardware.import_llama_cpp()
        return "" if module is None else str(getattr(module, "__version__", ""))

    def status(self, profile: HardwareProfile | None = None) -> dict:
        profile = profile or hardware.probe()
        installed = self.available()
        return {
            "id": self.id,
            "label": self.label,
            "installed": installed,
            "version": self.version(),
            "gpu": bool(profile.llama_gpu_offload) if installed else False,
            "detail": (
                "Не установлен: чат без него не запустится"
                if not installed
                else (
                    "Отдельный процесс с ускорением на видеокарте"
                    if profile.llama_gpu_offload
                    else "Отдельный процесс, расчёт на процессоре"
                )
            ),
        }

    def model_path(self, model: ChatModel) -> Path:
        return modelhub.local_path(self.models_dir, model.file)

    def ready(self, model: ChatModel) -> bool:
        return bool(modelhub.disk_status(self.models_dir, model.file)["ready"])

    def load(self, model: ChatModel, profile: HardwareProfile | None = None):
        if not self.available():
            raise RuntimeUnavailable("llama-cpp-python не установлен или не загрузился")
        profile = profile or hardware.probe()
        path = self.model_path(model)
        if not path.exists():
            raise RuntimeUnavailable(f"Файл модели не скачан: {path.name}")
        layers = plan_gpu_layers(model, profile)
        context = plan_context(model, profile)
        threads = plan_threads(profile)
        batch = plan_batch(profile)
        key = (str(path), context, layers, threads, batch)
        with self._lock:
            if self._loaded_key == key:
                return self
            if layers > 0:
                from dotaudio.vram_arbiter import get_arbiter

                get_arbiter().acquire("llm")
            try:
                self._request(
                    {
                        "cmd": "load",
                        "path": str(path),
                        "context": context,
                        "layers": layers,
                        "threads": threads,
                        "batch": batch,
                    }
                )
            except RuntimeUnavailable:
                if layers > 0:
                    from dotaudio.vram_arbiter import get_arbiter

                    get_arbiter().release("llm")
                raise
            self._loaded_key = key
            return self

    def release(self) -> None:
        with self._lock:
            key = self._loaded_key
            self._loaded_key = None
        if key is not None and key[2] > 0:
            from dotaudio.vram_arbiter import get_arbiter

            get_arbiter().release("llm")
        try:
            self._request({"cmd": "release"})
        except RuntimeUnavailable:
            self._stop_worker()

    def loaded(self) -> bool:
        with self._lock:
            return self._loaded_key is not None

    def stream(
        self,
        messages: Sequence[dict],
        model: ChatModel,
        options: GenerationOptions,
        cancel: threading.Event | None = None,
        profile: HardwareProfile | None = None,
    ) -> Iterator[str]:
        self.load(model, profile)
        payload = shape_messages(messages, model, options or GenerationOptions())
        request = {
            "cmd": "chat",
            "messages": payload,
            "options": {
                "temperature": (options or GenerationOptions()).temperature,
                "top_p": (options or GenerationOptions()).top_p,
                "max_tokens": (options or GenerationOptions()).max_tokens,
            },
        }
        with self._io_lock:
            self._ensure_worker()
            self._write(request)
            while True:
                if cancel is not None and cancel.is_set():
                    self._stop_worker()
                    raise GenerationCancelled()
                event = self._read_event()
                if event.get("type") == "error":
                    raise RuntimeUnavailable(str(event.get("message") or _WORKER_CRASH_HINT))
                if event.get("type") == "token":
                    text = str(event.get("text") or "")
                    if text:
                        yield text
                if event.get("type") == "done":
                    break


class OllamaRuntime:
    """Уже запущенный Ollama по HTTP: модели ставит и хранит он сам."""

    id = "ollama"
    label = "Ollama"
    # Опрос службы - сетевой запрос. Его результат живёт несколько секунд,
    # иначе один экран интерфейса успевает спросить «есть ли модель» десяток
    # раз и каждый раз ждёт ответа или таймаута.
    TAGS_TTL_SECONDS = 5.0
    PROBE_TIMEOUT_SECONDS = 0.6

    def __init__(self, base_url: str = OLLAMA_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._cached: tuple[float, list[str] | None] | None = None

    def available(self) -> bool:
        return self.tags() is not None

    def tags(self, refresh: bool = False) -> list[str] | None:
        """Список установленных в Ollama моделей; None - служба не отвечает."""

        now = time.monotonic()
        with self._lock:
            if not refresh and self._cached is not None:
                stamped, value = self._cached
                if now - stamped < self.TAGS_TTL_SECONDS:
                    return None if value is None else list(value)
        names: list[str] | None
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            names = None
        else:
            found = [str(item.get("name", "")) for item in data.get("models", [])]
            names = [name for name in found if name]
        with self._lock:
            self._cached = (time.monotonic(), names)
        return None if names is None else list(names)

    def status(self, profile: HardwareProfile | None = None) -> dict:
        names = self.tags()
        return {
            "id": self.id,
            "label": self.label,
            "installed": names is not None,
            "version": "",
            "models": names or [],
            "gpu": None,
            "detail": (
                f"Служба отвечает, моделей: {len(names)}"
                if names is not None
                else "Служба не запущена на " + self.base_url
            ),
        }

    def ready(self, model: ChatModel) -> bool:
        if not model.ollama:
            return False
        names = self.tags() or []
        base = model.ollama.split(":")[0]
        return any(name == model.ollama or name.startswith(base + ":") for name in names)

    def resolve_name(self, model: ChatModel) -> str:
        names = self.tags() or []
        if model.ollama in names:
            return model.ollama
        base = model.ollama.split(":")[0] if model.ollama else ""
        for name in names:
            if base and name.startswith(base + ":"):
                return name
        return model.ollama

    def stream(
        self,
        messages: Sequence[dict],
        model: ChatModel,
        options: GenerationOptions,
        cancel: threading.Event | None = None,
        profile: HardwareProfile | None = None,
    ) -> Iterator[str]:
        name = self.resolve_name(model)
        if not name:
            raise RuntimeUnavailable("В Ollama нет подходящей модели")
        payload = {
            "model": name,
            "messages": shape_messages(messages, model, options),
            "stream": True,
            "think": bool(options.thinking),
            "options": {
                "temperature": options.temperature,
                "top_p": options.top_p,
                "num_predict": options.max_tokens,
            },
        }
        think = _ThinkFilter()
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=5.0)) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if cancel is not None and cancel.is_set():
                        raise GenerationCancelled()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    piece = str((chunk.get("message") or {}).get("content") or "")
                    if piece:
                        visible = think.feed(piece)
                        if visible:
                            yield visible
                    if chunk.get("done"):
                        break
        tail = think.flush()
        if tail:
            yield tail

    def release(self) -> None:
        """Ollama держит модель сама; выгружать её из приложения нечего."""

    def loaded(self) -> bool:
        return False


@dataclass
class ChatEngine:
    """Единая точка генерации: выбирает рантайм и отдаёт поток текста."""

    models_dir: Path
    preference: str = "auto"
    _llama: LlamaCppRuntime = field(init=False)
    _subprocess: SubprocessLlamaRuntime = field(init=False)
    _ollama: OllamaRuntime = field(init=False)

    def __post_init__(self) -> None:
        self._llama = LlamaCppRuntime(self.models_dir)
        self._subprocess = SubprocessLlamaRuntime(self.models_dir)
        self._ollama = OllamaRuntime()

    @property
    def llama(self) -> LlamaCppRuntime:
        return self._llama

    @property
    def subprocess(self) -> SubprocessLlamaRuntime:
        return self._subprocess

    @property
    def ollama(self) -> OllamaRuntime:
        return self._ollama

    def _builtin_llama(self):
        if self.preference == "llama_inplace":
            return self._llama
        if self._subprocess.available():
            return self._subprocess
        return self._llama

    def runtimes(self) -> tuple:
        return (self._ollama, self._builtin_llama())

    def status(self, profile: HardwareProfile | None = None) -> list[dict]:
        profile = profile or hardware.probe()
        return [runtime.status(profile) for runtime in self.runtimes()]

    def pick_runtime(self, model: ChatModel):
        """Рантайм для этой модели.

        ``auto``: запущенный Ollama с нужной моделью выигрывает - она уже
        загружена в его память, и второй копии в нашем процессе не нужно.
        Иначе идёт изолированный llama.cpp со скачанным файлом.
        ``llama_cpp`` - тот же изолированный путь; ``llama_inplace`` - старый
        in-process для отладки и тестов.
        """

        if self.preference == "ollama":
            return self._ollama
        if self.preference == "llama_inplace":
            return self._llama
        if self.preference == "llama_cpp":
            return self._builtin_llama()
        if self._ollama.ready(model):
            return self._ollama
        return self._builtin_llama()

    def ready(self, model: ChatModel) -> bool:
        runtime = self.pick_runtime(model)
        return bool(runtime.available() and runtime.ready(model))

    def stream(
        self,
        messages: Sequence[dict],
        model: ChatModel,
        options: GenerationOptions | None = None,
        cancel: threading.Event | None = None,
        profile: HardwareProfile | None = None,
    ) -> Iterator[str]:
        runtime = self.pick_runtime(model)
        if not runtime.available():
            raise RuntimeUnavailable(runtime.status(profile).get("detail", runtime.label))
        yield from runtime.stream(
            messages,
            model,
            options or GenerationOptions(),
            cancel=cancel,
            profile=profile,
        )

    def complete(
        self,
        messages: Sequence[dict],
        model: ChatModel,
        options: GenerationOptions | None = None,
        cancel: threading.Event | None = None,
        profile: HardwareProfile | None = None,
        on_token=None,
    ) -> str:
        """Собрать ответ целиком, попутно отдавая куски в ``on_token``."""

        pieces: list[str] = []
        for piece in self.stream(messages, model, options, cancel=cancel, profile=profile):
            pieces.append(piece)
            if on_token is not None:
                on_token(piece)
        return "".join(pieces).strip()

    def release(self) -> None:
        self._llama.release()
        self._subprocess.release()

    def loaded(self) -> bool:
        return self._llama.loaded() or self._subprocess.loaded()


def catalog_cards(
    models_dir: Path,
    profile: HardwareProfile | None = None,
    engine: ChatEngine | None = None,
    models: Iterable[ChatModel] = CHAT_MODELS,
) -> list[dict]:
    """Каталог для интерфейса: требования, пригодность и что уже на диске."""

    profile = profile or hardware.probe()
    ollama_names = engine.ollama.tags() if engine is not None else None
    cards: list[dict] = []
    for model in models:
        status = modelhub.disk_status(models_dir, model.file)
        fit = model_fit(model, profile)
        in_ollama = False
        if ollama_names is not None and model.ollama:
            base = model.ollama.split(":")[0]
            in_ollama = any(
                name == model.ollama or name.startswith(base + ":") for name in ollama_names
            )
        cards.append(
            {
                "id": model.id,
                "label": model.label,
                "detail": model.detail,
                "tier": model.tier,
                "tierLabel": model.tier_label,
                "family": model.family,
                "params": model.params,
                "sizeGb": model.size_gb,
                "context": model.context,
                "ramGb": model.ram_gb,
                "vramGb": model.vram_gb,
                "license": model.license,
                "state": fit["state"],
                "note": fit["note"],
                "ready": bool(status["ready"]) or in_ollama,
                "onDisk": bool(status["ready"]),
                "inOllama": in_ollama,
                "downloadedBytes": int(status["bytes"]),
                "gpuLayers": plan_gpu_layers(model, profile),
                "path": status["path"],
            }
        )
    return cards
