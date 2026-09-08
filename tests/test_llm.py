"""Каталог локальных моделей, подбор под железо и разбор потока токенов."""

from __future__ import annotations

import threading

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


def test_a_small_card_does_not_downgrade_a_strong_processor() -> None:
    """Если целиком не влезает даже лёгкая модель, решает процессор.

    Карта на 3 ГБ всё равно возьмёт часть слоёв, но выбирать модель по ней
    нельзя: на машине с 16 ГБ ОЗУ обычная модель пойдёт, а на слабой - нет.
    """

    assert llm.recommend_model(_profile(threads=16, ram_gb=32, vram_gb=3, offload=True)) == "qwen3-4b"
    assert llm.recommend_model(_profile(threads=4, ram_gb=8, vram_gb=3, offload=True)) == "qwen3-1.7b"


def test_recommendation_falls_back_to_processor_memory() -> None:
    assert llm.recommend_model(_profile(threads=16, ram_gb=32)) == "qwen3-4b"
    assert llm.recommend_model(_profile(threads=4, ram_gb=8)) == "qwen3-1.7b"
    assert llm.recommend_model(_profile(threads=2, ram_gb=4)) == "qwen3-1.7b"
    # Неизвестный объём памяти не должен превращаться в ноль.
    assert llm.recommend_model(_profile(threads=16, ram_gb=None)) == llm.DEFAULT_MODEL_ID


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
    assert llm.plan_context(model, _profile(ram_gb=32)) == model.context
    assert llm.plan_context(model, _profile(ram_gb=6)) == 4096


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


def test_strip_thinking_cleans_a_finished_answer() -> None:
    assert llm.strip_thinking("<think>шум</think>  Ответ ") == "Ответ"


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
    assert engine.pick_runtime(model) is engine._llama

    engine.preference = "llama_cpp"
    engine._ollama = _FakeRuntime([], ready=True)
    assert engine.pick_runtime(model) is engine._llama


def test_engine_collects_the_answer_and_reports_tokens(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path, preference="llama_cpp")
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
    engine = llm.ChatEngine(tmp_path, preference="llama_cpp")
    engine._llama = _FakeRuntime(["раз", "два"])
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(llm.GenerationCancelled):
        engine.complete([{"role": "user", "content": "?"}], llm.MODELS_BY_ID["qwen3-4b"], cancel=cancel)


def test_engine_names_the_missing_runtime(tmp_path) -> None:
    engine = llm.ChatEngine(tmp_path, preference="llama_cpp")
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
