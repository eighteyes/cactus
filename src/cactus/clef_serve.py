"""
clef_serve.py — serve Cloudflare/clef-flash over local HTTP, SystemOne-shaped.

Responsibilities:
- Load the model once through the `joint_schema_model` code shipped in the
  Hugging Face repo (the card documents no server, only this Python API).
- Answer POST /v1/systemone by handing the body to its `systemone()` and
  returning the response body unchanged; answer GET /health.
- Bind 127.0.0.1 by default and run unauthenticated, like strands-decider.
- Exit 1 with the install command when torch/transformers are missing.

Run by `cactus decider start --backend clef`. Local only: the Workers AI
route is deliberately not here, because it would send row text to Cloudflare.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "Cloudflare/clef-flash"
INSTALL = "pip install torch transformers huggingface_hub pillow"


def _load(model_id: str):
    """(model, processor, systemone) for `model_id`; imports are lazy so a
    missing dependency reports itself instead of failing at import time."""
    import torch
    from huggingface_hub import snapshot_download

    path = snapshot_download(model_id)
    sys.path.insert(0, path)
    from joint_schema_model import load_release_model, systemone

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, processor = load_release_model(path, device=device)
    return model, processor, systemone


def serve(host: str, port: int, model_id: str = MODEL) -> int:
    try:
        model, processor, systemone = _load(model_id)
    except ImportError as exc:
        print(f"clef_serve: {exc}; install with: {INSTALL}", file=sys.stderr)
        return 1

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, code: int, payload: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, b'{"status": "ok"}')
            else:
                self._send(404, b"{}")

        def do_POST(self) -> None:
            if self.path != "/v1/systemone":
                self._send(404, b"{}")
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                reply = systemone(model, processor, json.loads(self.rfile.read(n)))
                self._send(200, json.dumps(reply).encode())
            except Exception as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode())

    ThreadingHTTPServer((host, port), Handler).serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="clef_serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--model", default=MODEL)
    args = p.parse_args(argv)
    return serve(args.host, args.port, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
