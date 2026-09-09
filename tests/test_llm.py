"""Каталог локальных моделей, подбор под железо и разбор потока токенов."""

from __future__ import annotations

import json
import threading
from io import StringIO

import pytest

from dotaudio import llm, modelhub
from dotaudio.hardware import (
    VENDOR_AMD,
    VENDOR_INTEL,
    VENDOR_NVIDIA,
    GpuDevice,
    HardwareProfile,
)


def _profile(
    threads: int = 8,
    ram_gb: float | None = 16.0,
    vram_gb: float | None = None,
    offload: bool | None = False,
    vendor: str = VENDOR_NVIDIA,
    integrated: bool = False,
) -> HardwareProfile:
    gpus: tuple[GpuDevice, ...] = ()
    if vram_gb is not None:
        gpus = (
            GpuDevice(
                index=0,
                name="Test GPU",
                vendor=vendor,
                vram_mb=int(vram_gb * 1024),
                integrated=integrated,
            ),
        )
    return HardwareProfile(
        threads=threads,
        ram_gb=ram_gb,
        gpus=gpus,
        platform="win32",
        llama_gpu_offload=offload,
    )


def test_catalog_entries_are_complete_and_unique() -> None:
    assert llm.CHAT_MODELS
    identifiers = [model.id for model in llm.CHAT_MODELS]
    assert len(identifiers) == len(set(identifiers))
    assert llm.DEFAULT_MODEL_ID in llm.MODELS_BY_ID
    for model in llm.CHAT_MODELS:
        # Размер файла нужен точный: по нему считается готовность на диске.
        assert model.size_bytes > 0
        assert model.filename.endswith(".gguf")
        assert "/" in model.repo
        assert model.layers > 0
        assert model.context >= 4096
        assert model.tier in llm.TIER_LABELS
        # Флаги шаблона должны совпадать с семейством, иначе чат падает на
        # первой же реплике с system / размышлением.
        if model.family.lower().startswith("gemma"):
            assert model.system_role is False
            assert model.thinking is False
        if model.family.startswith("Qwen3"):
            assert model.system_role is True
            assert model.thinking is True


def test_shape_messages_adapts_every_catalog_model() -> None:
    """Типичный запрос ассистента не должен оставлять system у Gemma
    и не должен давать два user подряд ни одной модели."""

    raw = [
        {"role": "system", "content": "Ты помощник по расшифровкам."},
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Здравствуй"},
        {"role": "user", "content": "Файл:\nданные"},
        {"role": "user", "content": "О чём это?"},
    ]
    for model in llm.CHAT_MODELS:
        shaped = llm.shape_messages(raw, model, llm.GenerationOptions())
        roles = [item["role"] for item in shaped]
        assert roles, model.id
        assert roles[0] in ("system", "user"), model.id
        if not model.system_role:
            assert "system" not in roles, model.id
            assert roles[0] == "user", model.id
        else:
            assert roles[0] == "system", model.id
        for left, right in zip(roles, roles[1:]):
            assert left != right, (model.id, roles)
        if model.thinking:
            last_user = next(
                item["content"] for item in reversed(shaped) if item["role"] == "user"
            )
            assert last_user.rstrip().endswith(llm.NO_THINK_SWITCH), model.id


def test_gemma_folds_system_role_into_first_user_turn() -> None:
    """Шаблон Gemma падает на role=system: инструкцию переносим в user."""

    gemma = llm.MODELS_BY_ID["vikhr-gemma-2b"]
    assert gemma.system_role is False
    shaped = llm.shape_messages(
        [
            {"role": "system", "content": "Ты помощник."},
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуй"},
            {"role": "user", "content": "Как дела?"},
        ],
        gemma,
        llm.GenerationOptions(),
    )
    assert [item["role"] for item in shaped] == ["user", "assistant", "user"]
    assert shaped[0]["content"].startswith("Ты помощник.")
    assert shaped[0]["content"].endswith("Привет")
    assert "system" not in {item["role"] for item in shaped}


def test_gemma3_also_rejects_system_role() -> None:
    shaped = llm.shape_messages(
        [
            {"role": "system", "content": "Правила"},
            {"role": "user", "content": "Вопрос"},
        ],
        llm.MODELS_BY_ID["gemma-3-4b"],
        llm.GenerationOptions(),
    )
    assert [item["role"] for item in shaped] == ["user"]
    assert "Правила" in shaped[0]["content"]
    assert "Вопрос" in shaped[0]["content"]


def test_qwen_keeps_system_role() -> None:
    shaped = llm.shape_messages(
        [
            {"role": "system", "content": "Инструкция"},
            {"role": "user", "content": "Вопрос"},
        ],
        llm.MODELS_BY_ID["qwen3-4b"],
        llm.GenerationOptions(),
    )
    assert shaped[0]["role"] == "system"
    assert shaped[0]["content"] == "Инструкция"
    assert shaped[1]["content"].endswith(llm.NO_THINK_SWITCH)


def test_adjacent_user_turns_are_merged_for_strict_templates() -> None:
    shaped = llm.shape_messages(
        [
            {"role": "system", "content": "Правила"},
            {"role": "user", "content": "файл"},
            {"role": "user", "content": "вопрос"},
        ],
        llm.MODELS_BY_ID["gemma-3-4b"],
        llm.GenerationOptions(),
    )
    assert [item["role"] for item in shaped] == ["user"]
    assert "файл" in shaped[0]["content"]
    assert "вопрос" in shaped[0]["content"]


def test_strip_thinking_cleans_a_finished_answer() -> None:
    assert llm.strip_thinking("<think>шум</think>  Ответ ") == "Ответ"


def test_ram_requirement_grows_with_the_file() -> None:
    """Требование к памяти не может быть меньше самой модели."""

    for model in llm.CHAT_MODELS:
        assert model.ram_gb > model.size_gb
        assert model.vram_gb >= model.size_gb


def test_video_memory_is_only_counted_when_the_build_can_use_it() -> None:
    # Карта есть, но сборка llama.cpp без ускорения: считать будем на CPU, и
    # обещать видеопамять нельзя.
    assert llm.usable_vram_gb(_profile(vram_gb=12, offload=False)) == 0.0
    assert llm.usable_vram_gb(_profile(vram_gb=12, offload=None)) == 0.0
    assert llm.usable_vram_gb(_profile(vram_gb=12, offload=True)) == 12.0
    # Встроенное видео делит память с системой: своей у него нет.
    assert llm.usable_vram_gb(_profile(vram_gb=8, offload=True, integrated=True)) == 0.0


def test_recommendation_follows_video_memory_when_offload_works() -> None:
    assert llm.recommend_model(_profile(vram_gb=24, offload=True)) == "qwen3-14b"
    assert llm.recommend_model(_profile(vram_gb=8.5, offload=True)) == "qwen3-8b"
    # 6 ГБ (типичный мобильный класс) не держат 8B вместе с контекстом.
    assert llm.recommend_model(_profile(vram_gb=6, offload=True)) == "qwen3-4b"


def test_a_small_card_falls_back_to_light_cpu_model() -> None:
    """Маленькая карта не влезает даже в лёгкую модель с запасом.

    Тогда совет идёт по CPU-пути: на процессоре по умолчанию light, а не 4B.
    """

    assert llm.recommend_model(_profile(threads=16, ram_gb=32, vram_gb=3, offload=True)) == "qwen3-1.7b"
    assert llm.recommend_model(_profile(threads=4, ram_gb=8, vram_gb=3, offload=True)) == "qwen3-1.7b"


def test_recommendation_falls_back_to_processor_memory() -> None:
    # Без GPU-offload даже на сильном CPU советуем лёгкую: 4B ползёт.
    assert llm.recommend_model(_profile(threads=16, ram_gb=32)) == "qwen3-1.7b"
    assert llm.recommend_model(_profile(threads=4, ram_gb=8)) == "qwen3-1.7b"
    assert llm.recommend_model(_profile(threads=2, ram_gb=4)) == "qwen3-1.7b"
    assert llm.recommend_model(_profile(threads=16, ram_gb=None)) == "qwen3-1.7b"


def test_plan_threads_leaves_one_core_for_the_ui() -> None:
    assert llm.plan_threads(_profile(threads=16)) == 15
    assert llm.plan_threads(_profile(threads=2)) == 2
    assert llm.plan_batch(_profile(offload=False)) == 256
    assert llm.plan_batch(_profile(vram_gb=12, offload=True)) == 512


def test_context_shrinks_without_gpu_offload() -> None:
    model = llm.MODELS_BY_ID["qwen3-4b"]
    assert llm.plan_context(model, _profile(ram_gb=32, offload=False)) == 4096
    assert llm.plan_context(model, _profile(ram_gb=32, vram_gb=12, offload=True)) == model.context


def test_recommendation_ignores_a_card_from_another_vendor_without_offload() -> None:
    """Radeon и Intel без рабочей сборки не дают права советовать тяжёлую модель."""

    for vendor in (VENDOR_AMD, VENDOR_INTEL):
        chosen = llm.recommend_model(_profile(threads=4, ram_gb=8, vram_gb=16, vendor=vendor))
        assert chosen == "qwen3-1.7b"


def test_model_fit_reports_memory_as_a_fact() -> None:
    heavy = llm.MODELS_BY_ID["qwen3-14b"]
    tight = llm.model_fit(heavy, _profile(threads=8, ram_gb=8))
    assert tight["state"] == "tight"
    assert "8" in tight["note"]

    fits = llm.model_fit(llm.MODELS_BY_ID["qwen3-4b"], _profile(vram_gb=12, offload=True))
    assert fits["state"] == "ok"

    partial = llm.model_fit(llm.MODELS_BY_ID["qwen3-14b"], _profile(vram_gb=6, offload=True))
    assert partial["state"] == "slow"


def test_gpu_layer_plan_is_all_or_a_share() -> None:
    model = llm.MODELS_BY_ID["qwen3-4b"]
    assert llm.plan_gpu_layers(model, _profile(vram_gb=12, offload=False)) == 0
    assert llm.plan_gpu_layers(model, _profile(vram_gb=12, offload=True)) > model.layers
    partial = llm.plan_gpu_layers(model, _profile(vram_gb=3.5, offload=True))
    assert 0 < partial < model.layers


def test_context_shrinks_on_a_small_machine() -> None:
    model = llm.MODELS_BY_ID["qwen3-4b"]
    # Без offload контекст всегда ужат: длинный промпт на CPU дорог.
    assert llm.plan_context(model, _profile(ram_gb=32)) == 4096
    assert llm.plan_context(model, _profile(ram_gb=6)) == 4096
    assert llm.plan_context(model, _profile(ram_gb=32, vram_gb=12, offload=True)) == model.context


def test_cpu_model_fit_warns_about_non_light_tiers() -> None:
    note = llm.model_fit(llm.MODELS_BY_ID["qwen3-4b"], _profile(threads=8, ram_gb=16))
    assert note["state"] == "slow"
    light = llm.model_fit(llm.MODELS_BY_ID["qwen3-1.7b"], _profile(threads=8, ram_gb=16))
    assert light["state"] == "ok"


def test_thinking_block_is_removed_even_when_split_between_chunks() -> None:
    """Поток приходит кусками, и тег может быть разрезан посередине."""

    filtered = llm._ThinkFilter()
    pieces = ["Сей", "час <thi", "nk>рассуждаю про", " запись</th", "ink>Ответ: ", "да"]
    visible = "".join(filtered.feed(piece) for piece in pieces) + filtered.flush()

    assert visible == "Сейчас Ответ: да"


def test_unclosed_thinking_block_does_not_leak_into_the_answer() -> None:
    filtered = llm._ThinkFilter()
    visible = filtered.feed("<think>думаю и не закрыл") + filtered.flush()

    assert visible == ""


class _FakeRuntime:
    """Рантайм-заглушка: отдаёт заранее известные куски."""

    id = "fake"
    label = "Заглушка"

    def __init__(self, pieces, ready=True, available=True) -> None:
        self.pieces = pieces
        self._ready = ready
        self._available = available
        self.seen: list = []

    def available(self) -> bool:
        return self._available

    def ready(self, _model) -> bool:
        return self._ready

    def status(self, _profile=None) -> dict:
        return {"id": self.id, "label": self.label, "detail": "заглушка"}

    def stream(self, messages, model, options, cancel=None, profile=None):
        self.seen.append((list(messages), options))
        for piece in self.pieces:
            if cancel is not None and cancel.is_set():
                raise llm.GenerationCancelled()
            yield piece


def test_engine_prefers_ollama_when_it_already_has_the_model(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path)
    model = llm.MODELS_BY_ID["qwen3-4b"]
    engine._ollama = _FakeRuntime([], ready=True)
    engine._llama = _FakeRuntime([], ready=True)

    assert engine.pick_runtime(model) is engine._ollama

    engine._ollama = _FakeRuntime([], ready=False)
    engine._subprocess = _FakeRuntime([], ready=True)
    assert engine.pick_runtime(model) is engine._subprocess

    engine.preference = "llama_cpp"
    engine._ollama = _FakeRuntime([], ready=True)
    engine._subprocess = _FakeRuntime([], ready=True)
    assert engine.pick_runtime(model) is engine._subprocess

    engine.preference = "llama_inplace"
    assert engine.pick_runtime(model) is engine._llama


def test_engine_collects_the_answer_and_reports_tokens(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path, preference="llama_inplace")
    engine._llama = _FakeRuntime(["Раз", " два", " три"])
    seen: list[str] = []

    text = engine.complete(
        [{"role": "user", "content": "?"}],
        llm.MODELS_BY_ID["qwen3-4b"],
        on_token=seen.append,
    )

    assert text == "Раз два три"
    assert seen == ["Раз", " два", " три"]


def test_engine_stops_on_cancel(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path, preference="llama_inplace")
    engine._llama = _FakeRuntime(["раз", "два"])
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(llm.GenerationCancelled):
        engine.complete([{"role": "user", "content": "?"}], llm.MODELS_BY_ID["qwen3-4b"], cancel=cancel)


def test_engine_names_the_missing_runtime(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path, preference="llama_inplace")
    engine._llama = _FakeRuntime([], available=False)

    with pytest.raises(llm.RuntimeUnavailable):
        engine.complete([{"role": "user", "content": "?"}], llm.MODELS_BY_ID["qwen3-4b"])


def test_catalog_cards_show_what_is_on_disk(tmp_path) -> None:
    model = llm.MODELS_BY_ID["qwen3-1.7b"]
    target = modelhub.local_path(tmp_path, model.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"0")

    cards = {card["id"]: card for card in llm.catalog_cards(tmp_path, _profile())}

    # Обрезанный файл не готов: отдать его модели значит получить непонятную
    # ошибку загрузки вместо ясного «скачано не полностью».
    assert cards[model.id]["onDisk"] is False
    assert cards[model.id]["downloadedBytes"] == 1
    assert cards["qwen3-4b"]["sizeGb"] == llm.MODELS_BY_ID["qwen3-4b"].size_gb


class _FakeWorkerProcess:
    """Имитация llm_worker: ping, load, chat, release."""

    def __init__(self) -> None:
        self.stdin = self
        self.stdout = self
        self._pending = ""
        self._out: list[str] = []

    def write(self, data: str) -> None:
        self._pending += data
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            payload = json.loads(line)
            cmd = payload["cmd"]
            if cmd == "ping":
                self._out.append(json.dumps({"type": "ok"}) + "\n")
            elif cmd == "load":
                self._out.append(json.dumps({"type": "ok"}) + "\n")
            elif cmd == "release":
                self._out.append(json.dumps({"type": "ok"}) + "\n")
            elif cmd == "chat":
                self._out.append(json.dumps({"type": "token", "text": "Привет"}) + "\n")
                self._out.append(json.dumps({"type": "done", "text": "Привет"}) + "\n")

    def flush(self) -> None:
        return

    def readline(self) -> str:
        return self._out.pop(0) if self._out else ""

    def poll(self):
        return None

    def kill(self) -> None:
        return

    def wait(self, timeout=None) -> int:
        return 0

    def close(self) -> None:
        return


def test_subprocess_runtime_streams_tokens(tmp_path, monkeypatch) -> None:
    worker = _FakeWorkerProcess()
    real_popen = llm.subprocess.Popen

    def fake_popen(args, *popen_args, **kwargs):
        if "-m" in args and "dotaudio.llm_worker" in args:
            return worker
        return real_popen(args, *popen_args, **kwargs)

    monkeypatch.setattr(llm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llm.hardware, "import_llama_cpp", lambda: object())

    runtime = llm.SubprocessLlamaRuntime(tmp_path)
    model = llm.MODELS_BY_ID["qwen3-1.7b"]
    target = modelhub.local_path(tmp_path, model.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")
    profile = _profile(offload=False)

    runtime.load(model, profile)
    pieces = list(
        runtime.stream(
            [{"role": "user", "content": "?"}],
            model,
            llm.GenerationOptions(),
            profile=profile,
        )
    )
    assert pieces == ["Привет"]


def test_llm_worker_ping_and_release(monkeypatch) -> None:
    from dotaudio import llm_worker

    stdin = StringIO('{"cmd":"ping"}\n{"cmd":"release"}\n')
    stdout = StringIO()
    monkeypatch.setattr(llm_worker.sys, "stdin", stdin)
    monkeypatch.setattr(llm_worker.sys, "stdout", stdout)
    llm_worker.main()
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines == [{"type": "ok"}, {"type": "ok"}]
