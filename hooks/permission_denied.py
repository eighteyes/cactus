#!/usr/bin/env python3
# permission_denied.py
# PermissionDenied hook: turn an auto-mode denial of a Bash command into a cactus run row the human can approve.
# Responsibilities:
#   - stay silent when cactus is not installed or no identity resolves
#   - act only on Bash denials; other tools have no command to re-run
#   - stay silent when the hook's cwd project is disabled
#   - post one row per tool_use_id, deduped through a state file, so a retried denial does not double-post
#   - carry the denial reason as --why and the hook's cwd as --cwd
# Python 3 stdlib only; calls the cactus CLI by argv.
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cactus_identity as ident  # noqa: E402


def main():
    if not shutil.which("cactus"):
        return 0
    payload = ident.read_stdin()
    agent = ident.resolve_agent(payload)
    if not agent:
        return 0

    data = ident.parse_json(payload)
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input")
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not ident.truthy_value(cmd) or cmd == "":
        return 0
    cmd = ident.as_text(cmd)
    tool_use_id = data.get("tool_use_id")
    tool_use_id = ident.as_text(tool_use_id) if ident.truthy_value(tool_use_id) else ""
    why = data.get("denial_reason")
    why = ident.as_text(why) if ident.truthy_value(why) else "denied by permission mode"
    cwd = data.get("cwd")
    cwd = ident.as_text(cwd) if ident.truthy_value(cwd) else ""
    if not cwd:
        cwd = os.getcwd()

    if not ident.project_enabled(["--cwd", cwd]):
        return 0

    # Dedupe on tool_use_id. One line per id; the file is per agent so a new
    # session never inherits another's history.
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    state = os.path.join(base, "cactus")
    try:
        os.makedirs(state, exist_ok=True)
    except OSError:
        return 0
    if tool_use_id:
        seen = os.path.join(state, "denied-" + agent)
        try:
            with open(seen, "r", encoding="utf-8", errors="replace") as f:
                if tool_use_id in f.read().split("\n"):
                    return 0
        except OSError:
            pass
        try:
            with open(seen, "a", encoding="utf-8") as f:
                f.write(tool_use_id + "\n")
        except OSError:
            pass

    try:
        subprocess.run(
            ["cactus", "run", cmd, "--no-wait", "--agent", agent, "--cwd", cwd, "--why", why, "-t", "denied"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
