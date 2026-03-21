# Native-Search Crawler

Single-machine, Python-native web crawler and live search engine that supports:

- Depth-limited crawling from an `origin` URL.
- Strict deduplication (same page is not crawled twice per run).
- Live search during active indexing (global by default, optional run filter).
- Back-pressure via bounded queue + token-bucket throttling.
- Recovery/resume after interruption using SQLite WAL-backed persistent state.
- Multiple concurrent crawl runs with isolated settings/state.
- Delete completed/failed runs.
- Localhost React-based control center with separate Start/Search/Status pages.

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
   - UI routes:
     - `#/start`
     - `#/search`
     - `#/status`

## API

- `POST /index`
  - body:
    - `origin` (required, URL)
    - `k` (required, max depth)
    - `hit_rate` (optional, req/sec)
    - `queue_capacity` (optional)
    - `max_urls` (optional)
  - example:
    - `{"origin":"https://example.com","k":2,"hit_rate":8,"queue_capacity":2000,"max_urls":50000}`
  - returns: `{"run_id":"..."}`
- `GET /search?q=term&limit=50&run_id=<optional>`
  - default behavior: search across all runs
  - returns: `{"query":"term","run_id":"...|null","results":[[relevant_url, origin_url, depth], ...]}`
- `GET /runs`
  - returns all runs with per-run settings/counters/frontier counts
- `GET /status`
  - global status snapshot
- `GET /runs/{run_id}/status`
  - run-scoped status snapshot
- `POST /runs/{run_id}/pause`
- `POST /runs/{run_id}/resume`
- `POST /control/stop`
  - force-stops all active/paused runs and drains queued crawl tasks
- `DELETE /runs/{run_id}`
  - deletes run data (active/paused runs are rejected)
- `GET /stats`
  - DB analytics across runs (depth, top domains/terms, dead letters)
- `GET /runs/{run_id}/stats`
  - DB analytics for a specific run

## Architecture Summary

- `src/core/crawler.py`
  - Shared worker-pool crawler with run-isolated contexts.
  - URL normalization + dedupe guard.
  - Per-run rate limiter and per-run queue/max URL enforcement.
- `src/core/index_store.py`
  - Durable crawl/index state in SQLite (`WAL` mode).
  - Stores run configs/counters, frontier, visited, pages, terms, and dead letters.
- `src/core/search.py`
  - SQL-backed retrieval with optional run filter and lightweight relevance ranking.
- `src/api/server.py`
  - HTTP API + SPA static serving.
- `frontend/dist/`
  - React-based control center (Start/Search/Status pages).

## Recovery Model

- Frontier + visited + indexed data are persisted.
- On startup, unfinished active frontier items (`queued`/`in_progress`) are reloaded.
- URL uniqueness constraints make reprocessing idempotent.
- Run-level settings (`hit_rate`, `queue_capacity`, `max_urls`) are persisted.

## Run Tests

```bash
python -m pytest -q
```

