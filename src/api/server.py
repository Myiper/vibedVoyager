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
        if parsed.path == "/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            try:
                limit = int(params.get("limit", ["50"])[0])
            except ValueError:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "limit must be integer"})
                return
            rows = self.manager.search(query=query, limit=max(1, min(limit, 200)))
            self._json_response(HTTPStatus.OK, {"query": query, "results": rows})
            return
        if parsed.path in {"/", "/index.html"}:
            self._serve_static("index.html", content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_static("app.js", content_type="application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_static("styles.css", content_type="text/css; charset=utf-8")
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

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
            if max_depth < 0:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "k must be >= 0"})
                return
            try:
                run_id = self.manager.start_index(origin=origin, max_depth=max_depth)
            except ValueError as exc:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json_response(HTTPStatus.ACCEPTED, {"run_id": run_id})
            return
        if parsed.path == "/control/pause":
            self.manager.pause()
            self._json_response(HTTPStatus.OK, {"status": "paused"})
            return
        if parsed.path == "/control/resume":
            self.manager.resume()
            self._json_response(HTTPStatus.OK, {"status": "active"})
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

