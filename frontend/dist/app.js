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

function toNonNegativeInteger(value, fallback) {
  const parsed = Number.parseInt(String(value), 10);
  if (Number.isNaN(parsed) || parsed < 0) return fallback;
  return parsed;
}

function loadStoredInteger(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    return toNonNegativeInteger(raw, fallback);
  } catch (_err) {
    return fallback;
  }
}

function loadStoredNumber(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed = Number.parseFloat(raw);
    if (Number.isNaN(parsed) || parsed < 0) return fallback;
    return parsed;
  } catch (_err) {
    return fallback;
  }
}

function StatusPill({ status }) {
  const className = `pill ${status || ""}`;
  return e("span", { className }, status || "unknown");
}

function StartPage({ onRunCreated }) {
  const [origin, setOrigin] = React.useState("");
  const [k, setK] = React.useState(() => loadStoredInteger("start.depth", 2));
  const [hitRate, setHitRate] = React.useState(() => loadStoredInteger("start.hitRate", 5));
  const [queueCapacity, setQueueCapacity] = React.useState(() => loadStoredInteger("start.queueCapacity", 5000));
  const [maxUrls, setMaxUrls] = React.useState(() => loadStoredInteger("start.maxUrls", 10000));
  const [message, setMessage] = React.useState("");

  React.useEffect(() => {
    try {
      window.localStorage.setItem("start.depth", String(k));
      window.localStorage.setItem("start.hitRate", String(hitRate));
      window.localStorage.setItem("start.queueCapacity", String(queueCapacity));
      window.localStorage.setItem("start.maxUrls", String(maxUrls));
    } catch (_err) {
      // Ignore storage failures (private mode or blocked storage).
    }
  }, [k, hitRate, queueCapacity, maxUrls]);

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
      window.location.hash = "/status";
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
        e("label", { key: "k" }, [
          "Depth (k)",
          e("input", {
            type: "number",
            min: 0,
            step: 1,
            value: k,
            onChange: (x) => setK(toNonNegativeInteger(x.target.value, 0)),
          }),
        ]),
        e("label", { key: "rate" }, [
          "Hit Rate (req/s)",
          e("input", {
            type: "number",
            min: 0,
            step: 1,
            value: hitRate,
            onChange: (x) => setHitRate(toNonNegativeInteger(x.target.value, 0)),
          }),
        ]),
        e("label", { key: "queue" }, [
          "Queue Capacity",
          e("input", {
            type: "number",
            min: 0,
            step: 1,
            value: queueCapacity,
            onChange: (x) => setQueueCapacity(toNonNegativeInteger(x.target.value, 0)),
          }),
        ]),
        e("label", { key: "max" }, [
          "Max URLs",
          e("input", {
            type: "number",
            min: 0,
            step: 1,
            value: maxUrls,
            onChange: (x) => setMaxUrls(toNonNegativeInteger(x.target.value, 0)),
          }),
        ]),
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
          e(
            "a",
            {
              key: "u",
              href: row[0],
              target: "_blank",
              rel: "noopener noreferrer",
            },
            row[0]
          ),
          e("div", { className: "muted", key: "meta" }, `origin: ${row[1]} | depth: ${row[2]}`),
        ])
      )
    ),
  ]);
}

function StatusPage({ runs, refreshRuns }) {
  const [controlMessage, setControlMessage] = React.useState("");
  const [events, setEvents] = React.useState([]);
  const [eventsError, setEventsError] = React.useState("");
  const [clearedAt, setClearedAt] = React.useState(() => loadStoredNumber("status.consoleClearedAt", 0));

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
        body: JSON.stringify({ confirm_stop: true }),
      });
      setControlMessage(`Stopped ${payload.stopped_runs || 0} run(s), dropped ${payload.dropped_tasks || 0} queued task(s).`);
      refreshRuns();
    } catch (err) {
      setControlMessage(err.message);
    }
  }

  const selectedRunId = runs.length === 1 ? runs[0].run_id : "";
  useInterval(() => {
    const params = new URLSearchParams({ limit: "5000" });
    if (selectedRunId) params.set("run_id", selectedRunId);
    api(`/events?${params.toString()}`)
      .then((payload) => {
        setEvents(payload.events || []);
        setEventsError("");
      })
      .catch((err) => setEventsError(err.message || "failed to load events"));
  }, 1200);
  React.useEffect(() => {
    try {
      window.localStorage.setItem("status.consoleClearedAt", String(clearedAt));
    } catch (_err) {
      // Ignore storage failures.
    }
  }, [clearedAt]);
  const visibleEvents = events.filter((entry) => Number(entry.ts || 0) >= clearedAt);
  const errorEvents = visibleEvents.filter((entry) => String(entry.event || "").toLowerCase() === "failed");
  const latestErrorEvent = errorEvents.length ? errorEvents[errorEvents.length - 1] : null;

  const runningRuns = runs.filter((run) => run.status === "active" || run.status === "paused");
  const failedRuns = runs.filter((run) => run.status === "failed");
  const now = new Date();
  const timestamp = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  const monitorLines = [
    `[${timestamp}] Crawl Monitor`,
    `Total runs: ${runs.length} | Running: ${runningRuns.length} | Failed: ${failedRuns.length}`,
    "------------------------------------------------------------",
  ];
  if (eventsError) {
    monitorLines.push(`UI event stream error: ${eventsError}`);
    monitorLines.push("------------------------------------------------------------");
  }
  if (latestErrorEvent) {
    monitorLines.push(`LATEST CRAWL ERROR: ${latestErrorEvent.error || "unknown failure"}`);
    monitorLines.push(`  URL: ${latestErrorEvent.url || "n/a"}`);
    monitorLines.push("------------------------------------------------------------");
  }

  if (!runningRuns.length) {
    monitorLines.push("No active crawl right now.");
    monitorLines.push("Start a new crawl from Start page to view live details.");
  } else {
    for (const run of runningRuns) {
      const discovered = Number(run.urls_discovered || 0);
      const processed = Number(run.urls_processed || 0);
      const queued = Number((run.frontier && run.frontier.queued) || 0);
      const maxUrls = Number(run.max_urls || 0);
      const progress = maxUrls > 0 ? `${Math.min(100, Math.round((discovered / maxUrls) * 100))}%` : "n/a";
      monitorLines.push(`Run ${String(run.run_id || "").slice(0, 8)} | ${run.status.toUpperCase()}`);
      monitorLines.push(`  Origin      : ${run.origin_url || "n/a"}`);
      monitorLines.push(`  Progress    : ${discovered}/${maxUrls} discovered (${progress}), ${processed} processed`);
      monitorLines.push(`  Queue       : ${queued} queued | capacity ${run.queue_capacity ?? "n/a"}`);
      monitorLines.push(`  Throttle    : ${run.hit_rate ?? "n/a"} req/s`);
      monitorLines.push("------------------------------------------------------------");
    }
  }
  monitorLines.push("Event Stream (queued + visited + failed):");
  if (!visibleEvents.length) {
    monitorLines.push("  no event yet");
  } else {
    const start = Math.max(0, visibleEvents.length - 300);
    for (let i = start; i < visibleEvents.length; i += 1) {
      const entry = visibleEvents[i];
      const eventDate = new Date((entry.ts || 0) * 1000);
      const t = `${String(eventDate.getHours()).padStart(2, "0")}:${String(eventDate.getMinutes()).padStart(2, "0")}:${String(eventDate.getSeconds()).padStart(2, "0")}`;
      const runPart = String(entry.run_id || "").slice(0, 8);
      const urlPart = entry.url || "n/a";
      const depthPart = Number(entry.depth || 0);
      const typePart = String(entry.event || "event").toUpperCase();
      const errorPart = entry.error ? ` | error: ${entry.error}` : "";
      monitorLines.push(`[${t}] [${runPart}] ${typePart} depth=${depthPart} ${urlPart}${errorPart}`);
    }
  }

  return e("div", null, [
    e("div", { className: "card", key: "run-table" }, [
      e("div", { key: "title-row", style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px", flexWrap: "wrap" } }, [
        e("h2", { key: "title" }, "Run Status"),
        e("button", { key: "stop-all", type: "button", className: "warn", onClick: stopAll }, "Stop Crawling"),
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
                e("button", { key: "pause", type: "button", className: "alt", onClick: () => action(run.run_id, "pause") }, "Pause"),
                e("button", { key: "resume", type: "button", className: "alt", onClick: () => action(run.run_id, "resume") }, "Resume"),
                e("button", { key: "delete", type: "button", className: "warn", onClick: () => remove(run.run_id) }, "Delete"),
              ])),
            ])
          )
        ),
      ]),
    ]),
    e("div", { className: "card", key: "monitor" }, [
      e("div", { key: "monitor-title-row", style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px", flexWrap: "wrap" } }, [
        e("h2", { key: "title" }, "Crawl Runtime Console"),
        e("button", { key: "clear-console", type: "button", className: "alt", onClick: () => { setClearedAt(Date.now() / 1000); setEvents([]); } }, "Clear Console"),
      ]),
      e("pre", { className: "crawl-console", key: "console" }, monitorLines.join("\n")),
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

