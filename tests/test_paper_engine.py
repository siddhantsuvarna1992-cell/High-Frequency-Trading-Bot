"""Unit tests for paper trading engine."""

import pytest
import asyncio

from config import settings
from data.models import Side, OrderStatus
from execution.paper_engine import PaperEngine


@pytest.fixture
def engine():
    return PaperEngine()


class TestPaperEngine:
    @pytest.mark.asyncio
    async def test_initial_balance(self, engine):
        assert engine.balance == settings.paper.initial_balance

    @pytest.mark.asyncio
    async def test_buy_order_fills(self, engine):
        result = await engine.place_market_order("BTCUSDT", Side.BUY, 0.1, 50000.0)
        assert result.status == OrderStatus.FILLED
        assert result.side == Side.BUY
        assert result.quantity == 0.1
        assert result.fee > 0
        # Price should include slippage
        assert result.price >= 50000.0

    @pytest.mark.asyncio
    async def test_sell_order_fills(self, engine):
        result = await engine.place_market_order("BTCUSDT", Side.SELL, 0.1, 50000.0)
        assert result.status == OrderStatus.FILLED
        assert result.side == Side.SELL
        # Sell fills at price minus slippage
        assert result.price <= 50000.0

    @pytest.mark.asyncio
    async def test_fee_deducted(self, engine):
        initial = engine.balance
        await engine.place_market_order("BTCUSDT", Side.BUY, 0.1, 50000.0)
        assert engine.balance < initial

    @pytest.mark.asyncio
    async def test_slippage_applied(self, engine):
        result = await engine.place_market_order("BTCUSDT", Side.BUY, 1.0, 50000.0)
        expected_slippage = 50000.0 * (settings.paper.slippage_bps / 10_000)
        assert result.price == pytest.approx(50000.0 + expected_slippage, abs=0.01)

    @pytest.mark.asyncio
    async def test_apply_pnl(self, engine):
        initial = engine.balance
        engine.apply_pnl(500.0)
        assert engine.balance == initial + 500.0
        engine.apply_pnl(-200.0)
        assert engine.balance == initial + 300.0

    @pytest.mark.asyncio
    async def test_order_id_unique(self, engine):
        r1 = await engine.place_market_order("BTCUSDT", Side.BUY, 0.1, 50000.0)
        r2 = await engine.place_market_order("BTCUSDT", Side.BUY, 0.1, 50000.0)
        assert r1.order_id != r2.order_id

    def test_total_return(self, engine):
        assert engine.total_return_pct == pytest.approx(0.0)
        engine.apply_pnl(10000.0)
        assert engine.total_return_pct > 0
