"""Rich Live terminal dashboard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from dashboard.panels import (
    log_panel,
    orderbook_panel,
    position_panel,
    price_panel,
    risk_panel,
    signal_panel,
)
from data.models import OrderBookSnapshot, Position
from strategy.signals import SignalBreakdown

if TYPE_CHECKING:
    from execution.order_manager import OrderManager
    from execution.position_tracker import PositionTracker
    from risk.manager import RiskManager
    from strategy.engine import StrategyEngine


class DashboardApp:
    """Async Rich Live dashboard that renders the trading bot state."""

    def __init__(
        self,
        symbol: str,
        mode: str,
    ):
        self._symbol = symbol
        self._mode = mode
        self._console = Console()
        self._live: Live | None = None
        self._running = False

        # State references (set via bind())
        self._price: float = 0.0
        self._signal: SignalBreakdown = SignalBreakdown()
        self._position: Position = Position()
        self._daily_pnl: float = 0.0
        self._equity: float = 0.0
        self._win_rate: float = 0.0
        self._risk_status: dict = {}
        self._orderbook: OrderBookSnapshot = OrderBookSnapshot(timestamp_ms=0)

    def bind(
        self,
        strategy_engine: StrategyEngine,
        position_tracker: PositionTracker,
        risk_manager: RiskManager,
        get_price: callable,
        get_equity: callable,
        get_orderbook: callable,
    ) -> None:
        """Bind live data sources for dashboard refresh."""
        self._strategy = strategy_engine
        self._tracker = position_tracker
        self._risk_mgr = risk_manager
        self._get_price = get_price
        self._get_equity = get_equity
        self._get_orderbook = get_orderbook

    async def start(self) -> None:
        """Start the dashboard refresh loop."""
        self._running = True
        self._live = Live(
            self._build_layout(),
            console=self._console,
            refresh_per_second=2,
            screen=True,
        )
        self._live.start()

        while self._running:
            try:
                self._refresh_state()
                self._live.update(self._build_layout())
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        self._running = False
        if self._live:
            self._live.stop()

    def _refresh_state(self) -> None:
        """Pull latest state from bound components."""
        try:
            self._price = self._get_price()
            self._signal = self._strategy.last_signal
            self._position = self._tracker.position
            self._daily_pnl = self._tracker.daily_pnl
            self._equity = self._get_equity()
            self._win_rate = self._tracker.win_rate
            self._risk_status = self._risk_mgr.status_summary
            self._orderbook = self._get_orderbook()
        except Exception:
            pass

    def _build_layout(self) -> Layout:
        """Construct the full dashboard layout."""
        layout = Layout()

        # Header
        mode_color = {"paper": "yellow", "testnet": "cyan", "live": "red"}.get(self._mode, "white")
        header = Layout(
            f"[bold] HFT Bot[/bold] | "
            f"[{mode_color}]{self._mode.upper()} MODE[/{mode_color}] | "
            f"{self._symbol}",
            size=3,
            name="header",
        )

        # Top row: Price + Signals + Position
        top = Layout(name="top", size=14)
        top.split_row(
            Layout(price_panel(self._symbol, self._price), name="price"),
            Layout(signal_panel(self._signal), name="signals", ratio=2),
            Layout(
                position_panel(
                    self._position, self._daily_pnl, self._equity, self._win_rate
                ),
                name="position",
            ),
        )

        # Bottom row: Risk + Orderbook + Log
        bottom = Layout(name="bottom")
        bottom.split_row(
            Layout(risk_panel(self._risk_status), name="risk"),
            Layout(orderbook_panel(self._orderbook), name="orderbook"),
            Layout(log_panel(), name="log", ratio=2),
        )

        layout.split_column(header, top, bottom)
        return layout
