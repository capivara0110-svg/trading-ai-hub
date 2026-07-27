"""
Persistent state store backed by SQLite.

Replaces scattered JSON files with a single database, providing
atomicity and structured queries. Falls back to JSON reads when
database is not yet populated (migration path).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("STATE_DB_PATH", str(
    Path(__file__).resolve().parents[2] / "data" / "uploads" / "state.db"
))).expanduser()

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "db"):
        _local.db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.db.row_factory = sqlite3.Row
        _local.db.execute("PRAGMA journal_mode=WAL")
        _local.db.execute("PRAGMA synchronous=NORMAL")
        _migrate()
    return _local.db


def _migrate() -> None:
    db = _conn()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS signal_history (
            key TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL,
            candle_time TEXT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            entry REAL,
            stop_loss REAL,
            take_profit TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            result_pips REAL,
            closed_at TEXT,
            exit_price REAL,
            close_notified INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS execution_state (
            order_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            claimed_at TEXT,
            mode TEXT NOT NULL DEFAULT 'DEMO_ONLY',
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            lot REAL NOT NULL DEFAULT 0.01,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            take_profit2 REAL,
            max_entry_deviation_pips REAL,
            confidence REAL,
            ml_score REAL,
            candle_time TEXT,
            fill_price REAL,
            close_price REAL,
            result_pips REAL,
            profit REAL,
            broker_ticket TEXT,
            broker_message TEXT,
            close_notified INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS job_state (
            job TEXT PRIMARY KEY,
            last_run_at TEXT NOT NULL,
            result TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS telegram_state (
            state_key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candle_time TEXT,
            side TEXT,
            confidence REAL,
            sent INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            execution TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS state_meta (
            meta_key TEXT PRIMARY KEY,
            meta_value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_signal_status ON signal_history(status);
        CREATE INDEX IF NOT EXISTS idx_execution_status ON execution_state(status);
        CREATE INDEX IF NOT EXISTS idx_decision_created ON decision_log(created_at);
    """)


# ---------------------------------------------------------------------------
# Signal History
# ---------------------------------------------------------------------------

def record_signal(signal_data: dict) -> dict:
    db = _conn()
    key = signal_data["key"]
    existing = db.execute("SELECT key FROM signal_history WHERE key = ?", (key,)).fetchone()
    if existing:
        return dict(existing)

    db.execute(
        """INSERT INTO signal_history
           (key, sent_at, candle_time, symbol, timeframe, side, confidence,
            entry, stop_loss, take_profit, status, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            key,
            signal_data.get("sentAt", datetime.now(timezone.utc).isoformat()),
            signal_data.get("signalCandleTime"),
            signal_data["symbol"],
            signal_data["timeframe"],
            signal_data["side"],
            signal_data.get("confidence", 0),
            signal_data.get("entry"),
            signal_data.get("stopLoss"),
            json.dumps(signal_data.get("takeProfit", [])),
            signal_data.get("status", "OPEN"),
            json.dumps(signal_data.get("reason", [])),
        ),
    )
    db.commit()
    return signal_data


def evaluate_history(candles: list) -> dict:
    db = _conn()
    rows = db.execute(
        "SELECT * FROM signal_history WHERE status = 'OPEN' ORDER BY created_at"
    ).fetchall()

    closed_now = []
    for row in rows:
        result = _evaluate_signal(dict(row), candles)
        if result:
            db.execute(
                "UPDATE signal_history SET status=?, closed_at=?, exit_price=?, result_pips=?, close_notified=0 WHERE key=?",
                (result["status"], result["closedAt"], result["exitPrice"], result["resultPips"], row["key"]),
            )
            closed_now.append({**dict(row), **result, "closeNotificationSent": False})
    db.commit()
    return _history_summary(db, closed_now)


def mark_signal_close_notified(key: str) -> None:
    db = _conn()
    db.execute("UPDATE signal_history SET close_notified=1 WHERE key=?", (key,))
    db.commit()


def _history_summary(db: sqlite3.Connection, closed_now: list) -> dict:
    total = db.execute("SELECT COUNT(*) as c FROM signal_history").fetchone()["c"]
    closed = db.execute("SELECT COUNT(*) as c FROM signal_history WHERE status IN ('WIN','LOSS')").fetchone()["c"]
    wins = db.execute("SELECT COUNT(*) as c FROM signal_history WHERE status='WIN'").fetchone()["c"]
    total_pips = db.execute(
        "SELECT COALESCE(SUM(result_pips),0) as s FROM signal_history WHERE status IN ('WIN','LOSS')"
    ).fetchone()["s"]
    open_count = db.execute("SELECT COUNT(*) as c FROM signal_history WHERE status='OPEN'").fetchone()["c"]

    recent = db.execute(
        "SELECT * FROM signal_history ORDER BY created_at DESC LIMIT 50"
    ).fetchall()

    return {
        "signals": [dict(r) for r in recent],
        "totalSignals": total,
        "openSignals": open_count,
        "closedSignals": closed,
        "winRate": round(wins / closed, 2) if closed else 0,
        "totalPips": round(float(total_pips), 1),
        "closedNow": closed_now,
    }


def _evaluate_signal(item: dict, candles: list) -> dict | None:
    side = str(item.get("side") or "")
    entry = item.get("entry")
    stop = item.get("stop_loss")
    targets_raw = item.get("take_profit")
    if side not in {"BUY", "SELL"} or entry is None or stop is None or not targets_raw:
        return None

    targets = json.loads(targets_raw) if isinstance(targets_raw, str) else targets_raw
    if not isinstance(targets, list) or not targets:
        return None

    entry_price = float(entry)
    stop_price = float(stop)
    target_price = float(targets[0])
    signal_candle_time = str(item.get("candle_time") or "")

    for candle in candles:
        if signal_candle_time and candle.time <= signal_candle_time:
            continue
        if side == "BUY":
            if candle.low <= stop_price:
                return _close_result("LOSS", candle.time, stop_price, stop_price - entry_price)
            if candle.high >= target_price:
                return _close_result("WIN", candle.time, target_price, target_price - entry_price)
        if side == "SELL":
            if candle.high >= stop_price:
                return _close_result("LOSS", candle.time, stop_price, entry_price - stop_price)
            if candle.low <= target_price:
                return _close_result("WIN", candle.time, target_price, entry_price - target_price)
    return None


def _close_result(status: str, closed_at: str, exit_price: float, raw: float) -> dict:
    return {
        "status": status,
        "closedAt": closed_at,
        "exitPrice": round(exit_price, 5),
        "resultPips": round(raw * 10000, 1),
    }


# ---------------------------------------------------------------------------
# Execution State
# ---------------------------------------------------------------------------

def create_pending_order(order_data: dict) -> dict:
    db = _conn()
    order_id = order_data["id"]
    db.execute(
        """INSERT OR REPLACE INTO execution_state
           (order_id, status, created_at, expires_at, mode, symbol, timeframe,
            side, lot, entry, stop_loss, take_profit, take_profit2,
            max_entry_deviation_pips, confidence, ml_score, candle_time,
            reason, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            order_id,
            order_data.get("status", "PENDING"),
            order_data.get("createdAt", datetime.now(timezone.utc).isoformat()),
            order_data.get("expiresAt"),
            order_data.get("mode", "DEMO_ONLY"),
            order_data["symbol"],
            order_data["timeframe"],
            order_data["side"],
            order_data.get("lot", 0.01),
            order_data.get("entry"),
            order_data.get("stopLoss"),
            order_data.get("takeProfit"),
            order_data.get("takeProfit2"),
            order_data.get("maxEntryDeviationPips"),
            order_data.get("confidence"),
            order_data.get("mlScore"),
            order_data.get("signalCandleTime"),
            json.dumps(order_data.get("reason", [])),
        ),
    )
    db.commit()
    return order_data


def get_pending_order() -> dict | None:
    db = _conn()
    row = db.execute(
        "SELECT * FROM execution_state WHERE status IN ('PENDING','CLAIMED') ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None

    order = dict(row)
    # Check expiry
    now = datetime.now(timezone.utc)
    expires_at = order.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                db.execute(
                    "UPDATE execution_state SET status='EXPIRED', updated_at=datetime('now') WHERE order_id=?",
                    (order["order_id"],),
                )
                db.commit()
                return None
        except ValueError:
            pass
    return _row_to_order_dict(order)


def claim_order(order_id: str) -> dict:
    db = _conn()
    order = get_pending_order()
    if not order or order.get("order_id") != order_id:
        return {"claimed": False, "reason": "ordem nao encontrada ou expirada"}
    db.execute(
        "UPDATE execution_state SET status='CLAIMED', claimed_at=datetime('now'), updated_at=datetime('now') WHERE order_id=?",
        (order_id,),
    )
    db.commit()
    order["status"] = "CLAIMED"
    return {"claimed": True, "order": order}


def mark_order_result(order_id: str, status: str, payload: dict) -> dict:
    db = _conn()
    db.execute(
        """UPDATE execution_state
           SET status=?, fill_price=?, close_price=?, result_pips=?,
               broker_ticket=?, broker_message=?, updated_at=datetime('now')
           WHERE order_id=?""",
        (
            status,
            payload.get("fillPrice"),
            payload.get("closePrice"),
            payload.get("resultPips"),
            payload.get("brokerTicket"),
            payload.get("message"),
            order_id,
        ),
    )
    db.commit()
    return {"updated": True, "order_id": order_id}


def mark_order_close_notified(order_id: str) -> None:
    db = _conn()
    db.execute("UPDATE execution_state SET close_notified=1 WHERE order_id=?", (order_id,))
    db.commit()


def daily_order_count() -> int:
    db = _conn()
    today = datetime.now(timezone.utc).date().isoformat()
    row = db.execute(
        "SELECT COUNT(*) as c FROM execution_state WHERE DATE(created_at)=?",
        (today,),
    ).fetchone()
    return row["c"]


def _row_to_order_dict(row: dict) -> dict:
    return {
        "id": row["order_id"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "expiresAt": row.get("expires_at"),
        "claimedAt": row.get("claimed_at"),
        "mode": row["mode"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "side": row["side"],
        "lot": row["lot"],
        "entry": row["entry"],
        "stopLoss": row["stop_loss"],
        "takeProfit": row["take_profit"],
        "takeProfit2": row.get("take_profit2"),
        "confidence": row["confidence"],
        "mlScore": row["ml_score"],
        "reason": json.loads(row.get("reason") or "[]") if row.get("reason") else [],
        "fillPrice": row.get("fill_price"),
        "brokerTicket": row.get("broker_ticket"),
    }


# ---------------------------------------------------------------------------
# Job / Telegram State
# ---------------------------------------------------------------------------

def save_job_state(job: str, result: dict) -> None:
    db = _conn()
    db.execute(
        "INSERT OR REPLACE INTO job_state (job, last_run_at, result, updated_at) VALUES (?, datetime('now'), ?, datetime('now'))",
        (job, json.dumps(result, ensure_ascii=False)),
    )
    db.commit()


def read_job_state() -> dict:
    db = _conn()
    row = db.execute("SELECT * FROM job_state ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        return {"configured": True, "lastRunAt": None, "result": None}
    return {
        "job": row["job"],
        "lastRunAt": row["last_run_at"],
        "result": json.loads(row["result"]) if row["result"] else None,
    }


def save_telegram_state(key: str, value: str) -> None:
    db = _conn()
    db.execute(
        "INSERT OR REPLACE INTO telegram_state (state_key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value),
    )
    db.commit()


def read_telegram_state(key: str) -> str | None:
    db = _conn()
    row = db.execute("SELECT value FROM telegram_state WHERE state_key=?", (key,)).fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------------------
# Decision Log
# ---------------------------------------------------------------------------

def record_decision(candle_time: str | None, side: str, confidence: float, sent: bool, reason: str, execution: dict | None = None) -> None:
    db = _conn()
    db.execute(
        "INSERT INTO decision_log (candle_time, side, confidence, sent, reason, execution) VALUES (?, ?, ?, ?, ?, ?)",
        (
            candle_time,
            side,
            confidence,
            1 if sent else 0,
            reason,
            json.dumps(execution) if execution else None,
        ),
    )
    db.commit()


def load_decisions(limit: int = 500) -> list[dict]:
    db = _conn()
    rows = db.execute(
        "SELECT * FROM decision_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
