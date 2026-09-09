"""Проверка, что URL указывает только на loopback/private хост."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


def _is_loopback_or_private(hostname: str) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"}:
        return True
    if host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Имена вроде my-pc.local не резолвим - только явный loopback.
        return False
    return bool(address.is_loopback or address.is_private or address.is_link_local)


def require_local_http_url(
    url: str,
    *,
    what: str,
    allow_env: str | None = None,
) -> None:
    """Разрешить только http(s) на loopback/private, без userinfo.

    Если задан ``allow_env`` и его значение ``1``, проверку хоста пропускаем
    (явный opt-in на внешний адрес).
    """

    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{what} must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{what} must not contain credentials")
    if allow_env and os.environ.get(allow_env, "").strip() == "1":
        return
    if not _is_loopback_or_private(parsed.hostname):
        raise ValueError(
            f"{what} may only point to localhost/private hosts "
            f"(или задайте {allow_env}=1)"
            if allow_env
            else f"{what} may only point to localhost/private hosts"
        )


__all__ = ["require_local_http_url"]
