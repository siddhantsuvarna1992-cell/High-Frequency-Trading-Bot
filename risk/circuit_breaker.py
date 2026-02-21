"""Circuit breaker: consecutive loss detection and cooldown enforcement."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from utils.logging import get_logger

log = get_logger("circuit_breaker")


@dataclass
class TradeEvent:
    timestamp: float
    pnl: float


class CircuitBreaker:
    """Detects dangerous loss patterns and halts trading."""

    def __init__(
        self,
        consecutive_limit: int = 3,
        window_sec: int = 1800,
        cooldown_sec: int = 300,
    ):
        self._consecutive_limit = consecutive_limit
        self._window_sec = window_sec
        self._cooldown_sec = cooldown_sec
        self._recent_trades: deque[TradeEvent] = deque(maxlen=50)
        self._consecutive_losses: int = 0
        self._last_loss_time: float = 0.0
        self._tripped = False
        self._trip_reason: str = ""

    def record_trade(self, pnl: float) -> None:
        """Record a trade result. Updates consecutive loss counter."""
        now = time.time()
        self._recent_trades.append(TradeEvent(timestamp=now, pnl=pnl))

        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = now
            self._check_consecutive_losses(now)
        else:
            self._consecutive_losses = 0

    def _check_consecutive_losses(self, now: float) -> None:
        """Check if consecutive losses in the window exceed the limit."""
        if self._consecutive_losses >= self._consecutive_limit:
            # Verify they all fall within the time window
            window_start = now - self._window_sec
            recent_trades = [e for e in self._recent_trades if e.timestamp >= window_start]

            # Count consecutive losses from the end
            consecutive_in_window = 0
            for e in reversed(recent_trades):
                if e.pnl < 0:
                    consecutive_in_window += 1
                else:
                    break

            if consecutive_in_window >= self._consecutive_limit:
                self._tripped = True
                self._trip_reason = (
                    f"{consecutive_in_window} consecutive losses in "
                    f"{self._window_sec // 60} minutes"
                )
                log.warning(f"CIRCUIT BREAKER TRIPPED: {self._trip_reason}")

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def trip_reason(self) -> str:
        return self._trip_reason

    @property
    def in_cooldown(self) -> bool:
        """True if a losing trade occurred within the cooldown period."""
        if self._last_loss_time == 0:
            return False
        elapsed = time.time() - self._last_loss_time
        return elapsed < self._cooldown_sec

    @property
    def cooldown_remaining_sec(self) -> float:
        if not self.in_cooldown:
            return 0.0
        return max(0.0, self._cooldown_sec - (time.time() - self._last_loss_time))

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def reset(self) -> None:
        """Manually reset the circuit breaker (e.g., after operator review)."""
        self._tripped = False
        self._trip_reason = ""
        self._consecutive_losses = 0
        log.info("Circuit breaker manually reset")
