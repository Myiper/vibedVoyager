from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{2,}")


def normalize_url(candidate: str, base_url: str | None = None) -> str | None:
    if base_url:
        candidate = urljoin(base_url, candidate)

    candidate, _fragment = urldefrag(candidate)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    normalized = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )
    return normalized


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]

