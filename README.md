# Native-Search Crawler

Single-machine, Python-native web crawler and live search engine that supports:

- Depth-limited crawling from an `origin` URL.
- Strict deduplication (same page is not crawled twice per run).
- Live search during active indexing.
- Back-pressure via bounded queue + token-bucket throttling.
- Recovery/resume after interruption using SQLite WAL-backed persistent state.
- Localhost web dashboard for index/search/status control.

## Quick Start

1. Create and activate a virtual environment (optional but recommended).
2. Install test dependency:

```bash
python -m pip install pytest
```

3. Start the app:

```bash
python main.py --host 127.0.0.1 --port 8080
```

4. Open [http://127.0.0.1:8080](http://127.0.0.1:8080)

## API

- `POST /index`
  - body: `{"origin":"https://example.com","k":2}`
  - returns: `{"run_id":"..."}`
- `GET /search?q=term&limit=50`
  - returns: `{"query":"term","results":[[relevant_url, origin_url, depth], ...]}`
- `GET /status`
  - returns queue depth, worker/back-pressure state, and run/index metrics.
- `POST /control/pause`
- `POST /control/resume`

## Architecture Summary

- `src/core/crawler.py`
  - Worker-pool crawler with bounded `queue.Queue(maxsize=N)`.
  - URL normalization + dedupe guard.
  - Rate limiter with token bucket.
- `src/core/index_store.py`
  - Durable crawl/index state in SQLite (`WAL` mode).
  - Stores runs, frontier, visited, pages, terms, and dead letters.
- `src/core/search.py`
  - SQL-backed retrieval and lightweight relevance ranking.
- `src/api/server.py`
  - HTTP API + static file serving for dashboard.
- `web/`
  - Minimal UI for initiating index/search and monitoring runtime status.

## Recovery Model

- Frontier + visited + indexed data are persisted.
- On startup, unfinished active frontier items (`queued`/`in_progress`) are reloaded.
- URL uniqueness constraints make reprocessing idempotent.

## Run Tests

```bash
python -m pytest -q
```

