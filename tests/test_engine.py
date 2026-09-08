from __future__ import annotations

import sys
from threading import Event
from types import SimpleNamespace

import numpy as np

from dotaudio.engine import LIVE_CONTEXT_CHARS, LIVE_TAIL_SECONDS, Engine, RecognitionConfig


class _Segment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


def test_local_engine_caches_model_and_normalises_segments(monkeypatch) -> None:
    created: list[tuple[str, str, str]] = []

    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["vad_filter"] is True
            assert kwargs["beam_size"] == 5
            assert kwargs["word_timestamps"] is False
            return iter([_Segment(0, 0.5, " first "), _Segment(0.5, 1, "")]), object()

    def model(name: str, *, device: str, compute_type: str, cpu_threads: int):
        assert 1 <= cpu_threads <= 4
        created.append((name, device, compute_type))
        return FakeModel()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    engine = Engine()
    config = RecognitionConfig(device="cpu")
    assert engine.transcribe(np.zeros(1600, dtype=np.float32), config) == [
        {"start": 0.0, "end": 0.5, "text": "first"}
    ]
    engine.transcribe(np.zeros(1600, dtype=np.float32), config)
    assert created == [("base", "cpu", "int8")]


def test_cached_model_skips_loading_status(monkeypatch) -> None:
    statuses: list[str] = []

    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter([_Segment(0, 0.4, "ok")]), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    engine = Engine()
    config = RecognitionConfig(device="cpu")
    engine.transcribe(np.zeros(1600, dtype=np.float32), config, on_status=statuses.append)
    statuses.clear()
    engine.transcribe(np.zeros(1600, dtype=np.float32), config, on_status=statuses.append)
    assert "loading_model" not in statuses


def test_release_cached_model_frees_the_idle_instance(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: object()),
    )
    engine = Engine()
    engine.prepare(RecognitionConfig(device="cpu"))

    assert engine.release_cached_model() is True
    assert engine.release_cached_model() is False


def test_initial_prompt_keeps_local_dictionary_terms_bounded() -> None:
    prompt = Engine._initial_prompt("ru", "DotAudio; CTranslate2")
    assert prompt is not None
    assert "DotAudio" in prompt
    assert Engine._initial_prompt("en", "") is None
    assert len(Engine._initial_prompt("en", "x" * 1000) or "") == 700


def test_local_engine_cancellation_stops_between_segments(monkeypatch) -> None:
    cancel = Event()

    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter([_Segment(0, 1, "one"), _Segment(1, 2, "two")]), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    seen: list[dict] = []

    def receive(segment: dict) -> None:
        seen.append(segment)
        cancel.set()

    result = Engine().transcribe(np.zeros(1600), RecognitionConfig(device="cpu"), cancel, receive)
    assert result == [{"start": 0.0, "end": 1.0, "text": "one"}]
    assert seen == result


def test_auto_device_retries_cuda_runtime_error_on_cpu(monkeypatch) -> None:
    attempts: list[tuple[str, str]] = []

    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter([_Segment(0, 1, "ready")]), object()

    def model(_name: str, *, device: str, compute_type: str, cpu_threads: int):
        assert 1 <= cpu_threads <= 4
        attempts.append((device, compute_type))
        if device == "cuda":
            raise RuntimeError("could not load cublas64_12.dll")
        return FakeModel()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    assert Engine().transcribe(np.zeros(1600), RecognitionConfig()) == [
        {"start": 0.0, "end": 1.0, "text": "ready"}
    ]
    assert attempts == [("cuda", "float16"), ("cpu", "int8")]


def test_auto_device_reuses_cpu_after_cuda_runtime_failure(monkeypatch) -> None:
    created: list[str] = []

    class FakeModel:
        def __init__(self, device: str) -> None:
            self.device = device

        def transcribe(self, _source, **_kwargs):
            if self.device == "cuda":
                raise RuntimeError("cublas runtime failure")
            return iter([_Segment(0, 1, "ready")]), object()

    def model(_name: str, *, device: str, compute_type: str, cpu_threads: int):
        assert 1 <= cpu_threads <= 4
        del compute_type
        created.append(device)
        return FakeModel(device)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    engine = Engine()
    config = RecognitionConfig(device="auto", live_preview=True)

    assert engine.transcribe(np.zeros(1600), config)[0]["text"] == "ready"
    assert engine.transcribe(np.zeros(1600), config)[0]["text"] == "ready"
    assert created == ["cuda", "cpu"]


def test_remote_backend_posts_form_and_returns_segments(monkeypatch) -> None:
    calls: dict = {}

    class Response:
        status_code = 200

        def iter_bytes(self):
            yield b'{"segments":[{"start":1,"end":2,"text":"hello"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, method, url, **kwargs):
            calls.update(method=method, url=url, **kwargs)
            return Response()

    fake_httpx = SimpleNamespace(Client=Client, Timeout=lambda *args, **kwargs: object())
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    result = Engine().transcribe(
        np.zeros(1600), RecognitionConfig(backend="remote", language="ru")
    )
    assert result == [{"start": 1.0, "end": 2.0, "text": "hello"}]
    assert calls["method"] == "POST"
    assert calls["url"] == "http://127.0.0.1:8765/v1/transcribe"
    assert calls["data"] == {"model": "base", "language": "ru", "task": "transcribe"}


def test_media_recipe_keeps_sung_words_and_word_timings(monkeypatch) -> None:
    class Word:
        word, start, end = "привет", 0.1, 0.5

    class Segment:
        start, end, text, words = 0.0, 1.0, "привет", [Word()]

    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["vad_filter"] is False
            assert kwargs["word_timestamps"] is True
            assert kwargs["compression_ratio_threshold"] == 2.4
            return iter([Segment()]), object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()))
    assert Engine().transcribe(np.zeros(1600), RecognitionConfig(device="cpu", media_mode=True)) == [
        {"start": 0.0, "end": 1.0, "text": "привет", "words": [{"text": "привет", "start": 0.1, "end": 0.5}]}
    ]


class _Extractor:
    sampling_rate = 16000
    hop_length = 160
    nb_max_frames = 3000

    def __call__(self, audio, padding=160):
        del padding
        return np.zeros((80, len(audio) // self.hop_length), dtype=np.float32)


class _Decoder:
    is_multilingual = True

    def __init__(self, score: float | None = -0.2) -> None:
        self.features = None
        self.kwargs: dict = {}
        self.score = score
        self.languages: list[tuple[str, float]] = [("<|ru|>", 0.99)]
        self.detections = 0

    def detect_language(self, _features):
        self.detections += 1
        index = min(self.detections, len(self.languages)) - 1
        return [[self.languages[index]]]

    def generate(self, features, prompts, **kwargs):
        del prompts
        self.features = features
        self.kwargs = kwargs
        scores = [] if self.score is None else [self.score]
        return [SimpleNamespace(sequences_ids=[[10, 11, 50257]], scores=scores)]


class _LiveModel:
    """A model exposing the CTranslate2 internals the live window relies on."""

    def __init__(self, score: float | None = -0.2) -> None:
        self.feature_extractor = _Extractor()
        self.model = _Decoder(score)
        self.hf_tokenizer = object()
        self.hotwords = "unset"
        self.previous: list[int] = []

    def get_prompt(self, _tokenizer, previous, without_timestamps=False, hotwords=None):
        assert without_timestamps is True
        self.hotwords = hotwords
        self.previous = list(previous)
        return [50258, 50259, 50360, 50364]

    def transcribe(self, *_args, **_kwargs):
        raise AssertionError("the live window must not reach the padded 30 s path")


class _Tokenizer:
    eot = 50257
    sot_sequence = (50258, 50259, 50360)
    no_timestamps = 50364
    languages: list[str] = []

    def __init__(self, *_args, language="ru", **_kwargs) -> None:
        _Tokenizer.languages.append(language)

    def decode(self, tokens):
        assert tokens == [10, 11]
        return "  живой текст  "

    def encode(self, text):
        # One fake token per word is enough to see what reached the prompt.
        return [1000 + index for index, _word in enumerate(text.split())]


def _install_live_stack(monkeypatch, model):
    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *_a, **_k: model)
    )
    monkeypatch.setitem(
        sys.modules, "faster_whisper.tokenizer", SimpleNamespace(Tokenizer=_Tokenizer)
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(StorageView=SimpleNamespace(from_array=lambda array: array)),
    )


def test_live_window_sizes_the_encoder_to_the_phrase(monkeypatch) -> None:
    model = _LiveModel()
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(device="cpu", live_stream=True)

    result = Engine().transcribe(np.zeros(4 * 16000, dtype=np.float32), config)

    assert result == [{"start": 0.0, "end": 4.0, "text": "живой текст"}]
    # Four seconds of speech plus the silence margin, instead of the 3000
    # frames Whisper would otherwise pad every window to.
    assert model.model.features.shape[-1] == int((4.0 + LIVE_TAIL_SECONDS) * 100)
    assert model.model.kwargs["beam_size"] == 3
    assert model.model.kwargs["no_repeat_ngram_size"] == 3


def test_live_window_bounds_the_token_budget_and_the_dictionary_hint(monkeypatch) -> None:
    model = _LiveModel()
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(device="cpu", live_preview=True, initial_prompt="ток " * 200)

    Engine().transcribe(np.zeros(16000, dtype=np.float32), config)

    # A one second window cannot legitimately produce hundreds of tokens; the
    # cap is what stops a looping decoder from blocking the next caption.
    assert model.model.kwargs["max_length"] == 4 + 32
    assert len(model.hotwords) <= 150


def test_live_window_reads_the_previous_text_as_context(monkeypatch) -> None:
    model = _LiveModel()
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(
        device="cpu", live_stream=True, live_context="Сегодня мы говорим о распознавании речи в реальном"
    )

    Engine().transcribe(np.zeros(16000, dtype=np.float32), config)

    # Eight words of previous text reach the decoder as the previous segment.
    assert len(model.previous) == 8

    Engine().transcribe(np.zeros(16000, dtype=np.float32), RecognitionConfig(device="cpu", live_stream=True))
    assert model.previous == []


def test_live_context_is_bounded_and_cut_at_a_word() -> None:
    long_text = " ".join(f"слово{index}" for index in range(100))
    context = Engine._live_context(long_text)
    assert len(context) <= LIVE_CONTEXT_CHARS
    assert context.startswith("слово")
    assert long_text.endswith(context)
    assert Engine._live_context("  два   слова ") == "два слова"


def test_live_window_drops_an_echo_of_the_context() -> None:
    context = "Сегодня мы говорим о распознавании речи в реальном"
    # The decoder repeated the end of the prompt before reading the audio.
    assert Engine._drop_echo("в реальном времени. Живые субтитры", context) == "времени. Живые субтитры"
    # An ending changed by the second pass still counts as the same word.
    assert Engine._drop_echo("в реальный времени", context) == "времени"
    # One shared word is not an echo: "и", "в", "не" begin many phrases.
    assert Engine._drop_echo("реальном шаге вперёд", context) == "реальном шаге вперёд"
    assert Engine._drop_echo("времени.", context) == "времени."
    assert Engine._drop_echo("времени.", "") == "времени."


def test_live_language_follows_the_phrases_but_not_the_previews(monkeypatch) -> None:
    model = _LiveModel()
    model.model.languages = [("<|ru|>", 0.99), ("<|en|>", 0.98)]
    _install_live_stack(monkeypatch, model)
    _Tokenizer.languages = []
    engine = Engine()
    phrase = RecognitionConfig(device="cpu", language="auto", live_stream=True)
    preview = RecognitionConfig(device="cpu", language="auto", live_preview=True)
    speech = np.zeros(2 * 16000, dtype=np.float32)

    engine.transcribe(speech, phrase)
    engine.transcribe(speech, preview)
    engine.transcribe(speech, phrase)

    # Detection costs about as much as the decode, so a preview never pays for
    # it, and the speaker can still change language between phrases.
    assert model.model.detections == 2
    assert _Tokenizer.languages == ["ru", "en"]


def test_live_language_is_not_changed_by_an_unsure_detection(monkeypatch) -> None:
    model = _LiveModel()
    model.model.languages = [("<|ru|>", 0.99), ("<|cy|>", 0.28)]
    _install_live_stack(monkeypatch, model)
    _Tokenizer.languages = []
    engine = Engine()
    config = RecognitionConfig(device="cpu", language="auto", live_stream=True)
    speech = np.zeros(2 * 16000, dtype=np.float32)

    engine.transcribe(speech, config)
    engine.transcribe(speech, config)

    # Measured, two seconds of digital silence come back as English at 0.28.
    # A guess like that must not rewrite the caption in another language.
    assert model.model.detections == 2
    assert _Tokenizer.languages == ["ru"]


def test_live_window_reports_nothing_when_the_decoder_is_guessing(monkeypatch) -> None:
    # Music and the tail of a cut phrase still make the decoder produce words.
    # Measured on real audio, speech stays above -0.72 and those guesses below
    # -1.07, which is the check the ordinary faster-whisper call also applies.
    model = _LiveModel(score=-1.5)
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(device="cpu", live_stream=True)
    segments: list[dict] = []

    result = Engine().transcribe(
        np.zeros(16000, dtype=np.float32), config, on_segment=segments.append
    )

    assert result == []
    assert segments == []


def test_everything_sensitivity_shows_what_the_decoder_heard(monkeypatch) -> None:
    # The explicit "caption everything, songs included" mode turns the same
    # gate off: the user asked to see the guess, not to hide the sound.
    model = _LiveModel(score=-1.5)
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(
        device="cpu", live_stream=True, live_sensitivity="everything"
    )

    result = Engine().transcribe(np.zeros(16000, dtype=np.float32), config)

    assert result[0]["text"] == "живой текст"


def test_live_window_keeps_text_when_the_build_returns_no_score(monkeypatch) -> None:
    model = _LiveModel(score=None)
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(device="cpu", live_stream=True)

    result = Engine().transcribe(np.zeros(16000, dtype=np.float32), config)

    assert result[0]["text"] == "живой текст"


def test_live_window_falls_back_once_when_internals_are_missing(monkeypatch) -> None:
    class PlainModel:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, _source, **kwargs):
            self.calls += 1
            assert kwargs["beam_size"] == 3
            return iter([_Segment(0, 1, "запасной путь")]), object()

    model = PlainModel()
    _install_live_stack(monkeypatch, model)
    config = RecognitionConfig(device="cpu", live_stream=True)
    engine = Engine()
    statuses: list[str] = []

    assert engine.transcribe(np.zeros(16000), config, on_status=statuses.append)[0][
        "text"
    ] == "запасной путь"
    engine.transcribe(np.zeros(16000), config)

    assert model.calls == 2
    assert statuses.count("live_window_unavailable") == 1


def test_live_window_drops_a_phrase_the_decoder_started_over() -> None:
    assert Engine._drop_restart(
        "Сегодня мы говорим о рас. Сегодня мы говорить о рас Сегодня мы поговорим"
    ) == "Сегодня мы говорим о рас."
    # The restart usually comes back in a different grammatical form, so the
    # comparison is on stems rather than on whole words.
    assert Engine._drop_restart(
        "Живые субтитры должны появляться почти мгновенно. Живое субтитры должны появ"
    ) == "Живые субтитры должны появляться почти мгновенно."
    assert Engine._drop_restart(
        "Это главная задача. Это главные задачи. Это главное задач"
    ) == "Это главная задача."
    # Text that simply moves forward is left alone, including a caption too
    # short to judge.
    assert Engine._drop_restart(
        "Живые субтитры должны появляться почти мгновенно"
    ) == "Живые субтитры должны появляться почти мгновенно"
    assert Engine._drop_restart(
        "Сегодня мы говорим о распознавании русской речи в реальном времени."
    ) == "Сегодня мы говорим о распознавании русской речи в реальном времени."
    assert Engine._drop_restart("Привет.") == "Привет."


def test_live_preview_recipe_uses_greedy_decoding(monkeypatch) -> None:
    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["beam_size"] == 1
            assert kwargs["best_of"] == 1
            assert kwargs["temperature"] == 0.0
            assert kwargs["word_timestamps"] is False
            assert kwargs["vad_filter"] is False
            assert kwargs["without_timestamps"] is True
            return iter([_Segment(0, 1, "черновик")]), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    result = Engine().transcribe(
        np.zeros(1600), RecognitionConfig(device="cpu", live_preview=True)
    )
    assert result[0]["text"] == "черновик"


def test_local_engine_drops_youtube_credit_hallucinations(monkeypatch) -> None:
    class FakeModel:
        def transcribe(self, _source, **_kwargs):
            return iter(
                [
                    _Segment(0, 0.5, "Привет"),
                    _Segment(0.5, 1.0, "Субтитры создавал DimaTorzok"),
                ]
            ), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    result = Engine().transcribe(np.zeros(1600, dtype=np.float32), RecognitionConfig(device="cpu"))
    assert [segment["text"] for segment in result] == ["Привет"]


def test_live_stream_recipe_skips_second_vad_and_uses_profile_beam(monkeypatch) -> None:
    class FakeModel:
        def transcribe(self, _source, **kwargs):
            assert kwargs["beam_size"] == 3
            assert kwargs["best_of"] == 1
            assert kwargs["temperature"] == 0.0
            assert kwargs["vad_filter"] is False
            assert kwargs["word_timestamps"] is False
            assert kwargs["without_timestamps"] is True
            assert "compression_ratio_threshold" not in kwargs
            return iter([_Segment(0, 1, "фраза")]), object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: FakeModel()),
    )
    result = Engine().transcribe(
        np.zeros(1600), RecognitionConfig(device="cpu", live_stream=True)
    )
    assert result[0]["text"] == "фраза"


def test_live_final_beam_follows_the_selected_profile() -> None:
    assert Engine._live_beam_size(RecognitionConfig(live_preview=True, profile="quality")) == 1
    assert Engine._live_beam_size(RecognitionConfig(live_stream=True, profile="fast")) == 1
    assert Engine._live_beam_size(RecognitionConfig(live_stream=True, profile="balanced")) == 3
    assert Engine._live_beam_size(RecognitionConfig(live_stream=True, profile="quality")) == 5


def test_live_greedy_finals_force_beam_one_for_very_weak_machines() -> None:
    # «Жадные финалы» не трогают ни качество-профиль, ни черновики: только
    # готовые фразы на очень слабом CPU считаются лучом 1, но пользователь
    # выбирает это явно.
    assert Engine._live_beam_size(
        RecognitionConfig(live_stream=True, profile="balanced", live_greedy_finals=True)
    ) == 1
    assert Engine._live_beam_size(
        RecognitionConfig(live_preview=True, profile="balanced", live_greedy_finals=False)
    ) == 1
    assert Engine._live_beam_size(
        RecognitionConfig(live_stream=True, profile="balanced", live_greedy_finals=False)
    ) == 3
