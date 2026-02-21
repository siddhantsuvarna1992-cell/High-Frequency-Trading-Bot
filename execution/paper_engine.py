"""Paper trading engine: simulated fills with slippage and fees."""

from __future__ import annotations

import time
import uuid

from config import settings
from data.models import Side, OrderResult, OrderStatus
from utils.logging import get_logger

log = get_logger("paper")


class PaperEngine:
    """Simulates order execution for paper trading mode."""

    def __init__(self):
        self._cfg = settings.paper
        self.balance: float = self._cfg.initial_balance
        self._initial_balance: float = self._cfg.initial_balance

    async def place_market_order(
        self, symbol: str, side: Side, quantity: float, current_price: float
    ) -> OrderResult:
        """Simulate a market order fill with slippage and fees."""
        # Apply slippage
        slippage = current_price * (self._cfg.slippage_bps / 10_000)
        if side == Side.BUY:
            fill_price = current_price + slippage
        else:
            fill_price = current_price - slippage

        # Calculate fee
        notional = fill_price * quantity
        fee = notional * self._cfg.fee_rate

        # Update balance
        if side == Side.BUY:
            self.balance -= fee  # Only deduct fee; PnL handled by position tracker
        else:
            self.balance -= fee

        result = OrderResult(
            order_id=f"PAPER-{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=fill_price,
            status=OrderStatus.FILLED,
            timestamp_ms=int(time.time() * 1000),
            fee=fee,
        )

        log.info(
            f"[PAPER] {side.value} {quantity:.6f} {symbol} "
            f"@ {fill_price:.2f} (fee: ${fee:.4f})"
        )
        return result

    def apply_pnl(self, pnl: float) -> None:
        """Apply realized PnL to paper balance."""
        self.balance += pnl
        log.debug(f"[PAPER] PnL applied: ${pnl:+.2f}, balance: ${self.balance:.2f}")

    @property
    def equity(self) -> float:
        return self.balance

    @property
    def total_return_pct(self) -> float:
        if self._initial_balance == 0:
            return 0.0
        return ((self.balance - self._initial_balance) / self._initial_balance) * 100
