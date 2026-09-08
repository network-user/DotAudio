import numpy as np

from dotaudio.speaker_id import cluster_embeddings, decode_audio


def _n(*values):
    return np.asarray(values, dtype=np.float32)


def test_decode_audio_array_is_mono_float32():
    stereo = np.zeros((64000, 2), dtype=np.float32)
    out = decode_audio(stereo)
    assert out.ndim == 1
    assert out.dtype == np.float32


def test_cluster_splits_far_voices_and_keeps_presence_order():
    a1 = _n(1.0, 0.0, 0.0)
    a2 = _n(0.99, 0.02, -0.05)
    b1 = _n(0.0, 1.0, 0.0)
    out = cluster_embeddings([a1, b1, a2])
    assert out == [0, 1, 0]


def test_cluster_keeps_none_and_accepts_missing_voices():
    a = _n(0.5, 0.5, 0.5)
    out = cluster_embeddings([a, None, a])
    assert out == [0, None, 0]
