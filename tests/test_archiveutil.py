"""Safe ZIP extract and local-URL guard."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from dotaudio.archiveutil import safe_extract_zip
from dotaudio.netguard import require_local_http_url


def test_safe_extract_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    dest = tmp_path / "out"
    with pytest.raises(RuntimeError, match="небезопасный"):
        safe_extract_zip(archive, dest)


def test_safe_extract_tar_writes_under_destination(tmp_path: Path) -> None:
    import tarfile

    from dotaudio.archiveutil import safe_extract_tar

    archive = tmp_path / "ok.tar"
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"ffmpeg")
    with tarfile.open(archive, "w") as tf:
        tf.add(payload, arcname="bin/ffmpeg")
    dest = tmp_path / "out"
    safe_extract_tar(archive, dest)
    assert (dest / "bin" / "ffmpeg").read_bytes() == b"ffmpeg"


def test_safe_extract_tar_rejects_traversal(tmp_path: Path) -> None:
    import tarfile

    from dotaudio.archiveutil import safe_extract_tar

    archive = tmp_path / "bad.tar"
    payload = tmp_path / "secret.txt"
    payload.write_text("nope", encoding="utf-8")
    with tarfile.open(archive, "w") as tf:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = payload.stat().st_size
        with payload.open("rb") as handle:
            tf.addfile(info, handle)
    dest = tmp_path / "out"
    with pytest.raises(RuntimeError, match="небезопасный"):
        safe_extract_tar(archive, dest)


def test_require_local_http_url_allows_loopback() -> None:
    require_local_http_url("http://127.0.0.1:8765", what="server_url")
    require_local_http_url("http://localhost:11434", what="ollama")


def test_require_local_http_url_blocks_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOTAUDIO_ALLOW_REMOTE_ASR", raising=False)
    with pytest.raises(ValueError, match="localhost"):
        require_local_http_url(
            "https://example.com/v1",
            what="server_url",
            allow_env="DOTAUDIO_ALLOW_REMOTE_ASR",
        )
    monkeypatch.setenv("DOTAUDIO_ALLOW_REMOTE_ASR", "1")
    require_local_http_url(
        "https://example.com/v1",
        what="server_url",
        allow_env="DOTAUDIO_ALLOW_REMOTE_ASR",
    )
