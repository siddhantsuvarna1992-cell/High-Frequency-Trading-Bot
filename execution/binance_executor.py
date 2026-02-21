"""Real Binance Futures API execution (async)."""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse

import aiohttp

from config import settings
from data.models import Side, OrderResult, OrderStatus
from utils.helpers import async_retry
from utils.logging import get_logger

log = get_logger("binance_exec")


class BinanceExecutor:
    """Executes real orders on Binance Futures via REST API."""

    def __init__(self):
        self._cfg = settings.exchange
        self._base_url = self._cfg.active_base_url
        self._session: aiohttp.ClientSession | None = None
        self.balance: float = 0.0

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"X-MBX-APIKEY": self._cfg.api_key}
        )
        await self._fetch_balance()

    async def stop(self) -> None:
        if self._session:
            await self._session.close()

    def apply_pnl(self, pnl: float) -> None:
        """Update tracked balance after a trade closes."""
        self.balance += pnl

    @async_retry(max_retries=3, delay=0.5)
    async def place_market_order(
        self, symbol: str, side: Side, quantity: float, current_price: float
    ) -> OrderResult:
        """Place a market order on Binance Futures."""
        params = {
            "symbol": symbol,
            "side": side.value,
            "type": "MARKET",
            "quantity": f"{quantity:.6f}",
            "timestamp": str(int(time.time() * 1000)),
        }
        params["signature"] = self._sign(params)

        url = f"{self._base_url}/fapi/v1/order"
        async with self._session.post(url, params=params) as resp:  # type: ignore[union-attr]
            data = await resp.json()

            if resp.status != 200:
                error_msg = data.get("msg", str(data))
                log.error(f"Order failed: {error_msg}")
                return OrderResult(
                    order_id="",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=current_price,
                    status=OrderStatus.REJECTED,
                    timestamp_ms=int(time.time() * 1000),
                )

            fill_price = float(data.get("avgPrice", current_price))
            fill_qty = float(data.get("executedQty", quantity))
            commission = sum(
                float(f.get("commission", 0))
                for f in data.get("fills", [])
            )

            log.info(
                f"[LIVE] {side.value} {fill_qty:.6f} {symbol} "
                f"@ {fill_price:.2f} (fee: ${commission:.4f})"
            )

            return OrderResult(
                order_id=str(data.get("orderId", "")),
                symbol=symbol,
                side=side,
                quantity=fill_qty,
                price=fill_price,
                status=OrderStatus.FILLED,
                timestamp_ms=int(data.get("updateTime", time.time() * 1000)),
                fee=commission,
            )

    @async_retry(max_retries=2, delay=1.0)
    async def _fetch_balance(self) -> None:
        """Fetch USDT futures balance."""
        params = {"timestamp": str(int(time.time() * 1000))}
        params["signature"] = self._sign(params)

        url = f"{self._base_url}/fapi/v2/balance"
        async with self._session.get(url, params=params) as resp:  # type: ignore[union-attr]
            data = await resp.json()
            if resp.status == 200:
                for asset in data:
                    if asset.get("asset") == "USDT":
                        self.balance = float(asset.get("balance", 0))
                        log.info(f"Binance balance: ${self.balance:,.2f} USDT")
                        return
            log.warning(f"Failed to fetch balance: {data}")

    def _sign(self, params: dict) -> str:
        """HMAC SHA256 signature for Binance API."""
        query = urllib.parse.urlencode(params)
        return hmac.new(
            self._cfg.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
