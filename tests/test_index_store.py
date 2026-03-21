from pathlib import Path

from src.core.index_store import IndexStore


def test_active_run_ids_handles_tuple_rows(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "store.db")
    run_id = store.create_run("https://example.com", 1)

    # Simulate environments where rows are returned as tuples.
    store._conn.row_factory = None  # type: ignore[attr-defined]
    active = store.active_run_ids()

    assert run_id in active
    store.close()


def test_active_run_ids_ignores_empty_tuple_rows(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "store_empty_tuple.db")
    assert store._extract_run_ids([(), ("",), ("abc",), None]) == ["abc"]  # type: ignore[arg-type]
    store.close()

