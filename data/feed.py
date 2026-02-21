"""Async WebSocket feed for Binance Futures (kline, trades, depth streams)."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Callable, Awaitable

import aiohttp
import pandas as pd

from config import settings
from data.models import Candle, Tick, OrderBookSnapshot
from utils.logging import get_logger

log = get_logger("feed")


class MarketDataFeed:
    """Manages three concurrent WebSocket streams from Binance Futures."""

    def __init__(self):
        self._cfg = settings
        sym = self._cfg.symbol.symbol.lower()
        interval = self._cfg.symbol.interval

        base_ws = self._cfg.exchange.active_ws_url
        self._streams = {
            "kline": f"{base_ws}/ws/{sym}@kline_{interval}",
            "trade": f"{base_ws}/ws/{sym}@aggTrade",
            "depth": f"{base_ws}/ws/{sym}@depth20@100ms",
        }

        self.candle_history: deque[Candle] = deque(maxlen=500)
        self.current_candle: Candle | None = None
        self.orderbook: OrderBookSnapshot = OrderBookSnapshot(timestamp_ms=0)
        self.last_price: float = 0.0
        self._tick_count: int = 0

        # Callbacks
        self._on_candle_closed: Callable[[Candle], Awaitable[None]] | None = None
        self._on_tick: Callable[[Tick], Awaitable[None]] | None = None
        self._on_depth: Callable[[OrderBookSnapshot], Awaitable[None]] | None = None

        self._session: aiohttp.ClientSession | None = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def on_candle_closed(self, callback: Callable[[Candle], Awaitable[None]]) -> None:
        self._on_candle_closed = callback

    def on_tick(self, callback: Callable[[Tick], Awaitable[None]]) -> None:
        self._on_tick = callback

    def on_depth(self, callback: Callable[[OrderBookSnapshot], Awaitable[None]]) -> None:
        self._on_depth = callback

    async def start(self) -> None:
        """Load warmup candles then start all WebSocket streams."""
        self._running = True
        self._session = aiohttp.ClientSession()
        await self._load_warmup_candles()
        log.info(
            f"Loaded {len(self.candle_history)} warmup candles for "
            f"{self._cfg.symbol.symbol} {self._cfg.symbol.interval}"
        )
        for name, url in self._streams.items():
            task = asyncio.create_task(self._ws_loop(name, url), name=f"ws-{name}")
            self._tasks.append(task)
        log.info("WebSocket streams started")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._session:
            await self._session.close()
        log.info("MarketDataFeed stopped")

    async def _load_warmup_candles(self) -> None:
        """Fetch historical klines via REST to warm up indicator computation."""
        sym = self._cfg.symbol.symbol
        interval = self._cfg.symbol.interval
        limit = self._cfg.symbol.warmup_candles
        url = f"{self._cfg.exchange.active_base_url}/fapi/v1/klines"
        params = {"symbol": sym, "interval": interval, "limit": limit}

        try:
            async with self._session.get(url, params=params) as resp:  # type: ignore[union-attr]
                resp.raise_for_status()
                raw = await resp.json()

            for k in raw:
                candle = Candle(
                    open_time=int(k[0]),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    close_time=int(k[6]),
                    quote_volume=float(k[7]),
                    trades=int(k[8]),
                    is_closed=True,
                )
                self.candle_history.append(candle)

            if self.candle_history:
                self.last_price = self.candle_history[-1].close
        except Exception as e:
            log.error(f"Failed to load warmup candles: {e}")

    async def _ws_loop(self, name: str, url: str) -> None:
        """Reconnecting WebSocket loop for a single stream."""
        while self._running:
            try:
                async with self._session.ws_connect(url, heartbeat=20) as ws:  # type: ignore[union-attr]
                    log.info(f"[{name}] WebSocket connected")
                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            await self._dispatch(name, data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning(f"[{name}] WebSocket error: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)

    async def _dispatch(self, stream: str, data: dict) -> None:
        if stream == "kline":
            await self._handle_kline(data)
        elif stream == "trade":
            await self._handle_trade(data)
        elif stream == "depth":
            await self._handle_depth(data)

    async def _handle_kline(self, data: dict) -> None:
        k = data.get("k", {})
        candle = Candle(
            open_time=int(k["t"]),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            close_time=int(k["T"]),
            quote_volume=float(k["q"]),
            trades=int(k["n"]),
            is_closed=k.get("x", False),
        )
        self.current_candle = candle
        self.last_price = candle.close

        if candle.is_closed:
            self.candle_history.append(candle)
            if self._on_candle_closed:
                await self._on_candle_closed(candle)

    async def _handle_trade(self, data: dict) -> None:
        tick = Tick(
            timestamp_ms=int(data["T"]),
            price=float(data["p"]),
            quantity=float(data["q"]),
            is_buyer_maker=data.get("m", False),
        )
        self.last_price = tick.price
        self._tick_count += 1

        if self._on_tick:
            await self._on_tick(tick)

    async def _handle_depth(self, data: dict) -> None:
        snapshot = OrderBookSnapshot(
            timestamp_ms=int(time.time() * 1000),
            bids=[(float(b[0]), float(b[1])) for b in data.get("b", [])[:10]],
            asks=[(float(a[0]), float(a[1])) for a in data.get("a", [])[:10]],
        )
        self.orderbook = snapshot
        if self._on_depth:
            await self._on_depth(snapshot)

    def candles_as_df(self) -> pd.DataFrame:
        """Convert candle history to a DataFrame for indicator computation."""
        if not self.candle_history:
            return pd.DataFrame()
        records = [c.to_dict() for c in self.candle_history]
        df = pd.DataFrame(records)
        for col in ("open", "high", "low", "close", "volume", "quote_volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    @property
    def tick_count(self) -> int:
        return self._tick_count
