from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path

from src.api.server import NativeSearchServer
from src.core.crawler import CrawlManager
from src.core.index_store import IndexStore


def test_spa_assets_and_route_fallback(tmp_path: Path) -> None:
    store = IndexStore(tmp_path / "frontend.db")
    manager = CrawlManager(store=store, workers=1, queue_maxsize=8, requests_per_second=5.0, burst=5)
    manager.start()
    server = NativeSearchServer(
        manager=manager,
        host="127.0.0.1",
        port=0,
        web_root=Path(__file__).resolve().parents[1] / "frontend" / "dist",
    )
    server.start(blocking=False)
    assert server._server is not None
    host, port = server._server.server_address

    conn = HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", "/")
    root_resp = conn.getresponse()
    root_body = root_resp.read().decode("utf-8")
    assert root_resp.status == 200
    assert "Native-Search Control Center" in root_body

    conn.request("GET", "/status")
    status_resp = conn.getresponse()
    status_resp.read()
    assert status_resp.status == 200

    conn.request("GET", "/search")
    search_resp = conn.getresponse()
    search_resp.read()
    # search endpoint exists; may return 200 with empty query response
    assert search_resp.status in {200, 400}

    conn.request("GET", "/some/react/route")
    route_resp = conn.getresponse()
    route_body = route_resp.read().decode("utf-8")
    assert route_resp.status == 200
    assert "root" in route_body

    conn.close()
    server.stop()
    manager.shutdown()
    store.close()

