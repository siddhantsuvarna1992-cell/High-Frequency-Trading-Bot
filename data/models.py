"""Data models for market data."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Action(str, Enum):
    OPEN_LONG = "OPEN_LONG"
    CLOSE_LONG = "CLOSE_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_SHORT = "CLOSE_SHORT"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Tick:
    timestamp_ms: int
    price: float
    quantity: float
    is_buyer_maker: bool


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int
    is_closed: bool = False

    def to_dict(self) -> dict:
        return {
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_time": self.close_time,
            "quote_volume": self.quote_volume,
            "trades": self.trades,
        }


@dataclass
class OrderBookSnapshot:
    timestamp_ms: int
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, qty)
    asks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    status: OrderStatus
    timestamp_ms: int
    fee: float = 0.0

    @property
    def cost(self) -> float:
        return self.price * self.quantity


@dataclass
class Position:
    symbol: str = ""
    side: Side | None = None
    entry_price: float = 0.0
    quantity: float = 0.0
    highest_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time_ms: int = 0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0 and self.side is not None

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value if self.side else None,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "highest_price": self.highest_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "entry_time_ms": self.entry_time_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Position:
        pos = cls(
            symbol=d.get("symbol", ""),
            side=Side(d["side"]) if d.get("side") else None,
            entry_price=d.get("entry_price", 0.0),
            quantity=d.get("quantity", 0.0),
            highest_price=d.get("highest_price", 0.0),
            unrealized_pnl=d.get("unrealized_pnl", 0.0),
            realized_pnl=d.get("realized_pnl", 0.0),
            entry_time_ms=d.get("entry_time_ms", 0),
        )
        return pos
