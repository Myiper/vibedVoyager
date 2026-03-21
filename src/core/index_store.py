from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from .utils import tokenize


class IndexStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    run_id TEXT PRIMARY KEY,
                    origin_url TEXT NOT NULL,
                    max_depth INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    hit_rate REAL NOT NULL DEFAULT 5.0,
                    queue_capacity INTEGER NOT NULL DEFAULT 5000,
                    max_urls INTEGER NOT NULL DEFAULT 10000,
                    urls_discovered INTEGER NOT NULL DEFAULT 0,
                    urls_processed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS frontier (
                    run_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    origin_url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    enqueued_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (run_id, url),
                    FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS visited (
                    run_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    first_seen_at REAL NOT NULL,
                    PRIMARY KEY (run_id, url),
                    FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS pages (
                    page_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    origin_url TEXT NOT NULL,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    snippet TEXT,
                    fetched_at REAL NOT NULL,
                    UNIQUE (run_id, url),
                    FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS terms (
                    term_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS page_terms (
                    page_id INTEGER NOT NULL,
                    term_id INTEGER NOT NULL,
                    freq INTEGER NOT NULL,
                    PRIMARY KEY (page_id, term_id),
                    FOREIGN KEY (page_id) REFERENCES pages(page_id) ON DELETE CASCADE,
                    FOREIGN KEY (term_id) REFERENCES terms(term_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    failed_at REAL NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES crawl_runs(run_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_pages_run_depth ON pages(run_id, depth);
                CREATE INDEX IF NOT EXISTS idx_page_terms_term_id ON page_terms(term_id);
                CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status);
                """
            )
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        required = {
            "hit_rate": "ALTER TABLE crawl_runs ADD COLUMN hit_rate REAL NOT NULL DEFAULT 5.0",
            "queue_capacity": "ALTER TABLE crawl_runs ADD COLUMN queue_capacity INTEGER NOT NULL DEFAULT 5000",
            "max_urls": "ALTER TABLE crawl_runs ADD COLUMN max_urls INTEGER NOT NULL DEFAULT 10000",
            "urls_discovered": "ALTER TABLE crawl_runs ADD COLUMN urls_discovered INTEGER NOT NULL DEFAULT 0",
            "urls_processed": "ALTER TABLE crawl_runs ADD COLUMN urls_processed INTEGER NOT NULL DEFAULT 0",
        }
        existing = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(crawl_runs)").fetchall()
        }
        with self._conn:
            for column_name, migration_sql in required.items():
                if column_name not in existing:
                    self._conn.execute(migration_sql)

    def create_run(
        self,
        origin_url: str,
        max_depth: int,
        hit_rate: float = 5.0,
        queue_capacity: int = 5000,
        max_urls: int = 10000,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = time.time()
        with self._write_lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO crawl_runs (
                    run_id, origin_url, max_depth, status, created_at, updated_at,
                    hit_rate, queue_capacity, max_urls
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (run_id, origin_url, max_depth, now, now, hit_rate, queue_capacity, max_urls),
            )
        return run_id

    def mark_run_status(self, run_id: str, status: str) -> None:
        now = time.time()
        with self._write_lock, self._conn:
            self._conn.execute(
                "UPDATE crawl_runs SET status=?, updated_at=? WHERE run_id=?",
                (status, now, run_id),
            )

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT
                run_id, origin_url, max_depth, status, created_at, updated_at,
                hit_rate, queue_capacity, max_urls, urls_discovered, urls_processed
            FROM crawl_runs
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                run_id, origin_url, max_depth, status, created_at, updated_at,
                hit_rate, queue_capacity, max_urls, urls_discovered, urls_processed
            FROM crawl_runs
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_or_update_frontier(
        self, run_id: str, origin_url: str, url: str, depth: int, max_depth: int, status: str = "queued"
    ) -> None:
        now = time.time()
        with self._write_lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO frontier (run_id, url, origin_url, depth, max_depth, status, enqueued_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, url) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_error=NULL
                """,
                (run_id, url, origin_url, depth, max_depth, status, now, now),
            )

    def mark_frontier_state(self, run_id: str, url: str, status: str, error: str | None = None) -> None:
        now = time.time()
        with self._write_lock, self._conn:
            self._conn.execute(
                """
                UPDATE frontier
                SET status=?, updated_at=?, last_error=?
                WHERE run_id=? AND url=?
                """,
                (status, now, error, run_id, url),
            )

    def mark_visited(self, run_id: str, url: str, depth: int) -> bool:
        now = time.time()
        with self._write_lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO visited (run_id, url, depth, first_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, url, depth, now),
            )
            inserted = cur.rowcount > 0
            if inserted:
                self._conn.execute(
                    """
                    UPDATE crawl_runs
                    SET urls_discovered=urls_discovered + 1, updated_at=?
                    WHERE run_id=?
                    """,
                    (now, run_id),
                )
            return inserted

    def persist_page(
        self,
        run_id: str,
        origin_url: str,
        url: str,
        depth: int,
        title: str,
        content: str,
    ) -> None:
        tokens = tokenize(content)
        counts = Counter(tokens)
        snippet = " ".join(content.split())[:240]
        fetched_at = time.time()
        with self._write_lock, self._conn:
            page_cur = self._conn.execute(
                """
                INSERT INTO pages (run_id, origin_url, url, depth, title, content, snippet, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, url) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    snippet=excluded.snippet,
                    fetched_at=excluded.fetched_at
                RETURNING page_id
                """,
                (run_id, origin_url, url, depth, title, content, snippet, fetched_at),
            )
            page_id = int(page_cur.fetchone()["page_id"])

            self._conn.execute("DELETE FROM page_terms WHERE page_id=?", (page_id,))
            for term, freq in counts.items():
                term_cur = self._conn.execute(
                    "INSERT INTO terms (term) VALUES (?) ON CONFLICT(term) DO NOTHING RETURNING term_id",
                    (term,),
                )
                row = term_cur.fetchone()
                if row is None:
                    term_id = int(
                        self._conn.execute("SELECT term_id FROM terms WHERE term=?", (term,)).fetchone()["term_id"]
                    )
                else:
                    term_id = int(row["term_id"])
                self._conn.execute(
                    "INSERT INTO page_terms (page_id, term_id, freq) VALUES (?, ?, ?)",
                    (page_id, term_id, freq),
                )

            self._conn.execute(
                """
                UPDATE crawl_runs
                SET
                    processed_count = processed_count + 1,
                    urls_processed = urls_processed + 1,
                    updated_at=?
                WHERE run_id=?
                """,
                (time.time(), run_id),
            )

    def record_failure(self, run_id: str, url: str, depth: int, error: str) -> None:
        with self._write_lock, self._conn:
            self._conn.execute(
                "INSERT INTO dead_letters (run_id, url, depth, error, failed_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, url, depth, error, time.time()),
            )

    def load_active_frontier(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT f.run_id, f.url, f.origin_url, f.depth, f.max_depth
            FROM frontier f
            JOIN crawl_runs r ON r.run_id=f.run_id
            WHERE r.status='active' AND f.status IN ('queued', 'in_progress')
            ORDER BY f.enqueued_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def active_run_ids(self) -> list[str]:
        rows = self._conn.execute("SELECT run_id FROM crawl_runs WHERE status='active'").fetchall()
        return self._extract_run_ids(rows)

    def _extract_run_ids(self, rows: list[object]) -> list[str]:
        run_ids: list[str] = []
        for row in rows:
            # sqlite rows may be Row, tuple/list, scalar, or unexpected shapes.
            if isinstance(row, sqlite3.Row):
                value = row["run_id"] if "run_id" in row.keys() else (row[0] if len(row) > 0 else None)
            elif isinstance(row, (tuple, list)):
                value = row[0] if len(row) > 0 else None
            else:
                value = row

            if value is None:
                continue
            text = str(value).strip()
            if text:
                run_ids.append(text)
        return run_ids

    def get_search_rows(self, terms: list[str], limit: int, run_id: str | None = None) -> list[sqlite3.Row]:
        if not terms:
            return []
        placeholders = ",".join(["?"] * len(terms))
        where_clause = f"WHERE t.term IN ({placeholders})"
        values: list[object] = list(terms)
        if run_id:
            where_clause += " AND p.run_id=?"
            values.append(run_id)
        query = f"""
            SELECT
                p.run_id, p.url AS relevant_url, p.origin_url, p.depth, p.title, p.snippet, t.term, pt.freq
            FROM pages p
            JOIN page_terms pt ON pt.page_id = p.page_id
            JOIN terms t ON t.term_id = pt.term_id
            {where_clause}
        """
        rows = self._conn.execute(query, values).fetchall()
        return rows[: max(limit * 20, limit)]

    def get_status_snapshot(self, run_id: str | None = None) -> dict:
        run_filter = ""
        run_values: list[object] = []
        if run_id:
            run_filter = " AND run_id=?"
            run_values = [run_id]

        row = self._conn.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM crawl_runs WHERE status='active'{" AND run_id=?" if run_id else ""}) AS active_runs,
                (SELECT COUNT(*) FROM visited WHERE 1=1{run_filter}) AS visited_urls,
                (SELECT COUNT(*) FROM pages WHERE 1=1{run_filter}) AS indexed_pages,
                (SELECT COUNT(*) FROM frontier WHERE status='queued'{run_filter}) AS queued_items,
                (SELECT COUNT(*) FROM frontier WHERE status='in_progress'{run_filter}) AS in_progress_items,
                (SELECT COUNT(*) FROM dead_letters WHERE 1=1{run_filter}) AS dead_letters
            """,
            (
                ([run_id] if run_id else [])
                + run_values
                + run_values
                + run_values
                + run_values
                + run_values
            ),
        ).fetchone()

        per_run_rows = self._conn.execute(
            f"""
            SELECT run_id, origin_url, max_depth, status, processed_count, created_at, updated_at
            FROM crawl_runs
            {"WHERE run_id=?" if run_id else ""}
            ORDER BY created_at DESC
            """,
            (run_id,) if run_id else (),
        ).fetchall()
        return {
            "global": dict(row) if row else {},
            "runs": [dict(item) for item in per_run_rows],
        }

    def get_run_frontier_counts(self) -> dict[str, dict[str, int]]:
        rows = self._conn.execute(
            """
            SELECT run_id, status, COUNT(*) AS count
            FROM frontier
            GROUP BY run_id, status
            """
        ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            result.setdefault(run_id, {"queued": 0, "in_progress": 0, "done": 0, "failed": 0})
            result[run_id][str(row["status"])] = int(row["count"])
        return result

    def delete_run(self, run_id: str) -> bool:
        with self._write_lock, self._conn:
            cur = self._conn.execute("DELETE FROM crawl_runs WHERE run_id=?", (run_id,))
        return cur.rowcount > 0

    def run_statistics(self, run_id: str | None = None) -> dict:
        values: list[object] = []
        run_clause = ""
        if run_id:
            run_clause = "WHERE p.run_id=?"
            values = [run_id]

        depth_rows = self._conn.execute(
            f"""
            SELECT p.run_id, p.depth, COUNT(*) AS count
            FROM pages p
            {run_clause}
            GROUP BY p.run_id, p.depth
            ORDER BY p.run_id, p.depth
            """,
            values,
        ).fetchall()

        domain_rows = self._conn.execute(
            f"""
            SELECT p.run_id, p.url
            FROM pages p
            {run_clause}
            LIMIT 5000
            """,
            values,
        ).fetchall()
        domains: dict[str, dict[str, int]] = {}
        for row in domain_rows:
            row_run_id = str(row["run_id"])
            domain = urlparse(str(row["url"])).netloc or "unknown"
            domains.setdefault(row_run_id, {})
            domains[row_run_id][domain] = domains[row_run_id].get(domain, 0) + 1

        term_rows = self._conn.execute(
            f"""
            SELECT p.run_id, t.term, SUM(pt.freq) AS total_freq
            FROM page_terms pt
            JOIN pages p ON p.page_id=pt.page_id
            JOIN terms t ON t.term_id=pt.term_id
            {"WHERE p.run_id=?" if run_id else ""}
            GROUP BY p.run_id, t.term
            ORDER BY total_freq DESC
            LIMIT 50
            """,
            [run_id] if run_id else [],
        ).fetchall()

        failure_rows = self._conn.execute(
            """
            SELECT run_id, COUNT(*) AS dead_letters
            FROM dead_letters
            GROUP BY run_id
            """
        ).fetchall()

        by_run: dict[str, dict] = {}
        for run in self.list_runs():
            by_run[str(run["run_id"])] = {
                "summary": run,
                "depth_distribution": [],
                "top_domains": [],
                "top_terms": [],
                "dead_letters": 0,
            }

        for row in depth_rows:
            row_run_id = str(row["run_id"])
            if row_run_id in by_run:
                by_run[row_run_id]["depth_distribution"].append(
                    {"depth": int(row["depth"]), "count": int(row["count"])}
                )

        for row_run_id, domain_counts in domains.items():
            if row_run_id in by_run:
                by_run[row_run_id]["top_domains"] = [
                    {"domain": domain, "count": count}
                    for domain, count in sorted(domain_counts.items(), key=lambda item: item[1], reverse=True)[:10]
                ]

        grouped_terms: dict[str, list[dict]] = {}
        for row in term_rows:
            row_run_id = str(row["run_id"])
            grouped_terms.setdefault(row_run_id, []).append(
                {"term": str(row["term"]), "count": int(row["total_freq"])}
            )
        for row_run_id, terms in grouped_terms.items():
            if row_run_id in by_run:
                by_run[row_run_id]["top_terms"] = terms[:10]

        for row in failure_rows:
            row_run_id = str(row["run_id"])
            if row_run_id in by_run:
                by_run[row_run_id]["dead_letters"] = int(row["dead_letters"])

        if run_id:
            return by_run.get(run_id, {})
        return {"runs": list(by_run.values())}

    def close(self) -> None:
        self._conn.close()

