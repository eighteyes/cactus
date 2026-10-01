"""
www.py — localhost web answering surface for cactus.

Responsibilities:
- Serve a single-page HTML/JS/CSS answering UI over http.server (stdlib only).
- Expose a small JSON API (/api/feed, /api/answer, /api/clear, /api/reopen,
  /api/poke) that mirrors what the TUI does through Store, plus /api/events
  for Server-Sent Events so the page updates without polling.
- Serialize every store call behind one lock: Store's sqlite3 connection is
  opened with the default check_same_thread=True, so a ThreadingHTTPServer
  handler thread cannot touch it directly without one.
- Bind loopback only by default and perform no authentication — this is a
  human's own machine reaching its own inbox, not a shared service.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .poke import PokeError, poke, wake_owner
from .store import ACTIONABLE, AlreadyAnswered, Question, Store

POLL_INTERVAL = 0.5
PING_INTERVAL = 15.0


def _msg(exc: BaseException) -> str:
    """Same repr-stripping cleanup cli._msg uses for KeyError."""
    if isinstance(exc, KeyError) and len(exc.args) == 1:
        return str(exc.args[0])
    return str(exc)


def _questions(store: Store, project: str | None) -> list[Question]:
    return store.tree(
        project=project,
        status=ACTIONABLE,
        all_projects=project is None,
    )


PAGE = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cactus</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 13px; background: #14161a; color: #d8dbe0;
    display: flex; height: 100vh; overflow: hidden;
  }
  #rail {
    width: 320px; min-width: 220px; max-width: 45vw; overflow-y: auto;
    border-right: 1px solid #2a2d34; flex-shrink: 0;
  }
  #card { flex: 1; overflow-y: auto; padding: 16px; }
  .proj-head {
    padding: 6px 10px; background: #1c1f26; color: #8b93a3;
    position: sticky; top: 0; font-weight: bold;
  }
  .row {
    padding: 8px 10px; border-bottom: 1px solid #1f222a; cursor: pointer;
  }
  .row:hover { background: #1a1d24; }
  .row.selected { background: #23324a; }
  .row-key { color: #8b93a3; }
  .row-thread { color: #6a7180; font-size: 11px; }
  .row-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .badge {
    display: inline-block; padding: 0 6px; border-radius: 3px;
    font-size: 11px; margin-left: 4px;
  }
  .badge-open { background: #3a3010; color: #e0c46a; }
  .badge-live { background: #123a2c; color: #6ae0a8; }
  .badge-elaborate { background: #3a1030; color: #e06ae0; }
  h1 { font-size: 14px; margin: 0 0 8px 0; }
  .field { margin-bottom: 12px; }
  .label { color: #6a7180; font-size: 11px; text-transform: uppercase; }
  pre {
    background: #1a1d24; padding: 8px; overflow-x: auto;
    white-space: pre-wrap; word-break: break-word;
  }
  button {
    background: #23262e; color: #d8dbe0; border: 1px solid #3a3d46;
    padding: 6px 10px; margin: 3px 4px 3px 0; cursor: pointer;
    font-family: inherit; font-size: 12px; border-radius: 3px;
  }
  button:hover { background: #2c2f38; }
  button.primary { background: #1e4d34; border-color: #2e7d54; }
  button.chosen { background: #1e3a5c; border-color: #2e6da4; }
  textarea, input[type=text] {
    width: 100%; background: #1a1d24; color: #d8dbe0;
    border: 1px solid #3a3d46; font-family: inherit; font-size: 12px;
    padding: 6px; margin-top: 4px;
  }
  #toast {
    position: fixed; bottom: 12px; right: 12px; max-width: 40vw;
  }
  .toast-item {
    background: #23262e; border: 1px solid #3a3d46; padding: 8px 10px;
    margin-top: 6px; border-radius: 4px; font-size: 12px;
  }
  .step { padding: 2px 0; }
  .verdict { padding: 4px 0; border-top: 1px dashed #2a2d34; }
  @media (max-width: 640px) {
    body { flex-direction: column; }
    #rail { width: 100%; max-width: 100%; height: 40vh; }
    #card { height: 60vh; }
  }
</style>
</head>
<body>
<div id="rail"></div>
<div id="card">select a row</div>
<div id="toast"></div>
<script>
"use strict";

let rows = [];
let selectedRef = null;
let lastKeys = new Set();
let multiPicked = new Set();

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast-item";
  el.textContent = text;
  document.getElementById("toast").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

function notifyArrival(newRows) {
  if (!newRows.length) return;
  for (const q of newRows) {
    toast("new: " + q.key);
  }
  if (window.Notification && Notification.permission === "granted") {
    for (const q of newRows) {
      new Notification("cactus " + q.key, { body: q.text.slice(0, 200) });
    }
  }
}

async function fetchFeed() {
  const res = await fetch("/api/feed");
  const doc = await res.json();
  const seen = new Set(doc.questions.map(q => q.ref));
  const fresh = doc.questions.filter(q => !lastKeys.has(q.ref));
  if (lastKeys.size > 0) notifyArrival(fresh);
  lastKeys = seen;

  const oldIndex = rows.findIndex(q => q.ref === selectedRef);
  rows = doc.questions;

  if (selectedRef && oldIndex >= 0 && !rows.find(q => q.ref === selectedRef)) {
    if (rows.length > 0) {
      const newIndex = Math.min(oldIndex, rows.length - 1);
      selectedRef = rows[newIndex].ref;
    } else {
      selectedRef = null;
    }
  }

  if (!selectedRef && rows.length > 0) {
    selectedRef = rows[0].ref;
  }

  render();
}

function groupByProject(list) {
  const groups = new Map();
  for (const q of list) {
    const label = q.ref.split(":")[0];
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(q);
  }
  return groups;
}

function badge(status) {
  return '<span class="badge badge-' + status + '">' + status + '</span>';
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function render() {
  const rail = document.getElementById("rail");
  rail.innerHTML = "";
  const groups = groupByProject(rows);
  for (const [label, items] of groups) {
    const head = document.createElement("div");
    head.className = "proj-head";
    head.textContent = label;
    rail.appendChild(head);
    for (const q of items) {
      const row = document.createElement("div");
      row.className = "row" + (q.ref === selectedRef ? " selected" : "");
      row.dataset.ref = q.ref;
      const indent = "  ".repeat(q.depth || 0);
      const thread = q.thread ? (q.agent || "?") + "/" + q.thread : "";
      row.innerHTML =
        '<div><span class="row-key">' + esc(indent + q.key) + '</span> ' +
        esc(q.act) + badge(q.status) + '</div>' +
        (thread ? '<div class="row-thread">' + esc(thread) + '</div>' : "") +
        '<div class="row-text">' + esc(q.text) + '</div>';
      row.onclick = () => { selectedRef = q.ref; render(); };
      rail.appendChild(row);
    }
  }
  if (!rows.length) rail.innerHTML = "<div style='padding:10px;color:#6a7180'>inbox empty</div>";
  renderCard();
}

function findSelected() {
  return rows.find(q => q.ref === selectedRef) || null;
}

function move(delta) {
  const flat = rows;
  if (!flat.length) return;
  let idx = flat.findIndex(q => q.ref === selectedRef);
  idx = idx < 0 ? 0 : Math.max(0, Math.min(flat.length - 1, idx + delta));
  selectedRef = flat[idx].ref;
  render();
}

function renderCard() {
  const card = document.getElementById("card");
  const q = findSelected();
  if (!q) { card.innerHTML = "select a row"; return; }
  multiPicked = new Set(q.recommend && q.kind === "multi" ? q.recommend : []);

  let html = "<h1>" + esc(q.ref) + " — " + esc(q.act) + badge(q.status) + "</h1>";
  html += '<div class="field"><div class="label">text</div>' + esc(q.text) + "</div>";
  if (q.context) {
    html += '<div class="field"><div class="label">context</div><pre>' + esc(q.context) + "</pre></div>";
  }
  if (q.act === "run" && q.review && q.review.run_cmd) {
    html += '<div class="field"><div class="label">command</div><pre>' + esc(q.review.run_cmd) + "</pre></div>";
  }
  if (q.result) {
    html += '<div class="field"><div class="label">result</div><pre>exit ' +
      esc(q.result.exit) + "\\n" + esc((q.result.tail || []).join("\\n")) + "</pre></div>";
  }

  if (q.act === "review" || q.act === "plan") {
    if (q.answers && q.answers.length) {
      html += '<div class="field"><div class="label">verdicts</div>';
      for (const a of q.answers) {
        html += '<div class="verdict">' + esc(a.created_at) + " — " +
          esc((a.selected || []).join(", ")) + (a.text ? " " + esc(a.text) : "") + "</div>";
      }
      html += "</div>";
    }
    if (q.steps && q.steps.length) {
      html += '<div class="field"><div class="label">steps</div>';
      for (const st of q.steps) {
        html += '<div class="step">[' + (st.done ? "x" : " ") + "] " + st.n + "  " + esc(st.text) + "</div>";
      }
      html += "</div>";
    }
  }

  const actionable = q.status === "open" || q.status === "live";
  if (actionable) {
    html += '<div class="field" id="choices"></div>';
    if (q.allow_free) {
      html += '<div class="field"><textarea id="freetext" rows="3" placeholder="free text"></textarea></div>';
    }
    html += '<div class="field">';
    html += '<button class="primary" onclick="submitAnswer()">Answer</button>';
    html += '<button onclick="submitSkip()">Skip</button>';
    html += '<button onclick="doClear()">Clear</button>';
    html += '<button onclick="doPoke()">Poke</button>';
    html += "</div>";
  } else if (q.status === "cleared") {
    html += '<div class="field"><button onclick="doReopen()">Reopen</button></div>';
  }
  if (q.status === "answered") {
    html += '<div class="field"><div class="label">answer</div>' +
      esc((q.answer && q.answer.selected || []).join(", ")) +
      (q.answer && q.answer.text ? " " + esc(q.answer.text) : "") + "</div>";
    html += '<div class="field"><button onclick="doReopen()">Reopen</button></div>';
  }

  html += '<div class="field"><button onclick="requestNotify()">enable notifications</button></div>';

  card.innerHTML = html;
  if (actionable) renderChoices(q);
}

function renderChoices(q) {
  const box = document.getElementById("choices");
  if (!box || !q.choices || !q.choices.length) return;
  const recommended = new Set(q.recommend || []);
  box.innerHTML = '<div class="label">choices</div>';
  for (const c of q.choices) {
    const btn = document.createElement("button");
    const isRec = recommended.has(c.label);
    btn.textContent = c.label + (c.description ? ": " + c.description : "") + (isRec ? " *" : "");
    btn.dataset.label = c.label;
    if (q.kind === "multi") {
      if (isRec) multiPicked.add(c.label);
      if (multiPicked.has(c.label)) btn.classList.add("chosen");
      btn.onclick = () => {
        if (multiPicked.has(c.label)) multiPicked.delete(c.label);
        else multiPicked.add(c.label);
        btn.classList.toggle("chosen");
      };
    } else {
      if (isRec) btn.classList.add("chosen");
      btn.onclick = () => {
        for (const b of box.querySelectorAll("button")) b.classList.remove("chosen");
        btn.classList.add("chosen");
        btn.dataset.picked = "1";
        box.dataset.picked = c.label;
      };
      if (isRec) box.dataset.picked = c.label;
    }
    box.appendChild(btn);
  }
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function currentSelection(q) {
  const box = document.getElementById("choices");
  if (!box) return [];
  if (q.kind === "multi") return Array.from(multiPicked);
  const picked = box.dataset.picked;
  return picked ? [picked] : [];
}

async function submitAnswer() {
  const q = findSelected();
  if (!q) return;
  const selected = currentSelection(q);
  const freeEl = document.getElementById("freetext");
  const text = freeEl ? freeEl.value : "";
  try {
    const data = await api("/api/answer", {
      key: q.key, project: q.project, selected, text, skipped: false,
    });
    toastPoke(data);
    await fetchFeed();
  } catch (e) { toast("error: " + e.message); }
}

async function submitSkip() {
  const q = findSelected();
  if (!q) return;
  try {
    const data = await api("/api/answer", { key: q.key, project: q.project, skipped: true });
    toastPoke(data);
    await fetchFeed();
  } catch (e) { toast("error: " + e.message); }
}

function toastPoke(data) {
  if (data.poked) toast("poked: " + data.poked);
  else if (data.poke_error) toast("poke failed: " + data.poke_error);
}

async function doClear() {
  const q = findSelected();
  if (!q) return;
  try { await api("/api/clear", { key: q.key, project: q.project }); await fetchFeed(); }
  catch (e) { toast("error: " + e.message); }
}

async function doReopen() {
  const q = findSelected();
  if (!q) return;
  try { await api("/api/reopen", { key: q.key, project: q.project }); await fetchFeed(); }
  catch (e) { toast("error: " + e.message); }
}

async function doPoke() {
  const q = findSelected();
  if (!q) return;
  try {
    const data = await api("/api/poke", { key: q.key, project: q.project });
    toast("poked: " + data.ran);
  } catch (e) { toast("error: " + e.message); }
}

function requestNotify() {
  if (window.Notification) Notification.requestPermission();
}

document.addEventListener("keydown", (ev) => {
  const tag = (ev.target && ev.target.tagName) || "";
  if (tag === "TEXTAREA" || tag === "INPUT") return;
  if (ev.key === "j") move(1);
  else if (ev.key === "k") move(-1);
  else if (ev.key === "Enter") submitAnswer();
});

function connectEvents() {
  try {
    const es = new EventSource("/api/events");
    es.addEventListener("change", fetchFeed);
    es.onerror = () => { es.close(); setTimeout(pollFallback, 500); };
  } catch (e) { pollFallback(); }
}

function pollFallback() {
  fetchFeed();
  setInterval(fetchFeed, 2000);
}

fetchFeed();
connectEvents();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "cactus-www/1"

    # Set on the server instance: db_path, project.

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 - silence per-request noise
        pass

    # ---- helpers ----------------------------------------------------------

    def _store(self) -> Store:
        """One Store per handler thread.

        `Store`'s sqlite3 connection is opened with the default
        check_same_thread=True, so a connection created on one thread cannot
        be reused on another — ThreadingHTTPServer hands each request its own
        thread. Every thread keeps its own connection instead, exactly like
        two separate cactus processes sharing the database over WAL already
        do; the store's own locking (BEGIN IMMEDIATE for writes) is what
        keeps them consistent, not a lock in this module.
        """
        local: threading.local = self.server.local  # type: ignore[attr-defined]
        store = getattr(local, "store", None)
        if store is None:
            store = Store(self.server.db_path)  # type: ignore[attr-defined]
            local.store = store
        return store

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, (ValueError, KeyError, AlreadyAnswered, PokeError)):
            self._send_json(400, {"error": _msg(exc)})
        else:
            self._send_json(500, {"error": _msg(exc)})

    # ---- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        try:
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html(PAGE)
            elif self.path.startswith("/api/feed"):
                self._handle_feed()
            elif self.path.startswith("/api/events"):
                self._handle_events()
            else:
                self._send_json(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the client
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/answer":
                self._handle_answer()
            elif self.path == "/api/clear":
                self._handle_clear()
            elif self.path == "/api/reopen":
                self._handle_reopen()
            elif self.path == "/api/poke":
                self._handle_poke()
            else:
                self._send_json(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    # ---- handlers -----------------------------------------------------------

    def _handle_feed(self) -> None:
        store = self._store()
        project = self.server.project  # type: ignore[attr-defined]
        items = _questions(store, project)
        cursor = store.cursor()
        docs = []
        for q in items:
            d = q.as_dict()
            d["depth"] = q.depth
            docs.append(d)
        self._send_json(200, {"cursor": list(cursor), "questions": docs})

    def _handle_events(self) -> None:
        store = self._store()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = store.cursor()
        last_ping = time.monotonic()
        try:
            while True:
                time.sleep(POLL_INTERVAL)
                cursor = store.cursor()
                if cursor != last:
                    last = cursor
                    payload = json.dumps({"cursor": list(cursor)})
                    self.wfile.write(f"event: change\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping >= PING_INTERVAL:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_answer(self) -> None:
        store = self._store()
        body = self._read_json()
        key = body.get("key")
        project = body.get("project")
        if not key:
            self._send_json(400, {"error": "key is required"})
            return
        q = store.answer(
            key,
            project=project,
            selected=body.get("selected") or [],
            text=body.get("text"),
            skipped=bool(body.get("skipped")),
        )
        poked: str | None = None
        poke_error: str | None = None
        try:
            poked = wake_owner(q.agent, q.pane, key=q.key, event="answered")
        except PokeError as exc:
            poke_error = _msg(exc)
        result = q.as_dict()
        result["poked"] = poked
        result["poke_error"] = poke_error
        self._send_json(200, result)

    def _handle_clear(self) -> None:
        store = self._store()
        body = self._read_json()
        key = body.get("key")
        project = body.get("project")
        if not key:
            self._send_json(400, {"error": "key is required"})
            return
        # Human-initiated, same as the TUI's `c` — keep the default
        # record=True so the clear writes a decision record.
        n = store.clear(keys=[key], project=project)
        self._send_json(200, {"cleared": n})

    def _handle_reopen(self) -> None:
        store = self._store()
        body = self._read_json()
        key = body.get("key")
        project = body.get("project")
        if not key:
            self._send_json(400, {"error": "key is required"})
            return
        q = store.reopen(key, project=project)
        self._send_json(200, q.as_dict())

    def _handle_poke(self) -> None:
        store = self._store()
        body = self._read_json()
        key = body.get("key")
        project = body.get("project")
        if not key:
            self._send_json(400, {"error": "key is required"})
            return
        q = store.get(key, project=project)
        if q is None:
            self._send_json(400, {"error": f"no such question: {key}"})
            return
        agent = q.agent
        try:
            ran = poke(agent, pane=q.pane)
        except PokeError as exc:
            self._send_json(400, {"error": _msg(exc)})
            return
        self._send_json(200, {"agent": agent, "ran": ran})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], db_path: Any, project: str | None) -> None:
        super().__init__(addr, _Handler)
        self.db_path = db_path
        self.project = project
        # Each handler thread opens its own Store (see _Handler._store) since
        # a sqlite3 connection cannot cross threads; this holds those.
        self.local = threading.local()


def run_www(
    store: Store,
    project: str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8642,
    open_browser: bool = False,
) -> int:
    """Serve the web answering surface. Returns a process exit code.

    `store` is only used for its path: every request is served from a
    thread-local Store opened on that same path (see _Handler._store), since
    a sqlite3 connection cannot be shared across threads. The caller's own
    `store` is left open and closed by `cli.main`'s `finally`, same as every
    other surface.
    """
    server = _Server((host, port), store.path, project)
    url = f"http://{host}:{port}"
    print(f"cactus: www on {url}", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
