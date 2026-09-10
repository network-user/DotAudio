"""Git-based updates for a source checkout (fetch + hard reset to main).

Data under platformdirs stays untouched. Local uncommitted changes are lost on
apply when the working tree is dirty - the UI must confirm that first.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from threading import Event

DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.I)


@dataclass(frozen=True)
class UpdateStatus:
    available: bool
    supported: bool
    repo_root: str
    remote: str
    branch: str
    current: str
    remote_tip: str
    behind: int
    dirty: bool
    app_version: str
    message: str

    def as_map(self) -> dict:
        return asdict(self)


def app_version() -> str:
    try:
        return metadata.version("dotaudio")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def package_root() -> Path:
    return Path(__file__).resolve().parent


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk parents for a .git directory; prefer the DotAudio checkout."""

    candidates: list[Path] = []
    if start is not None:
        candidates.append(Path(start).resolve())
    candidates.append(package_root())
    candidates.append(Path.cwd().resolve())
    seen: set[Path] = set()
    for base in candidates:
        for path in (base, *base.parents):
            if path in seen:
                continue
            seen.add(path)
            if (path / ".git").exists():
                return path
    return None


def _git(
    repo: Path,
    *args: str,
    timeout: float = 120.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
        creationflags=creationflags,
    )


def _git_ok(repo: Path, *args: str, timeout: float = 120.0) -> tuple[bool, str]:
    try:
        proc = _git(repo, *args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, err or out or f"git {' '.join(args)} failed ({proc.returncode})"
    return True, out


def _short_sha(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return text[:12] if _SHA_RE.match(text) else text


def _is_dirty(repo: Path) -> bool:
    # Untracked files (.venv, local notes) must not block updates or be wiped.
    ok, out = _git_ok(repo, "status", "--porcelain", "--untracked-files=no")
    return bool(ok and out)


def _resolve_python(repo: Path) -> Path:
    if sys.platform == "win32":
        local = repo / ".venv" / "Scripts" / "python.exe"
    else:
        local = repo / ".venv" / "bin" / "python"
    if local.is_file():
        return local
    return Path(sys.executable)


def check_update(
    repo_root: Path | None = None,
    *,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    fetch: bool = True,
    cancel: Event | None = None,
) -> UpdateStatus:
    """Compare HEAD to remote branch. Network only when fetch=True."""

    version = app_version()
    root = find_repo_root(repo_root)
    if root is None:
        return UpdateStatus(
            available=False,
            supported=False,
            repo_root="",
            remote=remote,
            branch=branch,
            current="",
            remote_tip="",
            behind=0,
            dirty=False,
            app_version=version,
            message="Обновление через git недоступно: приложение запущено не из клона репозитория.",
        )

    if cancel is not None and cancel.is_set():
        return UpdateStatus(
            available=False,
            supported=True,
            repo_root=str(root),
            remote=remote,
            branch=branch,
            current="",
            remote_tip="",
            behind=0,
            dirty=_is_dirty(root),
            app_version=version,
            message="Проверка обновления отменена.",
        )

    ok, current = _git_ok(root, "rev-parse", "HEAD")
    if not ok:
        return UpdateStatus(
            available=False,
            supported=False,
            repo_root=str(root),
            remote=remote,
            branch=branch,
            current="",
            remote_tip="",
            behind=0,
            dirty=False,
            app_version=version,
            message=f"git недоступен: {current}",
        )
    current = _short_sha(current)
    dirty = _is_dirty(root)

    if fetch:
        if cancel is not None and cancel.is_set():
            return UpdateStatus(
                available=False,
                supported=True,
                repo_root=str(root),
                remote=remote,
                branch=branch,
                current=current,
                remote_tip="",
                behind=0,
                dirty=dirty,
                app_version=version,
                message="Проверка обновления отменена.",
            )
        fok, ferr = _git_ok(root, "fetch", remote, branch, timeout=180.0)
        if not fok:
            # Fallback: fetch all refs for remotes that reject a single-branch fetch.
            fok, ferr = _git_ok(root, "fetch", remote, timeout=180.0)
        if not fok:
            return UpdateStatus(
                available=False,
                supported=True,
                repo_root=str(root),
                remote=remote,
                branch=branch,
                current=current,
                remote_tip="",
                behind=0,
                dirty=dirty,
                app_version=version,
                message=f"Не удалось связаться с {remote}: {ferr}",
            )

    tip_ref = f"{remote}/{branch}"
    ok, tip = _git_ok(root, "rev-parse", tip_ref)
    if not ok:
        return UpdateStatus(
            available=False,
            supported=True,
            repo_root=str(root),
            remote=remote,
            branch=branch,
            current=current,
            remote_tip="",
            behind=0,
            dirty=dirty,
            app_version=version,
            message=f"Ветка {tip_ref} не найдена. Проверьте remote.",
        )
    tip = _short_sha(tip)

    ok, count_raw = _git_ok(root, "rev-list", "--count", f"HEAD..{tip_ref}")
    behind = int(count_raw) if ok and count_raw.isdigit() else 0
    if not ok and tip and tip != current:
        behind = 1
    available = behind > 0

    if available:
        message = (
            f"Доступна новая версия на {tip_ref} "
            f"({behind} коммит(ов), {current[:7]} → {tip[:7]})."
        )
    elif tip and tip != current:
        message = (
            f"Локальная копия впереди или разошлась с {tip_ref} "
            f"({current[:7]} vs {tip[:7]}). Обновление выровняет к remote."
        )
    else:
        message = f"Уже последняя версия ({tip_ref}, {current[:7]})."

    return UpdateStatus(
        available=available,
        supported=True,
        repo_root=str(root),
        remote=remote,
        branch=branch,
        current=current,
        remote_tip=tip,
        behind=behind,
        dirty=dirty,
        app_version=version,
        message=message,
    )


def apply_update(
    repo_root: Path | None = None,
    *,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    allow_dirty: bool = False,
    reinstall: bool = True,
    cancel: Event | None = None,
) -> dict:
    """Force-sync working tree to remote/branch, then reinstall the editable package."""

    status = check_update(
        repo_root, remote=remote, branch=branch, fetch=True, cancel=cancel
    )
    if not status.supported:
        return {"ok": False, "restart_required": False, **status.as_map()}
    if cancel is not None and cancel.is_set():
        return {
            "ok": False,
            "restart_required": False,
            **status.as_map(),
            "message": "Обновление отменено.",
        }
    if status.dirty and not allow_dirty:
        return {
            "ok": False,
            "restart_required": False,
            **status.as_map(),
            "message": (
                "В рабочей копии есть локальные правки. "
                "Подтвердите обновление - они будут сброшены (git reset --hard)."
            ),
            "needs_confirm_dirty": True,
        }

    root = Path(status.repo_root)
    tip_ref = f"{remote}/{branch}"

    steps = [
        ("checkout", ("checkout", "-f", "-B", branch, tip_ref)),
        ("reset", ("reset", "--hard", tip_ref)),
    ]
    for name, args in steps:
        if cancel is not None and cancel.is_set():
            return {
                "ok": False,
                "restart_required": False,
                **status.as_map(),
                "message": "Обновление отменено.",
            }
        ok, detail = _git_ok(root, *args, timeout=120.0)
        if not ok:
            return {
                "ok": False,
                "restart_required": False,
                **status.as_map(),
                "message": f"Шаг {name} не удался: {detail}",
            }

    reinstall_note = ""
    if reinstall:
        python = _resolve_python(root)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                [str(python), "-m", "pip", "install", "-e", ".", "--quiet"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600.0,
                creationflags=creationflags,
                env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "restart_required": True,
                **status.as_map(),
                "message": (
                    f"Код обновлён ({tip_ref}), но pip install не завершился: {exc}. "
                    "Перезапустите приложение и при необходимости выполните pip install -e ."
                ),
            }
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            reinstall_note = (
                f" Код обновлён, pip вернул ошибку (часто из-за занятых DLL): {err[:400]}"
            )
        else:
            reinstall_note = " Зависимости пересобраны."

    after = check_update(root, remote=remote, branch=branch, fetch=False, cancel=cancel)
    return {
        "ok": True,
        "restart_required": True,
        **after.as_map(),
        "message": (
            f"Обновлено до {after.current[:7] or tip_ref}.{reinstall_note} "
            "Перезапустите DotAudio."
        ),
    }


def launch_restart(repo_root: Path | None = None) -> bool:
    """Start a fresh DotAudio process from the checkout, then caller should quit."""

    root = find_repo_root(repo_root)
    if root is None:
        return False
    python = _resolve_python(root)
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.is_file():
            python = pythonw
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            [str(python), "-m", "dotaudio"],
            cwd=str(root),
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError:
        return False
    return True


__all__ = [
    "DEFAULT_BRANCH",
    "DEFAULT_REMOTE",
    "UpdateStatus",
    "app_version",
    "apply_update",
    "check_update",
    "find_repo_root",
    "launch_restart",
    "package_root",
]
