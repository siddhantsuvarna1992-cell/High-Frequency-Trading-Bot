"""HFT Bot — Async entry point. Wires all components together."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

# Ensure project root is on path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from data.feed import MarketDataFeed
from data.models import Action, Candle, Tick
from dashboard.app import DashboardApp
from execution.order_manager import OrderManager
from execution.paper_engine import PaperEngine
from execution.position_tracker import PositionTracker
from risk.manager import RiskManager
from strategy.engine import StrategyEngine
from strategy.signals import SignalBreakdown
from utils.logging import setup_logging, get_logger


log = get_logger("main")


class TradingBot:
    """Top-level orchestrator that wires all components."""

    def __init__(self, mode: str):
        settings.mode = mode
        if mode == "testnet":
            settings.exchange.testnet = True

        self._mode = mode
        self._symbol = settings.symbol.symbol
        self._running = False

        # Components
        self._feed = MarketDataFeed()
        self._strategy = StrategyEngine()
        self._risk = RiskManager()
        self._tracker = PositionTracker(self._symbol, settings.state_dir)

        # Executor
        if mode == "paper":
            self._executor = PaperEngine()
        else:
            from execution.binance_executor import BinanceExecutor
            self._executor = BinanceExecutor()

        self._order_mgr = OrderManager(self._executor, self._risk, self._tracker)
        self._dashboard = DashboardApp(self._symbol, mode)

    async def start(self) -> None:
        """Initialize and start all components."""
        logger = setup_logging("INFO")

        if self._mode == "live":
            log.warning("=" * 50)
            log.warning("  LIVE TRADING MODE — REAL MONEY AT RISK")
            log.warning("=" * 50)
            confirm = input("\nType YES to confirm live trading: ")
            if confirm.strip() != "YES":
                log.info("Live trading cancelled.")
                return

        if self._mode in ("live", "testnet"):
            await self._executor.start()

        # Set initial equity tracking
        self._tracker.update_equity(self._executor.balance)
        if self._tracker.peak_equity == 0:
            self._tracker.peak_equity = self._executor.balance

        # Wire callbacks
        self._feed.on_candle_closed(self._on_candle_closed)
        self._feed.on_tick(self._on_tick)
        self._strategy.on_action(self._on_action)

        # Bind dashboard
        self._dashboard.bind(
            strategy_engine=self._strategy,
            position_tracker=self._tracker,
            risk_manager=self._risk,
            get_price=lambda: self._feed.last_price,
            get_equity=lambda: self._executor.balance,
            get_orderbook=lambda: self._feed.orderbook,
        )

        self._running = True
        log.info(f"Starting HFT Bot in {self._mode.upper()} mode for {self._symbol}")

        # Start feed + dashboard concurrently
        await asyncio.gather(
            self._feed.start(),
            self._dashboard.start(),
            self._state_save_loop(),
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        log.info("Shutting down...")
        self._running = False
        await self._feed.stop()
        await self._dashboard.stop()
        self._tracker.save_state(force=True)

        if self._mode in ("live", "testnet") and hasattr(self._executor, "stop"):
            await self._executor.stop()

        log.info("Bot stopped. Final equity: ${:.2f}".format(self._executor.balance))

    async def _on_candle_closed(self, candle: Candle) -> None:
        """Feed -> Strategy pipeline."""
        df = self._feed.candles_as_df()
        await self._strategy.on_candle_closed(candle, df)

    async def _on_tick(self, tick: Tick) -> None:
        """Check stop losses on ticks."""
        self._tracker.update_price(tick.price)
        await self._order_mgr.check_stop_losses(tick)

    async def _on_action(self, action: Action, signal: SignalBreakdown, price: float) -> None:
        """Strategy -> OrderManager pipeline."""
        await self._order_mgr.handle_action(action, signal, price)

    async def _state_save_loop(self) -> None:
        """Periodically save position state."""
        while self._running:
            await asyncio.sleep(settings.state_save_interval_sec)
            self._tracker.save_state()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="High-Frequency Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["paper", "testnet", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Trading pair (default: from config)",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help="Candle interval (default: from config)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.symbol:
        settings.symbol.symbol = args.symbol
    if args.interval:
        settings.symbol.interval = args.interval

    bot = TradingBot(mode=args.mode)

    # Graceful shutdown on Ctrl+C
    loop = asyncio.get_event_loop()

    def _shutdown():
        asyncio.ensure_future(bot.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
