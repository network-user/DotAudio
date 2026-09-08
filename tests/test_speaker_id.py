import numpy as np
import pytest

from dotaudio.nemo_diarize import Turn
from dotaudio.speaker_id import (
    apply_roles,
    assign_turns,
    cluster_embeddings,
    decode_audio,
    speaker_at,
)


def _n(*values):
    return np.asarray(values, dtype=np.float32)


def _turn(start, end, who):
    return Turn(start=start, end=end, speaker=who)


def _word(text, start, end):
    return {"text": text, "start": start, "end": end}


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


# ---- Разметка дорожки голосов (движок NeMo) поверх фраз распознавания.


def test_speaker_at_takes_the_largest_overlap():
    turns = [_turn(0.0, 2.0, "a"), _turn(1.9, 5.0, "b")]
    assert speaker_at(0.0, 1.8, turns) == "a"
    assert speaker_at(2.0, 4.0, turns) == "b"


def test_speaker_at_claims_a_word_that_fell_into_a_pause():
    # Диаризатор снимает голос чуть раньше конца слова, и слово оказывается
    # между отрезками. Ближайший отрезок его забирает, далёкий - нет.
    turns = [_turn(0.0, 2.0, "a")]
    assert speaker_at(2.2, 2.4, turns) == "a"
    assert speaker_at(40.0, 41.0, turns) is None


def test_roles_are_numbered_by_first_appearance():
    segments = [{"start": 3.0, "end": 4.0, "text": "второй"},
                {"start": 0.0, "end": 1.0, "text": "первый"}]
    turns = [_turn(0.0, 1.2, "spk3"), _turn(2.8, 4.2, "spk1")]
    rows = assign_turns(segments, turns)
    # Порядок задаёт список фраз, а не имена, которые придумал диаризатор.
    assert [row["role"] for row in rows] == [0, 1]


def test_phrase_without_words_gets_one_label():
    segments = [{"start": 0.0, "end": 2.0, "text": "раз"},
                {"start": 2.5, "end": 4.0, "text": "два"}]
    turns = [_turn(0.0, 2.1, "a"), _turn(2.4, 4.1, "b")]
    rows = assign_turns(segments, turns)
    assert len(rows) == 2
    assert [row["role"] for row in rows] == [0, 1]


def test_phrase_is_split_where_the_voice_changes():
    words = [_word("привет", 0.0, 0.8), _word("как", 0.9, 1.4),
             _word("нормально", 3.0, 4.0), _word("спасибо", 4.1, 4.9)]
    segments = [{"start": 0.0, "end": 4.9,
                 "text": "привет как нормально спасибо", "words": words}]
    rows = assign_turns(segments, [_turn(0.0, 1.5, "a"), _turn(2.9, 5.0, "b")])
    assert len(rows) == 2
    assert [row["role"] for row in rows] == [0, 1]
    assert rows[0]["text"] == "привет как"
    assert rows[1]["text"] == "нормально спасибо"
    assert rows[1]["start"] == pytest.approx(3.0)
    assert rows[0]["end"] == pytest.approx(1.4)


def test_single_voice_phrase_keeps_the_recognised_text():
    # Пунктуация и заглавные буквы Whisper не должны теряться там, где
    # разрезать фразу не понадобилось.
    words = [_word("Привет", 0.0, 0.5), _word("мир", 0.6, 1.0)]
    segments = [{"start": 0.0, "end": 1.0, "text": "Привет, мир!", "words": words}]
    rows = assign_turns(segments, [_turn(0.0, 1.2, "a")])
    assert len(rows) == 1
    assert rows[0]["text"] == "Привет, мир!"


def test_short_flip_between_the_same_voice_is_treated_as_jitter():
    words = [_word("раз", 0.0, 0.4), _word("два", 0.45, 0.6), _word("три", 0.7, 1.2)]
    turns = [_turn(0.0, 0.44, "a"), _turn(0.45, 0.61, "b"), _turn(0.62, 1.3, "a")]
    rows = assign_turns([{"start": 0.0, "end": 1.2, "text": "раз два три", "words": words}], turns)
    assert len(rows) == 1
    assert rows[0]["role"] == 0


def test_real_interjection_between_two_voices_survives():
    # Короткая реплика в стык двух разных голосов - это реплика, а не дрожание
    # границы, и она обязана остаться отдельной строкой.
    words = [_word("слушай", 0.0, 0.8), _word("да", 1.0, 1.2), _word("ладно", 2.0, 2.8)]
    turns = [_turn(0.0, 0.9, "a"), _turn(0.95, 1.3, "b"), _turn(1.9, 3.0, "c")]
    rows = assign_turns([{"start": 0.0, "end": 2.8, "text": "слушай да ладно", "words": words}], turns)
    assert [row["role"] for row in rows] == [0, 1, 2]


def test_phrase_outside_every_turn_keeps_no_role():
    rows = assign_turns([{"start": 50.0, "end": 51.0, "text": "эхо"}], [_turn(0.0, 2.0, "a")])
    assert rows[0]["role"] is None


def test_no_turns_at_all_leaves_every_phrase_unlabelled():
    rows = assign_turns([{"start": 0.0, "end": 1.0, "text": "раз"}], [])
    assert rows[0]["role"] is None
    assert rows[0]["text"] == "раз"


def test_apply_roles_matches_the_same_contract():
    rows = apply_roles([{"text": "раз"}, {"text": "два"}, {"text": "три"}], [0, None, 1])
    assert [row["role"] for row in rows] == [0, None, 1]
