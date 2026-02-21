"""Unit tests for risk management."""

import time

import pytest

from config.settings import RiskConfig, Settings
from data.models import Position, Side
from risk.circuit_breaker import CircuitBreaker
from risk.manager import RiskManager


class TestCircuitBreaker:
    def test_no_trip_on_wins(self):
        cb = CircuitBreaker(consecutive_limit=3, window_sec=1800)
        cb.record_trade(100.0)
        cb.record_trade(50.0)
        cb.record_trade(200.0)
        assert not cb.is_tripped
        assert cb.consecutive_losses == 0

    def test_trip_on_consecutive_losses(self):
        cb = CircuitBreaker(consecutive_limit=3, window_sec=1800)
        cb.record_trade(-10.0)
        cb.record_trade(-20.0)
        assert not cb.is_tripped
        cb.record_trade(-30.0)
        assert cb.is_tripped
        assert "3 consecutive losses" in cb.trip_reason

    def test_win_resets_consecutive(self):
        cb = CircuitBreaker(consecutive_limit=3, window_sec=1800)
        cb.record_trade(-10.0)
        cb.record_trade(-20.0)
        cb.record_trade(50.0)  # Win resets counter
        cb.record_trade(-10.0)
        assert not cb.is_tripped
        assert cb.consecutive_losses == 1

    def test_cooldown(self):
        cb = CircuitBreaker(consecutive_limit=3, window_sec=1800, cooldown_sec=300)
        cb.record_trade(-10.0)
        assert cb.in_cooldown
        assert cb.cooldown_remaining_sec > 0

    def test_reset(self):
        cb = CircuitBreaker(consecutive_limit=3, window_sec=1800)
        cb.record_trade(-10.0)
        cb.record_trade(-20.0)
        cb.record_trade(-30.0)
        assert cb.is_tripped
        cb.reset()
        assert not cb.is_tripped
        assert cb.consecutive_losses == 0


class TestRiskManager:
    def _make_manager(self) -> RiskManager:
        return RiskManager()

    def test_allow_trade_normal_conditions(self):
        rm = self._make_manager()
        allowed, reason = rm.check_can_open(
            side=Side.BUY,
            price=50000.0,
            balance=100000.0,
            position=Position(),
            daily_pnl=0.0,
            drawdown_pct=0.0,
        )
        assert allowed
        assert reason == "OK"

    def test_reject_when_position_open(self):
        rm = self._make_manager()
        pos = Position(symbol="BTCUSDT", side=Side.BUY, entry_price=50000, quantity=0.1)
        allowed, reason = rm.check_can_open(
            side=Side.BUY,
            price=50000.0,
            balance=100000.0,
            position=pos,
            daily_pnl=0.0,
            drawdown_pct=0.0,
        )
        assert not allowed
        assert "already open" in reason.lower()

    def test_reject_daily_loss_limit(self):
        rm = self._make_manager()
        allowed, reason = rm.check_can_open(
            side=Side.BUY,
            price=50000.0,
            balance=100000.0,
            position=Position(),
            daily_pnl=-600.0,  # Exceeds $500 limit
            drawdown_pct=0.0,
        )
        assert not allowed
        assert "daily loss" in reason.lower()

    def test_reject_max_drawdown(self):
        rm = self._make_manager()
        allowed, reason = rm.check_can_open(
            side=Side.BUY,
            price=50000.0,
            balance=100000.0,
            position=Position(),
            daily_pnl=0.0,
            drawdown_pct=0.20,  # 20% > 15% limit
        )
        assert not allowed
        assert "drawdown" in reason.lower()

    def test_reject_after_consecutive_losses(self):
        rm = self._make_manager()
        rm.record_trade_result(-100.0)
        rm.record_trade_result(-100.0)
        rm.record_trade_result(-100.0)
        allowed, reason = rm.check_can_open(
            side=Side.BUY,
            price=50000.0,
            balance=100000.0,
            position=Position(),
            daily_pnl=0.0,
            drawdown_pct=0.0,
        )
        assert not allowed

    def test_halt_persists(self):
        rm = self._make_manager()
        # Trigger daily loss halt
        rm.check_can_open(
            side=Side.BUY, price=50000.0, balance=100000.0,
            position=Position(), daily_pnl=-600.0, drawdown_pct=0.0,
        )
        assert rm.is_halted
        # Subsequent trades should also be rejected
        allowed, _ = rm.check_can_open(
            side=Side.BUY, price=50000.0, balance=100000.0,
            position=Position(), daily_pnl=0.0, drawdown_pct=0.0,
        )
        assert not allowed

    def test_reset(self):
        rm = self._make_manager()
        rm.check_can_open(
            side=Side.BUY, price=50000.0, balance=100000.0,
            position=Position(), daily_pnl=-600.0, drawdown_pct=0.0,
        )
        assert rm.is_halted
        rm.reset()
        assert not rm.is_halted
