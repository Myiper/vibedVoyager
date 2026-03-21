async function postJson(url, data = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return response.json();
}

function renderSearchResults(results) {
  const list = document.getElementById("search-results");
  list.innerHTML = "";
  if (!results.length) {
    const li = document.createElement("li");
    li.textContent = "No results.";
    list.appendChild(li);
    return;
  }
  for (const [relevantUrl, originUrl, depth] of results) {
    const li = document.createElement("li");
    li.textContent = `${relevantUrl} (origin: ${originUrl}, depth: ${depth})`;
    list.appendChild(li);
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/status");
    const data = await response.json();
    document.getElementById("status").textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    document.getElementById("status").textContent = `Status unavailable: ${error}`;
  }
}

document.getElementById("index-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const origin = document.getElementById("origin").value;
  const k = Number(document.getElementById("depth").value);
  const result = await postJson("/index", { origin, k });
  document.getElementById("index-result").textContent = result.run_id
    ? `Started run: ${result.run_id}`
    : `Error: ${result.error ?? "unknown"}`;
  refreshStatus();
});

document.getElementById("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const q = document.getElementById("query").value;
  const response = await fetch(`/search?q=${encodeURIComponent(q)}&limit=50`);
  const result = await response.json();
  renderSearchResults(result.results ?? []);
});

document.getElementById("pause-btn").addEventListener("click", async () => {
  await postJson("/control/pause");
  refreshStatus();
});

document.getElementById("resume-btn").addEventListener("click", async () => {
  await postJson("/control/resume");
  refreshStatus();
});

setInterval(refreshStatus, 1500);
refreshStatus();

