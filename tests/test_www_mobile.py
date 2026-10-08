"""
test_www_mobile.py — the web board's phone layout, PWA manifest, service worker and static files.

Responsibilities:
- Pin the mobile single-view markup and the PWA head tags in PAGE.
- Check the static whitelist: content types, sw.js headers, traversal 404s.
- Check the service worker never caches /api/*, /login, or query strings.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from cactus.www import PAGE, _Server


@pytest.fixture
def get(store):
    server = _Server(("127.0.0.1", 0), store.path, None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def _get(path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        headers = dict(r.getheaders())
        c.close()
        return r.status, headers, data

    yield _get
    server.shutdown()
    server.server_close()


def test_page_has_pwa_and_mobile_markup() -> None:
    assert '<link rel="manifest" href="/manifest.webmanifest">' in PAGE
    assert 'rel="apple-touch-icon"' in PAGE
    assert 'name="apple-mobile-web-app-capable"' in PAGE
    assert "viewport-fit=cover" in PAGE
    assert "env(safe-area-inset-bottom)" in PAGE
    assert "min-height: 44px" in PAGE
    assert "view-rail" in PAGE and "view-card" in PAGE
    assert "board offline" in PAGE
    assert "serviceWorker" in PAGE


def test_manifest(get) -> None:
    status, h, body = get("/manifest.webmanifest")
    assert status == 200
    assert h["Content-Type"].startswith("application/manifest+json")
    m = json.loads(body)
    assert m["name"] == "cactus" and m["display"] == "standalone"
    sizes = {(i["sizes"], i.get("purpose")) for i in m["icons"]}
    assert ("192x192", None) in sizes and ("512x512", None) in sizes
    assert ("512x512", "maskable") in sizes
    for i in m["icons"]:
        assert get(i["src"])[0] == 200


def test_sw_headers(get) -> None:
    status, h, _ = get("/sw.js")
    assert status == 200
    assert h["Content-Type"].startswith("text/javascript")
    assert h["Service-Worker-Allowed"] == "/"
    assert h["Cache-Control"] == "no-cache"


def test_sw_skips_api_login_and_queries(get) -> None:
    body = get("/sw.js")[2].decode()
    assert '"/api/"' in body and '"/login"' in body and "url.search" in body


@pytest.mark.parametrize("name", ["icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"])
def test_icons_are_png(get, name) -> None:
    status, h, body = get("/static/" + name)
    assert status == 200 and h["Content-Type"] == "image/png"
    assert body.startswith(b"\x89PNG")


@pytest.mark.parametrize("path", [
    "/static/../www.py", "/static/%2e%2e/www.py", "/static/%2e%2e%2fwww.py",
    "/static/sw.js/../../www.py", "/static/www.py", "/static/", "/static",
])
def test_static_traversal_and_unlisted_are_404(get, path) -> None:
    assert get(path)[0] == 404
