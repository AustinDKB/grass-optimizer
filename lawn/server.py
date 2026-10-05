from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from pydantic import ValidationError

HOST, PORT = "127.0.0.1", 8025


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        from lawn.daily import LEDGER, ROOT, load_yard

        path = urlparse(self.path).path
        if path in ("/api/yard", "/yard"):
            self._json(200, load_yard().model_dump())
            return
        if path in ("/api/ledger", "/ledger"):
            rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
            self._json(200, rows)
            return
        if path in ("/api/state", "/state"):
            p = ROOT / "lawn_state.json"
            self._json(200, json.loads(p.read_text()) if p.exists() else {})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            self._post()
        except (ValueError, ValidationError) as e:
            msg = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
            self._json(400, {"error": msg})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _post(self) -> None:
        from lawn.daily import run, save_yard

        n = int(self.headers.get("Content-Length") or 0)
        raw = json.loads(self.rfile.read(n) or b"{}")
        path = urlparse(self.path).path
        if path in ("/api/yard", "/yard"):
            # Save, then recompute from today's cached weather so the page numbers move.
            yard = save_yard(raw)
            report = run()
            self._json(200, {"yard": yard.model_dump(), "state": json.loads(report.model_dump_json())})
            return
        if path in ("/api/run", "/run"):
            report = run()
            self._json(200, json.loads(report.model_dump_json()))
            return
        self._json(404, {"error": "not found"})


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
