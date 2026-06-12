"""
Profit Manager Inteligente - Gerenciamento de Lucro pelo Backend
Substitui o break-even limitado do EA MT5 por um sistema completo:
1. Trailing Stop Progressivo
2. Take Profit Parcial
3. Protecao de Lucro Minimo
4. Controle de Loss Diario e Cooloff
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class ProfitLevel:
    trigger_pips: float
    action: str
    lock_pips: float = 0.0
    partial_close_pct: float = 0.0
    description: str = ""


@dataclass
class ProfitManagerConfig:
    levels: list[ProfitLevel] = field(default_factory=lambda: [
        ProfitLevel(4.0, "lock_profit", 0.5, 0.0, "Trava 0.5 pip aos 4 pips"),
        ProfitLevel(6.0, "lock_profit", 1.5, 0.0, "Sobe trava p/ 1.5 aos 6 pips"),
        ProfitLevel(9.0, "lock_profit", 3.0, 0.0, "Trava 3 pips aos 9 pips"),
        ProfitLevel(12.0, "partial_tp", 5.0, 25.0, "Fecha 25% aos 12 pips, trava 5"),
        ProfitLevel(16.0, "lock_profit", 8.0, 0.0, "Metade garantida aos 16 pips"),
        ProfitLevel(22.0, "partial_tp", 12.0, 35.0, "Fecha +35% aos 22 pips, trava 12"),
        ProfitLevel(30.0, "lock_profit", 20.0, 0.0, "20 pips garantidos aos 30"),
        ProfitLevel(40.0, "partial_tp", 25.0, 50.0, "Fecha metade aos 40, trava 25"),
        ProfitLevel(50.0, "lock_profit", 40.0, 0.0, "40 pips garantidos aos 50"),
    ])
    trailing_step_pips: float = 0.8
    enabled: bool = True
    max_daily_loss_pips: float = 50.0
    cooloff_minutes_after_loss: int = 30


@dataclass
class ManagedTrade:
    order_id: str
    symbol: str
    direction: str
    entry_price: float
    current_sl: float
    current_tp: float
    volume: float
    highest_profit_pips: float = 0.0
    current_profit_pips: float = 0.0
    last_trailing_update_pips: float = 0.0
    original_volume: float = 0.0
    closed_volume: float = 0.0
    realized_profit: float = 0.0
    last_update_time: float = 0.0
    active_levels: list[int] = field(default_factory=list)
    broker_ticket: str = ""

    def __post_init__(self):
        self.original_volume = self.volume


class ProfitManager:
    def __init__(self, config=None):
        self.config = config or ProfitManagerConfig()
        self.trades = {}
        self.daily_loss_pips = 0.0
        self.daily_wins = 0
        self.daily_losses = 0
        self.daily_trades = 0
        self.last_reset_day = ""
        self.cooloff_until = 0.0
        self.trade_history = []

    def _check_daily_reset(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.last_reset_day:
            self.daily_loss_pips = 0.0
            self.daily_wins = 0
            self.daily_losses = 0
            self.daily_trades = 0
            self.last_reset_day = today

    def can_trade(self):
        self._check_daily_reset()
        if not self.config.enabled:
            return True, "Gerenciamento desabilitado"
        if self.daily_loss_pips >= self.config.max_daily_loss_pips:
            return False, f"Loss diario maximo: {self.daily_loss_pips:.1f}/{self.config.max_daily_loss_pips} pips"
        if time.time() < self.cooloff_until:
            remaining = int(self.cooloff_until - time.time())
            return False, f"Cooloff por +{remaining}s"
        return True, "OK"

    def register_trade(self, order_id, symbol, direction, entry_price, sl, tp, volume, broker_ticket=""):
        trade = ManagedTrade(
            order_id=order_id, symbol=symbol, direction=direction,
            entry_price=entry_price, current_sl=sl, current_tp=tp,
            volume=volume, broker_ticket=broker_ticket
        )
        self.trades[order_id] = trade
        self.daily_trades += 1
        return trade

    def update_trade_price(self, order_id, current_price):
        if order_id not in self.trades:
            return None
        trade = self.trades[order_id]
        pip_mult = 10000.0
        if trade.direction == "buy":
            profit_pips = (current_price - trade.entry_price) * pip_mult
        else:
            profit_pips = (trade.entry_price - current_price) * pip_mult
        trade.current_profit_pips = profit_pips
        if profit_pips > trade.highest_profit_pips:
            trade.highest_profit_pips = profit_pips
        adjustments = self._process_adjustments(trade)
        trade.last_update_time = time.time()
        if adjustments:
            return {
                "order_id": order_id,
                "ticket": trade.broker_ticket,
                "new_sl": adjustments.get("new_sl"),
                "partial_close_pct": adjustments.get("partial_close_pct"),
                "partial_close_volume": adjustments.get("partial_close_volume"),
                "reason": adjustments.get("reason", ""),
                "profit_pips": round(profit_pips, 1),
                "highest_pips": round(trade.highest_profit_pips, 1),
            }
        return None

    def _find_max_locked(self, trade):
        max_lock = 0.0
        for i in trade.active_levels:
            if i < len(self.config.levels):
                if self.config.levels[i].lock_pips > max_lock:
                    max_lock = self.config.levels[i].lock_pips
        return max_lock

    def _process_adjustments(self, trade):
        if not self.config.enabled:
            return None
        profit = trade.current_profit_pips
        highest = trade.highest_profit_pips
        for i, level in enumerate(self.config.levels):
            if i in trade.active_levels:
                continue
            if profit >= level.trigger_pips:
                trade.active_levels.append(i)
                if level.action == "partial_tp" and level.partial_close_pct > 0:
                    close_vol = trade.volume * (level.partial_close_pct / 100)
                    if close_vol > 0 and trade.volume > 0:
                        trade.volume -= close_vol
                        trade.closed_volume += close_vol
                        new_sl = self._calc_sl_price(trade, level.lock_pips)
                        return {
                            "action": "partial_close",
                            "new_sl": new_sl,
                            "partial_close_pct": level.partial_close_pct,
                            "partial_close_volume": close_vol,
                            "reason": level.description,
                        }
                new_sl = self._calc_sl_price(trade, level.lock_pips)
                if self._is_sl_better(trade, new_sl):
                    trade.current_sl = new_sl
                    return {"action": "modify_sl", "new_sl": new_sl, "reason": level.description}
        if len(trade.active_levels) > 0:
            max_locked = self._find_max_locked(trade)
            if max_locked > 0 and highest > 0:
                trail_distance = highest - profit
                if trail_distance < self.config.trailing_step_pips:
                    new_lock = max(max_locked, profit - self.config.trailing_step_pips)
                    new_sl = self._calc_sl_price(trade, new_lock)
                    if self._is_sl_better(trade, new_sl):
                        trade.current_sl = new_sl
                        return {
                            "action": "modify_sl",
                            "new_sl": new_sl,
                            "reason": f"Trailing: lucro {profit:.1f}, travando {new_lock:.1f}",
                        }
        return None

    def _calc_sl_price(self, trade, lock_pips):
        if trade.direction == "buy":
            return trade.entry_price + (lock_pips / 10000)
        else:
            return trade.entry_price - (lock_pips / 10000)

    def _is_sl_better(self, trade, new_sl):
        if trade.direction == "buy":
            return new_sl > trade.current_sl
        else:
            return new_sl < trade.current_sl

    def remove_trade(self, order_id):
        if order_id in self.trades:
            trade = self.trades[order_id]
            if trade.current_profit_pips > 0:
                self.daily_wins += 1
            else:
                self.daily_losses += 1
                loss_pips = abs(trade.current_profit_pips)
                self.daily_loss_pips += loss_pips
                if loss_pips > 10.0:
                    self.cooloff_until = time.time() + self.config.cooloff_minutes_after_loss * 60
            hist = {
                "order_id": order_id, "symbol": trade.symbol,
                "direction": trade.direction,
                "profit_pips": round(trade.current_profit_pips, 1),
                "highest_pips": round(trade.highest_profit_pips, 1),
                "closed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self.trade_history.append(hist)
            while len(self.trade_history) > 500:
                self.trade_history.pop(0)
            del self.trades[order_id]

    def get_status(self):
        self._check_daily_reset()
        win_rate = 0.0
        total = self.daily_wins + self.daily_losses
        if total > 0:
            win_rate = (self.daily_wins / total) * 100
        return {
            "enabled": self.config.enabled,
            "trades_managed": len(self.trades),
            "daily": {
                "trades": self.daily_trades,
                "wins": self.daily_wins,
                "losses": self.daily_losses,
                "win_rate_pct": round(win_rate, 1),
                "loss_pips": round(self.daily_loss_pips, 1),
                "max_loss_pips": self.config.max_daily_loss_pips,
                "can_trade": self.can_trade()[0],
            },
            "cooloff_seconds": max(0, int(self.cooloff_until - time.time())),
            "active_trades": [
                {
                    "order_id": t.order_id, "direction": t.direction,
                    "profit_pips": round(t.current_profit_pips, 1),
                    "highest_pips": round(t.highest_profit_pips, 1),
                    "locked_pips": round(self._find_max_locked(t), 1),
                    "volume": round(t.volume, 2),
                    "closed_volume": round(t.closed_volume, 2),
                    "ticket": t.broker_ticket,
                }
                for t in self.trades.values()
            ],
            "recent_history": self.trade_history[-20:],
        }

    def to_dict(self):
        return {
            "config": {
                "levels": [
                    {"trigger_pips": l.trigger_pips, "action": l.action,
                     "lock_pips": l.lock_pips,
                     "partial_close_pct": l.partial_close_pct,
                     "description": l.description}
                    for l in self.config.levels
                ],
                "trailing_step_pips": self.config.trailing_step_pips,
                "enabled": self.config.enabled,
                "max_daily_loss_pips": self.config.max_daily_loss_pips,
                "cooloff_minutes": self.config.cooloff_minutes_after_loss,
            },
            "status": self.get_status(),
        }


_manager = None

def get_profit_manager():
    global _manager
    if _manager is None:
        _manager = ProfitManager()
    return _manager

def reset_profit_manager():
    global _manager
    _manager = None
