"""Портативный FFmpeg и его поиск."""

from __future__ import annotations

from dotaudio import tools_ffmpeg


def test_resolve_ffmpeg_prefers_path(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_ffmpeg.shutil, "which", lambda name: r"C:\bin\ffmpeg.exe")
    assert tools_ffmpeg.resolve_ffmpeg(tmp_path) == r"C:\bin\ffmpeg.exe"


def test_resolve_ffmpeg_falls_back_to_portable(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_ffmpeg.shutil, "which", lambda name: None)
    binary = tools_ffmpeg.local_binary(tmp_path)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"fake")
    assert tools_ffmpeg.resolve_ffmpeg(tmp_path) == str(binary)


def test_ensure_ffmpeg_skips_download_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_ffmpeg, "resolve_ffmpeg", lambda data_dir=None: r"C:\ffmpeg.exe")
    path = tools_ffmpeg.ensure_ffmpeg(tmp_path)
    assert path == r"C:\ffmpeg.exe"


def test_find_ffmpeg_in_tree(tmp_path):
    nested = tmp_path / "ffmpeg-master" / "bin"
    nested.mkdir(parents=True)
    target = nested / ("ffmpeg.exe" if tools_ffmpeg.sys.platform == "win32" else "ffmpeg")
    target.write_bytes(b"x")
    found = tools_ffmpeg._find_ffmpeg_in_tree(tmp_path)
    assert found == target
