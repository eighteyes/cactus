"""
mcp.py — Model Context Protocol server exposing cactus to MCP clients such as
Claude Desktop.

Responsibilities:
- Speak MCP over stdio: newline-delimited JSON-RPC 2.0, handling initialize,
  ping, tools/list and tools/call with no third-party dependency.
- Map each tool to one `cactus` CLI invocation run as a subprocess with
  `--json`, so validation, exit codes and ownership rules stay in cli.py.
- Supply a default agent identity and project scope from the environment,
  since an MCP host has neither a herdr pane nor a meaningful working directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .store import default_db_path

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_AGENT = "claude-desktop"
# Longest a single tool call may block. MCP hosts cap a call at about a
# minute; a `wait` past that reads as a hang, so the server clamps it and the
# client calls again. CACTUS_MCP_MAX_WAIT overrides it.
MAX_WAIT = 50.0
# Slack past the wait for the subprocess itself to start and exit.
SUBPROCESS_GRACE = 15.0

# Exit codes mirrored from cli.py; imported lazily there to keep startup cheap.
EXIT_OK, EXIT_ERROR, EXIT_TIMEOUT, EXIT_EMPTY = 0, 1, 2, 3

INSTRUCTIONS = """\
cactus is a durable question inbox between you and the human. Post a decision
with cactus_ask (one choice per direction, recommend when you have a pick),
keep working, and read the answer with cactus_get when you reach the fork.
The human answers in their own cactus TUI or web board on their own schedule.

Rules:
- Every row is filed under a project directory. Pass `project` (absolute path
  of the repository) whenever the question belongs to one; otherwise the
  server's default project is used.
- Prefer cactus_ask with act "steer" and `chosen` when you will proceed anyway
  and only need a veto. Use `wait` only when the very next step depends on the
  answer, and keep `timeout` under 50 seconds per call; call cactus_get again
  to keep waiting.
- Put the numbers, what you tried, what each option costs and the default if
  nobody answers in `context`. Never restate the question there.
- Clear your own rows with cactus_clear once you have acted on them.
- A `skipped` answer means the human declined to decide: act on your default.
"""


# ---- subprocess bridge ----------------------------------------------------


def _default_agent() -> str:
    return os.environ.get("CACTUS_AGENT") or DEFAULT_AGENT


def _default_project() -> str:
    return os.environ.get("CACTUS_PROJECT") or str(Path.home())


def _max_wait() -> float:
    try:
        return float(os.environ.get("CACTUS_MCP_MAX_WAIT") or MAX_WAIT)
    except ValueError:
        return MAX_WAIT


def _log_path() -> str | None:
    """Where request lines go: $CACTUS_MCP_LOG, else mcp.log beside the
    database; "0" or "" turns it off. A host shows no server stderr, so
    this file is the only trace of what reached the server."""
    raw = os.environ.get("CACTUS_MCP_LOG")
    if raw is None:
        return str(default_db_path().parent / "mcp.log")
    return raw if raw not in ("", "0") else None


def _log(line: str) -> None:
    """Append one timestamped line to the request log; never raises."""
    path = _log_path()
    if not path:
        return
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} [{os.getpid()}] {line.rstrip(chr(10))}\n")
    except (OSError, ValueError):
        pass


def _run(argv: list[str], *, project: str | None, agent: str | None = None,
         wait: float | None = None) -> dict[str, Any]:
    """Run one cactus verb and shape its outcome for a tool result.

    Exit 0 returns the parsed JSON (or raw text). Exit 3 is an empty match,
    not an error. Exit 2 is a --wait timeout, reported as such. Exit 1 is an
    error carrying the CLI's stderr line. `wait` is the --timeout the argv
    carries, so the hard subprocess limit can sit just past it.
    """
    cwd = project or _default_project()
    if not Path(cwd).is_dir():
        return {"is_error": True, "text": f"cactus: project directory not found: {cwd}"}
    env = dict(os.environ)
    env.setdefault("CACTUS_AGENT", agent or _default_agent())
    limit = (wait or 0.0) + SUBPROCESS_GRACE
    _log(f"run cwd={cwd} limit={limit:.0f}s argv={argv!r}")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "cactus", "--json", *argv],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=limit,
        )
    except subprocess.TimeoutExpired:
        _log("run killed: subprocess exceeded its limit")
        return {"is_error": True, "text": f"cactus: verb did not finish within {limit:.0f}s and was killed"}
    except OSError as exc:
        return {"is_error": True, "text": f"cactus: could not start subprocess: {exc}"}
    _log(f"run exit={proc.returncode}")
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    if proc.returncode == EXIT_OK:
        return {"is_error": False, "text": out or err or "ok"}
    if proc.returncode == EXIT_EMPTY:
        return {"is_error": False, "text": json.dumps({"match": False, "note": err or "no match"})}
    if proc.returncode == EXIT_TIMEOUT:
        return {"is_error": False, "text": json.dumps({"timeout": True, "note": "no answer yet; call cactus_get again to keep waiting"})}
    return {"is_error": True, "text": err or out or f"cactus: exit {proc.returncode}"}


# ---- tool table -----------------------------------------------------------


def _prop(kind: str, desc: str, **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"type": kind, "description": desc}
    d.update(extra)
    return d


_STR_LIST = {"type": "array", "items": {"type": "string"}}

_PROJECT = _prop("string", "Absolute path of the repository the row belongs to. Defaults to the server's CACTUS_PROJECT.")
_AGENT = _prop("string", "Owner identity for the row. Defaults to the server's CACTUS_AGENT.")
_KEY = _prop("string", "Row key: qN in the project, or LABEL:qN / /abs/path:qN for another project.")
_KEYS = {**_STR_LIST, "description": "Row keys: qN in the project, or LABEL:qN / /abs/path:qN for another project."}


def _tool(name: str, description: str, props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": {**props, "project": _PROJECT}}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS: list[dict[str, Any]] = [
    _tool(
        "cactus_ask",
        "Post a decision to the human's inbox and return its key. Does not block unless `wait` is set. "
        "Give two or three choices, one per direction, each 'label: description'. "
        "act 'data' rows take chunks as choices (label: body) and are copied by the human, not answered.",
        {
            "text": _prop("string", "The question, plainly."),
            "choices": {**_STR_LIST, "description": "Choices as 'label: description'; split on the first colon. Omit for a free-text question."},
            "files": {**_STR_LIST, "description": "File paths the human may preview or edit from the TUI."},
            "act": _prop("string", "What is being asked for.", enum=["ask", "steer", "notify", "review", "plan", "data"]),
            "kind": _prop("string", "Answer shape override; inferred from choices and flags otherwise.", enum=["choice", "multi", "text", "confirm"]),
            "multi": _prop("boolean", "Allow selecting several choices."),
            "confirm": _prop("boolean", "Yes/no question."),
            "context": _prop("string", "What the human cannot see from the labels: what you tried, the numbers, what each option costs, the default if unanswered."),
            "thread": _prop("string", "Group under a named thread."),
            "parent": _prop("string", "Attach as a follow-up to this row key."),
            "recommend": {**_STR_LIST, "description": "Recommended choice label(s); more than one only with multi. Requires confidence."},
            "confidence": _prop("string", "Required with recommend.", enum=["low", "med", "high"]),
            "why": _prop("string", "Why the recommendation."),
            "chosen": _prop("string", "steer only: the option you are proceeding with."),
            "blocked": _prop("boolean", "Whether the row blocks you (default follows the act)."),
            "no_free": _prop("boolean", "Refuse free text; choices only."),
            "word": _prop("string", "Short stable board label, 16 chars max."),
            "title": _prop("string", "Button label, 60 chars max."),
            "wait": _prop("boolean", "Block until answered. Pair with timeout under 50 seconds."),
            "timeout": _prop("number", "Seconds to wait with `wait`."),
            "agent": _AGENT,
        },
        ["text"],
    ),
    _tool(
        "cactus_run",
        "Post a shell command for the human to approve before it runs. Returns the key; read the row with cactus_get. "
        "A non-null `result` after approve means the human already ran it; null means run it yourself.",
        {
            "command": _prop("string", "The command, verbatim."),
            "why": _prop("string", "Why it is needed; becomes the row context."),
            "cwd": _prop("string", "Directory to run in."),
            "thread": _prop("string", "Group under a named thread."),
            "recommend": _prop("string", "Your pick.", enum=["approve", "deny"]),
            "confidence": _prop("string", "Required with recommend.", enum=["low", "med", "high"]),
            "agent": _AGENT,
        },
        ["command"],
    ),
    _tool(
        "cactus_get",
        "Read rows by key. With `wait`, block until the first key leaves open (answered, skipped, cleared) or timeout.",
        {
            "keys": _KEYS,
            "wait": _prop("boolean", "Block until answered."),
            "timeout": _prop("number", "Seconds to wait with `wait`; keep under 50 and call again."),
            "answered_only": _prop("boolean", "Only rows that carry an answer."),
            "all": _prop("boolean", "Search every project, not just this one."),
        },
        ["keys"],
    ),
    _tool(
        "cactus_list",
        "List rows in the project, filtered by status, thread, act or agent.",
        {
            "status": _prop("string", "Comma-separated statuses. Default open,live,elaborate."),
            "thread": _prop("string", "Only this thread."),
            "act": {**_STR_LIST, "description": "Only these acts."},
            "agent": _prop("string", "Only rows owned by this agent."),
            "all": _prop("boolean", "Span every project."),
        },
    ),
    _tool(
        "cactus_feed",
        "The actionable inbox as one JSON document: open, live and elaborate rows plus a cursor with the blocked count.",
        {
            "status": _prop("string", "Comma-separated statuses. Default open,live,elaborate."),
            "thread": _prop("string", "Only this thread."),
            "act": {**_STR_LIST, "description": "Only these acts."},
            "agent": _prop("string", "Only rows owned by this agent."),
            "here": _prop("boolean", "Only this project; the feed spans all projects by default."),
        },
    ),
    _tool(
        "cactus_answer",
        "Answer a row on the human's behalf. Only use when the human asked you to record their decision in this conversation.",
        {
            "key": _KEY,
            "select": {**_STR_LIST, "description": "Choice label(s) to select."},
            "text": _prop("string", "Free-text answer."),
            "skip": _prop("boolean", "Mark seen without deciding."),
            "dismiss": _prop("boolean", "Dismiss a notify/notice row."),
        },
        ["key"],
    ),
    _tool(
        "cactus_edit",
        "Rewrite an open, live or elaborate row you own in place; the key stays. `choices` replaces the whole list.",
        {
            "key": _KEY,
            "text": _prop("string", "New question text."),
            "context": _prop("string", "New context."),
            "choices": {**_STR_LIST, "description": "Replacement choices as 'label: description'."},
            "files": {**_STR_LIST, "description": "Replacement file paths; replaces the whole list."},
            "agent": _AGENT,
        },
        ["key"],
    ),
    _tool(
        "cactus_review",
        "Attach or update a verify block on a row: what to look at, a command, pass and fail conditions, what to do next. Omitted fields keep their value.",
        {
            "key": _KEY,
            "look_at": _prop("string", "What the human inspects."),
            "run": _prop("string", "Command the human runs; empty string clears it."),
            "pass_when": _prop("string", "What a good result looks like."),
            "fail_when": _prop("string", "What disqualifies it."),
            "then": _prop("string", "What to set up next."),
            "files": {**_STR_LIST, "description": "Replacement file paths; replaces the whole list; omit to keep it."},
            "agent": _prop("string", "If given, refuses when the row is owned by a different agent."),
        },
        ["key"],
    ),
    _tool(
        "cactus_plan",
        "Append steps to a plan row, or mark a 1-based step done or undone. `reset_steps` replaces the list.",
        {
            "key": _KEY,
            "steps": {**_STR_LIST, "description": "Step texts to append."},
            "reset_steps": _prop("boolean", "Replace the list with `steps` and clear every done flag."),
            "done": _prop("integer", "1-based step number to tick."),
            "undone": _prop("integer", "1-based step number to untick."),
            "files": {**_STR_LIST, "description": "Replacement file paths; replaces the whole list; omit to keep it."},
            "agent": _prop("string", "If given, refuses when the row is owned by a different agent."),
        },
        ["key"],
    ),
    _tool(
        "cactus_clear",
        "Retire rows you own, by key or by thread. Keeps the transcript unless `purge`.",
        {
            "keys": _KEYS,
            "thread": _prop("string", "Retire every row of yours in this thread."),
            "here": _prop("boolean", "Retire every row of yours in this project."),
            "purge": _prop("boolean", "Delete instead of retire."),
            "agent": _AGENT,
        },
    ),
    _tool(
        "cactus_reopen",
        "Move a cleared row you own back onto the board.",
        {"keys": _KEYS, "agent": _AGENT},
        ["keys"],
    ),
    _tool("cactus_threads", "Thread names in the project with their row counts.", {}),
    _tool("cactus_projects", "Every project with rows, with open counts.", {}),
    _tool("cactus_where", "The project the next row would be filed under, and the database path.", {}),
    _tool("cactus_help", "The full agent-facing cactus reference: verbs, acts, options, events, exit codes.", {}),
]


# ---- argv builders --------------------------------------------------------


def _flag(argv: list[str], name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            argv.append(name)
        return
    argv.extend([name, str(value)])


def _repeat(argv: list[str], name: str, values: Any) -> None:
    for v in values or []:
        argv.extend([name, str(v)])


def _clamp_wait(a: dict[str, Any]) -> float | None:
    """The --timeout to pass for a `wait` call: the caller's, clamped to the cap.

    A `wait` with no timeout would block the CLI forever, and an MCP host
    reads that as a hung tool. So every wait gets a timeout.
    """
    if not a.get("wait"):
        return None
    cap = _max_wait()
    try:
        asked = float(a.get("timeout")) if a.get("timeout") is not None else cap
    except (TypeError, ValueError):
        asked = cap
    return max(0.0, min(asked, cap))


def _argv_for(name: str, a: dict[str, Any]) -> list[str] | None:
    """Translate tool arguments into a cactus argv, or None for a tool with no CLI verb."""
    argv: list[str] = []
    if name == "cactus_ask":
        argv = ["ask", a["text"], "--agent", a.get("agent") or _default_agent()]
        _repeat(argv, "-c", a.get("choices"))
        _repeat(argv, "-f", a.get("files"))
        _flag(argv, "--act", a.get("act"))
        _flag(argv, "--kind", a.get("kind"))
        _flag(argv, "--multi", a.get("multi"))
        _flag(argv, "--confirm", a.get("confirm"))
        _flag(argv, "--context", a.get("context"))
        _flag(argv, "-t", a.get("thread"))
        _flag(argv, "-p", a.get("parent"))
        _repeat(argv, "--recommend", a.get("recommend"))
        _flag(argv, "--confidence", a.get("confidence"))
        _flag(argv, "--why", a.get("why"))
        _flag(argv, "--chosen", a.get("chosen"))
        if a.get("blocked") is True:
            argv.append("--blocked")
        elif a.get("blocked") is False:
            argv.append("--no-block")
        _flag(argv, "--no-free", a.get("no_free"))
        _flag(argv, "--word", a.get("word"))
        _flag(argv, "--title", a.get("title"))
        _flag(argv, "--wait", a.get("wait"))
        # The CLI waits by default; an MCP call waits only when `wait` is set.
        _flag(argv, "--no-wait", not a.get("wait"))
        _flag(argv, "--timeout", _clamp_wait(a))
    elif name == "cactus_run":
        argv = ["run", a["command"], "--agent", a.get("agent") or _default_agent()]
        _flag(argv, "--why", a.get("why"))
        _flag(argv, "--cwd", a.get("cwd"))
        _flag(argv, "-t", a.get("thread"))
        _flag(argv, "--recommend", a.get("recommend"))
        _flag(argv, "--confidence", a.get("confidence"))
        _flag(argv, "--no-wait", True)
    elif name == "cactus_get":
        argv = ["get", *a["keys"]]
        _flag(argv, "--wait", a.get("wait"))
        _flag(argv, "--timeout", _clamp_wait(a))
        _flag(argv, "--answered-only", a.get("answered_only"))
        _flag(argv, "--all", a.get("all"))
    elif name == "cactus_list":
        argv = ["list"]
        _flag(argv, "-s", a.get("status"))
        _flag(argv, "-t", a.get("thread"))
        _repeat(argv, "--act", a.get("act"))
        _flag(argv, "--agent", a.get("agent"))
        _flag(argv, "--all", a.get("all"))
    elif name == "cactus_feed":
        argv = ["feed"]
        _flag(argv, "-s", a.get("status"))
        _flag(argv, "-t", a.get("thread"))
        _repeat(argv, "--act", a.get("act"))
        _flag(argv, "--agent", a.get("agent"))
        _flag(argv, "--here", a.get("here"))
    elif name == "cactus_answer":
        argv = ["answer", a["key"]]
        _repeat(argv, "-s", a.get("select"))
        _flag(argv, "--skip", a.get("skip"))
        _flag(argv, "--dismiss", a.get("dismiss"))
        if a.get("text"):
            argv.append(a["text"])
    elif name == "cactus_edit":
        argv = ["edit", a["key"], "--agent", a.get("agent") or _default_agent()]
        _flag(argv, "--text", a.get("text"))
        _flag(argv, "--context", a.get("context"))
        _repeat(argv, "-c", a.get("choices"))
        _repeat(argv, "-f", a.get("files"))
    elif name == "cactus_review":
        argv = ["review", a["key"]]
        _flag(argv, "--look-at", a.get("look_at"))
        _flag(argv, "--run", a.get("run"))
        _flag(argv, "--pass", a.get("pass_when"))
        _flag(argv, "--fail", a.get("fail_when"))
        _flag(argv, "--then", a.get("then"))
        _repeat(argv, "-f", a.get("files"))
        _flag(argv, "--agent", a.get("agent"))
    elif name == "cactus_plan":
        argv = ["plan", a["key"]]
        _repeat(argv, "--step", a.get("steps"))
        _flag(argv, "--reset-steps", a.get("reset_steps"))
        _flag(argv, "--done", a.get("done"))
        _flag(argv, "--undone", a.get("undone"))
        _repeat(argv, "-f", a.get("files"))
        _flag(argv, "--agent", a.get("agent"))
    elif name == "cactus_clear":
        argv = ["clear", *(a.get("keys") or []), "--agent", a.get("agent") or _default_agent()]
        _flag(argv, "-t", a.get("thread"))
        _flag(argv, "--here", a.get("here"))
        _flag(argv, "--purge", a.get("purge"))
    elif name == "cactus_reopen":
        argv = ["reopen", *a["keys"], "--agent", a.get("agent") or _default_agent()]
    elif name == "cactus_threads":
        argv = ["threads"]
    elif name == "cactus_projects":
        argv = ["projects"]
    elif name == "cactus_where":
        argv = ["where"]
    else:
        return None
    return argv


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool and return an MCP CallToolResult body."""
    if name == "cactus_help":
        from .cli import AGENT_HELP
        return {"content": [{"type": "text", "text": AGENT_HELP}], "isError": False}
    argv = _argv_for(name, arguments)
    if argv is None:
        return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
    outcome = _run(argv, project=arguments.get("project"), agent=arguments.get("agent"),
                   wait=_clamp_wait(arguments))
    return {"content": [{"type": "text", "text": outcome["text"]}], "isError": outcome["is_error"]}


# ---- JSON-RPC over stdio --------------------------------------------------


def _reply(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: Any) -> dict[str, Any] | None:
    """Dispatch one request; a notification (no id) returns None."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request: expected a JSON object")
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    _log(f"<- {method} id={msg_id!r}")
    if method == "initialize":
        return _reply(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "cactus", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _reply(msg_id, {})
    if method == "tools/list":
        return _reply(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            return _reply(msg_id, call_tool(name, args))
        except KeyError as exc:
            return _reply(msg_id, {"content": [{"type": "text", "text": f"missing argument: {exc.args[0]}"}], "isError": True})
    if msg_id is None:
        return None
    return _error(msg_id, -32601, f"method not found: {method}")


def _emit(stdout, out: dict[str, Any] | None) -> bool:
    """Write one reply; False when the host has closed the pipe."""
    if out is None:
        return True
    try:
        stdout.write(json.dumps(out) + "\n")
        stdout.flush()
    except BrokenPipeError:
        _log("serve end: host closed stdout")
        return False
    return True


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

    One bad message never ends the loop: a parse error, a batch (a JSON
    array, answered element by element), or an exception inside a handler
    each produce an error reply for that message, and the next line is read.
    A silent exit here would look to the host exactly like a hung server.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    _log("serve start")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            if not _emit(stdout, _error(None, -32700, "parse error")):
                return 0
            continue
        for one in (msg if isinstance(msg, list) else [msg]):
            try:
                out = handle(one)
            except Exception as exc:  # noqa: BLE001 - keep serving whatever broke
                _log(f"handler error: {exc!r}")
                msg_id = one.get("id") if isinstance(one, dict) else None
                out = _error(msg_id, -32603, f"internal error: {exc}")
            if not _emit(stdout, out):
                return 0
    _log("serve end: stdin closed")
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    sys.exit(main())
