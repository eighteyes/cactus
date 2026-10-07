#!/usr/bin/env python3
# frontier.py
# UserPromptSubmit hook: inject this agent's cactus frontier as context on every prompt.
# Responsibilities:
#   - stay silent when cactus is not installed, no identity resolves, or the agent has no rows
#   - list the agent's rows awaiting elaboration first, then answered-but-not-cleared (acted-on backlog), then open
#   - cap the listing at CACTUS_FRONTIER_MAX rows (default 5), key and gist each, and close with one counts line
# Python 3 stdlib only; calls the cactus CLI by argv.
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cactus_identity as ident  # noqa: E402


def gist(row):
    word = row.get("word")
    if ident.truthy_value(word):
        return ident.as_text(word)
    return str(row.get("text"))[:60]


def verdict(row):
    answer = row.get("answer")
    if answer is None:
        return ""
    if ident.truthy_value(answer.get("skipped")):
        return " -> skipped"
    out = " -> " + ",".join(str(s) for s in (answer.get("selected") or []))
    text = answer.get("text")
    if ident.truthy_value(text):
        out += " " + str(text)[:40]
    return out


def hint(row):
    if row.get("status") != "elaborate":
        return ""
    value = row.get("elaborate")
    return " " + (ident.as_text(value) if ident.truthy_value(value) else "(eli5)")


def main():
    if not shutil.which("cactus"):
        return 0
    payload = ident.read_stdin()
    if not ident.project_enabled():
        return 0
    agent = ident.resolve_agent(payload)
    if not agent:
        return 0
    try:
        limit = int(os.environ.get("CACTUS_FRONTIER_MAX") or "5")
    except ValueError:
        return 0
    got = ident.run(["cactus", "list", "-s", "any", "--agent", agent, "--json"])
    if got is None or got[0] != 0 or not got[1].strip():
        return 0
    rows = ident.parse_json(got[1])
    if not isinstance(rows, list):
        return 0
    rows = [r for r in rows if isinstance(r, dict)]
    more = [r for r in rows if r.get("status") == "elaborate"]
    done = [r for r in rows if r.get("status") == "answered"]
    open_ = [r for r in rows if r.get("status") in ("open", "live")]
    total = len(more) + len(done) + len(open_)
    if total == 0:
        return 0
    lines = ["cactus frontier (--agent %s):" % agent]
    for r in (more + done + open_)[:limit]:
        lines.append("  %s %s%s %s%s" % (r.get("key"), r.get("status"), hint(r), gist(r), verdict(r)))
    if total > limit:
        lines.append("  ... %d more: cactus list -s any --agent %s" % (total - limit, agent))
    lines.append(
        "  %d to elaborate (cactus edit KEY --agent ID --context ...), %d answered to act on and clear, %d open"
        % (len(more), len(done), len(open_))
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
