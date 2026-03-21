from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlTask:
    run_id: str
    origin_url: str
    url: str
    depth: int
    max_depth: int

