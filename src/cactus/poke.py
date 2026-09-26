"""
poke.py — nudge the agent that owns a row to re-read its feed.

Responsibilities:
- Resolve the poke transport for one agent id (question-level).
- Default to herdr's agent prompt verb.
- If that agent is listed in the webhook map, POST the wake URL instead.
- CACTUS_POKE still overrides everything (tests / one-shot transports).
- After an answer, auto-poke only webhook-mapped agents (never herdr).
- Report a usable failure when a row has no owner or the transport is absent.
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

DEFAULT_COMMAND = "herdr agent prompt {agent} {message}"

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
        raise PokeError(f"cannot read webhook map {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PokeError(f"webhook map {path} must be a JSON object keyed by agent id")
    return data


def webhook_entry(agent: str) -> dict[str, Any] | None:
    """Webhook config for `agent`, or None when unmapped."""
    entry = load_webhooks().get(agent)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise PokeError(f"webhook map entry for {agent!r} must be an object")
    return entry


def poke_webhook_if_mapped(
    agent: str | None,
    *,
    message: str | None = None,
    timeout: float = 5.0,
) -> str | None:
    """Wake a webhook-mapped agent only.

    Used after an answer so external owners (Grok Bot, etc.) re-read the feed
    without requiring a separate `p`. Unmapped agents return None and are not
    poked — herdr / Claude monitor already sees the answer event.

    Ignores CACTUS_POKE: that override is for explicit `cactus poke` / tests,
    not for silently replacing herdr on every answer.
    """
    if not agent:
        return None
    entry = webhook_entry(agent)
    if entry is None:
        return None
    body = message or DEFAULT_MESSAGE.format(agent=agent)
    return _post_webhook(agent, body, entry, timeout)


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


def _run_argv(argv: list[str], timeout: float) -> str:
    if not argv:
        raise PokeError("CACTUS_POKE is empty")
    exe = resolve_executable(argv[0])
    if exe is None:
        dirs = ", ".join(str(d) for d in FALLBACK_BIN_DIRS)
        raise PokeError(
            f"{argv[0]} is not on PATH or in {dirs}; set CACTUS_POKE to a transport"
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


def poke(agent: str | None, *, message: str | None = None, timeout: float = 10.0) -> str:
    """Deliver a nudge to `agent`. Returns a short description of what ran.

    Raises PokeError when the row has no owner or the transport is missing —
    both are situations a human can fix, so they are reported rather than
    swallowed.

    Resolution order:
    1. CACTUS_POKE override (tests / forced transport) — same for every agent
    2. Webhook map entry for this agent id (CACTUS_POKE_WEBHOOKS /
       ~/.config/cactus/poke-webhooks.json)
    3. Default herdr agent prompt
    """
    if not agent:
        raise PokeError("this row has no agent; nothing to poke")

    body = message or DEFAULT_MESSAGE.format(agent=agent)

    if os.environ.get("CACTUS_POKE"):
        argv = [
            part.replace("{agent}", agent).replace("{message}", body)
            for part in poke_command()
        ]
        return _run_argv(argv, timeout)

    entry = webhook_entry(agent)
    if entry is not None:
        return _post_webhook(agent, body, entry, timeout)

    argv = [
        part.replace("{agent}", agent).replace("{message}", body)
        for part in shlex.split(DEFAULT_COMMAND)
    ]
    return _run_argv(argv, timeout)
