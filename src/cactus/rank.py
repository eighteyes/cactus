"""
rank.py — gate a row for the auto-decider by reversibility and complexity.

Responsibilities:
- Classify one row on two axes: reversibility {reversible, costly,
  irreversible} and complexity {low, med, high}. apint gets one small call
  per axis, both at once (q425: "one axis, 2x in parallel"); haiku gets one
  call for both.
- Gate: the AI may propose a pick only on a reversible, low-complexity row.
- Backends in order: apint (Apple on-device), then Haiku via `claude -p`.
  A backend that is missing, unavailable, fails, or times out falls through
  to the next; none left returns None. Never raises.
- CACTUS_RANK overrides every backend (tests / the TUI suite): a fixed
  "reversible,low" pair, "off" for no classifier, or a command template.
- Side leaf: never touches the store.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cactus.poke import resolve_executable

REVERSIBILITY = ("reversible", "costly", "irreversible")
COMPLEXITY = ("low", "med", "high")
AXES = {"reversibility": REVERSIBILITY, "complexity": COMPLEXITY}

# Per backend call. apint runs both axes at once, so each backend costs at
# most one timeout; a fall-through to haiku can add its own. Measured: apint
# ~1 s for both axes, haiku 8-15 s from a cold `claude -p`.
APINT_TIMEOUT = 10.0
HAIKU_TIMEOUT = 30.0
OVERRIDE_TIMEOUT = 10.0

# apint's context window is small; a row's text and context are clipped
# before they reach any backend.
MAX_TEXT = 1500
MAX_CONTEXT = 1500
MAX_CHOICE = 300

APINT = "apint"
CLAUDE = "claude"
HAIKU_ARGS = (
    "-p", "--model", "haiku", "--no-session-persistence",
    "--strict-mcp-config", "--disable-slash-commands",
    "--setting-sources", "", "--tools", "",
)

CAUTION = (
    "Be conservative. If you are unsure between two labels, pick the more "
    "cautious one (later in the list). Judge what happens if someone acts on "
    "whichever choice is picked, not the wording of the question."
)

SYSTEMS = {
    "reversibility": (
        "You label a decision a software agent is asking a human to make. "
        "Label how hard it is to undo acting on the decision.\n\n"
        "reversible: the effect stays local and can be undone exactly in "
        "minutes. Editing code or files under version control, renaming, "
        "wording, a default value, a UI or config setting, ordering, picking "
        "which of two local approaches to try first.\n"
        "Examples: \"name the flag --quiet or --silent\", \"put the helper in "
        "utils.py or its own file\", \"show the count left or right\".\n\n"
        "costly: undo is possible but takes real work or touches shared "
        "state. Schema or data migrations, changing a public API or file "
        "format, large rewrites, commits to a shared branch, merging "
        "branches, removing a feature people use.\n"
        "Examples: \"rebuild the answers table\", \"merge branch X into "
        "main\", \"rename the CLI verb users already script against\".\n\n"
        "irreversible: cannot be taken back once done. Pushing, publishing, "
        "releasing, deploying, sending messages or email, deleting or purging "
        "data with no backup, spending money, credentials, permissions, "
        "anything other people see or act on.\n"
        "Examples: \"push to origin\", \"purge cleared rows\", \"post the "
        "announcement\", \"rotate the API key\".\n\n" + CAUTION
    ),
    "complexity": (
        "You label a decision a software agent is asking a human to make. "
        "Label how much judgment the decision needs.\n\n"
        "low: one clear dimension, few options, and the text alone makes the "
        "better pick evident to a competent developer.\n"
        "Examples: \"tests in test_cli.py or a new file\", \"exit 1 or exit "
        "3 for a missing key, given exit 3 means no match\".\n\n"
        "med: several trade-offs or several parts touched; reasonable "
        "developers would pick differently.\n"
        "Examples: \"cache in memory or on disk\", \"split the module now or "
        "after the release\".\n\n"
        "high: architecture or product direction, the human's own taste, "
        "priorities or intent, facts not in the text, or many interacting "
        "parts. Any open-ended question asking what the human wants.\n"
        "Examples: \"what should the taxonomy be\", \"which project next\", "
        "\"does this design feel right\".\n\n" + CAUTION
    ),
}


@dataclass(frozen=True)
class Rank:
    reversibility: str   # reversible | costly | irreversible
    complexity: str      # low | med | high
    source: str          # apint | haiku | override

    @property
    def gated(self) -> bool:
        """True = the AI may propose a pick on this row."""
        return self.reversibility == "reversible" and self.complexity == "low"

    def reason(self) -> str:
        return f"{self.reversibility} · {self.complexity}"


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_row(text: str, context: str | None,
               choices: list[tuple[str, str]]) -> str:
    """The row as every backend sees it."""
    parts = [f"Question: {_clip(text, MAX_TEXT)}"]
    if context and context.strip():
        parts.append(f"Context: {_clip(context, MAX_CONTEXT)}")
    if choices:
        lines = []
        for label, desc in choices:
            desc = _clip(desc or "", MAX_CHOICE).replace("\n", " ")
            lines.append(f"- {label}: {desc}" if desc else f"- {label}")
        parts.append("Choices:\n" + "\n".join(lines))
    else:
        parts.append("Choices: none (free-text answer)")
    return "\n".join(parts)


def parse_label(output: str, labels: tuple[str, ...]) -> str | None:
    """The one label named in `output`, or None when none or several are."""
    words = set(re.findall(r"[a-z]+", output.lower()))
    found = [label for label in labels if label in words]
    return found[0] if len(found) == 1 else None


def parse_fixed(value: str) -> Rank | None:
    """`reversible,low` -> Rank(source="override"); None when malformed."""
    parts = [p.strip().lower() for p in value.split(",")]
    if len(parts) != 2:
        return None
    rev, cx = parts
    if rev not in REVERSIBILITY or cx not in COMPLEXITY:
        return None
    return Rank(rev, cx, "override")


def _run(argv: list[str], stdin: str, timeout: float) -> tuple[int, str] | None:
    """(exit code, stdout), or None when the call could not finish."""
    try:
        proc = subprocess.run(
            argv, input=stdin, capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "CACTUS_STOP_HOOK": "0"},
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return proc.returncode, proc.stdout


class _Unavailable(Exception):
    """This backend cannot classify; try the next one."""


def _both(ask, row: str) -> tuple[str, str]:
    """Run `ask(axis, row)` for both axes at once; raise if either fails."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {axis: pool.submit(ask, axis, row) for axis in AXES}
        out = {axis: f.result() for axis, f in futures.items()}
    if out["reversibility"] is None or out["complexity"] is None:
        raise _Unavailable
    return out["reversibility"], out["complexity"]


def _apint(timeout: float):
    """Both axes at once, one schema call each: a short `why` ahead of the
    label. With bare --labels the on-device model answered `high` to every
    complexity prompt; reasoning first fixed it."""
    exe = resolve_executable(APINT)
    if exe is None:
        raise _Unavailable

    def ask(axis: str, row: str) -> str | None:
        labels = AXES[axis]
        schema = json.dumps({
            "type": "object",
            "properties": {
                "why": {"type": "string", "description": "one short sentence"},
                axis: {"type": "string", "enum": list(labels)},
            },
            "required": ["why", axis],
        })
        argv = [exe, "--no-stream", "-t", "0", "-s", SYSTEMS[axis],
                "--schema", schema, f"Label the {axis} of this decision."]
        result = _run(argv, row, timeout)
        if result is None or result[0] != 0:
            return None
        try:
            label = json.loads(result[1]).get(axis)
        except (json.JSONDecodeError, AttributeError):
            return None
        return label if label in labels else None

    return lambda row: _both(ask, row)


def parse_pair(output: str) -> tuple[str, str] | None:
    """`reversibility: X` and `complexity: Y` lines -> (X, Y), else None."""
    got: dict[str, str] = {}
    for line in output.lower().splitlines():
        name, sep, value = line.partition(":")
        name = name.strip(" *-`")
        if sep and name in AXES:
            label = parse_label(value, AXES[name])
            if label is None:
                return None
            got[name] = label
    if set(got) != set(AXES):
        return None
    return got["reversibility"], got["complexity"]


def _haiku(timeout: float):
    """One call for both axes: a `claude -p` process is the slow part, and
    two at once took 8-20 s where one took ~3 s."""
    exe = resolve_executable(CLAUDE)
    if exe is None:
        raise _Unavailable

    def run(row: str) -> tuple[str, str]:
        prompt = (
            "Label one decision on two separate axes.\n\n"
            f"## reversibility\n{SYSTEMS['reversibility']}\n\n"
            f"## complexity\n{SYSTEMS['complexity']}\n\n"
            f"## decision\n{row}\n\n"
            "Reply with exactly two lines and nothing else:\n"
            "reversibility: <reversible|costly|irreversible>\n"
            "complexity: <low|med|high>"
        )
        result = _run([exe, *HAIKU_ARGS], prompt, timeout)
        if result is None or result[0] != 0:
            raise _Unavailable
        pair = parse_pair(result[1])
        if pair is None:
            raise _Unavailable
        return pair

    return run


def _template(template: str, timeout: float):
    """CACTUS_RANK as a command: `{axis}`/`{labels}` per argument, row on stdin."""
    try:
        argv = shlex.split(template)
    except ValueError:
        raise _Unavailable
    if not argv:
        raise _Unavailable
    exe = resolve_executable(argv[0])
    if exe is None:
        raise _Unavailable

    def ask(axis: str, row: str) -> str | None:
        labels = AXES[axis]
        subs = {"axis": axis, "labels": ",".join(labels)}
        args = [exe, *(a.format_map(subs) for a in argv[1:])]
        result = _run(args, row, timeout)
        if result is None or result[0] != 0:
            return None
        return parse_label(result[1], labels)

    return lambda row: _both(ask, row)


def classify(text: str, context: str | None,
             choices: list[tuple[str, str]], *,
             timeout: float | None = None) -> Rank | None:
    """Rank one row; None when no classifier is reachable. Never raises.

    `timeout` bounds each backend call (None: that backend's default)."""
    try:
        row = render_row(text, context, choices)
        override = os.environ.get("CACTUS_RANK")
        if override is not None and override.strip():
            value = override.strip()
            if value.lower() in ("off", "none"):
                return None
            if "," in value and " " not in value and "{" not in value:
                return parse_fixed(value)
            # An override never falls through to a real model.
            try:
                rev, cx = _template(value, timeout or OVERRIDE_TIMEOUT)(row)
            except _Unavailable:
                return None
            return Rank(rev, cx, "override")

        for source, backend, default in (("apint", _apint, APINT_TIMEOUT),
                                         ("haiku", _haiku, HAIKU_TIMEOUT)):
            try:
                rev, cx = backend(timeout or default)(row)
            except _Unavailable:
                continue
            return Rank(rev, cx, source)
        return None
    except Exception:  # the gate fails closed, never loud
        return None
