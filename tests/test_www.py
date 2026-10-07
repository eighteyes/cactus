"""
test_www.py — the web board's card renders a row's site as a safe link.
"""

from __future__ import annotations

from cactus.www import PAGE


def test_card_renders_site_as_escaped_blank_link() -> None:
    assert 'target="_blank" rel="noopener"' in PAGE
    # Only http(s) becomes a link, and the href is attribute-escaped.
    assert "/^https?:" in PAGE
    assert '.replace(/"/g, "&quot;")' in PAGE
    assert "esc(q.site)" in PAGE


# ---- CSRF / DNS-rebinding guard ---------------------------------------------

import http.client
import json
import threading

import pytest

from cactus.store import Choice
from cactus.www import _Server


@pytest.fixture
def www(store, project):
    q = store.ask("ship it?", project=project, cwd=project, kind="choice", choices=[Choice("approve"), Choice("deny")], agent="a1")
    server = _Server(("127.0.0.1", 0), store.path, None)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]

    def req(method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    yield req, port, q, store
    server.shutdown()
    server.server_close()


def _body(q):
    return json.dumps({"key": q.key, "project": q.project, "selected": ["approve"]})


def test_text_plain_post_is_415_and_row_stays_open(www) -> None:
    req, port, q, store = www
    status, _ = req("POST", "/api/answer", _body(q), {"Content-Type": "text/plain"})
    assert status == 415
    assert store.get(q.key, project=q.project).status == "open"


def test_json_post_without_origin_is_served(www) -> None:
    req, port, q, store = www
    status, _ = req("POST", "/api/answer", _body(q), {"Content-Type": "application/json; charset=utf-8"})
    assert status == 200
    assert store.get(q.key, project=q.project).status == "answered"


def test_foreign_origin_post_is_403(www) -> None:
    req, port, q, store = www
    h = {"Content-Type": "application/json", "Origin": "http://evil.example"}
    assert req("POST", "/api/answer", _body(q), h)[0] == 403
    assert store.get(q.key, project=q.project).status == "open"


def test_same_origin_post_is_served(www) -> None:
    req, port, q, store = www
    h = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}
    assert req("POST", "/api/answer", _body(q), h)[0] == 200


def test_foreign_host_is_403_and_localhost_is_200(www) -> None:
    req, port, q, store = www
    assert req("GET", "/api/feed", headers={"Host": "evil.example"})[0] == 403
    assert req("GET", "/api/feed", headers={"Host": f"localhost:{port}"})[0] == 200


def test_answer_pass_on_review_row_closes_it(www) -> None:
    req, port, q, store = www
    rq = store.ask("check", project=q.project, cwd=q.project, act="review", kind="confirm", agent="a1")
    body = json.dumps({"key": rq.key, "project": rq.project, "selected": ["pass"]})
    status, _ = req("POST", "/api/answer", body, {"Content-Type": "application/json"})
    assert status == 200
    assert store.get(rq.key, project=rq.project).status == "cleared"
