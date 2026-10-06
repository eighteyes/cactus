#!/usr/bin/env python3
# pretooluse_wait.py
# PreToolUse hook on Bash: refuse a foreground cactus ask|run that would wait for the human.
# Responsibilities:
#   - stay silent and fast for every Bash call that does not invoke cactus ask/run
#   - allow a waiting ask/run when tool_input.run_in_background is true
#   - match only at command position: drop heredoc bodies and quoted text first
#   - allow --no-wait, --no-block and the acts that never wait (steer notify review plan data)
#   - otherwise exit 2 with a stderr message telling the agent to background the call
#   - fail open (exit 0) on any payload it cannot read
# Python 3 stdlib only; it launches nothing.
import json
import re
import sys

BT = "\x60"  # a backtick
DP = "\x24("  # a dollar-paren
MESSAGE = (
    "cactus ask/run waits for the human by default; "
    "rerun with run_in_background: true. Its exit wakes you."
)
WS = " \t\n\v\f\r"
COMMENT_OK = ("", " ", "\t", "\n", ";", "&", "|", "(")
HEREDOC_STOP = set(WS + ";&|<>()")


def _has_expansion(text):
    return DP in text or BT in text


def scan_commands(cmd):
    """Reduce cmd to the text the shell runs as commands.

    Heredoc bodies and quoted strings are data, so a line in them that starts
    'cactus run' is not a call. Expansion is the exception, kept so it still
    matches: a double-quoted string holding $( or a backtick is scanned again
    on its own, and an unquoted heredoc body line keeps the part from its
    first $( or backtick on. A heuristic, not a parser: when unsure it keeps
    text, and a false block costs one rerun where a missed one parks the agent
    for an hour.
    """
    code = ""
    queue = [cmd]
    while queue:
        src = queue.pop(0)
        out = ""
        pending = []  # (delimiter, quoted, strip) for heredocs awaiting their body
        in_body = False
        delim, dquoted, dstrip = "", False, False
        open_q = ""
        span = ""
        for line in src.split("\n"):
            if in_body:
                test = line.lstrip("\t") if dstrip else line
                if test == delim:
                    if pending:
                        delim, dquoted, dstrip = pending.pop(0)
                    else:
                        in_body = False
                elif not dquoted and _has_expansion(line):
                    idxs = [p for p in (line.find(DP), line.find(BT)) if p >= 0]
                    out += line[min(idxs):] + "\n"
                continue
            n = len(line)
            i = 0
            while i < n:
                c = line[i]
                if open_q:
                    # Inside a quote that began on an earlier line.
                    if open_q == '"' and c == "\\":
                        span += line[i:i + 2]
                        i += 2
                        continue
                    if c == open_q:
                        if open_q == '"' and _has_expansion(span):
                            queue.append(span)
                        open_q = ""
                        span = ""
                    else:
                        span += c
                    i += 1
                    continue
                if c == "\\":
                    out += line[i:i + 2]
                    i += 2
                    continue
                if c in ("'", '"'):
                    open_q = c
                    span = ""
                    i += 1
                    continue
                if c == "#":
                    # A comment runs to end of line; its apostrophes open no quote.
                    if out[-1:] in COMMENT_OK:
                        break
                elif c == "<" and line[i:i + 2] == "<<" and line[i:i + 3] != "<<<":
                    i += 2
                    strip = False
                    if line[i:i + 1] == "-":
                        strip = True
                        i += 1
                    while line[i:i + 1] in (" ", "\t") and i < n:
                        i += 1
                    quoted = False
                    word = ""
                    while i < n:
                        q = line[i]
                        if q in ("'", '"', "\\"):
                            quoted = True
                        elif q in HEREDOC_STOP:
                            break
                        else:
                            word += q
                        i += 1
                    if word:
                        pending.append((word, quoted, strip))
                    out += " "
                    continue
                out += c
                i += 1
            if open_q:
                span += "\n"
                continue
            out += "\n"
            if pending:
                in_body = True
                delim, dquoted, dstrip = pending.pop(0)
        code += out + "\n"
    return code


# cactus ask|run at command position: line start or after ; & | ( a backtick, a
# dollar-paren, and optional VAR=val prefixes, with optional global flags before
# the verb.
_SEP = "(^|[;&|(" + BT + "\n]|\\$\\()[ \\t\\n\\v\\f\\r]*"
_ENV = "([A-Za-z_][A-Za-z0-9_]*=[^ \\t\\n\\v\\f\\r]*[ \\t\\n\\v\\f\\r]+)*"
CALL_RE = re.compile(
    _SEP + _ENV + "cactus([ \\t\\n\\v\\f\\r]+-[^ \\t\\n\\v\\f\\r]+)*[ \\t\\n\\v\\f\\r]+(ask|run)([ \\t\\n\\v\\f\\r]|\\Z)"
)
# Rows that do not wait. These match the raw command, not the reduced code: one
# of these flags anywhere in the call, even in a quoted string or a second
# command, lets the whole call through. Check here first when a waiting ask
# slipped by.
NO_WAIT_RE = re.compile("(^|[ \\t\\n\\v\\f\\r])--no-wait([ \\t\\n\\v\\f\\r=]|\\Z)")
NO_BLOCK_RE = re.compile("(^|[ \\t\\n\\v\\f\\r])--no-block([ \\t\\n\\v\\f\\r]|\\Z)")
ACT_RE = re.compile("--act[ \\t\\n\\v\\f\\r=]+(steer|notify|review|plan|data)([ \\t\\n\\v\\f\\r]|\\Z)")


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    # Fast path: no parsing unless the payload even mentions cactus.
    if "cactus" not in raw:
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    if tool_input.get("run_in_background") in (True, "true"):
        return 0
    cmd = tool_input.get("command")
    if not isinstance(cmd, str):
        return 0
    cmd = cmd.rstrip("\n")
    if "cactus" not in cmd:
        return 0

    if not CALL_RE.search(scan_commands(cmd)):
        return 0
    if NO_WAIT_RE.search(cmd) or NO_BLOCK_RE.search(cmd) or ACT_RE.search(cmd):
        return 0

    # Exit 2 is Claude Code's PreToolUse block: the call never runs and stderr
    # reaches the agent as the reason.
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
