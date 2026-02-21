"""Pre-trade risk checks, daily loss limits, and drawdown circuit breaker."""

from __future__ import annotations

from config import settings
from data.models import Side, Position
from risk.circuit_breaker import CircuitBreaker
from utils.logging import get_logger

log = get_logger("risk")


class RiskManager:
    """Enforces all risk management rules before order execution."""

    def __init__(self):
        self._cfg = settings.risk
        self.circuit_breaker = CircuitBreaker(
            consecutive_limit=self._cfg.consecutive_loss_limit,
            window_sec=self._cfg.consecutive_loss_window_sec,
            cooldown_sec=self._cfg.post_loss_cooldown_sec,
        )
        self._halted = False
        self._halt_reason = ""

    def check_can_open(
        self,
        side: Side,
        price: float,
        balance: float,
        position: Position,
        daily_pnl: float,
        drawdown_pct: float,
    ) -> tuple[bool, str]:
        """Run all pre-trade checks. Returns (allowed, reason)."""

        # 1. Bot halted?
        if self._halted:
            return False, f"Bot halted: {self._halt_reason}"

        # 2. Circuit breaker tripped?
        if self.circuit_breaker.is_tripped:
            return False, f"Circuit breaker: {self.circuit_breaker.trip_reason}"

        # 3. Post-loss cooldown
        if self.circuit_breaker.in_cooldown:
            remaining = self.circuit_breaker.cooldown_remaining_sec
            return False, f"Post-loss cooldown: {remaining:.0f}s remaining"

        # 4. Already has open position?
        if position.is_open:
            return False, "Position already open"

        # 5. Daily loss limit (USD)
        if daily_pnl <= -self._cfg.daily_loss_limit_usd:
            self._halt("Daily USD loss limit reached", daily_pnl)
            return False, f"Daily loss limit: ${daily_pnl:.2f}"

        # 6. Daily loss limit (%)
        if balance > 0 and abs(daily_pnl) / balance >= self._cfg.daily_loss_limit_pct and daily_pnl < 0:
            self._halt("Daily % loss limit reached", daily_pnl)
            return False, f"Daily loss % limit: {abs(daily_pnl) / balance * 100:.1f}%"

        # 7. Max drawdown breaker
        if drawdown_pct >= self._cfg.max_drawdown_pct:
            self._halt("Max drawdown limit reached", drawdown_pct)
            return False, f"Max drawdown: {drawdown_pct * 100:.1f}%"

        # 8. Position size check
        max_by_pct = balance * self._cfg.max_position_pct
        max_usd = min(self._cfg.max_position_usd, max_by_pct)
        if max_usd <= 0:
            return False, "Insufficient balance for position"

        return True, "OK"

    def record_trade_result(self, pnl: float) -> None:
        """Record a completed trade for circuit breaker tracking."""
        self.circuit_breaker.record_trade(pnl)

    def _halt(self, reason: str, value: float) -> None:
        self._halted = True
        self._halt_reason = f"{reason} ({value:.4f})"
        log.critical(f"TRADING HALTED: {self._halt_reason}")

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def status_summary(self) -> dict:
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "circuit_breaker_tripped": self.circuit_breaker.is_tripped,
            "in_cooldown": self.circuit_breaker.in_cooldown,
            "cooldown_remaining": self.circuit_breaker.cooldown_remaining_sec,
            "consecutive_losses": self.circuit_breaker.consecutive_losses,
        }

    def reset(self) -> None:
        """Manual reset (operator intervention)."""
        self._halted = False
        self._halt_reason = ""
        self.circuit_breaker.reset()
        log.info("Risk manager manually reset")
