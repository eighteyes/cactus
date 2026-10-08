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


# ---- token auth on a non-loopback bind ------------------------------------

from cactus.www import make_token, token_path  # noqa: E402


@pytest.fixture
def secured(store):
    token = make_token(store.path)
    server = _Server(("127.0.0.1", 0), store.path, None, token)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]

    def req(method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        return r.status, data, hdrs

    yield req, token, store
    server.shutdown()
    server.server_close()


def test_token_file_is_0600(store) -> None:
    make_token(store.path)
    assert oct(token_path(store.path).stat().st_mode & 0o777) == "0o600"


def test_loopback_bind_needs_no_token(www) -> None:
    req, port, q, store = www
    assert req("GET", "/api/feed")[0] == 200


def test_secured_routes_401_without_cookie(secured) -> None:
    req, token, store = secured
    assert req("GET", "/")[0] == 401
    assert req("GET", "/api/feed")[0] == 401
    assert req("GET", "/api/events")[0] == 401
    st, _, _ = req("POST", "/api/answer", body="{}", headers={"Content-Type": "application/json"})
    assert st == 401


def test_login_wrong_or_missing_token_is_401_no_cookie(secured) -> None:
    req, token, store = secured
    for path in ("/login", "/login?t=", "/login?t=nope"):
        st, _, hdrs = req("GET", path)
        assert st == 401 and "Set-Cookie" not in hdrs


def test_login_sets_cookie_and_unlocks(secured) -> None:
    req, token, store = secured
    st, _, hdrs = req("GET", f"/login?t={token}")
    assert st == 302 and hdrs["Location"] == "/"
    cookie = hdrs["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Max-Age=31536000" in cookie
    pair = cookie.split(";")[0]
    assert req("GET", "/api/feed", headers={"Cookie": pair})[0] == 200


def test_rotate_invalidates_old_cookie(secured) -> None:
    req, token, store = secured
    pair = f"cactus_token={token}"
    assert req("GET", "/api/feed", headers={"Cookie": pair})[0] == 200
    new = make_token(store.path, rotate=True)
    assert new != token
    assert req("GET", "/api/feed", headers={"Cookie": pair})[0] == 401
    assert req("GET", "/api/feed", headers={"Cookie": f"cactus_token={new}"})[0] == 200
