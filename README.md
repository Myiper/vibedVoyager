# Native-Search Crawler

Native-Search is a single-machine, Python-native web crawler and live search engine.
It crawls websites from a seed URL, indexes discovered pages into SQLite, and allows
search while crawling is still running.

## What This Project Is

- A depth-limited crawler (`origin`, `k`) built with Python stdlib networking/parsing.
- A real-time search engine over crawled pages with simple relevance scoring.
- A multi-run crawl controller with per-run limits and isolated runtime state.
- A local web dashboard with Start, Search, and Status pages.
- A persistent system: active runs recover after restart using SQLite WAL storage.

## Features

- Depth-limited recursive crawling.
- Strict deduplication per run (`visited` guard + DB constraints).
- Concurrent worker pool with back-pressure:
  - bounded queue
  - token-bucket throttling
- Live search during indexing (global by default, optional run filter).
- Per-run controls:
  - pause/resume
  - stop all active/paused crawls
  - delete completed/failed/stopped runs
- Runtime event stream:
  - queued URLs
  - visited URLs
  - failed fetches (including HTTP deny errors like `403`)
- Status console in UI with fixed height + scrollbar + clear console.
- Persistent recovery:
  - reload unfinished frontier (`queued`/`in_progress`) on restart.

## Prerequisites

- Python 3.10+ (3.12 recommended).
- `pip` (for installing test dependency).

## Installation

1. (Optional) Create and activate a virtual environment.
2. Install test dependency:

```bash
python -m pip install pytest
```

No other third-party runtime dependency is required for the application itself.

## Run the Application

Start server with defaults:

```bash
python main.py --host 127.0.0.1 --port 8080
```

Open:

- [http://127.0.0.1:8080](http://127.0.0.1:8080)

UI hash routes:

- `#/start`
- `#/search`
- `#/status`

### CLI Options

`main.py` supports:

- `--host` (default `127.0.0.1`)
- `--port` (default `8080`)
- `--db-path` (default `data/native_search.db`)
- `--workers` (default `8`)
- `--queue-maxsize` (default `5000`)
- `--rps` (default `5.0`)
- `--burst` (default `10`)

## How To Use (UI Workflow)

1. Go to `#/start`.
2. Enter:
   - origin URL
   - depth (`k`)
   - hit rate
   - queue capacity
   - max URLs
3. Click **Start Indexing**.
   - On success, UI redirects to `#/status`.
4. Monitor progress in Status:
   - run table
   - runtime console stream (queued/visited/failed)
5. Use controls as needed:
   - pause/resume specific run
   - stop all crawls
   - clear console
   - delete run (only when not active/paused)
6. Go to `#/search`:
   - search globally or filter by run
   - click any result URL to open website in a new tab

Notes:

- Start-page numeric settings are persisted in browser storage.
- Console clear state is also persisted across refresh.

## API Endpoints

### POST

#### `POST /index`

Start a new crawl run.

Body:

```json
{
  "origin": "https://example.com",
  "k": 2,
  "hit_rate": 8,
  "queue_capacity": 2000,
  "max_urls": 50000
}
```

Success (`202`):

```json
{"run_id":"<uuid>"}
```

Validation:

- `origin` required, valid `http/https` URL
- `k` integer and `>= 0`
- `hit_rate` (if provided) `> 0`
- `queue_capacity` (if provided) `> 0`
- `max_urls` `> 0`

#### `POST /runs/{run_id}/pause`

Pause a run.

Success (`200`):

```json
{"status":"paused","run_id":"<run_id>"}
```

#### `POST /runs/{run_id}/resume`

Resume a run.

Success (`200`):

```json
{"status":"active","run_id":"<run_id>"}
```

#### `POST /control/stop`

Stop all `active`/`paused` runs.

Body (required):

```json
{"confirm_stop": true}
```

Success (`200`):

```json
{"status":"stopped","stopped_runs":1,"dropped_tasks":42}
```

Validation:

- request must include `confirm_stop=true`

### GET

#### `GET /runs`

List runs with counters/settings/frontier summary.

#### `GET /status`

Global status snapshot.

#### `GET /runs/{run_id}/status`

Run-specific status snapshot.

#### `GET /search?q=<term>&limit=<n>&run_id=<optional>`

Search indexed pages.

- default scope: all runs
- optional `run_id` filter
- `limit` is clamped to `1..200`
- each result returns: `relevant_url`, `origin_url`, `depth`, `relevance_score`, `matched_term_frequency`

Success:

```json
{
  "query": "example",
  "run_id": null,
  "results": [
    ["https://example.com/page","https://example.com",1,7.5,4]
  ]
}
```

#### `GET /events?limit=<n>&run_id=<optional>`

Runtime crawl events used by status console.

Returns:

```json
{
  "events": [
    {
      "ts": 1710000000.0,
      "run_id": "<uuid>",
      "event": "queued|visited|failed",
      "url": "https://example.com",
      "depth": 0,
      "error": null
    }
  ]
}
```

Notes:

- `limit` default is `500` (bounded to `1..5000` internally).
- failed events include `error` message.

#### `GET /stats`

DB analytics across runs (depth distribution, top domains/terms, dead letters).

#### `GET /runs/{run_id}/stats`

DB analytics for one run.

### DELETE

#### `DELETE /runs/{run_id}`

Delete run data (cascades related records).

- `200` deleted
- `404` run not found
- `409` run is active/paused (cannot delete)

## Project Structure

```text
main.py
product_prd.md
README.md

src/
  api/
    server.py          # HTTP API + static SPA serving
  core/
    crawler.py         # CrawlManager, workers, run lifecycle, event stream
    index_store.py     # SQLite schema + persistence + analytics queries
    search.py          # Search ranking and query pipeline
    link_parser.py     # HTML link/title parsing
    rate_limit.py      # Token bucket limiter
    models.py          # CrawlTask model
    utils.py           # URL normalization, tokenization

frontend/dist/
  index.html
  app.js               # React UI logic
  styles.css

tests/
  test_integration_crawl.py
  test_multirun_features.py
  test_frontend_smoke.py
  test_recovery.py
  test_search.py
  test_index_store.py
  test_utils.py
```

## How It Works

1. `POST /index` creates a run and enqueues origin URL.
2. Worker threads consume tasks from shared queue.
3. For each URL:
   - apply per-run rate limiter
   - fetch HTML via `urllib`
   - parse links/title
   - extract text
   - persist page + terms into SQLite
4. Child links are normalized/deduplicated and re-enqueued (until depth/limits).
5. Search queries read indexed pages and rank results by:
   - token frequency
   - title match boost
   - URL match boost
6. Status and events endpoints expose runtime state for UI.

### Recovery Model

- Crawl frontier, visited URLs, pages, terms, and run settings are persisted.
- On startup, unfinished active frontier entries are reloaded into memory queue.
- URL uniqueness constraints make recovery idempotent.

## Error Handling and Visibility

- Backend fetch/network/content-type errors are recorded as failed events.
- HTTP deny responses (for example `403 Forbidden`) are captured and visible in UI.
- Status console shows latest crawl error and per-event error details.
- Worker failure bookkeeping is guarded so worker threads do not die due to DB race conditions.

## Testing

Run all tests:

```bash
python -m pytest -q
```

Notable coverage includes:

- integration crawling + live search
- multi-run isolation and controls
- stop endpoint behavior
- denied-request error visibility
- frontend route/smoke flow

