/* global React, ReactDOM */
const e = React.createElement;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function useInterval(callback, delay) {
  React.useEffect(() => {
    const id = setInterval(callback, delay);
    return () => clearInterval(id);
  }, [callback, delay]);
}

function StatusPill({ status }) {
  const className = `pill ${status || ""}`;
  return e("span", { className }, status || "unknown");
}

function StartPage({ onRunCreated }) {
  const [origin, setOrigin] = React.useState("");
  const [k, setK] = React.useState(2);
  const [hitRate, setHitRate] = React.useState(5);
  const [queueCapacity, setQueueCapacity] = React.useState(5000);
  const [maxUrls, setMaxUrls] = React.useState(10000);
  const [message, setMessage] = React.useState("");

  async function submit(event) {
    event.preventDefault();
    try {
      const payload = await api("/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, k, hit_rate: hitRate, queue_capacity: queueCapacity, max_urls: maxUrls }),
      });
      setMessage(`Run started: ${payload.run_id}`);
      onRunCreated();
    } catch (err) {
      setMessage(err.message);
    }
  }

  return e("div", { className: "card" }, [
    e("h2", { key: "title" }, "Start Crawl"),
    e("p", { className: "muted", key: "desc" }, "Create independent crawl runs with custom limits."),
    e(
      "form",
      { onSubmit: submit, key: "form" },
      e("div", { className: "row3" }, [
        e("label", { key: "origin" }, ["Origin URL", e("input", { value: origin, onChange: (x) => setOrigin(x.target.value), required: true })]),
        e("label", { key: "k" }, ["Depth (k)", e("input", { type: "number", min: 0, value: k, onChange: (x) => setK(Number(x.target.value)) })]),
        e("label", { key: "rate" }, ["Hit Rate (req/s)", e("input", { type: "number", step: 0.1, min: 0.1, value: hitRate, onChange: (x) => setHitRate(Number(x.target.value)) })]),
        e("label", { key: "queue" }, ["Queue Capacity", e("input", { type: "number", min: 1, value: queueCapacity, onChange: (x) => setQueueCapacity(Number(x.target.value)) })]),
        e("label", { key: "max" }, ["Max URLs", e("input", { type: "number", min: 1, value: maxUrls, onChange: (x) => setMaxUrls(Number(x.target.value)) })]),
      ]),
      e("div", { style: { marginTop: "12px" } }, e("button", { type: "submit" }, "Start Indexing"))
    ),
    message ? e("p", { key: "message" }, message) : null,
  ]);
}

function SearchPage({ runs }) {
  const [query, setQuery] = React.useState("");
  const [runId, setRunId] = React.useState("");
  const [results, setResults] = React.useState([]);
  const [error, setError] = React.useState("");

  async function submit(event) {
    event.preventDefault();
    const params = new URLSearchParams({ q: query, limit: "100" });
    if (runId) params.set("run_id", runId);
    try {
      const payload = await api(`/search?${params.toString()}`);
      setResults(payload.results || []);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  return e("div", { className: "card" }, [
    e("h2", { key: "title" }, "Search"),
    e(
      "form",
      { onSubmit: submit, key: "form" },
      e("div", { className: "row" }, [
        e("label", { key: "q" }, ["Query", e("input", { value: query, onChange: (x) => setQuery(x.target.value), required: true })]),
        e("label", { key: "run" }, [
          "Run Filter (default: all runs)",
          e(
            "select",
            { value: runId, onChange: (x) => setRunId(x.target.value) },
            [e("option", { key: "all", value: "" }, "All runs")].concat(
              runs.map((run) => e("option", { key: run.run_id, value: run.run_id }, `${run.origin_url} (${run.run_id.slice(0, 8)})`))
            )
          ),
        ]),
      ]),
      e("div", { style: { marginTop: "12px" } }, e("button", { type: "submit" }, "Search"))
    ),
    error ? e("p", { key: "error" }, error) : null,
    e(
      "div",
      { className: "result-list", key: "results" },
      results.map((row, idx) =>
        e("div", { className: "result-item", key: idx }, [
          e("div", { key: "u" }, row[0]),
          e("div", { className: "muted", key: "meta" }, `origin: ${row[1]} | depth: ${row[2]}`),
        ])
      )
    ),
  ]);
}

function StatusPage({ runs, refreshRuns }) {
  const [stats, setStats] = React.useState({ runs: [] });
  const [controlMessage, setControlMessage] = React.useState("");
  useInterval(() => {
    api("/stats").then(setStats).catch(() => undefined);
  }, 2500);

  async function action(runId, op) {
    await api(`/runs/${runId}/${op}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    refreshRuns();
  }

  async function remove(runId) {
    try {
      await api(`/runs/${runId}`, { method: "DELETE" });
      refreshRuns();
    } catch (err) {
      alert(err.message);
    }
  }

  async function stopAll() {
    if (!window.confirm("Stop all active crawls? This cannot be undone.")) return;
    try {
      const payload = await api("/control/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      setControlMessage(`Stopped ${payload.stopped_runs || 0} run(s), dropped ${payload.dropped_tasks || 0} queued task(s).`);
      refreshRuns();
    } catch (err) {
      setControlMessage(err.message);
    }
  }

  return e("div", null, [
    e("div", { className: "card", key: "run-table" }, [
      e("div", { key: "title-row", style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px", flexWrap: "wrap" } }, [
        e("h2", { key: "title" }, "Run Status"),
        e("button", { key: "stop-all", className: "warn", onClick: stopAll }, "Stop Crawling"),
      ]),
      controlMessage ? e("p", { key: "stop-message", className: "muted" }, controlMessage) : null,
      e("table", { className: "table", key: "table" }, [
        e("thead", { key: "h" }, e("tr", null, ["Origin", "Run ID", "Status", "Discovered", "Processed", "Queued", "Actions"].map((h) => e("th", { key: h }, h)))),
        e(
          "tbody",
          { key: "b" },
          runs.map((run) =>
            e("tr", { key: run.run_id }, [
              e("td", { key: "origin" }, run.origin_url),
              e("td", { key: "id" }, run.run_id.slice(0, 8)),
              e("td", { key: "st" }, e(StatusPill, { status: run.status })),
              e("td", { key: "d" }, String(run.urls_discovered || 0)),
              e("td", { key: "p" }, String(run.urls_processed || 0)),
              e("td", { key: "q" }, String((run.frontier && run.frontier.queued) || 0)),
              e("td", { key: "a" }, e("div", { className: "actions" }, [
                e("button", { key: "pause", className: "alt", onClick: () => action(run.run_id, "pause") }, "Pause"),
                e("button", { key: "resume", className: "alt", onClick: () => action(run.run_id, "resume") }, "Resume"),
                e("button", { key: "delete", className: "warn", onClick: () => remove(run.run_id) }, "Delete"),
              ])),
            ])
          )
        ),
      ]),
    ]),
    e("div", { className: "card", key: "stats" }, [
      e("h2", { key: "title" }, "Database Analytics"),
      e("div", { className: "grid", key: "grid" }, (stats.runs || []).slice(0, 6).map((entry) =>
        e("div", { className: "metric", key: entry.summary.run_id }, [
          e("div", { className: "label", key: "lbl" }, entry.summary.origin_url),
          e("div", { className: "value", key: "val" }, String(entry.summary.urls_processed || 0)),
          e("div", { className: "muted", key: "meta" }, `processed | dead letters: ${entry.dead_letters}`),
        ])
      )),
    ]),
  ]);
}

function App() {
  const [runs, setRuns] = React.useState([]);
  const [path, setPath] = React.useState(window.location.hash.replace("#", "") || "/start");

  const refreshRuns = React.useCallback(() => {
    api("/runs")
      .then((payload) => setRuns(payload.runs || []))
      .catch(() => setRuns([]));
  }, []);

  useInterval(refreshRuns, 1800);
  React.useEffect(() => {
    refreshRuns();
    const onHash = () => setPath(window.location.hash.replace("#", "") || "/start");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [refreshRuns]);

  let page = e(StartPage, { onRunCreated: refreshRuns });
  if (path === "/search") page = e(SearchPage, { runs });
  if (path === "/status") page = e(StatusPage, { runs, refreshRuns });

  return e("div", { className: "layout" }, [
    e("div", { className: "topbar", key: "top" }, [
      e("div", { className: "brand", key: "b" }, "Native-Search Control Center"),
      e("div", { className: "nav", key: "n" }, [
        e("a", { href: "#/start", className: path === "/start" ? "active" : "" }, "Start Crawl"),
        e("a", { href: "#/search", className: path === "/search" ? "active" : "" }, "Search"),
        e("a", { href: "#/status", className: path === "/status" ? "active" : "" }, "Status"),
      ]),
    ]),
    page,
  ]);
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App));

