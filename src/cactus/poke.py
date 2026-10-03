"""
poke.py — nudge the agent that owns a row to re-read its feed.

Responsibilities:
- Resolve the poke transport for one agent id (question-level).
- Default to herdr's agent prompt verb.
- If that agent is listed in the webhook map, POST the wake URL instead.
- CACTUS_POKE still overrides everything (tests / one-shot transports).
- After an answer, deliver to agents that declared a delivery entry: a webhook
  or `{"herdr": true}` (`cactus deliver`). Unregistered agents are never poked.
- Read and write that per-agent delivery map (atomic write, other entries kept).
- Report a usable failure when a row has no owner or the transport is absent.
- Visit: focus the herdr pane a row was asked from ($CACTUS_VISIT overrides).
- Pin herdr to the row's own session (`herdr --session S`): a pane id only
  names a pane inside one session.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# A poke carries no instruction. It tells an agent that the inbox moved and lets
# the agent decide what that means, which keeps the human out of the business of
# composing prompts and keeps cactus out of the business of driving agents.
DEFAULT_MESSAGE = (
    "cactus: your inbox moved — re-read it with `cactus feed --json "
    "--agent {agent}` and act on what changed."
)

# What a herdr-registered agent is told after an answer.
ANSWERED_MESSAGE = (
    "cactus: a row was answered — read it with `cactus feed --json "
    "--agent {agent}`."
)

# herdr resolves a prompt target by pane id (`w3B:p3`), never by the
# conversation id cactus uses as an owner, so the default transport prompts
# the pane stamped on the row. `{target}` is the pane when the row has one,
# else the agent id; `{agent}` stays the owner for templates that route on it.
DEFAULT_COMMAND = "herdr agent prompt {target} {message}"

# Visiting jumps the human's herdr view to the pane that asked. Pane ids are
# valid `herdr agent` targets. CACTUS_VISIT overrides it, with `{pane}`
# substituted per argument, so tests can point it somewhere inert.
DEFAULT_VISIT_COMMAND = "herdr agent focus {pane}"


def _herdr_argv(command: str, session: str | None) -> list[str]:
    """Split a default herdr command, pinned to `session` when the row has
    one. A pane id is only unique inside its session, and herdr's own pick
    (`HERDR_SOCKET_PATH`, else its default session) is whatever the caller
    happens to run under: a TUI outside herdr, or in another session, gets
    `agent_not_found`. `--session` beats both."""
    argv = shlex.split(command)
    if session and argv and argv[0] == "herdr":
        argv[1:1] = ["--session", session]
    return argv

DEFAULT_WEBHOOKS_PATH = Path("~/.config/cactus/poke-webhooks.json").expanduser()

# The default transport really does prompt a live agent. `cactus ask` requires
# --agent and never falls back to a pane id, so a row's owner is whatever the
# asking session declared — but that is still a live agent once poked.
# Anything exercising poke must set CACTUS_POKE to something inert first, or
# the test pokes the person running it.


class PokeError(RuntimeError):
    """A poke that could not be delivered, with a reason worth showing a human."""


def webhooks_path() -> Path:
    """Path to the agent→webhook map (JSON object keyed by agent id)."""
    override = os.environ.get("CACTUS_POKE_WEBHOOKS")
    return Path(override).expanduser() if override else DEFAULT_WEBHOOKS_PATH


def load_webhooks() -> dict[str, Any]:
    """Return the webhook map, or {} when the file is missing/empty."""
    path = webhooks_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Usually a hand edit (trailing comma). Every answer path (CLI, TUI,
        # www) then warns "webhook poke failed" on any agent, and `cactus
        # deliver` refuses to write until the file parses again.
        raise PokeError(f"cannot read webhook map {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PokeError(f"webhook map {path} must be a JSON object keyed by agent id")
    return data


def delivery_entry(agent: str) -> dict[str, Any] | None:
    """The raw delivery-map entry for `agent` (webhook or herdr), or None."""
    entry = load_webhooks().get(agent)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise PokeError(f"webhook map entry for {agent!r} must be an object")
    return entry


def is_herdr_entry(entry: dict[str, Any] | None) -> bool:
    """A `{"herdr": true}` entry: deliver by prompting the row's herdr pane."""
    # An entry carrying both is a webhook: `url` wins, so a stale herdr flag
    # left beside a URL never reroutes delivery to a pane.
    return bool(entry) and entry.get("herdr") is True and "url" not in entry


def webhook_entry(agent: str) -> dict[str, Any] | None:
    """Webhook config for `agent`, or None when unmapped or herdr-registered."""
    entry = delivery_entry(agent)
    if entry is None or is_herdr_entry(entry):
        return None
    return entry


def write_delivery(agent: str, entry: dict[str, Any] | None) -> None:
    """Set (or, with None, remove) one agent's entry in the delivery map.

    Other agents' entries and unknown keys are kept. The file is replaced
    atomically (temp file in the same directory, then rename) and its parent
    directory is created.
    """
    path = webhooks_path()
    data = load_webhooks()
    if entry is None:
        data.pop(agent, None)
    else:
        data[agent] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid-suffixed temp + os.replace: a reader never sees a half-written map.
    # Not locked: two concurrent writers race and the last rename wins.
    # 0600 because an entry may carry an Authorization header.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def deliver_if_mapped(
    agent: str | None,
    *,
    pane: str | None = None,
    session: str | None = None,
    message: str | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Deliver an answer to an agent that declared a delivery entry.

    A webhook entry POSTs as before. A `{"herdr": true}` entry prompts the
    row's `pane` through the normal poke transport (CACTUS_POKE overrides it);
    with no pane there is nothing to prompt and it is skipped silently.
    Unregistered agents return None and are not poked.

    The webhook branch ignores CACTUS_POKE: that override is for explicit
    `cactus poke` / tests, not for silently replacing the webhook.
    """
    if not agent:
        return None
    entry = delivery_entry(agent)
    if entry is None:
        return None
    if is_herdr_entry(entry):
        # A row posted outside herdr has no pane; herdr cannot prompt an
        # agent id (see DEFAULT_COMMAND), so skip rather than fail the answer.
        if not pane:
            return None
        body = message or ANSWERED_MESSAGE.format(agent=agent)
        # webhook=False: this entry has no url, so poke's webhook step must
        # not see it; CACTUS_POKE still overrides, which keeps tests inert.
        return poke(agent, pane=pane, session=session, message=body,
                    timeout=timeout, webhook=False)
    body = message or DEFAULT_MESSAGE.format(agent=agent)
    return _post_webhook(agent, body, entry, timeout)


# Kept so callers and tests written against the webhook-only name still work.
poke_webhook_if_mapped = deliver_if_mapped


def poke_command() -> list[str]:
    """The configured override transport, as an argv template.

    CACTUS_POKE overrides per-agent routing entirely. The template is split with
    shlex and the {agent} and {message} tokens are substituted per-argument
    afterwards, so neither a pane id nor a message body is ever handed to a shell.
    """
    return shlex.split(os.environ.get("CACTUS_POKE") or DEFAULT_COMMAND)


def _post_webhook(agent: str, body: str, entry: dict[str, Any], timeout: float) -> str:
    """POST JSON {agent, message} to the mapped webhook URL."""
    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        raise PokeError(f"webhook map entry for {agent!r} needs a string url")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    auth = entry.get("authorization") or entry.get("Authorization")
    if isinstance(auth, str) and auth.strip():
        headers["Authorization"] = auth.strip()
    extra = entry.get("headers")
    if isinstance(extra, dict):
        for key, value in extra.items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value

    payload = json.dumps({"agent": agent, "message": body}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            status = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as exc:
        detail = (exc.read() or b"").decode("utf-8", errors="replace").strip()
        tail = detail.splitlines()[-1] if detail else exc.reason
        raise PokeError(f"webhook HTTP {exc.code}: {tail}") from exc
    except urllib.error.URLError as exc:
        raise PokeError(f"webhook failed: {exc.reason}") from exc

    return f"webhook POST {url} ({status})"


# Where a user-installed transport lives when the poking process did not start
# from a login shell: a TUI under launchd, a web board under a service manager.
# Those inherit /usr/bin:/bin:/usr/sbin:/sbin and nothing the user added.
FALLBACK_BIN_DIRS = (
    Path("~/.local/bin").expanduser(),
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def resolve_executable(name: str) -> str | None:
    """Absolute path for `name`: PATH first, then the usual user bin dirs.

    A bare name that PATH cannot find is retried in FALLBACK_BIN_DIRS, so a
    poke from a process with a stripped PATH still reaches a transport the
    user installed. A name with a slash is taken as given.
    """
    found = shutil.which(name)
    if found:
        return found
    if os.sep in name:
        return None
    for directory in FALLBACK_BIN_DIRS:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run_argv(argv: list[str], timeout: float, env_name: str = "CACTUS_POKE") -> str:
    # Failures surface verbatim to the human (TUI flash, CLI stderr). A
    # missing herdr under launchd means PATH is stripped and herdr lives
    # outside FALLBACK_BIN_DIRS: set CACTUS_POKE/CACTUS_VISIT to its full path.
    if not argv:
        raise PokeError(f"{env_name} is empty")
    exe = resolve_executable(argv[0])
    if exe is None:
        dirs = ", ".join(str(d) for d in FALLBACK_BIN_DIRS)
        raise PokeError(
            f"{argv[0]} is not on PATH or in {dirs}; set {env_name} to a transport"
        )
    argv = [exe, *argv[1:]]

    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise PokeError(f"{argv[0]} timed out after {timeout:g}s") from exc

    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {done.returncode}"
        raise PokeError(f"{argv[0]}: {tail}")

    return " ".join(shlex.quote(a) for a in argv)


def poke(
    agent: str | None,
    *,
    pane: str | None = None,
    session: str | None = None,
    message: str | None = None,
    timeout: float = 10.0,
    webhook: bool = True,
) -> str:
    """Deliver a nudge to `agent`, at `pane` when the default transport needs one.

    Returns a short description of what ran. Raises PokeError when the row has
    no owner, the transport is missing, or the default transport has no pane
    to prompt — all situations a human can fix, so they are reported rather
    than swallowed.

    Resolution order:
    1. CACTUS_POKE override (tests / forced transport) — same for every agent
    2. Webhook map entry for this agent id (CACTUS_POKE_WEBHOOKS /
       ~/.config/cactus/poke-webhooks.json)
    3. Default herdr agent prompt, targeting the row's pane stamp in its
       herdr `session` (`{session}` in an override template)

    `webhook=False` skips step 2 (a project-wide poke is herdr only).
    """
    if not agent:
        raise PokeError("this row has no agent; nothing to poke")

    body = message or DEFAULT_MESSAGE.format(agent=agent)
    target = pane or agent

    def fill(template: list[str]) -> list[str]:
        return [
            part.replace("{agent}", agent).replace("{target}", target)
            .replace("{session}", session or "").replace("{message}", body)
            for part in template
        ]

    # The override wins before the webhook map is read, so a malformed map
    # cannot break a test or a forced transport.
    if os.environ.get("CACTUS_POKE"):
        return _run_argv(fill(poke_command()), timeout)

    entry = webhook_entry(agent) if webhook else None
    if entry is not None:
        return _post_webhook(agent, body, entry, timeout)

    if not pane:
        raise PokeError(
            f"herdr prompts a pane and {agent} has no pane stamp; poke by KEY so "
            "the row's pane is used, or map the agent to a webhook"
        )
    return _run_argv(fill(_herdr_argv(DEFAULT_COMMAND, session)), timeout)


def reachable(agent: str | None, pane: str | None) -> bool:
    """Whether `poke` has somewhere to deliver: an override transport, a
    webhook for this agent, or a herdr pane stamp on the row."""
    if not agent:
        return False
    if os.environ.get("CACTUS_POKE"):
        return True
    if pane:
        return True
    return webhook_entry(agent) is not None


def visit(pane: str | None, *, session: str | None = None, timeout: float = 5.0) -> str:
    """Focus the herdr pane a row was asked from. Returns what ran.

    Only a pane stamp can be visited: a row posted outside herdr has no
    conversation on screen to jump to, so it raises rather than guessing.
    `session` pins herdr to the row's own session (`{session}` in a
    CACTUS_VISIT template).
    """
    if not pane:
        raise PokeError("posted outside herdr; no pane to visit")
    override = os.environ.get("CACTUS_VISIT")
    template = shlex.split(override) if override else _herdr_argv(DEFAULT_VISIT_COMMAND, session)
    return _run_argv(
        [part.replace("{pane}", pane).replace("{session}", session or "") for part in template],
        timeout, "CACTUS_VISIT",
    )
