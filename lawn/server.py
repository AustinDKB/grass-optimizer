from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

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
        from lawn.daily import publish, run, save_yard

        n = int(self.headers.get("Content-Length") or 0)
        raw = json.loads(self.rfile.read(n) or b"{}")
        path = urlparse(self.path).path
        if path in ("/api/yard", "/yard"):
            yard = save_yard(raw)
            publish()
            self._json(200, yard.model_dump())
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
