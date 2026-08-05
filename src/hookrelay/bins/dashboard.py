"""Dashboard 'Bins' view — live request feed for capture bins (v1.6.0).

``broadcast_bin_capture`` pushes every captured request to the process-wide
live :class:`hookrelay.dashboard.connection_manager.ConnectionManager` (the
same manager serving ``/dashboard/ws/live``), so the Bins view can render a
live feed without any polling. ``create_bins_dashboard_router`` serves the
Bins page at ``GET /dashboard/bins``: create a bin, copy its URL, watch the
live feed, and click-to-forward captured requests.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hookrelay.dashboard.connection_manager import ConnectionManager


async def broadcast_bin_capture(manager: ConnectionManager, captured: Any) -> None:
    """Broadcast a newly captured request to connected live-feed clients."""
    payload = {
        "type": "bin.capture",
        "bin_id": captured.bin_id,
        "request_id": captured.request_id,
        "method": captured.method,
        "path": captured.path,
        "source_ip": captured.source_ip,
        "received_at": captured.received_at,
    }
    await manager.broadcast(payload)


_BINS_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bins — Hookrelay</title>
<link rel="stylesheet" href="/dashboard/static/style.css"></head><body>
<nav class="dashboard-nav"><div class="nav-brand">Hookrelay</div><div class="nav-links">
<a href="/dashboard/">Live Feed</a><a href="/dashboard/history">History</a>
<a href="/dashboard/bins" class="active">Bins</a>
<a href="/dashboard/backups">Backups</a><a href="/dashboard/settings">Settings</a>
</div></nav>
<main class="dashboard-main"><header class="page-header"><h1>Bins</h1>
<span class="badge"><span id="bin-count">0</span> bins</span>
<span id="connection-status" class="connection-status reconnecting" role="status" aria-live="polite">Connecting…</span>
</header>
<section class="bins-create"><form id="bin-create-form" class="inline-form">
<input id="bin-description" name="description" type="text" placeholder="Description (optional)" aria-label="Bin description">
<button class="btn btn-primary" type="submit">Create bin</button>
</form></section>
<section class="bins-list" id="bins-list" aria-label="Capture bins"></section>
<section class="bins-forward" id="bins-forward" hidden>
<h2>Forward captured request</h2>
<p>Request <code id="forward-request-id"></code> &middot; bin <code id="forward-bin-id"></code></p>
<form id="forward-form" class="inline-form">
<input id="forward-target-url" name="target_url" type="url" placeholder="https://example.com/webhook" required aria-label="Target URL">
<button class="btn btn-primary" type="submit">Forward</button>
</form>
<p id="forward-result" class="forward-result" role="status" aria-live="polite"></p>
</section>
<section class="live-feed"><h2>Live request feed</h2>
<table class="request-table"><thead><tr><th>Time</th><th>Method</th><th>Bin</th><th>Path</th><th>Source</th><th>ID</th><th>Actions</th></tr></thead>
<tbody id="bins-feed-body"></tbody></table>
<div class="empty-state" id="bins-empty-state"><h2>No captures yet</h2>
<p>Point a webhook sender at a bin URL and captured requests will appear here.</p></div>
</section></main>
<script>
(function () {
  const listEl = document.getElementById("bins-list");
  const feedBody = document.getElementById("bins-feed-body");
  const emptyEl = document.getElementById("bins-empty-state");
  const countEl = document.getElementById("bin-count");
  let bins = [];
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  async function loadBins() {
    try {
      const res = await fetch("/api/bins");
      bins = await res.json();
      countEl.textContent = bins.length;
      listEl.innerHTML = bins.length
        ? bins.map(function (b) {
            return '<div class="bin-card"><div class="bin-meta"><strong>' + esc(b.bin_id.slice(0, 12)) + "</strong> " +
              esc(b.description || "") + ' <span class="badge">' + b.request_count + " requests</span></div>" +
              '<div class="bin-url"><input type="text" readonly value="' + esc(b.url) + '" aria-label="Bin URL">' +
              '<button class="btn btn-secondary" data-copy="' + esc(b.url) + '" type="button">Copy</button></div>' +
              '<div><a class="btn btn-secondary" href="/api/bins/' + esc(b.bin_id) + '/requests">View requests</a></div></div>';
          }).join("")
        : '<div class="empty-state"><h2>No bins yet</h2><p>Create your first capture bin above.</p></div>';
    } catch (e) { /* storage not ready */ }
  }
  document.getElementById("bin-create-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    const description = document.getElementById("bin-description").value;
    fetch("/api/bins", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({description: description || null})})
      .then(function (r) { return r.json(); })
      .then(function () { document.getElementById("bin-description").value = ""; loadBins(); });
  });
  listEl.addEventListener("click", function (ev) {
    const btn = ev.target.closest("[data-copy]");
    if (!btn) return;
    navigator.clipboard.writeText(btn.getAttribute("data-copy"));
  });
  function addFeedRow(msg) {
    emptyEl.style.display = "none";
    const tr = document.createElement("tr");
    tr.innerHTML = '<td class="time">' + esc((msg.received_at || "").slice(-12)) + '</td>' +
      '<td><span class="method method-' + esc((msg.method || "").toLowerCase()) + '">' + esc(msg.method) + '</span></td>' +
      '<td>' + esc(msg.bin_id) + '</td><td>' + esc(msg.path || "/") + '</td><td>' + esc(msg.source_ip) + '</td>' +
      '<td>' + esc(msg.request_id) + '</td>' +
      '<td><a class="btn btn-secondary" href="/dashboard/bins?request=' + esc(msg.request_id) + '&bin=' + esc(msg.bin_id) + '">Forward</a></td>';
    feedBody.prepend(tr);
    while (feedBody.children.length > 100) feedBody.removeChild(feedBody.lastChild);
  }
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(proto + "://" + location.host + "/dashboard/ws/live");
    ws.onopen = function () {
      const el = document.getElementById("connection-status");
      el.textContent = "Live"; el.className = "connection-status live";
    };
    ws.onmessage = function (event) {
      let msg; try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === "bin.capture") addFeedRow(msg);
    };
    ws.onclose = function () { setTimeout(connect, 2000); };
  }
  const forwardParams = new URLSearchParams(location.search);
  const fwdRequestId = forwardParams.get("request");
  const fwdBinId = forwardParams.get("bin");
  const forwardPanel = document.getElementById("bins-forward");
  if (fwdRequestId && fwdBinId) {
    document.getElementById("forward-request-id").textContent = fwdRequestId;
    document.getElementById("forward-bin-id").textContent = fwdBinId;
    forwardPanel.hidden = false;
  }
  document.getElementById("forward-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    const resultEl = document.getElementById("forward-result");
    if (!fwdRequestId || !fwdBinId) return;
    const targetUrl = document.getElementById("forward-target-url").value;
    resultEl.textContent = "Forwarding\u2026";
    fetch("/api/bins/" + encodeURIComponent(fwdBinId) + "/requests/" + encodeURIComponent(fwdRequestId) + "/forward", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({target_url: targetUrl})
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && typeof data.status_code === "number") {
          resultEl.textContent = "Forwarded \u2014 HTTP " + data.status_code + " in " + Math.round(data.latency_ms) + " ms";
        } else {
          resultEl.textContent = "Forward failed: " + ((data && data.error) ? data.error : "unknown error");
        }
      })
      .catch(function () { resultEl.textContent = "Forward request failed"; });
  });
  loadBins();
  connect();
})();
</script></body></html>"""


def create_bins_dashboard_router() -> APIRouter:
    """Create the router serving the Bins dashboard view."""
    router = APIRouter()

    @router.get("/dashboard/bins", response_class=HTMLResponse)
    async def bins_view(request: Request):
        return HTMLResponse(_BINS_PAGE)

    return router
