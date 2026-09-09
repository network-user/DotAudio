"""VRAM arbiter: вытеснение ASR и LLM."""

from __future__ import annotations

from dotaudio.vram_arbiter import VramArbiter


def test_acquire_same_owner_is_idempotent() -> None:
    arbiter = VramArbiter()
    assert arbiter.acquire("asr") is True
    assert arbiter.owner() == "asr"
    assert arbiter.acquire("asr") is True
    assert arbiter.owner() == "asr"


def test_llm_acquire_evicts_asr_callback() -> None:
    arbiter = VramArbiter()
    evicted: list[str] = []
    arbiter.on_evict("asr", lambda: evicted.append("asr"))
    arbiter.acquire("asr")
    arbiter.acquire("llm")
    assert evicted == ["asr"]
    assert arbiter.owner() == "llm"


def test_asr_acquire_evicts_llm_callback() -> None:
    arbiter = VramArbiter()
    evicted: list[str] = []
    arbiter.on_evict("llm", lambda: evicted.append("llm"))
    arbiter.acquire("llm")
    arbiter.acquire("asr")
    assert evicted == ["llm"]
    assert arbiter.owner() == "asr"


def test_release_clears_owner() -> None:
    arbiter = VramArbiter()
    arbiter.acquire("llm")
    arbiter.release("llm")
    assert arbiter.owner() is None


def test_release_other_owner_keeps_current() -> None:
    arbiter = VramArbiter()
    arbiter.acquire("asr")
    arbiter.release("llm")
    assert arbiter.owner() == "asr"
