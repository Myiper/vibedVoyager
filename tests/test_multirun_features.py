from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.api.server import NativeSearchServer
from src.core.crawler import CrawlManager
from src.core.index_store import IndexStore


class MultiRunFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        pages = {
            "/site1": '<html><head><title>Site1</title></head><body>alpha <a href="/site1-a">A</a></body></html>',
            "/site1-a": "<html><body>alpha second</body></html>",
            "/site2": '<html><head><title>Site2</title></head><body>beta <a href="/site2-a">A</a></body></html>',
            "/site2-a": "<html><body>beta second</body></html>",
            "/dense": "".join(
                [
                    "<html><body>dense "
                    + " ".join([f'<a href="/dense-{idx}">x{idx}</a>' for idx in range(10)])
                    + "</body></html>"
                ]
            ),
            **{f"/dense-{idx}": f"<html><body>node{idx}</body></html>" for idx in range(10)},
        }
        body = pages.get(self.path, "<html><body>missing</body></html>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _wait_until(predicate, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _request(method: str, host: str, port: int, path: str, payload: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    conn.request(method, path, body=body if method != "GET" else None, headers=headers if method != "GET" else {})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    status = resp.status
    conn.close()
    return status, data


def test_multirun_isolation_and_search_filters(tmp_path: Path) -> None:
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), MultiRunFixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    host, port = fixture.server_address

    store = IndexStore(tmp_path / "multi.db")
    manager = CrawlManager(store=store, workers=4, queue_maxsize=64, requests_per_second=40.0, burst=20)
    manager.start()

    run1 = manager.start_index(f"http://{host}:{port}/site1", max_depth=1)
    run2 = manager.start_index(f"http://{host}:{port}/site2", max_depth=1)

    assert _wait_until(lambda: len(manager.search("alpha", run_id=run1)) > 0)
    assert _wait_until(lambda: len(manager.search("beta", run_id=run2)) > 0)

    alpha_run2 = manager.search("alpha", run_id=run2)
    beta_run1 = manager.search("beta", run_id=run1)
    assert alpha_run2 == []
    assert beta_run1 == []

    global_alpha = manager.search("alpha")
    assert global_alpha

    manager.shutdown()
    store.close()
    fixture.shutdown()
    fixture.server_close()


def test_max_urls_enforced(tmp_path: Path) -> None:
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), MultiRunFixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    host, port = fixture.server_address

    store = IndexStore(tmp_path / "limit.db")
    manager = CrawlManager(store=store, workers=3, queue_maxsize=64, requests_per_second=40.0, burst=20)
    manager.start()

    run_id = manager.start_index(f"http://{host}:{port}/dense", max_depth=2, max_urls=3)
    assert _wait_until(lambda: store.get_run(run_id)["urls_discovered"] >= 1)
    assert int(store.get_run(run_id)["urls_discovered"]) <= 3

    manager.shutdown()
    store.close()
    fixture.shutdown()
    fixture.server_close()


def test_api_run_lifecycle_endpoints(tmp_path: Path) -> None:
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), MultiRunFixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_host, fixture_port = fixture.server_address

    store = IndexStore(tmp_path / "api.db")
    manager = CrawlManager(store=store, workers=2, queue_maxsize=32, requests_per_second=30.0, burst=10)
    manager.start()
    api_server = NativeSearchServer(manager=manager, host="127.0.0.1", port=0, web_root=Path("web"))
    api_server.start(blocking=False)
    assert api_server._server is not None
    api_host, api_port = api_server._server.server_address

    status, created = _request(
        "POST",
        api_host,
        int(api_port),
        "/index",
        {
            "origin": f"http://{fixture_host}:{fixture_port}/site1",
            "k": 1,
            "hit_rate": 10,
            "queue_capacity": 100,
            "max_urls": 20,
        },
    )
    assert status == 202
    run_id = created["run_id"]

    status, runs_payload = _request("GET", api_host, int(api_port), "/runs")
    assert status == 200
    assert any(run["run_id"] == run_id for run in runs_payload["runs"])

    pause_status, _pause_payload = _request("POST", api_host, int(api_port), f"/runs/{run_id}/pause", {})
    assert pause_status == 200
    resume_status, _resume_payload = _request("POST", api_host, int(api_port), f"/runs/{run_id}/resume", {})
    assert resume_status == 200

    # Deleting active run should fail.
    delete_active_status, _delete_active_payload = _request("DELETE", api_host, int(api_port), f"/runs/{run_id}", {})
    assert delete_active_status == 409

    store.mark_run_status(run_id, "completed")
    delete_status, delete_payload = _request("DELETE", api_host, int(api_port), f"/runs/{run_id}", {})
    assert delete_status == 200
    assert delete_payload["deleted"] is True

    api_server.stop()
    manager.shutdown()
    store.close()
    fixture.shutdown()
    fixture.server_close()


def test_api_stop_all_endpoint(tmp_path: Path) -> None:
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), MultiRunFixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_host, fixture_port = fixture.server_address

    store = IndexStore(tmp_path / "api-stop.db")
    manager = CrawlManager(store=store, workers=2, queue_maxsize=32, requests_per_second=30.0, burst=10)
    manager.start()
    api_server = NativeSearchServer(manager=manager, host="127.0.0.1", port=0, web_root=Path("web"))
    api_server.start(blocking=False)
    assert api_server._server is not None
    api_host, api_port = api_server._server.server_address

    status, created = _request(
        "POST",
        api_host,
        int(api_port),
        "/index",
        {
            "origin": f"http://{fixture_host}:{fixture_port}/dense",
            "k": 2,
            "hit_rate": 10,
            "queue_capacity": 100,
            "max_urls": 20,
        },
    )
    assert status == 202
    run_id = created["run_id"]
    assert _wait_until(lambda: any(run["run_id"] == run_id for run in manager.list_runs()))

    stop_status, stop_payload = _request("POST", api_host, int(api_port), "/control/stop", {})
    assert stop_status == 200
    assert stop_payload["status"] == "stopped"
    assert int(stop_payload["stopped_runs"]) >= 1

    assert _wait_until(
        lambda: any(run["run_id"] == run_id and run["status"] == "stopped" for run in manager.list_runs()),
        timeout=5.0,
    )

    api_server.stop()
    manager.shutdown()
    store.close()
    fixture.shutdown()
    fixture.server_close()

