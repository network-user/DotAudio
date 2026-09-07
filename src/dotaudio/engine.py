"""Core speech-recognition engine for DotAudio.

The module deliberately has no UI dependencies.  Heavy libraries are imported
only when their corresponding backend is used, keeping application startup
fast on machines that use the remote worker only.
"""

from __future__ import annotations

import json
import mimetypes
import wave
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable
from urllib.parse import urlsplit

import numpy as np

Segment = dict[str, Any]
SegmentCallback = Callable[[Segment], None]
StatusCallback = Callable[[str], None]

# Whisper pads every input to 30 seconds, so a 2 s live window costs as much as
# a full chunk.  CTranslate2 accepts a shorter mel spectrogram, which is what
# makes Live affordable on a CPU.  The trailing silence is not decoration: with
# no margin after the speech the decoder keeps generating and repeats itself.
# Silence appended after the phrase.  It doubles as a floor: even the shortest
# phrase gets a two second encoder window, below which Whisper returns
# phonetic guesses instead of words.
LIVE_TAIL_SECONDS = 2.0
# A live window is short.  Anything past this token budget is a decoder loop,
# not speech, and it would block the next caption.
LIVE_TOKENS_PER_SECOND = 12
LIVE_MAX_TOKENS = 200
LIVE_HINT_CHARS = 150
# Mean token log probability below which the window is not reported as speech.
# The ordinary faster-whisper call applies this check by default; the fast live
# path bypasses that call, so it applies the same threshold itself.  Measured on
# real audio, sung and spoken: speech windows from 1.2 s upwards score between
# -0.18 and -0.72, while the words the decoder invents over music and over the
# tail of a phrase score -1.07 and lower.
LIVE_MIN_LOGPROB = -1.0


@dataclass(slots=True, frozen=True)
class RecognitionConfig:
    """Options shared by local faster-whisper and the optional worker."""

    model: str = "base"
    device: str = "auto"
    # Russian is the useful default for the article and avoids an unnecessary
    # language-identification pass at the beginning of a live subtitle.
    language: str = "ru"
    task: str = "transcribe"
    backend: str = "local"
    server_url: str = "http://127.0.0.1:8765"
    profile: str = "balanced"
    media_mode: bool = False
    # Preview requests are short, disposable snapshots used only by Live UI.
    # They deliberately favour cadence over the final transcript's accuracy.
    live_preview: bool = False
    # Live finals keep greedy decode and skip a second VAD pass: SpeechBuffer
    # already endpointed the phrase.  Dictation and media keep the profile.
    live_stream: bool = False
    # Domain terms are supplied by the user-facing dictionary.  They remain a
    # hint to the recognizer, never a replacement for the spoken audio.
    initial_prompt: str = ""


class Engine:
    """A bounded, thread-safe recognizer.

    A model can be large enough to evict most application state on modest
    devices.  Keeping exactly one cached model also prevents a switch from a
    quick dictation model to a studio model from retaining both in memory.
    """

    _MAX_REMOTE_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self) -> None:
        self._models: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self._tokenizers: dict[tuple[str, str, str, str], Any] = {}
        self._detected_languages: dict[tuple[str, str], str] = {}
        self._live_window = True
        self._model_lock = Lock()
        self._inference_lock = Lock()

    def release_cached_model(self) -> bool:
        """Release the in-process model once the application is idle.

        The downloaded model files stay in the Hugging Face cache, so the next
        use avoids a download but intentionally pays the normal load time.
        Taking the inference lock first means an active native decode keeps its
        model alive until it has returned.
        """

        with self._inference_lock, self._model_lock:
            if not self._models:
                return False
            self._models.clear()
            self._tokenizers.clear()
            self._detected_languages.clear()
            return True

    def transcribe(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None = None,
        on_segment: SegmentCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> list[Segment]:
        """Transcribe a path or a 16 kHz mono float array.

        Cancellation is cooperative.  It stops iteration between emitted
        Whisper segments (or network response chunks) and returns completed
        segments, which lets a live UI retain text already shown to the user.
        """

        self._validate_config(config)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []

        if config.backend == "remote":
            return self._transcribe_remote(
                source, config, cancel, on_segment, on_status
            )
        return self._transcribe_local(
            source, config, cancel, on_segment, on_status
        )

    def prepare(
        self,
        config: RecognitionConfig,
        on_status: StatusCallback | None = None,
    ) -> str:
        """Download and initialise a local model before the user starts recording.

        ``WhisperModel`` uses the Hugging Face cache, so preparation survives an
        application restart.  A precise download percentage is intentionally
        not fabricated: the dependency can reuse files already in its cache.
        """

        self._validate_config(config)
        if config.backend == "remote":
            self._status(on_status, "remote_model_managed_by_server")
            return "remote"
        self._status(on_status, "loading_model")
        model, device = self._model_for(config.model, config.device)
        if config.live_stream:
            warm_error = self._warm_live_decoder(model, config)
            if warm_error is not None:
                if (
                    config.device == "auto"
                    and device == "cuda"
                    and self._is_cuda_error(warm_error)
                ):
                    self._status(on_status, "gpu_unavailable_falling_back_cpu")
                    self._drop_model(config.model, "cuda")
                    model, device = self._model_for(config.model, "cpu")
                    cpu_error = self._warm_live_decoder(model, config)
                    if cpu_error is not None:
                        raise cpu_error
                else:
                    raise warm_error
        self._status(on_status, "model_ready")
        return device

    @staticmethod
    def _validate_config(config: RecognitionConfig) -> None:
        if config.backend not in {"local", "remote"}:
            raise ValueError("backend must be 'local' or 'remote'")
        if config.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be 'auto', 'cpu', or 'cuda'")
        if config.task not in {"transcribe", "translate"}:
            raise ValueError("task must be 'transcribe' or 'translate'")
        if config.profile not in {"fast", "balanced", "quality"}:
            raise ValueError("profile must be 'fast', 'balanced', or 'quality'")
        if not config.model.strip():
            raise ValueError("model must not be empty")

    @staticmethod
    def _cancelled(cancel: Event | None) -> bool:
        return cancel is not None and cancel.is_set()

    @staticmethod
    def _status(callback: StatusCallback | None, value: str) -> None:
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            # UI callbacks must never break an active transcription.
            return

    @staticmethod
    def _emit_segment(callback: SegmentCallback | None, segment: Segment) -> None:
        if callback is None:
            return
        try:
            callback(segment)
        except Exception:
            return

    def _transcribe_local(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        """Run local inference, retrying once on CPU for CUDA runtime faults."""

        if not self._has_cached_model(config.model, config.device):
            self._status(on_status, "loading_model")
        try:
            return self._run_local(
                source, config, config.device, cancel, on_segment, on_status
            )
        except (RuntimeError, OSError) as exc:
            if config.device != "auto" or not self._is_cuda_error(exc):
                raise
            self._status(on_status, "gpu_unavailable_falling_back_cpu")
            self._drop_model(config.model, "cuda")
            return self._run_local(
                source, config, "cpu", cancel, on_segment, on_status
            )

    def _run_local(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        requested_device: str,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        model, actual_device = self._model_for(config.model, requested_device)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []

        if (config.live_preview or config.live_stream) and isinstance(source, np.ndarray):
            live = self._run_live_window(
                model, config, actual_device, source, cancel, on_segment, on_status
            )
            if live is not None:
                return live

        language = None if config.language.strip().lower() == "auto" else config.language
        # This is the spoken-audio subset of the .sound recipe: word timings
        # power the karaoke view, VAD skips silence, and no previous-text
        # conditioning limits repeated phrases at live chunk boundaries.
        profile = {
            "fast": {"beam": 3, "patience": 1.0},
            "balanced": {"beam": 5, "patience": 1.0},
            "quality": {"beam": 8, "patience": 1.5},
        }[config.profile]
        live_fast = config.live_preview or config.live_stream
        if live_fast:
            profile = {"beam": 1, "patience": 1.0}
        # Music commonly has speech-like instrumental fragments.  DotSound
        # keeps VAD off for this case.  Live already endpointed the phrase in
        # SpeechBuffer, so a second Silero pass only delays the caption.
        use_vad = not config.media_mode and not live_fast
        kwargs: dict[str, Any] = {
            "task": config.task,
            "language": language,
            "beam_size": profile["beam"],
            "patience": profile["patience"],
            "vad_filter": use_vad,
            "condition_on_previous_text": False,
            # Word alignment is needed for offline karaoke, but it adds work
            # that live phrase captions do not need.
            "word_timestamps": config.media_mode,
            "initial_prompt": self._initial_prompt(language, config.initial_prompt),
        }
        if live_fast:
            # Greedy, no timestamps, no temperature fallback: one decode pass
            # on a 1 s window is what makes the overlay feel live.
            kwargs["best_of"] = 1
            kwargs["temperature"] = 0.0
            kwargs["without_timestamps"] = True
            kwargs["word_timestamps"] = False
        if use_vad:
            kwargs["vad_parameters"] = {
                "threshold": 0.35,
                "min_silence_duration_ms": 350,
                "min_speech_duration_ms": 120,
            }
        elif config.media_mode:
            # Less aggressive filtering preserves real sung Russian words.
            kwargs.update({
                "compression_ratio_threshold": 2.4,
                "log_prob_threshold": -1.2,
                "no_speech_threshold": 0.3,
            })
        self._status(on_status, f"transcribing_{actual_device}")
        result: list[Segment] = []
        # CTranslate2 / CUDA execution is native and is not safe to run in
        # parallel inside one desktop process.  Model loading remains separate
        # so a second caller can observe the cache while this call is running.
        with self._inference_lock:
            segments, _info = model.transcribe(source, **kwargs)
            for raw in segments:
                if self._cancelled(cancel):
                    self._status(on_status, "cancelled")
                    return result
                text = str(getattr(raw, "text", "")).strip()
                if not text:
                    continue
                segment: Segment = {
                    "start": float(getattr(raw, "start", 0.0)),
                    "end": float(getattr(raw, "end", 0.0)),
                    "text": text,
                }
                words = self._word_timings(raw)
                if words:
                    segment["words"] = words
                result.append(segment)
                self._emit_segment(on_segment, segment)
        self._status(on_status, "completed")
        return result

    def _run_live_window(
        self,
        model: Any,
        config: RecognitionConfig,
        device: str,
        audio: np.ndarray,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment] | None:
        """Decode one live window with an encoder sized to the phrase itself.

        Returns ``None`` when the fast path is unavailable, so the caller falls
        back to the ordinary faster-whisper call instead of losing a caption.
        """

        if not self._live_window:
            return None
        window = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        try:
            import ctranslate2

            extractor = model.feature_extractor
            seconds = len(window) / extractor.sampling_rate
            frames_per_second = extractor.sampling_rate // extractor.hop_length
            wanted = min(
                extractor.nb_max_frames,
                int((seconds + LIVE_TAIL_SECONDS) * frames_per_second),
            )
            # The tail is appended to the audio, not to the spectrogram.  A
            # mel padded with zeros is not silence to the model: measured, the
            # floor for digital silence is about -1.5, and zeros there read as
            # sound, which made the decoder retell the phrase it just wrote.
            tail = np.zeros(int(LIVE_TAIL_SECONDS * extractor.sampling_rate), dtype=np.float32)
            features = extractor(np.concatenate((window, tail)), padding=0)
            if features.shape[-1] < wanted:
                features = np.pad(features, ((0, 0), (0, wanted - features.shape[-1])))
            else:
                features = features[:, :wanted]
            storage = ctranslate2.StorageView.from_array(
                np.ascontiguousarray(features[np.newaxis, ...].astype(np.float32))
            )
            tokenizer = self._live_tokenizer(model, config, device, storage)
            # The user dictionary is a hint, not a rewrite.  It is bounded hard:
            # every hint token is decoder context paid on each live window.
            terms = " ".join(str(config.initial_prompt).split())[:LIVE_HINT_CHARS]
            prompt = model.get_prompt(
                tokenizer, [], without_timestamps=True, hotwords=terms or None
            )
            budget = min(LIVE_MAX_TOKENS, int(seconds * LIVE_TOKENS_PER_SECOND) + 8)
            self._status(on_status, f"transcribing_{device}")
            with self._inference_lock:
                if self._cancelled(cancel):
                    self._status(on_status, "cancelled")
                    return []
                result = model.model.generate(
                    storage,
                    [prompt],
                    beam_size=1,
                    max_length=len(prompt) + budget,
                    # A cut-off window tempts the decoder into repeating the
                    # last phrase until the token budget runs out.
                    no_repeat_ngram_size=3,
                    suppress_blank=True,
                    return_scores=True,
                )[0]
        except (AttributeError, ImportError, KeyError, TypeError):
            # The window is assembled from faster-whisper and CTranslate2
            # internals.  If their shape ever differs, degrade to the supported
            # call once instead of failing every live window from now on.
            # Decoding faults are not caught here: they must stay visible.
            self._live_window = False
            self._status(on_status, "live_window_unavailable")
            return None

        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []
        # There is deliberately no ``no_speech_prob`` filter here.  Measured on
        # windows this short, tiny and base score speech and silence in the
        # same 0.6-0.8 band, so the filter discarded real captions.  Whether a
        # window contains voice is decided before it reaches the decoder.
        tokens = [token for token in result.sequences_ids[0] if token < tokenizer.eot]
        text = self._drop_restart(tokenizer.decode(tokens).strip())
        if text and not self._confident(result):
            # Music and the tail of a cut phrase still produce words: "75",
            # "Велосипед", "Cutie".  They are reported as nothing rather than as
            # a caption, and the caller says so through live_no_text.
            self._status(on_status, "completed")
            return []
        if not text:
            self._status(on_status, "completed")
            return []
        segment: Segment = {"start": 0.0, "end": seconds, "text": text}
        self._emit_segment(on_segment, segment)
        self._status(on_status, "completed")
        return [segment]

    @staticmethod
    def _confident(result: Any) -> bool:
        """Whether the decoder believes the window it just transcribed.

        CTranslate2 normalises the sequence score by length, so it is the mean
        log probability per token, the same quantity faster-whisper rejects a
        segment on.  A build that does not return scores is trusted, because
        losing the check is better than losing every caption.
        """

        scores = getattr(result, "scores", None)
        if not scores:
            return True
        return float(scores[0]) >= LIVE_MIN_LOGPROB

    @staticmethod
    def _drop_restart(text: str) -> str:
        """Cut the point where the decoder starts the phrase over again.

        A live window ends in the middle of speech, and Whisper reacts by
        retelling what it has just produced: "это главная задача. это главные
        задачи. это главное задач".  The retelling repeats no exact n-gram, so
        the decoder's own guard does not stop it, but it does restart on the
        same words as the phrase itself, usually in a different form.  Matching
        on word stems catches "главная" against "главные".

        The cost of the rule is a genuine "я думаю, я думаю" losing its second
        half.  On a live caption that is a better trade than showing the same
        sentence three times.
        """

        words = text.split()
        if len(words) < 4:
            return text
        stems = [Engine._stem(word) for word in words]
        head = stems[:2]
        for index in range(2, len(stems) - 1):
            if stems[index : index + 2] == head:
                return " ".join(words[:index]).strip()
        return text

    @staticmethod
    def _stem(word: str) -> str:
        """Drop punctuation, case and a Russian ending for comparison only."""

        clean = word.strip(".,!?…:;-«»\"'()").casefold()
        return clean[: max(3, len(clean) - 2)]

    def _live_tokenizer(
        self, model: Any, config: RecognitionConfig, device: str, storage: Any
    ) -> Any:
        """Return a cached tokenizer, resolving ``auto`` once per model."""

        from faster_whisper.tokenizer import Tokenizer

        language = config.language.strip().lower()
        if language == "auto":
            language = self._detect_live_language(model, config, device, storage)
        key = (config.model, device, config.task, language)
        with self._model_lock:
            cached = self._tokenizers.get(key)
        if cached is not None:
            return cached
        tokenizer = Tokenizer(
            model.hf_tokenizer,
            model.model.is_multilingual,
            task=config.task,
            language=language,
        )
        with self._model_lock:
            self._tokenizers[key] = tokenizer
        return tokenizer

    def _detect_live_language(
        self, model: Any, config: RecognitionConfig, device: str, storage: Any
    ) -> str:
        """Detect the language once and keep it for the rest of the session.

        Live windows are short and noisy.  Re-detecting per window makes the
        caption switch languages mid-phrase; the user can still pin a language
        in settings.
        """

        key = (config.model, device)
        with self._model_lock:
            known = self._detected_languages.get(key)
        if known:
            return known
        with self._inference_lock:
            detected = model.model.detect_language(storage)[0][0][0]
        language = str(detected).strip("<|>")
        with self._model_lock:
            self._detected_languages[key] = language
        return language

    @staticmethod
    def _initial_prompt(language: str | None, user_terms: str) -> str | None:
        """Build a bounded ASR hint without turning it into hidden rewriting."""

        base = "Русская речь. Сохраняй имена, термины и пунктуацию." if language == "ru" else ""
        terms = " ".join(str(user_terms).split())[:700]
        prompt = " ".join(part for part in (base, terms) if part)
        return prompt or None

    @staticmethod
    def _word_timings(raw: Any) -> list[dict[str, float | str]]:
        """Normalise optional faster-whisper word timings for QML and export."""

        result: list[dict[str, float | str]] = []
        for word in getattr(raw, "words", None) or []:
            text = str(getattr(word, "word", "")).strip()
            if not text:
                continue
            start = max(0.0, float(getattr(word, "start", 0.0)))
            end = max(start, float(getattr(word, "end", start)))
            result.append({"text": text, "start": start, "end": end})
        return result

    def _model_for(self, model_name: str, requested_device: str) -> tuple[Any, str]:
        if requested_device == "auto":
            # Reuse the device that successfully handled the previous call.
            # In particular, after a CUDA runtime failure _run_local loads the
            # CPU model.  Trying CUDA first again for every 350 ms Live window
            # makes the stream permanently fall behind and can prevent any
            # caption from reaching the UI.
            with self._model_lock:
                cached_key = next(
                    (key for key in reversed(self._models) if key[0] == model_name),
                    None,
                )
                if cached_key is not None:
                    self._models.move_to_end(cached_key)
                    return self._models[cached_key], cached_key[1]
        candidates = ("cuda", "cpu") if requested_device == "auto" else (requested_device,)
        last_error: BaseException | None = None
        for device in candidates:
            try:
                return self._get_or_load_model(model_name, device), device
            except (RuntimeError, OSError) as exc:
                last_error = exc
                if requested_device != "auto" or not self._is_cuda_error(exc):
                    raise
        assert last_error is not None
        raise last_error

    def _has_cached_model(self, model_name: str, requested_device: str) -> bool:
        with self._model_lock:
            if requested_device == "auto":
                return any(name == model_name for name, _device in self._models)
            return (model_name, requested_device) in self._models

    def _warm_live_decoder(
        self, model: Any, config: RecognitionConfig
    ) -> BaseException | None:
        """Run a silent 300 ms pass so the first live caption is not a cold start."""

        language = None if config.language.strip().lower() == "auto" else config.language
        silence = np.zeros(4800, dtype=np.float32)
        try:
            with self._inference_lock:
                segments, _info = model.transcribe(
                    silence,
                    language=language,
                    task=config.task,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    vad_filter=False,
                    without_timestamps=True,
                    condition_on_previous_text=False,
                )
                list(segments)
        except Exception as exc:
            return exc
        return None

    def _get_or_load_model(self, model_name: str, device: str) -> Any:
        key = (model_name, device)
        with self._model_lock:
            cached = self._models.get(key)
            if cached is not None:
                self._models.move_to_end(key)
                return cached
            # Imported here so remote-only installations do not need the
            # local ASR stack at startup.
            from faster_whisper import WhisperModel

            compute_type = "float16" if device == "cuda" else "int8"
            loaded = WhisperModel(
                model_name, device=device, compute_type=compute_type
            )
            self._models.clear()
            self._tokenizers.clear()
            self._detected_languages.clear()
            self._models[key] = loaded
            return loaded

    def _drop_model(self, model_name: str, device: str) -> None:
        with self._model_lock:
            self._models.pop((model_name, device), None)
            for key in [k for k in self._tokenizers if k[:2] == (model_name, device)]:
                self._tokenizers.pop(key, None)
            self._detected_languages.pop((model_name, device), None)

    @staticmethod
    def _is_cuda_error(error: BaseException) -> bool:
        text = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in text
            for marker in ("cuda", "cublas", "cudnn", "cudart", "nvrtc")
        )

    def _transcribe_remote(
        self,
        source: str | np.ndarray,
        config: RecognitionConfig,
        cancel: Event | None,
        on_segment: SegmentCallback | None,
        on_status: StatusCallback | None,
    ) -> list[Segment]:
        self._validate_server_url(config.server_url)
        if self._cancelled(cancel):
            self._status(on_status, "cancelled")
            return []
        self._status(on_status, "uploading")

        import httpx

        filename, body, content_type = self._remote_file(source)
        try:
            files = {"file": (filename, body, content_type)}
            form = {
                "model": config.model,
                "language": config.language,
                "task": config.task,
            }
            with httpx.Client(timeout=httpx.Timeout(30.0, read=15.0)) as client:
                with client.stream(
                    "POST", config.server_url.rstrip("/") + "/v1/transcribe",
                    files=files,
                    data=form,
                    headers={"Accept": "application/json"},
                ) as response:
                    raw = self._read_bounded_response(response, cancel)
                    if self._cancelled(cancel):
                        self._status(on_status, "cancelled")
                        return []
                    if response.status_code < 200 or response.status_code >= 300:
                        detail = raw.decode("utf-8", errors="replace")[:500]
                        raise RuntimeError(
                            f"remote ASR returned HTTP {response.status_code}: {detail}"
                        )
        finally:
            body.close()

        payload = json.loads(raw.decode("utf-8"))
        raw_segments = payload.get("segments", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_segments, list):
            raise RuntimeError("remote ASR response must contain a segments list")
        result: list[Segment] = []
        for item in raw_segments:
            if self._cancelled(cancel):
                self._status(on_status, "cancelled")
                return result
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            segment: Segment = {
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "text": text,
            }
            words = item.get("words")
            if isinstance(words, list):
                segment["words"] = words
            result.append(segment)
            self._emit_segment(on_segment, segment)
        self._status(on_status, "completed")
        return result

    def _read_bounded_response(self, response: Any, cancel: Event | None) -> bytes:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            if self._cancelled(cancel):
                break
            size += len(chunk)
            if size > self._MAX_REMOTE_RESPONSE_BYTES:
                raise RuntimeError("remote ASR response exceeds 8 MiB limit")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_server_url(server_url: str) -> None:
        parsed = urlsplit(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("server_url must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("server_url must not contain credentials")

    @staticmethod
    def _remote_file(source: str | np.ndarray) -> tuple[str, BytesIO | Any, str]:
        if isinstance(source, np.ndarray):
            audio = np.asarray(source, dtype=np.float32)
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            if audio.ndim != 1:
                raise ValueError("audio array must be mono or shaped (frames, channels)")
            clipped = np.clip(audio, -1.0, 1.0)
            pcm = (clipped * 32767.0).astype("<i2", copy=False)
            data = BytesIO()
            with wave.open(data, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm.tobytes())
            data.seek(0)
            return "capture.wav", data, "audio/wav"

        path = Path(source).expanduser()
        if not path.is_file():
            raise ValueError("remote backend accepts an existing local media file")
        media = open(path, "rb")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.name, media, content_type


    @staticmethod
    def disk_status(model_name: str) -> dict[str, Any]:
        """Describe Hugging Face cache presence without starting a download."""

        name = str(model_name).strip()
        aliases = {
            "turbo": ("faster-whisper-large-v3-turbo", "faster-whisper-turbo"),
            "large-v3-turbo": ("faster-whisper-large-v3-turbo",),
        }
        needles = aliases.get(name, (f"faster-whisper-{name}",))
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        size = 0
        found = ""
        if hub.is_dir():
            for entry in hub.iterdir():
                if not entry.is_dir():
                    continue
                if not any(needle in entry.name for needle in needles):
                    continue
                found = str(entry)
                for item in entry.rglob("*"):
                    if item.is_file():
                        try:
                            size += item.stat().st_size
                        except OSError:
                            continue
                break
        return {
            "model": name,
            "ready": size >= 1_000_000,
            "bytes": size,
            "path": found,
            "message": (
                f"В кеше · {size / (1024 * 1024):.0f} МБ"
                if size >= 1_000_000
                else "Ещё не скачана · будет загружена при подготовке"
            ),
        }


__all__ = ["Engine", "RecognitionConfig", "Segment"]
