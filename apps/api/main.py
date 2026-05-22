from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packages.strategy_core.backtest import run_backtest
from packages.strategy_core.data import load_candles
from packages.strategy_core.signals import detect_forex_signal


DEFAULT_DATASET = ROOT / "data" / "forex" / "eurusd_m5_sample.csv"
WEB_ROOT = ROOT / "apps" / "web"
APP_VERSION = "0.2.0"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class TradingApiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self.send_json(
                {
                    "status": "ok",
                    "project": "trading-ai-hub",
                    "version": APP_VERSION,
                    "dataset": DEFAULT_DATASET.name,
                }
            )
            return

        if parsed.path == "/signals/latest":
            candles = load_candles(DEFAULT_DATASET)
            self.send_json(detect_forex_signal(candles).to_dict())
            return

        if parsed.path == "/backtest":
            candles = load_candles(DEFAULT_DATASET)
            self.send_json(run_backtest(candles).to_dict())
            return

        if self.send_static(parsed.path):
            return

        self.send_json({"error": "route not found"}, status=404)

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, request_path: str) -> bool:
        relative_path = "index.html" if request_path == "/" else request_path.lstrip("/")
        file_path = (WEB_ROOT / relative_path).resolve()

        if WEB_ROOT not in file_path.parents and file_path != WEB_ROOT:
            return False

        if not file_path.is_file():
            return False

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run_server() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    server = HTTPServer((host, port), TradingApiHandler)
    print(f"Trading AI Hub API running at http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
