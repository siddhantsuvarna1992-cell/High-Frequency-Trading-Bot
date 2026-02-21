"""Central order coordinator: strategy -> risk check -> executor -> position update."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable

from config import settings
from data.models import Action, Side, OrderResult, Tick
from execution.position_tracker import PositionTracker
from strategy.signals import SignalBreakdown
from utils.helpers import RateLimiter
from utils.logging import get_logger

log = get_logger("orders")


@runtime_checkable
class Executor(Protocol):
    """Protocol for order execution backends (paper or live)."""

    balance: float

    async def place_market_order(
        self, symbol: str, side: Side, quantity: float, current_price: float
    ) -> OrderResult: ...

    def apply_pnl(self, pnl: float) -> None: ...


class OrderManager:
    """Coordinates signal actions through risk checks to order execution."""

    def __init__(self, executor: Executor, risk_manager, position_tracker: PositionTracker):
        self._executor = executor
        self._risk = risk_manager
        self._tracker = position_tracker
        self._cfg = settings
        self._rate_limiter = RateLimiter(settings.risk.max_orders_per_second)
        self._order_lock = asyncio.Lock()
        self._tick_count = 0

    async def handle_action(self, action: Action, signal: SignalBreakdown, price: float) -> None:
        """Process a strategy action through the full pipeline."""
        async with self._order_lock:
            pos = self._tracker.position

            # If we already have an open position
            if pos.is_open:
                if action == Action.OPEN_LONG and pos.side == Side.SELL:
                    # Close short, then open long
                    await self._close_position(price, "Signal reversal (short -> long)")
                    await self._open_position(Side.BUY, price, signal)
                elif action == Action.OPEN_SHORT and pos.side == Side.BUY:
                    # Close long, then open short
                    await self._close_position(price, "Signal reversal (long -> short)")
                    await self._open_position(Side.SELL, price, signal)
                elif action == Action.OPEN_LONG and pos.side == Side.BUY:
                    log.debug("Already in LONG position, holding")
                elif action == Action.OPEN_SHORT and pos.side == Side.SELL:
                    log.debug("Already in SHORT position, holding")
                return

            # No open position — open new
            if action == Action.OPEN_LONG:
                await self._open_position(Side.BUY, price, signal)
            elif action == Action.OPEN_SHORT:
                await self._open_position(Side.SELL, price, signal)

    async def check_stop_losses(self, tick: Tick) -> None:
        """Check hard stop and trailing stop on each N-th tick."""
        self._tick_count += 1
        if self._tick_count % self._cfg.stop_check_tick_interval != 0:
            return

        pos = self._tracker.position
        if not pos.is_open:
            return

        price = tick.price
        self._tracker.update_price(price)

        # Hard stop loss
        if self._tracker.should_hard_stop(price, self._cfg.risk.hard_stop_loss_pct):
            async with self._order_lock:
                await self._close_position(price, "HARD STOP LOSS")
            return

        # Trailing stop
        if self._tracker.should_trailing_stop(price, self._cfg.risk.trailing_stop_pct):
            async with self._order_lock:
                await self._close_position(price, "TRAILING STOP")
            return

    async def _open_position(self, side: Side, price: float, signal: SignalBreakdown) -> None:
        """Open a position after risk checks."""
        # Risk pre-trade check
        can_trade, reason = self._risk.check_can_open(
            side=side,
            price=price,
            balance=self._executor.balance,
            position=self._tracker.position,
            daily_pnl=self._tracker.daily_pnl,
            drawdown_pct=self._tracker.current_drawdown_pct,
        )
        if not can_trade:
            log.warning(f"Risk rejected: {reason}")
            return

        # Calculate position size
        quantity = self._calculate_quantity(price)
        if quantity <= 0:
            log.warning("Calculated quantity is 0, skipping")
            return

        await self._rate_limiter.acquire()
        result = await self._executor.place_market_order(
            self._cfg.symbol.symbol, side, quantity, price
        )

        if result.status.value == "FILLED":
            self._tracker.open_position(side, result.price, result.quantity, result.fee)
            self._tracker.update_equity(self._executor.balance)
            self._tracker.save_state()

    async def _close_position(self, price: float, reason: str) -> None:
        """Close the current position."""
        pos = self._tracker.position
        if not pos.is_open:
            return

        close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
        log.info(f"Closing position: {reason}")

        await self._rate_limiter.acquire()
        result = await self._executor.place_market_order(
            self._cfg.symbol.symbol, close_side, pos.quantity, price
        )

        if result.status.value == "FILLED":
            pnl = self._tracker.close_position(result.price, result.fee)
            self._executor.apply_pnl(pnl)
            self._risk.record_trade_result(pnl)
            self._tracker.update_equity(self._executor.balance)
            self._tracker.save_state(force=True)

    def _calculate_quantity(self, price: float) -> float:
        """Compute position size respecting risk limits."""
        balance = self._executor.balance
        max_by_pct = balance * self._cfg.risk.max_position_pct
        max_usd = min(self._cfg.risk.max_position_usd, max_by_pct)
        quantity = max_usd / price if price > 0 else 0.0
        # Round to reasonable precision
        return round(quantity, 6)
