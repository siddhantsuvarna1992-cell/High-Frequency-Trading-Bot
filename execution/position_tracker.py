"""Position state, PnL tracking, trade history, and state persistence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from data.models import Position, Side, OrderResult
from utils.logging import get_logger

log = get_logger("position")


@dataclass
class TradeRecord:
    entry_time_ms: int
    exit_time_ms: int
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fee: float

    def to_dict(self) -> dict:
        return self.__dict__


class PositionTracker:
    """Tracks open position, realized/unrealized PnL, trade history."""

    def __init__(self, symbol: str, state_dir: Path):
        self.symbol = symbol
        self._state_file = state_dir / "position_state.json"
        self.position = Position(symbol=symbol)
        self.trade_history: list[TradeRecord] = []
        self.daily_pnl: float = 0.0
        self.peak_equity: float = 0.0
        self.total_equity: float = 0.0
        self._last_save = 0.0

        self._load_state()

    def open_position(self, side: Side, price: float, quantity: float, fee: float = 0.0) -> None:
        """Open a new position."""
        self.position = Position(
            symbol=self.symbol,
            side=side,
            entry_price=price,
            quantity=quantity,
            highest_price=price,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            entry_time_ms=int(time.time() * 1000),
        )
        self.daily_pnl -= fee
        log.info(f"Opened {side.value} {quantity:.6f} @ {price:.2f} (fee: {fee:.4f})")

    def close_position(self, exit_price: float, fee: float = 0.0) -> float:
        """Close the current position and return realized PnL."""
        pos = self.position
        if not pos.is_open:
            return 0.0

        if pos.side == Side.BUY:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pnl -= fee
        self.daily_pnl += pnl

        record = TradeRecord(
            entry_time_ms=pos.entry_time_ms,
            exit_time_ms=int(time.time() * 1000),
            side=pos.side.value if pos.side else "",
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=pnl,
            fee=fee,
        )
        self.trade_history.append(record)

        log.info(
            f"Closed {pos.side.value if pos.side else '?'} {pos.quantity:.6f} "
            f"@ {exit_price:.2f} | PnL: ${pnl:+.2f}"
        )

        self.position = Position(symbol=self.symbol)
        return pnl

    def update_price(self, current_price: float) -> None:
        """Update unrealized PnL and highest price (for trailing stop)."""
        pos = self.position
        if not pos.is_open:
            return

        if pos.side == Side.BUY:
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
            pos.highest_price = max(pos.highest_price, current_price)
        elif pos.side == Side.SELL:
            pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity
            # For shorts, "highest_price" tracks lowest (most favorable)
            if pos.highest_price == 0 or current_price < pos.highest_price:
                pos.highest_price = current_price

    def update_equity(self, balance: float) -> None:
        """Update total equity and peak equity for drawdown tracking."""
        self.total_equity = balance + (self.position.unrealized_pnl if self.position.is_open else 0.0)
        self.peak_equity = max(self.peak_equity, self.total_equity)

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.total_equity) / self.peak_equity

    @property
    def recent_trades(self) -> list[TradeRecord]:
        return self.trade_history[-20:]

    @property
    def win_rate(self) -> float:
        if not self.trade_history:
            return 0.0
        wins = sum(1 for t in self.trade_history if t.pnl > 0)
        return wins / len(self.trade_history)

    def should_hard_stop(self, current_price: float, stop_pct: float) -> bool:
        """Check if hard stop loss is triggered."""
        pos = self.position
        if not pos.is_open:
            return False
        if pos.side == Side.BUY:
            return current_price <= pos.entry_price * (1 - stop_pct)
        else:
            return current_price >= pos.entry_price * (1 + stop_pct)

    def should_trailing_stop(self, current_price: float, trail_pct: float) -> bool:
        """Check if trailing stop is triggered."""
        pos = self.position
        if not pos.is_open or pos.highest_price == 0:
            return False
        if pos.side == Side.BUY:
            return current_price <= pos.highest_price * (1 - trail_pct)
        else:
            # For shorts, highest_price tracks the lowest price seen
            return current_price >= pos.highest_price * (1 + trail_pct)

    def save_state(self, force: bool = False) -> None:
        """Persist position and trade history to disk."""
        now = time.time()
        if not force and (now - self._last_save) < 30:
            return
        self._last_save = now

        state = {
            "position": self.position.to_dict(),
            "daily_pnl": self.daily_pnl,
            "peak_equity": self.peak_equity,
            "total_equity": self.total_equity,
            "trade_history": [t.to_dict() for t in self.trade_history[-100:]],
        }
        try:
            self._state_file.write_text(json.dumps(state, indent=2))
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def _load_state(self) -> None:
        """Load persisted state on startup."""
        if not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
            self.position = Position.from_dict(state.get("position", {}))
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.peak_equity = state.get("peak_equity", 0.0)
            self.total_equity = state.get("total_equity", 0.0)
            history = state.get("trade_history", [])
            self.trade_history = [TradeRecord(**t) for t in history]
            if self.position.is_open:
                log.info(
                    f"Restored position: {self.position.side.value if self.position.side else '?'} "
                    f"{self.position.quantity:.6f} @ {self.position.entry_price:.2f}"
                )
            log.info(f"Loaded state: daily_pnl=${self.daily_pnl:+.2f}, {len(self.trade_history)} trades")
        except Exception as e:
            log.warning(f"Failed to load state: {e}")

    def reset_daily(self) -> None:
        """Reset daily PnL counter (call at UTC midnight)."""
        log.info(f"Daily PnL reset. Previous: ${self.daily_pnl:+.2f}")
        self.daily_pnl = 0.0
