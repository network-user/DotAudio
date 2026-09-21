from __future__ import annotations

import json

import pytest

from dotaudio.model_registry import ModelRegistry, ModelValidationError
from dotaudio.modelhub import UnsafeModelPath, safe_join


def _model(path):
    path.mkdir()
    (path / "model.bin").write_bytes(b"weights")
    (path / "config.json").write_text(json.dumps({"model_type": "marian"}), encoding="utf-8")
    (path / "source.spm").write_bytes(b"source")
    (path / "target.spm").write_bytes(b"target")
    return path


def test_registry_registers_and_reloads_a_valid_translation_model(tmp_path) -> None:
    root = tmp_path / "registry"
    model = _model(tmp_path / "en-ru")
    registry = ModelRegistry(root)

    descriptor = registry.register_local(
        model,
        model_id="my-en-ru",
        source_language="en",
        target_language="ru",
    )

    assert descriptor.pair.code == "en-ru"
    assert registry.path.is_file()
    loaded = ModelRegistry(root)
    assert loaded.require("my-en-ru").validate().valid


def test_registry_rejects_invalid_model_and_path_escape(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "registry")
    with pytest.raises(ModelValidationError):
        registry.register_local(
            tmp_path / "missing",
            model_id="broken",
            source_language="en",
            target_language="ru",
        )

    with pytest.raises(UnsafeModelPath):
        safe_join(tmp_path, "../outside.bin")
