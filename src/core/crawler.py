from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .index_store import IndexStore
from .link_parser import HTMLLinkParser
from .models import CrawlTask
from .rate_limit import TokenBucketRateLimiter
from .search import SearchEngine
from .utils import normalize_url


USER_AGENT = "NativeSearchCrawler/1.0"


@dataclass
class RunContext:
    run_id: str
    hit_rate: float
    queue_capacity: int
    max_urls: int
    limiter: TokenBucketRateLimiter
    paused: bool = False
    backpressure_events: int = 0


class CrawlManager:
    def __init__(
        self,
        store: IndexStore,
        workers: int = 8,
        queue_maxsize: int = 5000,
        requests_per_second: float = 5.0,
        burst: int = 10,
        request_timeout_seconds: int = 10,
        max_retries: int = 2,
    ) -> None:
        self._store = store
        self._search = SearchEngine(store)
        self._queue: queue.Queue[CrawlTask] = queue.Queue(maxsize=queue_maxsize)
        self._rate_limiter = TokenBucketRateLimiter(rate_per_sec=requests_per_second, burst=burst)
        self._request_timeout = request_timeout_seconds
        self._max_retries = max_retries
        self._workers: list[threading.Thread] = []
        self._workers_count = workers
        self._stop_event = threading.Event()
        self._visited_lock = threading.Lock()
        self._visited: set[tuple[str, str]] = set()
        self._active_jobs = 0
        self._active_jobs_lock = threading.Lock()
        self._run_contexts: dict[str, RunContext] = {}
        self._events_lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=20000)
        self._default_rps = requests_per_second
        self._default_queue_capacity = queue_maxsize
        self._booted = False

    def start(self) -> None:
        if self._booted:
            return
        self._booted = True
        self._restore_recovery_state()
        for index in range(self._workers_count):
            thread = threading.Thread(target=self._worker_loop, name=f"crawler-worker-{index}", daemon=True)
            self._workers.append(thread)
            thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        for thread in self._workers:
            thread.join(timeout=1.0)
        self._workers.clear()

    def pause(self, run_id: str) -> None:
        context = self._run_contexts.get(run_id)
        if context is not None:
            context.paused = True
            self._store.mark_run_status(run_id, "paused")

    def resume(self, run_id: str) -> None:
        context = self._run_contexts.get(run_id)
        if context is not None:
            context.paused = False
            self._store.mark_run_status(run_id, "active")

    def start_index(
        self,
        origin: str,
        max_depth: int,
        hit_rate: float | None = None,
        queue_capacity: int | None = None,
        max_urls: int = 10000,
    ) -> str:
        normalized = normalize_url(origin)
        if not normalized:
            raise ValueError("origin must be a valid http/https URL")
        effective_hit_rate = hit_rate if hit_rate is not None else self._default_rps
        effective_queue_capacity = queue_capacity if queue_capacity is not None else self._default_queue_capacity
        run_id = self._store.create_run(
            normalized,
            max_depth,
            hit_rate=effective_hit_rate,
            queue_capacity=effective_queue_capacity,
            max_urls=max_urls,
        )
        self._run_contexts[run_id] = RunContext(
            run_id=run_id,
            hit_rate=effective_hit_rate,
            queue_capacity=effective_queue_capacity,
            max_urls=max_urls,
            limiter=TokenBucketRateLimiter(rate_per_sec=effective_hit_rate, burst=max(1, int(effective_hit_rate * 2))),
        )
        self._enqueue_if_new(
            CrawlTask(
                run_id=run_id,
                origin_url=normalized,
                url=normalized,
                depth=0,
                max_depth=max_depth,
            )
        )
        return run_id

    def search(self, query: str, limit: int = 50, run_id: str | None = None) -> list[tuple[str, str, int, float, int]]:
        return self._search.search(query=query, limit=limit, run_id=run_id)

    def status(self, run_id: str | None = None) -> dict[str, Any]:
        with self._active_jobs_lock:
            active_jobs = self._active_jobs
        snapshot = self._store.get_status_snapshot(run_id=run_id)
        frontier_counts = self._store.get_run_frontier_counts()
        for run in snapshot.get("runs", []):
            counts = frontier_counts.get(str(run["run_id"]), {})
            run["frontier"] = counts
            context = self._run_contexts.get(str(run["run_id"]))
            run["runtime"] = {
                "is_paused": bool(context.paused) if context else False,
                "is_throttled": bool(context.limiter.throttled) if context else False,
                "backpressure_events": int(context.backpressure_events) if context else 0,
            }
        snapshot["runtime"] = {
            "queue_depth": self._queue.qsize(),
            "queue_maxsize": self._queue.maxsize,
            "active_workers": active_jobs,
            "worker_count": self._workers_count,
        }
        return snapshot

    def list_runs(self) -> list[dict]:
        runs = self._store.list_runs()
        frontier_counts = self._store.get_run_frontier_counts()
        for run in runs:
            run["frontier"] = frontier_counts.get(str(run["run_id"]), {"queued": 0, "in_progress": 0, "done": 0, "failed": 0})
        return runs

    def delete_run(self, run_id: str) -> bool:
        run = self._store.get_run(run_id)
        if not run:
            return False
        if run["status"] in {"active", "paused"}:
            raise ValueError("active or paused runs cannot be deleted")
        self._run_contexts.pop(run_id, None)
        with self._visited_lock:
            self._visited = {item for item in self._visited if item[0] != run_id}
        return self._store.delete_run(run_id)

    def run_statistics(self, run_id: str | None = None) -> dict:
        return self._store.run_statistics(run_id=run_id)

    def recent_events(self, limit: int = 500, run_id: str | None = None) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 5000))
        with self._events_lock:
            items = list(self._events)
        if run_id:
            items = [event for event in items if str(event.get("run_id")) == run_id]
        return items[-bounded:]

    def stop_all(self) -> dict[str, int]:
        run_ids = [
            str(run["run_id"])
            for run in self._store.list_runs()
            if str(run.get("status", "")).strip() in {"active", "paused"}
        ]
        if not run_ids:
            return {"stopped_runs": 0, "dropped_tasks": 0}

        for run_id in run_ids:
            self._store.mark_run_status(run_id, "stopped")
        self._store.mark_frontier_for_runs(
            run_ids=run_ids,
            from_statuses=("queued", "in_progress"),
            to_status="failed",
            error="stopped by user",
        )

        for run_id in run_ids:
            self._run_contexts.pop(run_id, None)
        with self._visited_lock:
            stopped_set = set(run_ids)
            self._visited = {item for item in self._visited if item[0] not in stopped_set}
        dropped_tasks = self._drop_buffered_tasks_for_runs(set(run_ids))
        return {"stopped_runs": len(run_ids), "dropped_tasks": dropped_tasks}

    def _restore_recovery_state(self) -> None:
        for run in self._store.list_runs():
            if run["status"] in {"active", "paused"}:
                paused = str(run["status"]) == "paused"
                self._run_contexts[str(run["run_id"])] = RunContext(
                    run_id=str(run["run_id"]),
                    hit_rate=float(run["hit_rate"]),
                    queue_capacity=int(run["queue_capacity"]),
                    max_urls=int(run["max_urls"]),
                    limiter=TokenBucketRateLimiter(
                        rate_per_sec=float(run["hit_rate"]), burst=max(1, int(float(run["hit_rate"]) * 2))
                    ),
                    paused=paused,
                )
        for job in self._store.load_active_frontier():
            task = CrawlTask(
                run_id=str(job["run_id"]),
                origin_url=str(job["origin_url"]),
                url=str(job["url"]),
                depth=int(job["depth"]),
                max_depth=int(job["max_depth"]),
            )
            self._enqueue_task(task)
            self._mark_visited_in_memory(task.run_id, task.url)

    def _enqueue_if_new(self, task: CrawlTask) -> bool:
        context = self._run_contexts.get(task.run_id)
        if context is None:
            return False
        run_data = self._store.get_run(task.run_id)
        if run_data is None:
            return False
        if int(run_data["urls_discovered"]) >= context.max_urls:
            return False
        if self._run_queued_items(task.run_id) >= context.queue_capacity:
            context.backpressure_events += 1
            return False

        with self._visited_lock:
            key = (task.run_id, task.url)
            if key in self._visited:
                return False
            inserted = self._store.mark_visited(task.run_id, task.url, task.depth)
            if not inserted:
                self._visited.add(key)
                return False
            self._visited.add(key)
        self._store.add_or_update_frontier(
            task.run_id, task.origin_url, task.url, task.depth, task.max_depth, status="queued"
        )
        self._record_event(task.run_id, "queued", task.url, task.depth)
        self._enqueue_task(task)
        return True

    def _mark_visited_in_memory(self, run_id: str, url: str) -> None:
        with self._visited_lock:
            self._visited.add((run_id, url))

    def _enqueue_task(self, task: CrawlTask) -> None:
        while not self._stop_event.is_set():
            try:
                self._queue.put(task, timeout=0.1)
                return
            except queue.Full:
                context = self._run_contexts.get(task.run_id)
                if context is not None:
                    context.backpressure_events += 1
                time.sleep(0.05)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                try:
                    self._check_run_completion()
                except Exception:
                    # Never kill workers during idle completion checks.
                    pass
                continue

            self._store.mark_frontier_state(task.run_id, task.url, "in_progress")
            with self._active_jobs_lock:
                self._active_jobs += 1
            try:
                self._process_task(task)
                self._store.mark_frontier_state(task.run_id, task.url, "done")
            except Exception as exc:  # pragma: no cover
                self._record_event(task.run_id, "failed", task.url, task.depth, error=str(exc))
                # Storage rows may be removed concurrently (e.g., run deletion/stop).
                # Never let worker threads die because bookkeeping writes fail.
                try:
                    self._store.mark_frontier_state(task.run_id, task.url, "failed", error=str(exc))
                except Exception:
                    pass
                try:
                    self._store.record_failure(task.run_id, task.url, task.depth, str(exc))
                except Exception:
                    pass
            finally:
                with self._active_jobs_lock:
                    self._active_jobs -= 1
                self._queue.task_done()

    def _process_task(self, task: CrawlTask) -> None:
        context = self._run_contexts.get(task.run_id)
        if context is None:
            return
        if context.paused:
            self._store.mark_frontier_state(task.run_id, task.url, "queued")
            self._enqueue_task(task)
            time.sleep(0.05)
            return

        html, page_url = self._fetch_html_for_task(task)
        parser = HTMLLinkParser()
        parser.feed(html)
        title = parser.title or page_url
        text = self._extract_text(html)
        self._store.persist_page(
            run_id=task.run_id,
            origin_url=task.origin_url,
            url=page_url,
            depth=task.depth,
            title=title,
            content=text,
        )
        self._record_event(task.run_id, "visited", page_url, task.depth)

        if task.depth >= task.max_depth:
            return

        child_depth = task.depth + 1
        for candidate in parser.links:
            normalized = normalize_url(candidate, base_url=page_url)
            if not normalized:
                continue
            child = CrawlTask(
                run_id=task.run_id,
                origin_url=task.origin_url,
                url=normalized,
                depth=child_depth,
                max_depth=task.max_depth,
            )
            self._enqueue_if_new(child)

    def _fetch_html_for_task(self, task: CrawlTask) -> tuple[str, str]:
        context = self._run_contexts.get(task.run_id)
        if context is None:
            raise RuntimeError(f"missing run context: {task.run_id}")
        attempt = 0
        last_error_message = "unknown error"
        while attempt <= self._max_retries:
            try:
                context.limiter.acquire()
                request = Request(url=task.url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, timeout=self._request_timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" not in content_type:
                        raise ValueError(f"unsupported content type: {content_type}")
                    encoding = response.headers.get_content_charset() or "utf-8"
                    raw = response.read()
                    html = raw.decode(encoding, errors="replace")
                    final_url = normalize_url(response.geturl()) or task.url
                    return html, final_url
            except HTTPError as exc:
                last_error_message = f"http error {exc.code} {exc.reason}"
                if attempt == self._max_retries:
                    break
                time.sleep(0.25 * (2**attempt))
                attempt += 1
            except URLError as exc:
                last_error_message = f"network error {exc.reason}"
                if attempt == self._max_retries:
                    break
                time.sleep(0.25 * (2**attempt))
                attempt += 1
            except TimeoutError:
                last_error_message = "request timed out"
                if attempt == self._max_retries:
                    break
                time.sleep(0.25 * (2**attempt))
                attempt += 1
            except ValueError as exc:
                last_error_message = str(exc)
                if attempt == self._max_retries:
                    break
                time.sleep(0.25 * (2**attempt))
                attempt += 1
        raise RuntimeError(f"fetch failed for {task.url}: {last_error_message}")

    def _extract_text(self, html: str) -> str:
        cleaned = []
        inside_tag = False
        chunk: list[str] = []
        for char in html:
            if char == "<":
                inside_tag = True
                if chunk:
                    cleaned.append("".join(chunk))
                    chunk = []
                continue
            if char == ">":
                inside_tag = False
                continue
            if not inside_tag:
                chunk.append(char)
        if chunk:
            cleaned.append("".join(chunk))
        return " ".join(" ".join(cleaned).split())

    def _check_run_completion(self) -> None:
        run_ids = self._store.active_run_ids()
        if not run_ids:
            return
        frontier_counts = self._store.get_run_frontier_counts()
        for run_id in run_ids:
            counts = frontier_counts.get(run_id, {})
            queued_items = int(counts.get("queued", 0))
            in_progress_items = int(counts.get("in_progress", 0))
            has_buffered = self._has_buffered_tasks(run_id)
            if queued_items == 0 and in_progress_items == 0 and not has_buffered:
                self._store.mark_run_status(run_id, "completed")
                self._run_contexts.pop(run_id, None)

    def _run_queued_items(self, run_id: str) -> int:
        counts = self._store.get_run_frontier_counts().get(run_id, {})
        return int(counts.get("queued", 0)) + int(counts.get("in_progress", 0))

    def _has_buffered_tasks(self, run_id: str) -> bool:
        with self._queue.mutex:
            return any(task.run_id == run_id for task in list(self._queue.queue))

    def _drop_buffered_tasks_for_runs(self, run_ids: set[str]) -> int:
        if not run_ids:
            return 0
        with self._queue.mutex:
            queued_tasks = list(self._queue.queue)
            kept_tasks = [task for task in queued_tasks if task.run_id not in run_ids]
            removed = len(queued_tasks) - len(kept_tasks)
            if removed <= 0:
                return 0
            self._queue.queue = deque(kept_tasks)
            self._queue.unfinished_tasks = max(0, self._queue.unfinished_tasks - removed)
            self._queue.not_full.notify_all()
            if self._queue.unfinished_tasks == 0:
                self._queue.all_tasks_done.notify_all()
            return removed

    def _record_event(self, run_id: str, event_type: str, url: str, depth: int, error: str | None = None) -> None:
        with self._events_lock:
            self._events.append(
                {
                    "ts": time.time(),
                    "run_id": run_id,
                    "event": event_type,
                    "url": url,
                    "depth": int(depth),
                    "error": error,
                }
            )

