"""Safe ZIP extraction: refuse absolute paths, ``..`` and symlink members."""

from __future__ import annotations

import zipfile
from pathlib import Path


def safe_extract_zip(archive: Path | str, destination: Path | str) -> None:
    """Extract ``archive`` into ``destination`` with path confinement.

    Rejects absolute member names, parent-directory traversal and symlink
    entries. Every extracted path must resolve under ``destination``.
    """

    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
                raise RuntimeError(f"небезопасный путь в архиве: {name}")
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise RuntimeError(f"небезопасный путь в архиве: {name}")
            # Symlink members can escape the destination on extract.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError(f"symlink в архиве запрещён: {name}")
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise RuntimeError(f"выход за каталог распаковки: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())

__all__ = ["safe_extract_zip"]
