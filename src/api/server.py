from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.core.crawler import CrawlManager


class NativeSearchHandler(BaseHTTPRequestHandler):
    manager: CrawlManager
    web_root: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self._json_response(HTTPStatus.OK, self.manager.status())
            return
        if parsed.path == "/runs":
            self._json_response(HTTPStatus.OK, {"runs": self.manager.list_runs()})
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/status"):
            run_id = parsed.path.split("/")[2]
            self._json_response(HTTPStatus.OK, self.manager.status(run_id=run_id))
            return
        if parsed.path == "/stats":
            self._json_response(HTTPStatus.OK, self.manager.run_statistics())
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/stats"):
            run_id = parsed.path.split("/")[2]
            self._json_response(HTTPStatus.OK, self.manager.run_statistics(run_id=run_id))
            return
        if parsed.path == "/events":
            params = parse_qs(parsed.query)
            run_id = params.get("run_id", [""])[0].strip() or None
            try:
                limit = int(params.get("limit", ["500"])[0])
            except ValueError:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "limit must be integer"})
                return
            self._json_response(
                HTTPStatus.OK,
                {"events": self.manager.recent_events(limit=limit, run_id=run_id)},
            )
            return
        if parsed.path == "/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            run_id = params.get("run_id", [""])[0].strip() or None
            try:
                limit = int(params.get("limit", ["50"])[0])
            except ValueError:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "limit must be integer"})
                return
            rows = self.manager.search(query=query, limit=max(1, min(limit, 200)), run_id=run_id)
            self._json_response(HTTPStatus.OK, {"query": query, "run_id": run_id, "results": rows})
            return
        self._serve_spa(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/index":
            payload = self._read_json()
            if payload is None:
                return
            origin = str(payload.get("origin", "")).strip()
            k = payload.get("k", 0)
            try:
                max_depth = int(k)
            except ValueError:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "k must be integer"})
                return
            hit_rate = payload.get("hit_rate")
            queue_capacity = payload.get("queue_capacity")
            max_urls = payload.get("max_urls", 10000)
            try:
                hit_rate_value = float(hit_rate) if hit_rate is not None else None
                queue_capacity_value = int(queue_capacity) if queue_capacity is not None else None
                max_urls_value = int(max_urls)
            except ValueError:
                self._json_response(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "hit_rate must be float, queue_capacity and max_urls must be integers"},
                )
                return
            if max_depth < 0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "k must be >= 0"})
                return
            if hit_rate_value is not None and hit_rate_value <= 0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "hit_rate must be > 0"})
                return
            if queue_capacity_value is not None and queue_capacity_value <= 0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "queue_capacity must be > 0"})
                return
            if max_urls_value <= 0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "max_urls must be > 0"})
                return
            try:
                run_id = self.manager.start_index(
                    origin=origin,
                    max_depth=max_depth,
                    hit_rate=hit_rate_value,
                    queue_capacity=queue_capacity_value,
                    max_urls=max_urls_value,
                )
            except ValueError as exc:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json_response(HTTPStatus.ACCEPTED, {"run_id": run_id})
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/pause"):
            run_id = parsed.path.split("/")[2]
            self.manager.pause(run_id)
            self._json_response(HTTPStatus.OK, {"status": "paused", "run_id": run_id})
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/resume"):
            run_id = parsed.path.split("/")[2]
            self.manager.resume(run_id)
            self._json_response(HTTPStatus.OK, {"status": "active", "run_id": run_id})
            return
        if parsed.path == "/control/stop":
            payload = self._read_json()
            if payload is None:
                return
            if payload.get("confirm_stop") is not True:
                self._json_response(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "confirm_stop=true is required"},
                )
                return
            result = self.manager.stop_all()
            self._json_response(HTTPStatus.OK, {"status": "stopped", **result})
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/runs/"):
            run_id = parsed.path.split("/")[2]
            try:
                deleted = self.manager.delete_run(run_id)
            except ValueError as exc:
                self._json_response(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            if deleted:
                self._json_response(HTTPStatus.OK, {"deleted": True, "run_id": run_id})
                return
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "run not found"})
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
            return None
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return None

    def _json_response(self, status: HTTPStatus, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_static(self, filename: str, content_type: str) -> None:
        target = self.web_root / filename
        if not target.exists():
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "static file missing"})
            return
        raw = target.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_spa(self, request_path: str) -> None:
        normalized = request_path.lstrip("/")
        if not normalized:
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        candidate = self.web_root / normalized
        if candidate.is_file():
            suffix = candidate.suffix
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png",
                ".svg": "image/svg+xml",
            }.get(suffix, "application/octet-stream")
            self._serve_static(normalized, content_type)
            return
        # React Router fallback
        self._serve_static("index.html", "text/html; charset=utf-8")


class NativeSearchServer:
    def __init__(self, manager: CrawlManager, host: str, port: int, web_root: Path) -> None:
        self._manager = manager
        self._host = host
        self._port = port
        self._web_root = web_root
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, blocking: bool = True) -> None:
        handler_type = type(
            "ConfiguredNativeSearchHandler",
            (NativeSearchHandler,),
            {"manager": self._manager, "web_root": self._web_root},
        )
        self._server = ThreadingHTTPServer((self._host, self._port), handler_type)
        if blocking:
            self._server.serve_forever()
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=1.0)

