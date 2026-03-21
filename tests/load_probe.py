from __future__ import annotations

import argparse
import json
import threading
import time
from http.client import HTTPConnection


def _post(host: str, port: int, path: str, payload: dict) -> dict:
    conn = HTTPConnection(host, port, timeout=5)
    raw = json.dumps(payload).encode("utf-8")
    conn.request("POST", path, body=raw, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return json.loads(body.decode("utf-8"))


def _get(host: str, port: int, path: str) -> dict:
    conn = HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return json.loads(body.decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple load probe for /index, /search and /status")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--origin", required=True, help="Origin URL for crawl")
    parser.add_argument("--k", default=2, type=int)
    parser.add_argument("--search-query", default="test")
    parser.add_argument("--search-rps", default=5, type=int)
    parser.add_argument("--seconds", default=15, type=int)
    args = parser.parse_args()

    result = _post(args.host, args.port, "/index", {"origin": args.origin, "k": args.k})
    print("run:", result)

    stop = threading.Event()

    def spam_search() -> None:
        delay = 1 / max(args.search_rps, 1)
        while not stop.is_set():
            _get(args.host, args.port, f"/search?q={args.search_query}&limit=20")
            time.sleep(delay)

    workers = [threading.Thread(target=spam_search, daemon=True) for _ in range(3)]
    for worker in workers:
        worker.start()

    deadline = time.time() + args.seconds
    while time.time() < deadline:
        status = _get(args.host, args.port, "/status")
        runtime = status.get("runtime", {})
        print(
            {
                "queue_depth": runtime.get("queue_depth"),
                "is_throttled": runtime.get("is_throttled"),
                "backpressure_events": runtime.get("backpressure_events"),
            }
        )
        time.sleep(1)

    stop.set()
    for worker in workers:
        worker.join(timeout=1)


if __name__ == "__main__":
    main()

