"""
poke.py — nudge the agent that owns a row to re-read its feed.

Responsibilities:
- Resolve the poke command, defaulting to herdr's agent prompt verb.
- Deliver a contentless nudge to one agent/pane without blocking the caller.
- Report a usable failure when a row has no owner or the transport is absent.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

# A poke carries no instruction. It tells an agent that the inbox moved and lets
# the agent decide what that means, which keeps the human out of the business of
# composing prompts and keeps cactus out of the business of driving agents.
DEFAULT_MESSAGE = (
    "cactus: your inbox moved — re-read it with `cactus feed --json "
    "--agent {agent}` and act on what changed."
)

DEFAULT_COMMAND = "herdr agent prompt {agent} {message}"

# The default transport really does prompt a live agent. `cactus ask` requires
# --agent and never falls back to a pane id, so a row's owner is whatever the
# asking session declared — but that is still a live agent once poked.
# Anything exercising poke must set CACTUS_POKE to something inert first, or
# the test pokes the person running it.


class PokeError(RuntimeError):
    """A poke that could not be delivered, with a reason worth showing a human."""


def poke_command() -> list[str]:
    """The configured transport, as an argv template.

    CACTUS_POKE overrides it. The template is split with shlex and the {agent}
    and {message} tokens are substituted per-argument afterwards, so neither a
    pane id nor a message body is ever handed to a shell.
    """
    return shlex.split(os.environ.get("CACTUS_POKE") or DEFAULT_COMMAND)


def poke(agent: str | None, *, message: str | None = None, timeout: float = 10.0) -> str:
    """Deliver a nudge to `agent`. Returns the command that was run.

    Raises PokeError when the row has no owner or the transport is missing —
    both are situations a human can fix, so they are reported rather than
    swallowed.
    """
    if not agent:
        raise PokeError("this row has no agent; nothing to poke")

    body = message or DEFAULT_MESSAGE.format(agent=agent)
    argv = [
        part.replace("{agent}", agent).replace("{message}", body)
        for part in poke_command()
    ]
    if not argv:
        raise PokeError("CACTUS_POKE is empty")
    if shutil.which(argv[0]) is None:
        raise PokeError(f"{argv[0]} is not on PATH; set CACTUS_POKE to a transport")

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
