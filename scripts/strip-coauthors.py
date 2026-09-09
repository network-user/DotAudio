#!/usr/bin/env python3
"""Убрать соавторов из истории git, оставить одного автора.

Удаляет из сообщений коммитов трейлеры вроде::

    Co-authored-by: Cursor <cursoragent@cursor.com>
    Co-Authored-By: ...
    Generated-by: ...

и (по умолчанию) выставляет author/committer на одного человека.

Требует ``git-filter-repo``. Переписывает SHA - после прогона нужен
``git push --force-with-lease``, только с явного согласия.

Примеры::

    python scripts/strip-coauthors.py --dry-run
    python scripts/strip-coauthors.py
    python scripts/strip-coauthors.py --author "Имя <mail@example.com>"
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TRAILER_RE = re.compile(
    rb"(?im)^[ \t]*(?:"
    rb"co-authored-by|coauthored-by|signed-off-by|generated-by|"
    rb"generated-with|assisted-by|acked-by|reviewed-by"
    rb")[ \t]*:.*$(?:\r?\n)?"
)
CURSOR_EMAIL_RE = re.compile(rb"(?i)cursoragent@cursor\.com")
AUTHOR_RE = re.compile(r"^(.+?)\s*<([^>]+)>\s*$")


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def _config(key: str) -> str:
    result = _git("config", "--get", key, check=False)
    return (result.stdout or "").strip()


def _parse_author(value: str) -> tuple[bytes, bytes]:
    match = AUTHOR_RE.match(value.strip())
    if not match:
        raise SystemExit(
            'Автор: ожидается формат Name <email>, например "Иван <ivan@example.com>".'
        )
    return match.group(1).encode("utf-8"), match.group(2).encode("utf-8")


def _count_trailers() -> int:
    result = _git("log", "--all", "--format=%B", check=False)
    return len(re.findall(r"(?im)^co-authored-by\s*:", result.stdout or ""))


def _write_callbacks(
    path: Path,
    *,
    name: bytes,
    email: bytes,
    keep_authors: bool,
) -> None:
    # filter-repo выполняет callback как Python-фрагмент с объектом commit.
    keep = "True" if keep_authors else "False"
    path.write_text(
        f"""
import re

_TRAILER = re.compile(
    rb"(?im)^[ \\t]*(?:"
    rb"co-authored-by|coauthored-by|signed-off-by|generated-by|"
    rb"generated-with|assisted-by|acked-by|reviewed-by"
    rb")[ \\t]*:.*$(?:\\r?\\n)?"
)
_KEEP_AUTHORS = {keep}
_NAME = {name!r}
_EMAIL = {email!r}

def _clean_message(message: bytes) -> bytes:
    cleaned = _TRAILER.sub(b"", message)
    cleaned = re.sub(rb"\\n{{3,}}", b"\\n\\n", cleaned)
    return cleaned.strip() + b"\\n"

commit.message = _clean_message(commit.message)
if not _KEEP_AUTHORS:
    commit.author_name = _NAME
    commit.author_email = _EMAIL
    commit.committer_name = _NAME
    commit.committer_email = _EMAIL
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Удаляет Co-authored-by и оставляет одного автора в истории git."
    )
    parser.add_argument(
        "--author",
        default="",
        help='Единственный автор: Name <email>. По умолчанию git config user.*',
    )
    parser.add_argument(
        "--keep-authors",
        action="store_true",
        help="Не переписывать author/committer, только вырезать трейлеры соавторов",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать, сколько трейлеров найдено, без переписи истории",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Передать --force в git-filter-repo (нужно для уже опубликованного репо)",
    )
    args = parser.parse_args()

    root = Path(_git("rev-parse", "--show-toplevel").stdout.strip())
    os.chdir(root)

    if not shutil.which("git-filter-repo"):
        raise SystemExit(
            "Нужен git-filter-repo: pip install git-filter-repo"
        )

    author = args.author.strip()
    if not author:
        name = _config("user.name")
        email = _config("user.email")
        if not name or not email:
            raise SystemExit(
                "Задайте --author \"Name <email>\" или git config user.name / user.email."
            )
        author = f"{name} <{email}>"
    name_b, email_b = _parse_author(author)

    trailers = _count_trailers()
    print(f"Репозиторий: {root}")
    print(f"Трейлеров Co-authored-by: {trailers}")
    print(f"Автор после прогона: {author}")
    print(
        "Режим: только трейлеры"
        if args.keep_authors
        else "Режим: один author/committer на все коммиты"
    )
    if args.dry_run:
        print("dry-run: история не изменена.")
        return 0

    dirty = _git("status", "--porcelain", "--untracked-files=no", check=False).stdout.strip()
    if dirty:
        raise SystemExit("Сначала закоммитьте или спрячьте изменения в отслеживаемых файлах.")

    origin = _git("remote", "get-url", "origin", check=False)
    origin_url = (origin.stdout or "").strip() if origin.returncode == 0 else ""

    callback = root / ".git" / "strip-coauthors-callback.py"
    _write_callbacks(
        callback,
        name=name_b,
        email=email_b,
        keep_authors=args.keep_authors,
    )

    cmd = ["git", "filter-repo", "--commit-callback", str(callback)]
    if args.force:
        cmd.append("--force")
    print("Запуск:", " ".join(cmd))
    completed = subprocess.run(cmd, check=False)
    callback.unlink(missing_ok=True)
    if completed.returncode != 0:
        return completed.returncode

    if origin_url and _git("remote", "get-url", "origin", check=False).returncode != 0:
        _git("remote", "add", "origin", origin_url)
        print(f"Восстановлен remote origin: {origin_url}")

    left = _count_trailers()
    print(f"Готово. Осталось Co-authored-by: {left}")
    print("Если ветка уже на remote: git push --force-with-lease (только по согласию).")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
