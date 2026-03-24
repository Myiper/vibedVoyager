from pathlib import Path

from src.core.index_store import IndexStore
from src.core.search import SearchEngine


def test_search_returns_scored_rows(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "search.db")
    run_id = store.create_run("https://example.com", 1)
    store.persist_page(
        run_id=run_id,
        origin_url="https://example.com",
        url="https://example.com/alpha",
        depth=0,
        title="Alpha Doc",
        content="alpha alpha beta",
    )
    store.persist_page(
        run_id=run_id,
        origin_url="https://example.com",
        url="https://example.com/beta",
        depth=1,
        title="Beta Doc",
        content="beta beta beta",
    )
    search = SearchEngine(store)
    rows = search.search("alpha")
    assert rows
    assert rows[0][0] == "https://example.com/alpha"
    assert rows[0][1] == "https://example.com"
    assert isinstance(rows[0][2], int)
    assert isinstance(rows[0][3], float)
    assert rows[0][3] > 0
    assert isinstance(rows[0][4], int)
    assert rows[0][4] >= 2
    store.close()

