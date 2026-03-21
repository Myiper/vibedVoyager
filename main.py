from __future__ import annotations

import argparse
from pathlib import Path

from src.api.server import NativeSearchServer
from src.core.crawler import CrawlManager
from src.core.index_store import IndexStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native-Search crawler and live search API")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", default=8080, type=int, help="HTTP server port")
    parser.add_argument("--db-path", default="data/native_search.db", help="SQLite file path")
    parser.add_argument("--workers", default=8, type=int, help="Crawler worker count")
    parser.add_argument("--queue-maxsize", default=5000, type=int, help="Frontier queue max size")
    parser.add_argument("--rps", default=5.0, type=float, help="Global requests per second")
    parser.add_argument("--burst", default=10, type=int, help="Token bucket burst")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    store = IndexStore(root / args.db_path)
    manager = CrawlManager(
        store=store,
        workers=args.workers,
        queue_maxsize=args.queue_maxsize,
        requests_per_second=args.rps,
        burst=args.burst,
    )
    manager.start()
    server = NativeSearchServer(manager=manager, host=args.host, port=args.port, web_root=root / "web")
    print(f"Native-Search running at http://{args.host}:{args.port}")
    try:
        server.start(blocking=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        manager.shutdown()
        store.close()


if __name__ == "__main__":
    main()

