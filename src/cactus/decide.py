"""
decide.py — ask a local decision server which choice to propose for a row.

Responsibilities:
- POST a question and its choices to a backend's /v1/systemone endpoint.
- Keep a registry of backends ("strands", "clef"), each with a default URL, a
  request builder and a response parser returning Proposal or None.
- Pick the backend: CACTUS_DECIDER_BACKEND, then the caller's setting (the TUI
  `decider_backend`), then "strands".
- Return a Proposal (label, confidence, probabilities), or None on any failure.
- Never raise and never touch the store; the caller decides what to do with it.
- Probe the server's /health.
- CACTUS_DECIDE overrides the network for tests: "off" always yields None,
  "LABEL:0.93" yields a fixed Proposal when LABEL is among the choices.
- CACTUS_DECIDER_URL moves the server (default per backend).

Clef is served LOCALLY only (see clef_serve.py). Cloudflare's Workers AI
route is deliberately absent: it would send row text to Cloudflare, which
nobody has approved.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_URL = "http://127.0.0.1:8000"
BACKEND_NAMES = ("strands", "clef")


@dataclass(frozen=True)
class Proposal:
    label: str
    confidence: float
    probabilities: dict[str, float]


def _body(text: str, context: str | None, choices: list[tuple[str, str]]) -> dict[str, Any]:
    """The Jev/SystemOne request both backends share: one `choice` question."""
    return {
        "state": f"{text}\n\n{context}" if context else text,
        "questions": {
            "q": {
                "type": "choice",
                "instructions": text,
                "criteria": {label: desc or label for label, desc in choices},
            }
        },
    }


def _clef_body(text: str, context: str | None, choices: list[tuple[str, str]]) -> dict[str, Any]:
    return {"model": "clef-flash", **_body(text, context, choices)}


def _parse(reply: dict[str, Any], labels: list[str]) -> Proposal | None:
    """Read answers.q; confidence falls back to the top probability when absent."""
    answer = reply["answers"]["q"]
    probs = {str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()}
    label = answer.get("choice")
    if label is None and probs:
        label = max(probs, key=probs.get)
    if label not in labels:
        return None
    confidence = answer.get("confidence")
    if confidence is None:
        if not probs:
            return None
        confidence = max(probs.values())
    return Proposal(label, float(confidence), probs)


@dataclass(frozen=True)
class Backend:
    url: str
    build: Callable[[str, str | None, list[tuple[str, str]]], dict[str, Any]]
    parse: Callable[[dict[str, Any], list[str]], Proposal | None]


# Both speak POST /v1/systemone; clef-flash's card says its API is fully
# compatible with Jev/SystemOne. Clef gets its own port so both can run.
BACKENDS: dict[str, Backend] = {
    "strands": Backend(DEFAULT_URL, _body, _parse),
    "clef": Backend("http://127.0.0.1:8001", _clef_body, _parse),
}


def resolve_backend(backend: str | None = None) -> str:
    """CACTUS_DECIDER_BACKEND, then `backend` (the TUI setting), then "strands"."""
    for name in (os.environ.get("CACTUS_DECIDER_BACKEND"), backend):
        if name in BACKENDS:
            return name
    return "strands"


def base_url(backend: str | None = None) -> str:
    """CACTUS_DECIDER_URL, else the resolved backend's default."""
    return (os.environ.get("CACTUS_DECIDER_URL") or BACKENDS[resolve_backend(backend)].url).rstrip("/")


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
    backend: str | None = None,
) -> Proposal | None:
    """Propose one of `choices` ((label, description) pairs), or None."""
    labels = [label for label, _ in choices]
    handled, fixed = _override(labels)
    if handled:
        return fixed
    if len(choices) < 2:
        return None
    be = BACKENDS[resolve_backend(backend)]
    try:
        req = urllib.request.Request(
            f"{base_url(backend)}/v1/systemone",
            data=json.dumps(be.build(text, context, choices)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return be.parse(json.loads(resp.read()), labels)
    except Exception:
        return None


def health(backend: str | None = None, timeout: float = 0.5) -> bool:
    """True when the backend's server answers GET /health; ignores CACTUS_DECIDE."""
    try:
        with urllib.request.urlopen(f"{base_url(backend)}/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def available(timeout: float = 0.5, backend: str | None = None) -> bool:
    """True when the decider answers GET /health."""
    spec = os.environ.get("CACTUS_DECIDE")
    if spec:
        return spec != "off"
    return health(backend, timeout)
