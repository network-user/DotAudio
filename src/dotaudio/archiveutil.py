"""Safe archive extraction: refuse absolute paths, ``..`` and symlink members."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path


def _reject_member_name(name: str) -> None:
    text = name.replace("\\", "/")
    if not text or text.endswith("/"):
        return
    if text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise RuntimeError(f"небезопасный путь в архиве: {name}")
    if Path(text).is_absolute() or ".." in Path(text).parts:
        raise RuntimeError(f"небезопасный путь в архиве: {name}")


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
            _reject_member_name(name)
            # Symlink members can escape the destination on extract.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError(f"symlink в архиве запрещён: {name}")
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise RuntimeError(f"выход за каталог распаковки: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())


def safe_extract_tar(archive: Path | str, destination: Path | str) -> None:
    """Extract a tar/tar.gz/tar.xz archive with the same confinement rules as ZIP."""

    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                if member.issym() or member.islnk():
                    raise RuntimeError(f"symlink в архиве запрещён: {member.name}")
                continue
            name = member.name.replace("\\", "/")
            _reject_member_name(name)
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise RuntimeError(f"выход за каталог распаковки: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                continue
            with source, open(target, "wb") as out:
                out.write(source.read())
            mode = member.mode & 0o777
            if mode:
                target.chmod(mode)


__all__ = ["safe_extract_tar", "safe_extract_zip"]
