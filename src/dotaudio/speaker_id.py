"""Local, off-line speaker diarization over already-transcribed segments.

This module is deliberately Qt-free and keeps audio on this machine.  Heavy
libraries are imported lazily so that running without the optional diarization
stack (SpeechBrain/torch) still starts fast; transcriptions that never enable
diarization never import them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
