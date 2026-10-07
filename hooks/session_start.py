#!/usr/bin/env python3
# session_start.py
# SessionStart hook: inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print the workflow every agent follows: ask, wait (backgrounded), work, act on each wake, clear
#   - resolve the --agent value through cactus_identity and print it
#   - rehome rows this pane posted under a previous identity (after /clear or --resume)
#   - teach the escape: wait on the denied hook's cactus run row, post one only when none exists
#   - print the open rows for this project so an unanswered thread is not forgotten
#   - list rows untouched past the stale threshold (CACTUS_STALE_HOURS, default 24h)
# Python 3 stdlib only; calls the cactus CLI by argv.
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cactus_identity as ident  # noqa: E402

DISABLED = "Cactus is disabled for this project. Run \x60cactus project activate\x60 to reactivate it."

WORKFLOW = """cactus is installed. Its workflow is required, not optional:
  1 ask      post every decision the human makes to \x60cactus ask\x60, not to chat or AskUserQuestion; one -c per direction, --recommend LABEL --confidence L when you have a pick, -f for every file the question is about, --agent on every row
  2 wait     a blocking ask (ask, run) waits for the human by default. Post it as ONE backgrounded command (Bash run_in_background); its exit is your wake-up. No monitor. --no-wait posts and returns; steer/notify/review/plan/data never wait; collect those with one backgrounded \x60cactus get KEY... --wait\x60
  2b work    do everything the answer does not block while it waits
  3 act      on each wake (answered, elaborate, reopened, cleared), read the row with \x60cactus get KEY --agent ID\x60. Read every review/plan row with \x60cactus get KEY --agent ID\x60 (that tells the human you heard); after acting on its verdict, respond with \x60cactus plan|review|edit KEY --agent ID\x60
  4 clear    your own rows, by key, once acted on
Blocked by a permission prompt? Do not stop. In auto mode the PermissionDenied hook already posted the command as a \x60cactus run\x60 row in thread denied: find it with \x60cactus list -s open -t denied --agent ID\x60 and wait on it with one backgrounded \x60cactus get KEY --wait --agent ID\x60. Post \x60cactus run CMD --agent ID\x60 (backgrounded) yourself only when no such row exists. The human approves it from the TUI.
Load the cactus skill before the first ask."""

STALE_HEADER = (
    "Stale cactus rows in this project (untouched past the threshold). Rows you own: "
    "'cactus edit' if still relevant, or 'cactus clear KEY --agent ID' if dead. "
    "Rows owned by others: leave them, the human clears them."
)


def rehomed(agent):
    got = ident.run(["cactus", "rehome", "--agent", agent, "--json"])
    data = ident.parse_json(got[1]) if got else None
    if not isinstance(data, dict):
        return "0"
    for key in ("rehomed", "count"):
        if ident.truthy_value(data.get(key)):
            return ident.as_text(data[key])
    return "0"


def stale_lines():
    got = ident.run(["cactus", "list", "--json", "-s", "open,live,elaborate"])
    rows = ident.parse_json(got[1]) if got else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get("stale") is not True:
            continue
        try:
            hours = row.get("idle_hours")
            idle = "%dd" % math.floor(hours / 24) if hours >= 48 else "%dh" % math.floor(hours)
            owner = row.get("agent")
            owner = (ident.as_text(owner) if ident.truthy_value(owner) else "unowned")[:8]
            first = str(row.get("text")).split("\n")[0]
        except (TypeError, ValueError):
            continue
        out.append("  %s  %s  %s  %s" % (row.get("key"), owner, idle, first))
    return out


def main():
    if not shutil.which("cactus"):
        return 0
    payload = ident.read_stdin()
    if not ident.project_enabled():
        print(DISABLED)
        return 0
    agent = ident.resolve_agent(payload)

    print(WORKFLOW)
    if agent:
        print("Your cactus identity for this session: --agent " + agent)
        # A /clear or --resume rotates the conversation id. Rows this pane posted
        # under the old id are still stamped with the pane and herdr session, so
        # move them onto the new id; exit 1 (no stamps) and count 0 are both silent.
        moved = rehomed(agent)
        if moved != "0":
            print("Rehomed %s row(s) from this pane's previous identity onto --agent %s." % (moved, agent))
    else:
        print("No herdr session resolved. Choose one stable --agent value for this session and pass it on every ask and clear.")

    got = ident.run(["cactus", "list", "-s", "open"])
    if got and got[0] == 0 and got[1].rstrip("\n"):
        print("Open cactus rows in this project (collect with \x60cactus get KEY --agent ID --json\x60):")
        print(got[1].rstrip("\n"))

    # Rows untouched past the stale threshold (CACTUS_STALE_HOURS, default 24h).
    stale = stale_lines()
    if stale:
        print(STALE_HEADER)
        print("\n".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
