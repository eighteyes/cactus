"""
decide.py — ask a local decision server which choice to propose for a row.

Responsibilities:
- POST a question and its choices to the decider's /v1/systemone endpoint.
- Return a Proposal (label, confidence, probabilities), or None on any failure.
- Never raise and never touch the store; the caller decides what to do with it.
- Probe the server's /health.
- CACTUS_DECIDE overrides the network for tests: "off" always yields None,
  "LABEL:0.93" yields a fixed Proposal when LABEL is among the choices.
- CACTUS_DECIDER_URL moves the server (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class Proposal:
    label: str
    confidence: float
    probabilities: dict[str, float]


def _base() -> str:
    return (os.environ.get("CACTUS_DECIDER_URL") or DEFAULT_URL).rstrip("/")


def _override(labels: list[str]) -> tuple[bool, Proposal | None]:
    """(handled, proposal) for CACTUS_DECIDE; handled False means go to the net."""
    spec = os.environ.get("CACTUS_DECIDE")
    if not spec:
        return False, None
    if spec == "off":
        return True, None
    label, _, conf = spec.rpartition(":")
    try:
        confidence = float(conf)
    except ValueError:
        return True, None
    if label not in labels:
        return True, None
    return True, Proposal(label, confidence, {label: confidence})


def propose(
    text: str,
    context: str | None,
    choices: list[tuple[str, str]],
    timeout: float = 3.0,
) -> Proposal | None:
    """Propose one of `choices` ((label, description) pairs), or None."""
    labels = [label for label, _ in choices]
    handled, fixed = _override(labels)
    if handled:
        return fixed
    if len(choices) < 2:
        return None
    body = {
        "state": f"{text}\n\n{context}" if context else text,
        "questions": {
            "q": {
                "type": "choice",
                "instructions": text,
                "criteria": {label: desc or label for label, desc in choices},
            }
        },
    }
    try:
        req = urllib.request.Request(
            f"{_base()}/v1/systemone",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            answer = json.loads(resp.read())["answers"]["q"]
        label = answer["choice"]
        if label not in labels:
            return None
        probs = {str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()}
        return Proposal(label, float(answer["confidence"]), probs)
    except Exception:
        return None


def available(timeout: float = 0.5) -> bool:
    """True when the decider answers GET /health."""
    spec = os.environ.get("CACTUS_DECIDE")
    if spec:
        return spec != "off"
    try:
        with urllib.request.urlopen(f"{_base()}/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
