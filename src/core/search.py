from __future__ import annotations

from collections import defaultdict

from .index_store import IndexStore
from .utils import tokenize


class SearchEngine:
    def __init__(self, store: IndexStore) -> None:
        self._store = store

    def search(self, query: str, limit: int = 50) -> list[tuple[str, str, int]]:
        terms = tokenize(query)
        if not terms:
            return []

        rows = self._store.get_search_rows(terms=terms, limit=limit)
        scored: dict[tuple[str, str, int], float] = defaultdict(float)

        for row in rows:
            key = (str(row["relevant_url"]), str(row["origin_url"]), int(row["depth"]))
            score = float(row["freq"])
            title = (row["title"] or "").lower()
            relevant_url = str(row["relevant_url"]).lower()
            term = str(row["term"])
            if term in title:
                score += 2.0
            if term in relevant_url:
                score += 1.0
            scored[key] += score

        ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)
        return [item[0] for item in ranked[:limit]]

