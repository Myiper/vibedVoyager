from __future__ import annotations

import queue
import threading
import time
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
        self._paused_event = threading.Event()
        self._visited_lock = threading.Lock()
        self._visited: set[tuple[str, str]] = set()
        self._active_jobs = 0
        self._active_jobs_lock = threading.Lock()
        self._backpressure_count = 0
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

    def pause(self) -> None:
        self._paused_event.set()

    def resume(self) -> None:
        self._paused_event.clear()

    def start_index(self, origin: str, max_depth: int) -> str:
        normalized = normalize_url(origin)
        if not normalized:
            raise ValueError("origin must be a valid http/https URL")
        run_id = self._store.create_run(normalized, max_depth)
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

    def search(self, query: str, limit: int = 50) -> list[tuple[str, str, int]]:
        return self._search.search(query=query, limit=limit)

    def status(self) -> dict[str, Any]:
        with self._active_jobs_lock:
            active_jobs = self._active_jobs
        snapshot = self._store.get_status_snapshot()
        snapshot["runtime"] = {
            "queue_depth": self._queue.qsize(),
            "queue_maxsize": self._queue.maxsize,
            "active_workers": active_jobs,
            "worker_count": self._workers_count,
            "is_paused": self._paused_event.is_set(),
            "is_throttled": self._rate_limiter.throttled,
            "backpressure_events": self._backpressure_count,
        }
        return snapshot

    def _restore_recovery_state(self) -> None:
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
                self._backpressure_count += 1
                time.sleep(0.05)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._paused_event.is_set():
                time.sleep(0.1)
                continue
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
                self._store.mark_frontier_state(task.run_id, task.url, "failed", error=str(exc))
                self._store.record_failure(task.run_id, task.url, task.depth, str(exc))
            finally:
                with self._active_jobs_lock:
                    self._active_jobs -= 1
                self._queue.task_done()

    def _process_task(self, task: CrawlTask) -> None:
        html, page_url = self._fetch_html(task.url)
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

    def _fetch_html(self, url: str) -> tuple[str, str]:
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self._max_retries:
            try:
                self._rate_limiter.acquire()
                request = Request(url=url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, timeout=self._request_timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" not in content_type:
                        raise ValueError(f"unsupported content type: {content_type}")
                    encoding = response.headers.get_content_charset() or "utf-8"
                    raw = response.read()
                    html = raw.decode(encoding, errors="replace")
                    final_url = normalize_url(response.geturl()) or url
                    return html, final_url
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    break
                time.sleep(0.25 * (2**attempt))
                attempt += 1
        raise RuntimeError(f"fetch failed for {url}: {last_exc}")

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
        if not self._store.active_run_ids():
            return
        snapshot = self._store.get_status_snapshot()
        global_status = snapshot.get("global", {})
        queued_items = int(global_status.get("queued_items", 0))
        in_progress_items = int(global_status.get("in_progress_items", 0))
        with self._active_jobs_lock:
            active = self._active_jobs
        if queued_items == 0 and in_progress_items == 0 and active == 0 and self._queue.empty():
            for run_id in self._store.active_run_ids():
                self._store.mark_run_status(run_id, "completed")

