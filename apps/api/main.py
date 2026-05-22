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
from packages.strategy_core.alpha_vantage import alpha_vantage_status
from packages.strategy_core.alpha_vantage import fetch_fx_intraday
from packages.strategy_core.data import load_candles
from packages.strategy_core.datasets import DatasetStore
from packages.strategy_core.datasets import Dataset
from packages.strategy_core.datasets import candles_from_payload
from packages.strategy_core.ml_model import train_signal_quality_model
from packages.strategy_core.signals import detect_forex_signal
from packages.strategy_core.telegram_alerts import format_signal_message
from packages.strategy_core.telegram_alerts import mark_signal_sent
from packages.strategy_core.telegram_alerts import send_telegram_message
from packages.strategy_core.telegram_alerts import should_send_signal
from packages.strategy_core.telegram_alerts import telegram_config_status
from packages.strategy_core.twelve_data import fetch_time_series
from packages.strategy_core.twelve_data import twelve_data_status
from packages.strategy_core.validation import run_out_of_sample_validation


DEFAULT_DATASET = ROOT / "data" / "forex" / "eurusd_m5_sample.csv"
EURUSD_D1_DATASET = ROOT / "data" / "forex" / "eurusd_d1_yahoo.csv"
WEB_ROOT = ROOT / "apps" / "web"
APP_VERSION = "0.10.0"
DATASETS = DatasetStore(
    ROOT,
    DEFAULT_DATASET,
    bundled_datasets=[
        Dataset("eurusd-d1-yahoo", "EURUSD", "D1", EURUSD_D1_DATASET, 0),
    ],
)
TELEGRAM_ALERT_STATE = ROOT / "data" / "uploads" / "telegram_alert_state.json"
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
                    "dataset": DATASETS.active_path().name,
                }
            )
            return

        if parsed.path == "/datasets":
            active_id = DATASETS.active_id() or "sample-eurusd-m5"
            self.send_json({"datasets": [dataset.to_dict(active_id) for dataset in DATASETS.list()]})
            return

        if parsed.path == "/signals/latest":
            dataset = DATASETS.active_dataset()
            candles = load_candles(DATASETS.active_path())
            self.send_json(
                detect_forex_signal(
                    candles,
                    symbol=dataset.symbol if dataset else "EURUSD",
                    timeframe=dataset.timeframe if dataset else "M5",
                ).to_dict()
            )
            return

        if parsed.path == "/backtest":
            candles = load_candles(DATASETS.active_path())
            self.send_json(run_backtest(candles).to_dict())
            return

        if parsed.path == "/ml/status":
            candles = load_candles(DATASETS.active_path())
            self.send_json(train_signal_quality_model(candles).to_dict())
            return

        if parsed.path == "/ml/validation":
            candles = load_candles(DATASETS.active_path())
            self.send_json(run_out_of_sample_validation(candles).to_dict())
            return

        if parsed.path == "/alerts/telegram/status":
            self.send_json(telegram_config_status())
            return

        if parsed.path == "/market/alpha-vantage/status":
            self.send_json(alpha_vantage_status())
            return

        if parsed.path == "/market/twelve-data/status":
            self.send_json(twelve_data_status())
            return

        if self.send_static(parsed.path):
            return

        self.send_json({"error": "route not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path == "/datasets/select":
                payload = self.read_json()
                dataset = DATASETS.set_active(str(payload.get("id") or ""))
                self.send_json({"dataset": dataset.to_dict(DATASETS.active_id())})
                return

            if parsed.path == "/datasets/import":
                payload = self.read_json(max_size=1_200_000)
                dataset = DATASETS.save_csv(
                    symbol=str(payload.get("symbol") or ""),
                    timeframe=str(payload.get("timeframe") or ""),
                    content=str(payload.get("content") or ""),
                )
                self.send_json({"dataset": dataset.to_dict(DATASETS.active_id())}, status=201)
                return

            if parsed.path == "/market/candles":
                payload = self.read_json(max_size=2_500_000)
                if not self.authorized_market_ingest(payload):
                    self.send_json({"error": "ingestao nao autorizada"}, status=401)
                    return
                dataset = DATASETS.save_candles(
                    symbol=str(payload.get("symbol") or ""),
                    timeframe=str(payload.get("timeframe") or ""),
                    candles=candles_from_payload(payload.get("candles")),
                )
                response: dict[str, object] = {"dataset": dataset.to_dict(DATASETS.active_id())}
                if bool(payload.get("alert")):
                    response["alert"] = check_and_send_latest_alert()
                self.send_json(response, status=201)
                return

            if parsed.path == "/market/alpha-vantage/refresh":
                payload = self.read_json(max_size=20_000)
                if not self.authorized_market_ingest(payload):
                    self.send_json({"error": "ingestao nao autorizada"}, status=401)
                    return
                symbol = str(payload.get("symbol") or "EURUSD")
                timeframe = str(payload.get("timeframe") or "M5")
                outputsize = str(payload.get("outputsize") or "compact")
                candles = fetch_fx_intraday(symbol, timeframe, outputsize)
                dataset = DATASETS.save_candles(symbol=symbol, timeframe=timeframe, candles=candles)
                response: dict[str, object] = {"dataset": dataset.to_dict(DATASETS.active_id())}
                if bool(payload.get("alert")):
                    response["alert"] = check_and_send_latest_alert()
                self.send_json(response, status=201)
                return

            if parsed.path == "/market/twelve-data/refresh":
                payload = self.read_json(max_size=20_000)
                if not self.authorized_market_ingest(payload):
                    self.send_json({"error": "ingestao nao autorizada"}, status=401)
                    return
                symbol = str(payload.get("symbol") or "EURUSD")
                timeframe = str(payload.get("timeframe") or "M5")
                outputsize = int(payload.get("outputsize") or 100)
                candles = fetch_time_series(symbol, timeframe, outputsize)
                dataset = DATASETS.save_candles(symbol=symbol, timeframe=timeframe, candles=candles)
                response: dict[str, object] = {"dataset": dataset.to_dict(DATASETS.active_id())}
                if bool(payload.get("alert")):
                    response["alert"] = check_and_send_latest_alert()
                self.send_json(response, status=201)
                return

            if parsed.path == "/alerts/telegram/test":
                result = send_telegram_message(
                    "Trading AI Hub\n\nTeste de conexao Telegram realizado com sucesso.\n\nAviso: ambiente experimental."
                )
                self.send_json({"sent": True, "telegramOk": bool(result.get("ok"))})
                return

            if parsed.path == "/alerts/telegram/latest-signal":
                dataset = DATASETS.active_dataset()
                candles = load_candles(DATASETS.active_path())
                signal = detect_forex_signal(
                    candles,
                    symbol=dataset.symbol if dataset else "EURUSD",
                    timeframe=dataset.timeframe if dataset else "M5",
                )
                result = send_telegram_message(format_signal_message(signal))
                self.send_json({"sent": True, "telegramOk": bool(result.get("ok")), "signal": signal.to_dict()})
                return

            if parsed.path == "/alerts/telegram/check-latest":
                self.send_json(check_and_send_latest_alert())
                return

            if parsed.path == "/jobs/check-alerts":
                payload = self.read_json(max_size=2_000)
                if not self.authorized_job(payload):
                    self.send_json({"error": "job nao autorizado"}, status=401)
                    return
                self.send_json(check_and_send_latest_alert())
                return

            self.send_json({"error": "route not found"}, status=404)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)

    def read_json(self, max_size: int = 200_000) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Corpo da requisicao vazio")
        if length > max_size:
            raise ValueError("Arquivo muito grande para este prototipo")
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON invalido")
        return payload

    def authorized_job(self, payload: dict[str, object]) -> bool:
        expected = os.getenv("ALERT_JOB_SECRET")
        if not expected:
            raise ValueError("ALERT_JOB_SECRET nao configurado")
        provided = self.headers.get("X-Job-Secret") or str(payload.get("secret") or "")
        return provided == expected

    def authorized_market_ingest(self, payload: dict[str, object]) -> bool:
        expected = os.getenv("MARKET_INGEST_SECRET")
        if not expected:
            return True
        provided = self.headers.get("X-Market-Secret") or str(payload.get("secret") or "")
        return provided == expected

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run_server() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    server = HTTPServer((host, port), TradingApiHandler)
    print(f"Trading AI Hub API running at http://{host}:{port}", flush=True)
    server.serve_forever()


def latest_signal() -> object:
    dataset = DATASETS.active_dataset()
    candles = load_candles(DATASETS.active_path())
    return detect_forex_signal(
        candles,
        symbol=dataset.symbol if dataset else "EURUSD",
        timeframe=dataset.timeframe if dataset else "M5",
    )


def check_and_send_latest_alert() -> dict[str, object]:
    signal = latest_signal()
    should_send, reason = should_send_signal(signal, TELEGRAM_ALERT_STATE)
    if not should_send:
        return {"sent": False, "reason": reason, "signal": signal.to_dict()}
    result = send_telegram_message(format_signal_message(signal))
    mark_signal_sent(signal, TELEGRAM_ALERT_STATE)
    return {"sent": True, "telegramOk": bool(result.get("ok")), "signal": signal.to_dict()}


if __name__ == "__main__":
    run_server()
