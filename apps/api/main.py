from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packages.strategy_core.backtest import BacktestCosts, run_backtest
from packages.strategy_core.alpha_vantage import alpha_vantage_status
from packages.strategy_core.alpha_vantage import fetch_fx_intraday
from packages.strategy_core.data import load_candles
from packages.strategy_core.datasets import DatasetStore
from packages.strategy_core.datasets import Dataset
from packages.strategy_core.datasets import candles_from_payload
from packages.strategy_core.decision_log import evaluate_decisions, load_decisions, record_decision, update_decision_execution
from packages.strategy_core.market_hours import forex_market_status
from packages.strategy_core.market_hours import session_confidence_adjustment
from packages.strategy_core.market_hours import should_skip_forex_scan
from packages.strategy_core.execution import authorize_execution
from packages.strategy_core.execution import claim_order
from packages.strategy_core.execution import create_pending_order
from packages.strategy_core.execution import execution_status
from packages.strategy_core.execution import mark_order_close_notification_sent
from packages.strategy_core.execution import mark_order_result
from packages.strategy_core.execution import pending_order_eligibility
from packages.strategy_core.execution import pending_order
from packages.strategy_core.ml_model import train_signal_quality_model
from packages.strategy_core.openai_ai import explain_signal
from packages.strategy_core.openai_ai import openai_config_status
from packages.strategy_core.openai_ai import should_add_ai_to_telegram
from packages.strategy_core.signal_history import evaluate_history
from packages.strategy_core.signal_history import history_summary
from packages.strategy_core.signal_history import load_history
from packages.strategy_core.signal_history import mark_signal_close_notification_sent
from packages.strategy_core.signal_history import record_signal
from packages.strategy_core.signals import detect_forex_signal
from packages.strategy_core.telegram_alerts import format_signal_message
from packages.strategy_core.telegram_alerts import format_order_result_message
from packages.strategy_core.telegram_alerts import format_signal_result_message
from packages.strategy_core.telegram_alerts import mark_signal_sent
from packages.strategy_core.telegram_alerts import send_telegram_message
from packages.strategy_core.telegram_alerts import should_send_signal
from packages.strategy_core.telegram_alerts import telegram_config_status
from packages.strategy_core.twelve_data import fetch_time_series
from packages.strategy_core.twelve_data import twelve_data_status
from packages.strategy_core.validation import run_out_of_sample_validation
from packages.strategy_core.walk_forward import run_walk_forward_validation
from packages.strategy_core.profit_manager import get_profit_manager


DEFAULT_DATASET = ROOT / "data" / "forex" / "eurusd_m5_sample.csv"
EURUSD_D1_DATASET = ROOT / "data" / "forex" / "eurusd_d1_yahoo.csv"
EURUSD_M5_FBS_DATASET = ROOT / "data" / "forex" / "eurusd_m5_fbs_real_12m.csv"
WEB_ROOT = ROOT / "apps" / "web"
APP_VERSION = "0.33.0"
RUNTIME_DATA_DIR = Path(os.getenv("RUNTIME_DATA_DIR", str(ROOT / "data" / "uploads"))).expanduser()
DATASETS = DatasetStore(
    ROOT,
    DEFAULT_DATASET,
    bundled_datasets=[
        Dataset("eurusd-d1-yahoo", "EURUSD", "D1", EURUSD_D1_DATASET, 0),
        Dataset("eurusd-m5-fbs-real-12m", "EURUSD", "M5", EURUSD_M5_FBS_DATASET, 0),
    ],
    uploads=RUNTIME_DATA_DIR,
)
TELEGRAM_ALERT_STATE = RUNTIME_DATA_DIR / "telegram_alert_state.json"
TELEGRAM_STATUS_STATE = RUNTIME_DATA_DIR / "telegram_status_state.json"
JOB_STATE = RUNTIME_DATA_DIR / "job_state.json"
SIGNAL_HISTORY = RUNTIME_DATA_DIR / "signal_history.json"
EXECUTION_STATE = RUNTIME_DATA_DIR / "execution_state.json"
DECISION_LOG = RUNTIME_DATA_DIR / "decision_log.json"
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
            dataset = DATASETS.active_dataset()
            self.send_json(run_backtest(candles, costs=backtest_costs(parsed.query), symbol=dataset.symbol if dataset else "EURUSD").to_dict())
            return

        if parsed.path == "/ml/status":
            candles = load_candles(DATASETS.active_path())
            self.send_json(train_signal_quality_model(candles).to_dict())
            return

        if parsed.path == "/ml/validation":
            candles = load_candles(DATASETS.active_path())
            dataset = DATASETS.active_dataset()
            self.send_json(run_out_of_sample_validation(candles, costs=backtest_costs(parsed.query), symbol=dataset.symbol if dataset else "EURUSD").to_dict())
            return

        if parsed.path == "/ml/walk-forward":
            candles = load_candles(DATASETS.active_path())
            dataset = DATASETS.active_dataset()
            query = parse_qs(parsed.query)
            self.send_json(
                run_walk_forward_validation(
                    candles,
                    train_candles=query_int(query, "trainCandles", 80),
                    test_candles=query_int(query, "testCandles", 40),
                    step_candles=query_int(query, "stepCandles", 40),
                    min_confidence=query_float(query, "minConfidence", 0.58),
                    ml_threshold=query_float(query, "mlThreshold", 0.55),
                    costs=backtest_costs(parsed.query),
                    symbol=dataset.symbol if dataset else "EURUSD",
                )
            )
            return

        if parsed.path == "/alerts/telegram/status":
            self.send_json(telegram_config_status())
            return

        if parsed.path == "/ai/status":
            self.send_json(openai_config_status())
            return

        if parsed.path == "/market/alpha-vantage/status":
            self.send_json(alpha_vantage_status())
            return

        if parsed.path == "/market/twelve-data/status":
            self.send_json(twelve_data_status())
            return

        if parsed.path == "/market/forex/status":
            self.send_json(current_forex_status())
            return

        if parsed.path == "/jobs/status":
            self.send_json(read_job_state())
            return

        if parsed.path == "/signals/history":
            self.send_json(current_signal_history())
            return

        if parsed.path == "/signals/decisions":
            decisions = load_decisions(DECISION_LOG)
            self.send_json({"decisions": decisions[-500:], "total": len(decisions)})
            return

        if parsed.path == "/execution/status":
            self.send_json(execution_status(EXECUTION_STATE))
            return

        if parsed.path == "/execution/pending":
            query = parse_qs(parsed.query)
            payload = {"secret": (query.get("secret") or [""])[0]}
            if not authorize_execution(self.headers, payload):
                self.send_json({"error": "execucao nao autorizada"}, status=401)
                return
            self.send_json(pending_order(EXECUTION_STATE))
            return

        if parsed.path == "/profit-manager/status":
            pm = get_profit_manager()
            self.send_json(pm.to_dict())
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
                    source_timezone=str(payload.get("sourceTimezone") or "").strip() or None,
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
                ai_allowed, _ = pending_order_eligibility(signal, EXECUTION_STATE)
                result = send_telegram_message(format_signal_message(signal, ai_note=optional_ai_note(signal, ai_allowed)))
                history_item = (
                    record_signal(signal, SIGNAL_HISTORY, candles[-1].time if candles else None)
                    if signal.side != "NO_TRADE"
                    else None
                )
                self.send_json(
                    {
                        "sent": True,
                        "telegramOk": bool(result.get("ok")),
                        "signal": signal.to_dict(),
                        "history": history_item,
                    }
                )
                return

            if parsed.path == "/alerts/telegram/check-latest":
                result = check_and_send_latest_alert()
                save_job_state("manual-check", result)
                self.send_json(result)
                return

            if parsed.path == "/ai/explain-latest-signal":
                self.send_json(explain_signal(latest_signal()))
                return

            if parsed.path == "/execution/claim":
                payload = self.read_json(max_size=4_000)
                if not authorize_execution(self.headers, payload):
                    self.send_json({"error": "execucao nao autorizada"}, status=401)
                    return
                self.send_json(
                    claim_order(
                        EXECUTION_STATE,
                        str(payload.get("id") or ""),
                        str(payload.get("accountMode") or ""),
                    )
                )
                return

            if parsed.path == "/execution/result":
                payload = self.read_json(max_size=10_000)
                if not authorize_execution(self.headers, payload):
                    self.send_json({"error": "execucao nao autorizada"}, status=401)
                    return
                order_id = str(payload.get("id") or "")
                result = mark_order_result(EXECUTION_STATE, order_id, payload)
                update_decision_execution(DECISION_LOG, order_id, payload)
                if result.get("shouldNotify") and isinstance(result.get("order"), dict):
                    try:
                        telegram = send_telegram_message(format_order_result_message(result["order"]))
                        result["telegramOk"] = bool(telegram.get("ok"))
                        mark_order_close_notification_sent(EXECUTION_STATE, order_id)
                    except Exception as error:
                        result["telegramOk"] = False
                        result["telegramError"] = str(error)
                self.send_json(result)
                return

            if parsed.path == "/jobs/check-alerts":
                payload = self.read_json(max_size=2_000)
                if not self.authorized_job(payload):
                    self.send_json({"error": "job nao autorizado"}, status=401)
                    return
                result = check_and_send_latest_alert()
                save_job_state("check-alerts", result)
                self.send_json(result)
                return

            if parsed.path == "/profit-manager/update":
                payload = self.read_json(max_size=10_000)
                if not authorize_execution(self.headers, payload):
                    self.send_json({"error": "execucao nao autorizada"}, status=401)
                    return
                pm = get_profit_manager()
                result = pm.update_trade_price(
                    str(payload.get("order_id") or ""),
                    float(payload.get("current_price") or 0),
                )
                self.send_json({"adjusted": result is not None, "adjustment": result})
                return

            if parsed.path == "/profit-manager/remove":
                payload = self.read_json(max_size=4_000)
                if not authorize_execution(self.headers, payload):
                    self.send_json({"error": "execucao nao autorizada"}, status=401)
                    return
                pm = get_profit_manager()
                pm.remove_trade(str(payload.get("order_id") or ""))
                self.send_json({"removed": True})
                return

            if parsed.path == "/profit-manager/config":
                payload = self.read_json(max_size=10_000)
                if not authorize_execution(self.headers, payload):
                    self.send_json({"error": "execucao nao autorizada"}, status=401)
                    return
                pm = get_profit_manager()
                if "enabled" in payload:
                    pm.config.enabled = bool(payload["enabled"])
                if "max_daily_loss_pips" in payload:
                    pm.config.max_daily_loss_pips = float(payload["max_daily_loss_pips"])
                self.send_json({"updated": True, "config": pm.to_dict()})
                return

            if parsed.path == "/jobs/twelve-data-scan":

                payload = self.read_json_optional(max_size=4_000)
                if not self.authorized_job(payload):
                    self.send_json({"error": "job nao autorizado"}, status=401)
                    return
                result = refresh_twelve_data_and_alert(payload)
                save_job_state("twelve-data-scan", result)
                self.send_json(result, status=201)
                return

            self.send_json({"error": "route not found"}, status=404)
        except ValueError as error:
            if parsed.path.startswith("/jobs/"):
                save_job_state("job-error", {"sent": False, "reason": str(error), "error": str(error)})
            self.send_json({"error": str(error)}, status=400)

    def read_json_optional(self, max_size: int = 200_000) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > max_size:
            raise ValueError("Arquivo muito grande para este prototipo")
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("JSON invalido")
        return payload

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Job-Secret, X-Market-Secret")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {redact_log_line(format % args)}")


def run_server() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    start_auto_scan_worker()
    server = HTTPServer((host, port), TradingApiHandler)
    print(f"Trading AI Hub API running at http://{host}:{port}", flush=True)
    server.serve_forever()


def start_auto_scan_worker() -> None:
    if os.getenv("AUTO_SCAN_ENABLED", "true").lower() != "true":
        print("Auto scan disabled.", flush=True)
        return
    worker = threading.Thread(target=auto_scan_loop, name="auto-scan-worker", daemon=True)
    worker.start()


def auto_scan_loop() -> None:
    interval = max(900, int(os.getenv("AUTO_SCAN_INTERVAL_SECONDS", "900")))
    initial_delay = int(os.getenv("AUTO_SCAN_INITIAL_DELAY_SECONDS", "20"))
    print(f"Auto scan enabled. First run in {initial_delay}s, interval {interval}s.", flush=True)
    time.sleep(max(0, initial_delay))
    while True:
        try:
            result = refresh_twelve_data_and_alert({})
            save_job_state("auto-scan", result)
            print(f"Auto scan result: {json.dumps(result, ensure_ascii=False)}", flush=True)
        except Exception as error:
            result = {"sent": False, "reason": str(error), "error": str(error)}
            save_job_state("auto-scan-error", result)
            print(f"Auto scan error: {error}", flush=True)
            if "429" in str(error):
                time.sleep(max(900, interval))
                continue
        time.sleep(max(60, interval))


def redact_log_line(value: str) -> str:
    return re.sub(r"(secret=)[^&\s\"]+", r"\1***", value)


def query_float(query: dict[str, list[str]], name: str, default: float) -> float:
    raw = (query.get(name) or [str(default)])[0]
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    raw = (query.get(name) or [str(default)])[0]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def backtest_costs(raw_query: str) -> BacktestCosts:
    query = parse_qs(raw_query)
    return BacktestCosts(
        spread_pips=query_float(query, "spreadPips", float(os.getenv("BACKTEST_SPREAD_PIPS", "0"))),
        slippage_pips=query_float(query, "slippagePips", float(os.getenv("BACKTEST_SLIPPAGE_PIPS", "0"))),
        commission_pips=query_float(query, "commissionPips", float(os.getenv("BACKTEST_COMMISSION_PIPS", "0"))),
    )


def latest_signal() -> object:
    dataset = DATASETS.active_dataset()
    candles = load_candles(DATASETS.active_path())
    return detect_forex_signal(
        candles,
        symbol=dataset.symbol if dataset else "EURUSD",
        timeframe=dataset.timeframe if dataset else "M5",
    )


def check_and_send_latest_alert() -> dict[str, object]:
    dataset = DATASETS.active_dataset()
    candles = load_candles(DATASETS.active_path())
    signal = detect_forex_signal(
        candles,
        symbol=dataset.symbol if dataset else "EURUSD",
        timeframe=dataset.timeframe if dataset else "M5",
    )
    signal = apply_stored_mtf_confirmation(signal)
    signal = apply_session_adjustment(signal)
    should_send, reason = should_send_signal(signal, TELEGRAM_ALERT_STATE)
    execution = create_execution_for_signal(signal, candles[-1].time if candles else None)
    decision = record_decision(
        DECISION_LOG,
        candles[-1].time if candles else None,
        signal,
        should_send,
        reason,
        execution,
    )
    history_item = None
    if not should_send:
        if execution.get("created"):
            history_item = record_signal(signal, SIGNAL_HISTORY, candles[-1].time if candles else None)
        return {
            "sent": False,
            "reason": reason,
            "signal": signal.to_dict(),
            "history": history_item,
            "execution": execution,
            "decision": decision,
        }
    ai_allowed = bool(execution.get("created"))
    result = send_telegram_message(
        format_signal_message(
            signal,
            ai_note=optional_ai_note(signal, ai_allowed),
            execution_note=format_execution_note(execution),
        )
    )
    mark_signal_sent(signal, TELEGRAM_ALERT_STATE)
    history_item = record_signal(signal, SIGNAL_HISTORY, candles[-1].time if candles else None)
    return {
        "sent": True,
        "telegramOk": bool(result.get("ok")),
        "signal": signal.to_dict(),
        "history": history_item,
        "execution": execution,
        "decision": decision,
    }


def create_execution_for_signal(signal: object, candle_time: str | None) -> dict[str, object]:
    return create_pending_order(signal, EXECUTION_STATE, candle_time)


def format_execution_note(execution: dict[str, object]) -> str:
    if execution.get("created"):
        return "MT5: ordem pendente criada para o robo."
    return f"MT5: nao enviado - {execution.get('reason') or 'filtro operacional'}."


def refresh_twelve_data_and_alert(payload: dict[str, object]) -> dict[str, object]:
    skip_scan, market = should_skip_forex_scan(payload)
    if skip_scan:
        return {
            "skipped": True,
            "reason": "Mercado Forex fechado. Job automatico pausado ate a reabertura.",
            "market": market,
        }

    symbol = str(payload.get("symbol") or os.getenv("WATCH_SYMBOL") or "EURUSD")
    timeframe = str(payload.get("timeframe") or os.getenv("WATCH_TIMEFRAME") or "M5")
    outputsize = int(payload.get("outputsize") or os.getenv("WATCH_OUTPUTSIZE") or 120)
    candles = fetch_time_series(symbol, timeframe, outputsize)
    dataset = DATASETS.save_candles(symbol=symbol, timeframe=timeframe, candles=candles)
    confirmation_datasets = refresh_confirmation_timeframes(symbol, timeframe)
    performance = evaluate_history(SIGNAL_HISTORY, candles)
    decision_performance = evaluate_decisions(DECISION_LOG, candles)
    paper_notifications = notify_closed_paper_signals(performance)
    alert = check_and_send_latest_alert()
    market = forex_market_status(candles)
    dataset_payload = dataset.to_dict(DATASETS.active_id())
    status_update = maybe_send_monitor_status(alert, market, dataset_payload, len(candles))
    return {
        "skipped": False,
        "market": market,
        "dataset": dataset_payload,
        "candles": len(candles),
        "alert": alert,
        "statusUpdate": status_update,
        "performance": performance,
        "decisionPerformance": decision_performance,
        "paperNotifications": paper_notifications,
        "confirmations": confirmation_datasets,
    }


def notify_closed_paper_signals(performance: dict[str, object]) -> dict[str, object]:
    if os.getenv("TELEGRAM_SEND_PAPER_RESULTS", "true").lower() != "true":
        return {"sent": 0, "reason": "resultado paper desativado"}

    candidates: list[dict[str, object]] = []
    closed_now = performance.get("closedNow")
    if isinstance(closed_now, list):
        candidates.extend([item for item in closed_now if isinstance(item, dict)])
    recent_signals = performance.get("signals")
    if isinstance(recent_signals, list):
        candidates.extend(
            [
                item
                for item in recent_signals
                if isinstance(item, dict)
                and item.get("status") in {"WIN", "LOSS"}
                and not item.get("closeNotificationSent")
            ]
        )
    if not candidates:
        return {"sent": 0, "reason": "sem fechamentos"}

    sent = 0
    errors: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item.get("closeNotificationSent"):
            continue
        key = str(item.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            result = send_telegram_message(format_signal_result_message(item))
            if result.get("ok"):
                sent += 1
                mark_signal_close_notification_sent(SIGNAL_HISTORY, key)
        except Exception as error:
            errors.append(str(error))
    return {"sent": sent, "errors": errors}


def refresh_confirmation_timeframes(symbol: str, primary_timeframe: str) -> list[dict[str, object]]:
    if os.getenv("MTF_CONFIRMATION_ENABLED", "true").lower() != "true":
        return []
    timeframes = [
        item.strip().upper()
        for item in os.getenv("MTF_CONFIRM_TIMEFRAMES", "M15,H1").split(",")
        if item.strip()
    ]
    saved: list[dict[str, object]] = []
    for timeframe in timeframes:
        if timeframe == primary_timeframe.upper():
            continue
        try:
            candles = fetch_time_series(symbol, timeframe, int(os.getenv("MTF_OUTPUTSIZE", "120")))
            dataset = DATASETS.save_candles(symbol=symbol, timeframe=timeframe, candles=candles)
            saved.append(dataset.to_dict(DATASETS.active_id()))
        except ValueError as error:
            print(f"MTF confirmation skipped for {timeframe}: {error}", flush=True)
    primary = DATASETS.get(f"{symbol.lower()}-{primary_timeframe.lower()}")
    if primary:
        DATASETS.set_active(primary.id)
    return saved


def apply_stored_mtf_confirmation(signal: object) -> object:
    if os.getenv("MTF_CONFIRMATION_ENABLED", "true").lower() != "true":
        return signal
    if getattr(signal, "side", "NO_TRADE") == "NO_TRADE":
        return signal

    bonus = 0.0
    reasons: list[str] = []
    for timeframe in [
        item.strip().upper()
        for item in os.getenv("MTF_CONFIRM_TIMEFRAMES", "M15,H1").split(",")
        if item.strip()
    ]:
        dataset = DATASETS.get(f"{signal.symbol.lower()}-{timeframe.lower()}")
        if not dataset:
            reasons.append(f"{timeframe} sem dados para confirmacao")
            continue
        candles = load_candles(dataset.path)
        trend = timeframe_bias(candles)
        if trend == signal.side:
            bonus += float(os.getenv("MTF_CONFIRM_BONUS", "0.05"))
            reasons.append(f"{timeframe} confirma {signal.side}")
        elif trend == "NEUTRAL":
            reasons.append(f"{timeframe} neutro")
        else:
            bonus -= float(os.getenv("MTF_CONFLICT_PENALTY", "0.08"))
            reasons.append(f"{timeframe} contra {signal.side}")
    return signal.with_adjustment(bonus, reasons)


def apply_session_adjustment(signal: object) -> object:
    if os.getenv("SESSION_CONFIDENCE_ENABLED", "true").lower() != "true":
        return signal
    if getattr(signal, "side", "NO_TRADE") == "NO_TRADE":
        return signal
    adjustment = session_confidence_adjustment()
    return signal.with_adjustment(float(adjustment["delta"]), [str(adjustment["reason"])])


def timeframe_bias(candles: list[object]) -> str:
    closes = [candle.close for candle in candles]
    if len(closes) < 20:
        return "NEUTRAL"
    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-20:]) / 20
    last = closes[-1]
    spread = abs(fast - slow) / max(last, 0.00001)
    if spread < 0.00008:
        return "NEUTRAL"
    if fast > slow and last >= fast:
        return "BUY"
    if fast < slow and last <= fast:
        return "SELL"
    return "NEUTRAL"


def current_forex_status() -> dict[str, object]:
    try:
        candles = load_candles(DATASETS.active_path())
    except ValueError:
        candles = []
    return forex_market_status(candles)


def current_signal_history() -> dict[str, object]:
    try:
        candles = load_candles(DATASETS.active_path())
    except ValueError:
        candles = []
    if candles:
        return evaluate_history(SIGNAL_HISTORY, candles)
    return history_summary(load_history(SIGNAL_HISTORY))


def save_job_state(job: str, result: dict[str, object]) -> None:
    JOB_STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job": job,
        "lastRunAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": result,
    }
    JOB_STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_state() -> dict[str, object]:
    if not JOB_STATE.exists():
        return {"configured": True, "lastRunAt": None, "result": None}
    try:
        payload = json.loads(JOB_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"configured": True, "lastRunAt": None, "result": None, "error": "estado do job invalido"}
    return payload if isinstance(payload, dict) else {"configured": True, "lastRunAt": None, "result": None}


def maybe_send_monitor_status(
    alert: dict[str, object],
    market: dict[str, object],
    dataset: dict[str, object],
    candles: int,
) -> dict[str, object]:
    if os.getenv("TELEGRAM_SEND_MONITOR_STATUS", "false").lower() != "true":
        return {"sent": False, "reason": "status/no-trade desativado"}
    if alert.get("sent") is True:
        return {"sent": False, "reason": "sinal operacional ja enviado"}

    interval_minutes = int(os.getenv("TELEGRAM_STATUS_EVERY_MINUTES", "240"))
    now = datetime.now(timezone.utc)
    last_sent = read_last_status_sent_at()
    if last_sent and (now - last_sent).total_seconds() < interval_minutes * 60:
        return {"sent": False, "reason": "aguardando intervalo do status"}

    signal = alert.get("signal") if isinstance(alert.get("signal"), dict) else {}
    message = "\n".join(
        [
            "Trading AI Hub",
            "",
            "Status do robo",
            f"Mercado: {'aberto' if market.get('isOpen') else 'fechado'}",
            f"Dataset: {dataset.get('symbol')} {dataset.get('timeframe')} | {candles} candles",
            f"Ultima leitura: {signal.get('side', 'NO_TRADE')}",
            f"Motivo: {alert.get('reason') or 'Sem sinal operacional.'}",
            "",
            "Aviso: status automatico, nao e recomendacao financeira.",
        ]
    )
    try:
        result = send_telegram_message(message)
    except ValueError as error:
        return {"sent": False, "reason": str(error)}
    mark_status_sent_at(now)
    return {"sent": True, "telegramOk": bool(result.get("ok"))}


def read_last_status_sent_at() -> datetime | None:
    if not TELEGRAM_STATUS_STATE.exists():
        return None
    try:
        payload = json.loads(TELEGRAM_STATUS_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = payload.get("lastSentAt")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def mark_status_sent_at(value: datetime) -> None:
    TELEGRAM_STATUS_STATE.parent.mkdir(parents=True, exist_ok=True)
    TELEGRAM_STATUS_STATE.write_text(
        json.dumps({"lastSentAt": value.isoformat(timespec="seconds")}, indent=2),
        encoding="utf-8",
    )


def optional_ai_note(signal: object, auto_trade_eligible: bool = False) -> str | None:
    if not should_add_ai_to_telegram():
        return None
    if os.getenv("AI_ONLY_FOR_AUTO_TRADE", "true").lower() != "false" and not auto_trade_eligible:
        return None
    try:
        explanation = explain_signal(signal)
    except Exception as error:
        print(f"AI explanation skipped: {error}", flush=True)
        return None
    text = explanation.get("text")
    return str(text) if text else None


if __name__ == "__main__":
    run_server()
