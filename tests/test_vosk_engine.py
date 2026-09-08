"""Тесты vosk-движка живого распознавания (без установленного пакета vosk).

vosk здесь фейковый: проверяем контракт движка жеется с pipeline и порог
уверенности, а не Kaldi-декодер (его без модели изолированно не прогнать).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import dotaudio.vosk_engine as ve
from dotaudio.engine import RecognitionConfig
from dotaudio.vosk_engine import VoskEngine, vosk_model_name

RATE = ve.RATE


def _speech(seconds: float = 1.2) -> np.ndarray:
    """Псевдо-речь нужной длины (фейк не декодирует звук, важна длина)."""
    n = int(seconds * RATE)
    return np.sin(np.arange(n) / 20.0).astype(np.float32) * 0.2


def _config(**kw) -> RecognitionConfig:
    base = dict(model="vosk-model-small-ru-0.22", device="cpu",
                language="ru", profile="fast", live_sensitivity="speech")
    base.update(kw)
    return RecognitionConfig(**base)


class _Rec:
    def __init__(self, text="я мёд ты тесто", conf=1.0):
        self.text = text
        self.conf = conf
        self._seen = b""

    def SetWords(self, _on):  # noqa: N802
        pass

    def AcceptWaveform(self, data):  # noqa: N802
        self._seen += bytes(data)
        return 0

    def FinalResult(self):  # noqa: N802
        result = [
            {"word": w, "start": idx * 0.3, "end": idx * 0.3 + 0.25, "conf": self.conf}
            for idx, w in enumerate(self.text.split())
        ]
        return json.dumps({"text": self.text, "result": result})


class _FakeVosk:
    def __init__(self, text="я мёд ты тесто", conf=1.0):
        self._text = text
        self._conf = conf
        self.loaded: list[str] = []

    def Model(self, model_name=None, lang=None):  # noqa: N802
        self.loaded.append(model_name or f"vosk-model-{lang}")
        return object()

    def KaldiRecognizer(self, _model, _rate):  # noqa: N802
        return _Rec(text=self._text, conf=self._conf)


@pytest.fixture(autouse=True)
def fake_vosk(monkeypatch):
    """Подменяет настоящий vosk фейковым на всём сборе тестов модуля."""
    fake = _FakeVosk()
    monkeypatch.setattr(ve, "_import_vosk", lambda: fake)
    yield fake


def test_model_name_mapping():
    assert vosk_model_name("big") == "vosk-model-ru-0.42"
    assert vosk_model_name("small") == "vosk-model-small-ru-0.22"


def test_prepare_is_idempotent_and_returns_vosk(fake_vosk):
    eng = VoskEngine(model_size="small")
    assert eng.prepare(_config()) == "vosk"
    assert fake_vosk.loaded == ["vosk-model-small-ru-0.22"]
    fake_vosk.loaded.clear()
    statuses: list[str] = []
    eng.prepare(_config(), lambda s: statuses.append(s))
    assert fake_vosk.loaded == []  # модель уже загружена - повтор не качает
    assert "model_ready" in statuses
    assert eng.release_cached_model() is True


def test_transcribe_returns_single_segment():
    eng = VoskEngine(model_size="small")
    eng.prepare(_config())
    segs = eng.transcribe(_speech(), _config())
    assert len(segs) == 1
    assert segs[0]["text"] == "я мёд ты тесто"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == pytest.approx(len(_speech()) / RATE, abs=0.02)
    assert segs[0]["words"]


def test_transcribe_rejects_file_source():
    eng = VoskEngine(model_size="small")
    eng.prepare(_config())
    with pytest.raises(ValueError):
        eng.transcribe("/tmp/speech.wav", _config())


def test_short_window_returns_empty():
    eng = VoskEngine(model_size="small")
    eng.prepare(_config())
    assert eng.transcribe(_speech(0.1), _config()) == []


def test_not_prepared_raises():
    eng = VoskEngine()
    with pytest.raises(RuntimeError):
        eng.transcribe(_speech(), _config())


def test_low_confidence_is_dropped_in_speech_mode(monkeypatch):
    monkeypatch.setattr(ve, "_import_vosk", lambda: _FakeVosk(conf=0.1))
    eng = VoskEngine(model_size="small")
    eng.prepare(_config())
    assert eng.transcribe(_speech(), _config()) == []


def test_everything_mode_keeps_low_confidence(monkeypatch):
    monkeypatch.setattr(ve, "_import_vosk", lambda: _FakeVosk(conf=0.1))
    eng = VoskEngine(model_size="small")
    cfg = _config(live_sensitivity="everything")
    eng.prepare(cfg)
    assert len(eng.transcribe(_speech(), cfg)) == 1


def test_disk_status_detects_cached_model(monkeypatch, tmp_path):
    name = "vosk-model-small-ru-0.99"
    folder = tmp_path / "vosk" / name / "am"
    folder.mkdir(parents=True)
    folder.joinpath("final.mdl").write_bytes(b"data" * 64)
    monkeypatch.setattr(ve, "_import_vosk", lambda: _FakeVosk())
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    eng = VoskEngine()
    st = eng.disk_status(name)
    assert st["ready"] is True
    assert st["bytes"] > 0
    assert eng.disk_status("vosk-model-missing")["ready"] is False


def test_model_size_selects_target_public():
    assert VoskEngine(model_size="small").model_name == "vosk-model-small-ru-0.22"
    assert VoskEngine(model_size="big").model_name == "vosk-model-ru-0.42"
