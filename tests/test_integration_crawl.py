from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.core.crawler import CrawlManager
from src.core.index_store import IndexStore


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        pages = {
            "/": '<html><head><title>Root</title></head><body>alpha <a href="/a">A</a></body></html>',
            "/a": '<html><head><title>A Page</title></head><body>beta <a href="/b">B</a></body></html>',
            "/b": "<html><head><title>B Page</title></head><body>gamma</body></html>",
        }
        body = pages.get(self.path, "<html><body>missing</body></html>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_live_search_while_indexing(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    store = IndexStore(tmp_path / "crawl.db")
    manager = CrawlManager(store=store, workers=3, queue_maxsize=16, requests_per_second=20.0, burst=20)
    manager.start()

    run_id = manager.start_index(f"http://{host}:{port}/", max_depth=2)
    assert run_id

    found = _wait_until(lambda: bool(manager.search("gamma", limit=10)))
    assert found, json.dumps(manager.status(), indent=2)

    completed = _wait_until(
        lambda: any(run["run_id"] == run_id and run["status"] == "completed" for run in manager.status()["runs"]),
        timeout=10.0,
    )
    assert completed

    manager.shutdown()
    store.close()
    server.shutdown()
    server.server_close()

