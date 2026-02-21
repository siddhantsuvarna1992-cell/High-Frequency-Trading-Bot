"""Unit tests for technical indicators."""

import numpy as np
import pandas as pd
import pytest

from strategy.indicators import ema, rsi, vwap, bollinger_bands, volume_spike, atr


def _make_ohlcv(closes: list[float], n: int | None = None) -> pd.DataFrame:
    """Helper: create a simple OHLCV DataFrame from close prices."""
    if n is None:
        n = len(closes)
    df = pd.DataFrame({
        "open": closes[:n],
        "high": [c * 1.01 for c in closes[:n]],
        "low": [c * 0.99 for c in closes[:n]],
        "close": closes[:n],
        "volume": [100.0] * n,
    })
    return df


class TestEMA:
    def test_ema_single_value(self):
        series = pd.Series([100.0])
        result = ema(series, 9)
        assert result.iloc[0] == pytest.approx(100.0)

    def test_ema_constant_series(self):
        series = pd.Series([50.0] * 20)
        result = ema(series, 9)
        # EMA of constant series should equal the constant
        assert result.iloc[-1] == pytest.approx(50.0, abs=0.01)

    def test_ema_fast_reacts_quicker(self):
        prices = [100.0] * 10 + [110.0] * 5
        series = pd.Series(prices)
        fast = ema(series, 3)
        slow = ema(series, 9)
        # Fast EMA should be closer to 110 after the jump
        assert fast.iloc[-1] > slow.iloc[-1]


class TestRSI:
    def test_rsi_flat_series(self):
        # Flat prices -> RSI should be NaN or ~50 (no gains/losses)
        series = pd.Series([100.0] * 30)
        result = rsi(series, 14)
        # With zero change, RSI is undefined but our implementation yields NaN
        # which is acceptable
        assert pd.isna(result.iloc[-1]) or abs(result.iloc[-1] - 50.0) < 1

    def test_rsi_all_up(self):
        # Monotonically increasing -> RSI should be ~100
        series = pd.Series([float(i) for i in range(50, 80)])
        result = rsi(series, 14)
        assert result.iloc[-1] > 95.0

    def test_rsi_all_down(self):
        # Monotonically decreasing -> RSI should be ~0
        series = pd.Series([float(i) for i in range(80, 50, -1)])
        result = rsi(series, 14)
        assert result.iloc[-1] < 5.0

    def test_rsi_range(self):
        np.random.seed(42)
        prices = pd.Series(np.random.normal(100, 5, 50).cumsum())
        result = rsi(prices, 14)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


class TestVWAP:
    def test_vwap_constant_price(self):
        df = _make_ohlcv([100.0] * 20)
        result = vwap(df)
        assert result.iloc[-1] == pytest.approx(100.0, abs=0.5)

    def test_vwap_exists(self):
        prices = [100 + i * 0.5 for i in range(20)]
        df = _make_ohlcv(prices)
        result = vwap(df)
        assert not result.dropna().empty


class TestBollingerBands:
    def test_bb_constant_series(self):
        series = pd.Series([100.0] * 25)
        mid, upper, lower = bollinger_bands(series, 20, 2.0)
        assert mid.iloc[-1] == pytest.approx(100.0)
        # Std dev of constant is 0 -> upper == lower == mid
        assert upper.iloc[-1] == pytest.approx(100.0)
        assert lower.iloc[-1] == pytest.approx(100.0)

    def test_bb_ordering(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 5, 30))
        mid, upper, lower = bollinger_bands(series, 20, 2.0)
        last = -1
        assert upper.iloc[last] > mid.iloc[last] > lower.iloc[last]


class TestVolumeSpike:
    def test_no_spike(self):
        vol = pd.Series([100.0] * 25)
        result = volume_spike(vol, 20, 2.0)
        assert result.iloc[-1] == 0.0

    def test_spike_detected(self):
        vol = pd.Series([100.0] * 24 + [300.0])
        result = volume_spike(vol, 20, 2.0)
        assert result.iloc[-1] == 1.0


class TestATR:
    def test_atr_positive(self):
        prices = [100 + i * 0.5 for i in range(30)]
        df = _make_ohlcv(prices)
        result = atr(df, 14)
        valid = result.dropna()
        assert (valid > 0).all()
