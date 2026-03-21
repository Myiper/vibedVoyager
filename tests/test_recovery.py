from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.core.crawler import CrawlManager
from src.core.index_store import IndexStore


class RecoveryFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b'<html><head><title>Recovery</title></head><body>recoverable <a href="/x">x</a></body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def test_frontier_recovery_bootstrap(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecoveryFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    db_path = tmp_path / "recovery.db"
    store = IndexStore(db_path)
    run_id = store.create_run(f"http://{host}:{port}/", 1)
    store.mark_visited(run_id, f"http://{host}:{port}/", 0)
    store.add_or_update_frontier(run_id, f"http://{host}:{port}/", f"http://{host}:{port}/", 0, 1, status="queued")
    store.close()

    recovered_store = IndexStore(db_path)
    manager = CrawlManager(recovered_store, workers=1, queue_maxsize=8, requests_per_second=20.0, burst=10)
    manager.start()

    deadline = time.time() + 5
    completed = False
    while time.time() < deadline:
        status = manager.status()
        if any(run["run_id"] == run_id and run["status"] == "completed" for run in status["runs"]):
            completed = True
            break
        time.sleep(0.1)

    assert completed
    manager.shutdown()
    recovered_store.close()
    server.shutdown()
    server.server_close()

