"""Отдельный процесс для llama.cpp: падение CUDA не роняет GUI.

Читает команды JSON-lines из stdin, пишет ответы JSON-lines в stdout.
llama_cpp импортируется только здесь.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from dotaudio.llm import CONTEXT_OVERFLOW, RuntimeUnavailable, _ThinkFilter, is_context_overflow


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _load(payload: dict) -> None:
    from dotaudio import hardware

    module = hardware.import_llama_cpp()
    if module is None:
        raise RuntimeUnavailable("llama-cpp-python не установлен или не загрузился")
    path = str(payload["path"])
    context = int(payload["context"])
    layers = int(payload["layers"])
    threads = int(payload["threads"])
    batch = int(payload.get("batch") or 256)
    key = (path, context, layers, threads, batch)
    state: dict[str, Any] = _load.state  # type: ignore[attr-defined]
    if state.get("key") == key and state.get("model") is not None:
        _write({"type": "ok"})
        return
    _release_model(state)
    try:
        state["model"] = module.Llama(
            model_path=path,
            n_ctx=context,
            n_threads=threads,
            n_gpu_layers=layers,
            n_batch=batch,
            verbose=False,
        )
    except OSError as error:
        raise RuntimeUnavailable(
            "Установленная сборка llama.cpp не запускается на этом процессоре. "
            "Выберите сборку «Процессор» в каталоге моделей."
        ) from error
    state["key"] = key
    _write({"type": "ok"})


def _release_model(state: dict[str, Any]) -> None:
    model = state.pop("model", None)
    state.pop("key", None)
    if model is not None:
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _chat(payload: dict) -> None:
    state: dict[str, Any] = _load.state  # type: ignore[attr-defined]
    model = state.get("model")
    if model is None:
        raise RuntimeUnavailable("Модель не загружена")
    messages = payload["messages"]
    options = payload.get("options") or {}
    try:
        stream = model.create_chat_completion(
            messages=messages,
            temperature=float(options.get("temperature", 0.3)),
            top_p=float(options.get("top_p", 0.9)),
            max_tokens=int(options.get("max_tokens", 900)),
            stream=True,
        )
    except ValueError as error:
        if is_context_overflow(error):
            raise RuntimeUnavailable(CONTEXT_OVERFLOW) from error
        raise
    think = _ThinkFilter()
    pieces: list[str] = []
    for chunk in stream:
        for choice in chunk.get("choices", ()):
            piece = (choice.get("delta") or {}).get("content") or ""
            if not piece:
                continue
            visible = think.feed(piece)
            if visible:
                pieces.append(visible)
                _write({"type": "token", "text": visible})
    tail = think.flush()
    if tail:
        pieces.append(tail)
        _write({"type": "token", "text": tail})
    _write({"type": "done", "text": "".join(pieces)})


def _handle(line: str) -> None:
    payload = json.loads(line)
    cmd = str(payload.get("cmd") or "")
    if cmd == "ping":
        _write({"type": "ok"})
        return
    if cmd == "load":
        _load(payload)
        return
    if cmd == "release":
        _release_model(_load.state)  # type: ignore[attr-defined]
        _write({"type": "ok"})
        return
    if cmd == "chat":
        _chat(payload)
        return
    raise RuntimeUnavailable(f"Неизвестная команда воркера: {cmd}")


def main() -> None:
    _load.state = {}  # type: ignore[attr-defined]
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            _handle(text)
        except RuntimeUnavailable as error:
            _write({"type": "error", "message": str(error)})
        except Exception as error:
            _write({"type": "error", "message": f"{type(error).__name__}: {error}"})


if __name__ == "__main__":
    main()
