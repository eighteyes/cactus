"""
test_decide.py — tests for cactus.decide against a stub HTTP server.

Responsibilities:
- Exercise the CACTUS_DECIDE override paths (off, fixed label, bad label).
- Exercise propose() on success, bad label, malformed JSON, timeout, unreachable.
- Exercise the fewer-than-two-choices refusal and available().
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cactus import decide

CHOICES = [("a", "first"), ("b", "")]


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch):
    """A stub decider; set `box['reply']` (bytes) and `box['delay']`."""
    box: dict = {"reply": b"{}", "delay": 0.0, "seen": None}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            box["seen"] = json.loads(self.rfile.read(n))
            time.sleep(box["delay"])
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(box["reply"])
            except OSError:
                pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.delenv("CACTUS_DECIDE", raising=False)
    monkeypatch.setenv("CACTUS_DECIDER_URL", f"http://127.0.0.1:{srv.server_port}")
    yield box
    srv.shutdown()
    srv.server_close()


def _reply(choice: str) -> bytes:
    return json.dumps({"answers": {"q": {
        "choice": choice, "probabilities": {"a": 0.8, "b": 0.2}, "confidence": 0.8,
    }}}).encode()


def test_override_off(monkeypatch):
    monkeypatch.setenv("CACTUS_DECIDE", "off")
    assert decide.propose("t", None, CHOICES) is None
    assert decide.available() is False


def test_override_fixed_label(monkeypatch):
    monkeypatch.setenv("CACTUS_DECIDE", "b:0.93")
    got = decide.propose("t", None, CHOICES)
    assert got is not None and (got.label, got.confidence) == ("b", 0.93)


def test_override_label_not_among_choices(monkeypatch):
    monkeypatch.setenv("CACTUS_DECIDE", "zzz:0.93")
    assert decide.propose("t", None, CHOICES) is None


def test_success_and_request_shape(stub):
    stub["reply"] = _reply("a")
    got = decide.propose("which?", "ctx", CHOICES)
    assert got == decide.Proposal("a", 0.8, {"a": 0.8, "b": 0.2})
    q = stub["seen"]["questions"]["q"]
    assert stub["seen"]["state"] == "which?\n\nctx"
    assert q["criteria"] == {"a": "first", "b": "b"}
    assert q["type"] == "choice" and q["instructions"] == "which?"


def test_fewer_than_two_choices(stub):
    stub["reply"] = _reply("a")
    assert decide.propose("t", None, CHOICES[:1]) is None
    assert stub["seen"] is None


def test_bad_label(stub):
    stub["reply"] = _reply("zzz")
    assert decide.propose("t", None, CHOICES) is None


def test_malformed_json(stub):
    stub["reply"] = b"{not json"
    assert decide.propose("t", None, CHOICES) is None
    stub["reply"] = b'{"answers": {}}'
    assert decide.propose("t", None, CHOICES) is None


def test_timeout(stub):
    stub["reply"] = _reply("a")
    stub["delay"] = 1.0
    assert decide.propose("t", None, CHOICES, timeout=0.2) is None


def test_unreachable(monkeypatch):
    monkeypatch.delenv("CACTUS_DECIDE", raising=False)
    monkeypatch.setenv("CACTUS_DECIDER_URL", "http://127.0.0.1:1")
    assert decide.propose("t", None, CHOICES) is None
    assert decide.available() is False


def test_available_true(stub):
    assert decide.available() is True


# ---- backends ---------------------------------------------------------------


def _clef_reply(probs: dict[str, float], **extra) -> bytes:
    return json.dumps({"answers": {"q": {"probabilities": probs, **extra}}}).encode()


def test_clef_round_trip(stub, monkeypatch):
    """Clef posts the SystemOne body plus its model name; the reply parses the same."""
    monkeypatch.setenv("CACTUS_DECIDER_BACKEND", "clef")
    stub["reply"] = _reply("b")
    got = decide.propose("which?", "ctx", CHOICES)
    assert got is not None and got.label == "b"
    assert stub["seen"]["model"] == "clef-flash"
    assert stub["seen"]["questions"]["q"]["criteria"] == {"a": "first", "b": "b"}


def test_clef_confidence_is_max_probability(stub, monkeypatch):
    monkeypatch.setenv("CACTUS_DECIDER_BACKEND", "clef")
    stub["reply"] = _clef_reply({"a": 0.3, "b": 0.7})
    assert decide.propose("t", None, CHOICES) == decide.Proposal("b", 0.7, {"a": 0.3, "b": 0.7})


def test_strands_body_has_no_model_field(stub):
    stub["reply"] = _reply("a")
    decide.propose("t", None, CHOICES)
    assert "model" not in stub["seen"]


def test_backend_selection_order(monkeypatch):
    monkeypatch.delenv("CACTUS_DECIDER_BACKEND", raising=False)
    monkeypatch.delenv("CACTUS_DECIDER_URL", raising=False)
    assert decide.resolve_backend() == "strands"
    assert decide.resolve_backend("clef") == "clef"
    assert decide.resolve_backend("nonsense") == "strands"
    monkeypatch.setenv("CACTUS_DECIDER_BACKEND", "strands")
    assert decide.resolve_backend("clef") == "strands"
    monkeypatch.setenv("CACTUS_DECIDER_BACKEND", "bogus")
    assert decide.resolve_backend("clef") == "clef"


def test_backend_default_urls_and_url_override(monkeypatch):
    monkeypatch.delenv("CACTUS_DECIDER_BACKEND", raising=False)
    monkeypatch.delenv("CACTUS_DECIDER_URL", raising=False)
    assert decide.base_url("strands") == "http://127.0.0.1:8000"
    assert decide.base_url("clef") == "http://127.0.0.1:8001"
    monkeypatch.setenv("CACTUS_DECIDER_URL", "http://127.0.0.1:9/")
    assert decide.base_url("clef") == "http://127.0.0.1:9"


def test_setting_picks_backend_when_env_unset(stub, monkeypatch):
    monkeypatch.delenv("CACTUS_DECIDER_BACKEND", raising=False)
    stub["reply"] = _reply("a")
    assert decide.propose("t", None, CHOICES, backend="clef") is not None
    assert stub["seen"]["model"] == "clef-flash"


def test_override_short_circuits_backend(monkeypatch):
    monkeypatch.setenv("CACTUS_DECIDE", "a:0.5")
    assert decide.propose("t", None, CHOICES, backend="clef").label == "a"
    assert decide.available(backend="clef") is True
