"""Local, off-line speaker diarization over already-transcribed segments.

This module is deliberately Qt-free and keeps audio on this machine.  Heavy
libraries are imported lazily so that running without the optional diarization
stack (SpeechBrain/torch) still starts fast; transcriptions that never enable
diarization never import them.

Two engines feed the same segment contract.  The embedding engine scores one
window per phrase and clusters the results, so it can only label a phrase as a
whole.  The NeMo engine (``nemo_diarize``) returns a real timeline of speech
turns, which additionally lets a phrase be split where the voice changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dotaudio.nemo_diarize import Turn

SAMPLE_RATE = 16000
MIN_VOICE_SECONDS = 0.25
EMBED_WINDOW_SECONDS = 2.5
# Cosine similarity above this treats two utterances as the same voice.  The
# fixed threshold is deliberately conservative: merging two speakers reads worse
# than splitting one, so crossings tend to open a new numbered role.
SAME_SPEAKER_SIMILARITY = 0.70

# HuggingFace id of the SpeechBrain SpeechBrain ECAPA-TDNN embedder.  Weights
# are fetched once into a local cache directory on first use; audio never leaves
# the machine.
EMBEDDER_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"

# A diarizer marks a voice active slightly after the word has started and drops
# it slightly before the word ends, so a word can fall just outside every turn.
# Within this distance the nearest turn still claims it; further away the word
# keeps no role rather than borrowing one from another part of the recording.
NEAR_TURN_SECONDS = 0.75
# A voice that holds the floor for less than this inside somebody else's phrase
# is boundary jitter, not a reply, and is absorbed by its neighbours.  A real
# short interjection between two different voices is kept: only a flip framed
# by the *same* speaker on both sides is treated as jitter.
MIN_RUN_SECONDS = 0.35


class DiarizationUnavailable(RuntimeError):
    """Raised when the optional torch/speechbrain stack is not installed."""


def decode_audio(source: str | Path | np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return float32 mono PCM at ``sample_rate`` from a path or raw array.

    Uses faster-whisper's decoder (already a dependency) and never contacts a
    server.  Video files keep their audio stream.
    """
    if isinstance(source, np.ndarray):
        audio = np.asarray(source, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        return np.ascontiguousarray(audio.reshape(-1))
    if isinstance(source, Path):
        source = str(source)
    from faster_whisper.audio import decode_audio as _decode  # already a core dependency

    audio = _decode(source, sampling_rate=sample_rate)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    return np.ascontiguousarray(audio.reshape(-1))


def _center_window(start: float, end: float) -> slice:
    """A slice around the middle of an utterance, bounded to speech end."""
    length = max(0.0, end - start)
    win = min(EMBED_WINDOW_SECONDS, length) if length > 0 else EMBED_WINDOW_SECONDS
    half = win / 2.0
    mid = (start + end) / 2.0
    low = max(start, mid - half)
    high = min(end, low + win)
    if high - low < MIN_VOICE_SECONDS * 0.5:
        low, high = start, max(start + MIN_VOICE_SECONDS, start + length)
    return slice(int(low * SAMPLE_RATE), max(int(low * SAMPLE_RATE) + 1, int(high * SAMPLE_RATE)))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na <= 0 or nb <= 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cluster_embeddings(embeddings: list[np.ndarray | None]) -> list[int | None]:
    """Map one embedding per utterance to a stable role index.

    Returns one entry per input (``None`` stays ``None``) and assigns roles in
    first-appearance order, so the earliest speaker is always role zero.  Roles
    are clustered online against a running mean and merge by cosine similarity.
    """
    labels: list[int | None] = []
    centroids: dict[int, np.ndarray] = {}
    counts: dict[int, int] = {}

    for emb in embeddings:
        if emb is None:
            labels.append(None)
            continue
        best = -1
        best_sim = 0.0
        for role, centroid in centroids.items():
            sim = _cosine(emb, centroid)
            if sim > best_sim and sim >= SAME_SPEAKER_SIMILARITY:
                best, best_sim = role, sim
        if best < 0:
            best = len(centroids)
            centroids[best] = np.asarray(emb, dtype=np.float32).copy()
            counts[best] = 0
        # Update the running centroid so a role follows a speaker drift.
        counts[best] += 1
        keep = counts[best]
        centroids[best] = (centroids[best] * (keep - 1) + np.asarray(emb)) / keep
        labels.append(best)
    return labels


@dataclass(slots=True)
class SpeakerEmbedder:
    """Thin lazy wrapper over the optional SpeechBrain ECAPA-TDNN model."""

    cache_dir: str | Path

    def __post_init__(self) -> None:
        self._classifier: object | None = None

    def _load(self) -> object:
        if self._classifier is not None:
            return self._classifier
        try:
            from speechbrain.inference.speaker import EncoderClassifier  # optional
        except Exception as exc:  # pragma: no cover - depends on extras
            raise DiarizationUnavailable(
                "Идентификация голосов требует установки доп. зависимостей: "
                "pip install -e \".[diarize]\". Затем перезапустите приложение."
            ) from exc
        cache = str(Path(self.cache_dir))
        self._classifier = EncoderClassifier.from_hparams(
            source=EMBEDDER_SOURCE,
            savedir=cache,
            run_opts={"device": "cpu"},
        )
        return self._classifier

    def embed(self, window: np.ndarray) -> np.ndarray | None:
        """One 192-dim ECAPA-TDNN embedding for a mono window, or None."""
        if window.size < int(MIN_VOICE_SECONDS * SAMPLE_RATE):
            return None
        classifier = self._load()
        import torch  # optional; only reached when speechbrain is present

        clip = np.ascontiguousarray(window.astype(np.float32))
        signal = torch.from_numpy(clip).reshape(1, -1)
        with torch.inference_mode():
            emb = classifier.encode_batch(signal)[0, 0]
        emb = emb.detach().cpu().numpy().astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm <= 0:
            return None
        return emb / norm


def diarize_segments(
    audio: np.ndarray,
    segments: list[dict],
    cache_dir: str | Path,
) -> list[int | None]:
    """Assign a role index to every segment that has an acceptable voice window.

    Utterances too short to trust (<MIN_VOICE_SECONDS) come back as ``None`` and
    the UI renders them without a colour role.
    """
    embedder = SpeakerEmbedder(cache_dir)
    windows = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        index = _center_window(start, end)
        window = audio[index]
        windows.append(window if window.size >= int(MIN_VOICE_SECONDS * SAMPLE_RATE) else np.array([], dtype=np.float32))

    embeddings: list[np.ndarray | None] = []
    for window in windows:
        if window.size == 0:
            embeddings.append(None)
        else:
            try:
                embeddings.append(embedder.embed(window))
            except DiarizationUnavailable:
                raise
            except Exception:
                embeddings.append(None)
    return cluster_embeddings(embeddings)


# ---- Общий контракт: сегмент с ролью говорящего.


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def speaker_at(start: float, end: float, turns: list[Turn]) -> str | None:
    """Голос, которому принадлежит отрезок, или ``None``.

    Побеждает наибольшее пересечение. Если пересечений нет вовсе (слово
    попало в паузу между отрезками), берётся ближайший отрезок в пределах
    ``NEAR_TURN_SECONDS``.
    """

    if not turns:
        return None
    end = max(float(start), float(end))
    best: str | None = None
    best_overlap = 0.0
    for turn in turns:
        shared = _overlap(float(start), end, turn.start, turn.end)
        if shared > best_overlap:
            best, best_overlap = turn.speaker, shared
    if best is not None:
        return best
    middle = (float(start) + end) / 2.0
    nearest: str | None = None
    nearest_gap = NEAR_TURN_SECONDS
    for turn in turns:
        gap = 0.0 if turn.start <= middle <= turn.end else min(
            abs(turn.start - middle), abs(middle - turn.end)
        )
        if gap <= nearest_gap:
            nearest, nearest_gap = turn.speaker, gap
    return nearest


def _word_span(word: dict) -> tuple[float, float]:
    start = max(0.0, float(word.get("start", 0.0)))
    return start, max(start, float(word.get("end", start)))


def _voice_runs(words: list[dict], turns: list[Turn]) -> list[list]:
    """Разбить слова фразы на группы подряд идущих слов одного голоса."""

    runs: list[list] = []
    for word in words:
        start, end = _word_span(word)
        who = speaker_at(start, end, turns)
        if runs and runs[-1][0] == who:
            runs[-1][1].append(word)
        else:
            runs.append([who, [word]])
    return runs


def _merge_adjacent(runs: list[list]) -> list[list]:
    merged: list[list] = []
    for who, words in runs:
        if merged and merged[-1][0] == who:
            merged[-1][1].extend(words)
        else:
            merged.append([who, list(words)])
    return merged


def _smooth_runs(runs: list[list]) -> list[list]:
    """Убрать короткие перескоки между одинаковыми соседями."""

    if len(runs) < 3:
        return _merge_adjacent(runs)
    kept: list[list] = []
    for index, (who, words) in enumerate(runs):
        following = runs[index + 1][0] if index + 1 < len(runs) else None
        previous = kept[-1][0] if kept else None
        span = _word_span(words[-1])[1] - _word_span(words[0])[0]
        if kept and following is not None and previous == following and span < MIN_RUN_SECONDS:
            kept[-1][1].extend(words)
            continue
        kept.append([who, list(words)])
    return _merge_adjacent(kept)


def _piece(segment: dict, words: list[dict], rebuild: bool) -> dict:
    """Сегмент из части слов исходной фразы.

    Пока фраза принадлежит одному голосу, её текст остаётся ровно таким,
    каким его выдало распознавание. Пересобирается он только у настоящего
    разреза, где исходной строки для куска попросту нет.
    """

    piece = dict(segment)
    if not rebuild:
        return piece
    piece["start"] = _word_span(words[0])[0]
    piece["end"] = _word_span(words[-1])[1]
    piece["text"] = " ".join(str(word.get("text", "")).strip() for word in words).strip()
    piece["words"] = list(words)
    return piece


def assign_turns(segments: list[dict], turns: list[Turn], split: bool = True) -> list[dict]:
    """Разложить фразы по голосам из размеченной диаризатором дорожки.

    Возвращает новый список сегментов: у каждого появляется ``role`` -
    сквозной номер голоса с нуля в порядке первого появления, либо ``None``,
    если для фразы голос определить не удалось. Когда у фразы есть слова с
    таймкодами и ``split`` включён, фраза со сменой голоса разрезается по
    границе: именно это отличает разметку дорожки от одной метки на фразу.
    """

    ordered = sorted(turns, key=lambda turn: (turn.start, turn.end))
    rows: list[tuple[str | None, dict]] = []
    for segment in segments:
        words = [word for word in (segment.get("words") or []) if str(word.get("text", "")).strip()]
        if split and len(words) > 1:
            runs = _smooth_runs(_voice_runs(words, ordered))
        else:
            runs = []
        if len(runs) > 1:
            for who, group in runs:
                rows.append((who, _piece(segment, group, rebuild=True)))
            continue
        who = runs[0][0] if runs else speaker_at(
            float(segment.get("start", 0.0)),
            float(segment.get("end", segment.get("start", 0.0))),
            ordered,
        )
        rows.append((who, dict(segment)))

    order: dict[str, int] = {}
    for who, _segment in rows:
        if who is not None and who not in order:
            order[who] = len(order)
    result: list[dict] = []
    for who, segment in rows:
        segment["role"] = order.get(who) if who is not None else None
        result.append(segment)
    return result


def apply_roles(segments: list[dict], roles: list[int | None]) -> list[dict]:
    """Прикрепить роли эмбеддингового движка: одна метка на фразу.

    Приведение к тому же контракту, что и :func:`assign_turns`, чтобы
    интерфейс и экспорт не знали, каким движком получены голоса.
    """

    result: list[dict] = []
    for index, segment in enumerate(segments):
        role = roles[index] if index < len(roles) else None
        row = dict(segment)
        row["role"] = int(role) if role is not None else None
        result.append(row)
    return result
