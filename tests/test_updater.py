"""Git updater: status mapping and local-repo helpers (no network in unit tests)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dotaudio import process_priority, updater


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


@pytest.fixture()
def git_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", str(remote), str(local))
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test")
    (local / "README.md").write_text("one\n", encoding="utf-8")
    _git(local, "add", "README.md")
    _git(local, "commit", "-m", "init")
    _git(local, "push", "-u", "origin", "main")
    return remote, local


def _push_new_commit(remote: Path, work: Path, text: str, message: str) -> None:
    if work.exists():
        raise AssertionError(f"work path already exists: {work}")
    _git(work.parent, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text(text, encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", message)
    try:
        _git(work, "push", "origin", "HEAD:main")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AssertionError(f"push failed: {detail}") from exc


def test_find_repo_root_from_nested(git_pair: tuple[Path, Path]) -> None:
    _remote, local = git_pair
    nested = local / "src" / "dotaudio"
    nested.mkdir(parents=True)
    assert updater.find_repo_root(nested) == local.resolve()


def test_check_update_same_commit_without_fetch(git_pair: tuple[Path, Path]) -> None:
    _remote, local = git_pair
    status = updater.check_update(local, fetch=False)
    assert status.supported
    assert not status.available
    assert status.behind == 0
    assert status.current
    assert "последняя" in status.message.lower() or "уже" in status.message.lower()


def test_check_update_detects_remote_ahead(git_pair: tuple[Path, Path], tmp_path: Path) -> None:
    remote, local = git_pair
    _push_new_commit(remote, tmp_path / "other", "two\n", "second")

    status = updater.check_update(local, fetch=True)
    assert status.supported
    assert status.available
    assert status.behind >= 1


def test_apply_update_refuses_dirty_without_flag(git_pair: tuple[Path, Path]) -> None:
    _remote, local = git_pair
    (local / "README.md").write_text("edited\n", encoding="utf-8")
    result = updater.apply_update(local, allow_dirty=False, reinstall=False)
    assert not result["ok"]
    assert result.get("needs_confirm_dirty")


def test_apply_update_hard_resets_dirty(git_pair: tuple[Path, Path], tmp_path: Path) -> None:
    remote, local = git_pair
    _push_new_commit(remote, tmp_path / "peer", "three\n", "third")

    readme = local / "README.md"
    readme.write_text("local-edit\n", encoding="utf-8")
    result = updater.apply_update(local, allow_dirty=True, reinstall=False)
    assert result["ok"]
    assert readme.read_text(encoding="utf-8") == "three\n"


def test_check_update_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater, "package_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    status = updater.check_update(tmp_path, fetch=False)
    assert not status.supported
    assert not status.available


def test_process_priority_idempotent() -> None:
    first = process_priority.set_process_priority("below_normal")
    second = process_priority.set_process_priority("below_normal")
    assert second is True or first is False
    process_priority.set_process_priority("normal")


def test_defaults_include_update_keys() -> None:
    from dotaudio.controller import DEFAULTS

    assert DEFAULTS["update_check_enabled"] is True
    assert DEFAULTS["update_auto_prompt"] is True
