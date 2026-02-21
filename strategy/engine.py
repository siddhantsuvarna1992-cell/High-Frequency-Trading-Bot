"""Strategy engine: orchestrates candle -> indicators -> signal -> action."""

from __future__ import annotations

from typing import Callable, Awaitable

import pandas as pd

from config import settings
from data.models import Candle, Action
from strategy.indicators import compute_all
from strategy.signals import SignalGenerator, SignalBreakdown
from utils.logging import get_logger

log = get_logger("strategy")


class StrategyEngine:
    """Receives closed candles, computes indicators and signals, emits actions."""

    def __init__(self):
        self._cfg = settings.strategy
        self._signal_gen = SignalGenerator(self._cfg)
        self._on_action: Callable[[Action, SignalBreakdown, float], Awaitable[None]] | None = None
        self.last_signal: SignalBreakdown = SignalBreakdown()
        self.last_df: pd.DataFrame = pd.DataFrame()

    def on_action(self, callback: Callable[[Action, SignalBreakdown, float], Awaitable[None]]) -> None:
        """Register callback: on_action(action, signal_breakdown, current_price)."""
        self._on_action = callback

    async def on_candle_closed(self, candle: Candle, candle_df: pd.DataFrame) -> None:
        """Called when a new candle closes. Runs the full signal pipeline."""
        if candle_df.empty or len(candle_df) < 30:
            log.debug(f"Not enough candles yet ({len(candle_df)}), skipping signal generation")
            return

        # Compute indicators
        df = compute_all(candle_df, self._cfg)
        self.last_df = df
        if df.empty:
            return

        # Generate composite signal
        signal = self._signal_gen.generate(df)
        self.last_signal = signal
        price = float(candle.close)

        # Determine action
        action = self._decide_action(signal)

        log.info(
            f"Signal: composite={signal.composite:+.3f} "
            f"[EMA={signal.ema_signal:+.2f} RSI={signal.rsi_signal:+.2f} "
            f"VWAP={signal.vwap_signal:+.2f} BB={signal.bb_signal:+.2f} "
            f"VOL={signal.volume_signal:.1f}] -> {action.value}"
        )

        if self._on_action and action != Action.HOLD:
            await self._on_action(action, signal, price)

    def _decide_action(self, signal: SignalBreakdown) -> Action:
        """Convert composite signal into a trading action."""
        if signal.composite >= self._cfg.buy_threshold:
            return Action.OPEN_LONG
        elif signal.composite <= self._cfg.sell_threshold:
            return Action.OPEN_SHORT
        return Action.HOLD
