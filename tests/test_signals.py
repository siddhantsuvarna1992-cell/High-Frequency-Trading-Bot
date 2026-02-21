"""Unit tests for signal generation."""

import numpy as np
import pandas as pd
import pytest

from config.settings import StrategyConfig
from strategy.indicators import compute_all
from strategy.signals import SignalGenerator, SignalBreakdown


def _make_df_with_indicators(closes: list[float], cfg: StrategyConfig | None = None) -> pd.DataFrame:
    """Build an OHLCV DataFrame and compute all indicators."""
    if cfg is None:
        cfg = StrategyConfig()
    n = len(closes)
    df = pd.DataFrame({
        "open_time": list(range(n)),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [100.0] * n,
        "quote_volume": [10000.0] * n,
    })
    return compute_all(df, cfg)


class TestSignalGenerator:
    def test_neutral_signal_flat_market(self):
        """Flat market should produce near-zero composite signal."""
        cfg = StrategyConfig()
        closes = [100.0] * 50
        df = _make_df_with_indicators(closes, cfg)
        gen = SignalGenerator(cfg)
        sig = gen.generate(df)
        assert abs(sig.composite) < 0.3

    def test_bullish_signal_strong_uptrend(self):
        """Strong uptrend should produce positive signals."""
        cfg = StrategyConfig()
        # Create a strong uptrend with a recent bullish EMA cross
        closes = [100.0] * 30 + [100 + i * 2 for i in range(20)]
        df = _make_df_with_indicators(closes, cfg)
        gen = SignalGenerator(cfg)
        sig = gen.generate(df)
        # EMA signal should be positive in an uptrend
        assert sig.ema_signal > 0

    def test_rsi_signal_oversold(self):
        """Dropping prices should push RSI to oversold territory."""
        cfg = StrategyConfig()
        gen = SignalGenerator(cfg)
        # RSI signal when oversold
        assert gen._rsi_signal(25.0) == 1.0
        # RSI signal when overbought
        assert gen._rsi_signal(75.0) == -1.0
        # RSI signal at midpoint
        assert gen._rsi_signal(50.0) == pytest.approx(0.0)

    def test_vwap_signal(self):
        cfg = StrategyConfig()
        gen = SignalGenerator(cfg)
        # Price below VWAP -> bullish (mean reversion)
        sig = gen._vwap_signal(98.0, 100.0)
        assert sig > 0
        # Price above VWAP -> bearish
        sig = gen._vwap_signal(102.0, 100.0)
        assert sig < 0

    def test_bb_signal(self):
        cfg = StrategyConfig()
        gen = SignalGenerator(cfg)
        # Price below lower band -> bullish
        sig = gen._bb_signal(95.0, 110.0, 100.0)
        assert sig > 0
        # Price above upper band -> bearish
        sig = gen._bb_signal(115.0, 110.0, 100.0)
        assert sig < 0

    def test_composite_bounded(self):
        """Composite signal must always be in [-1, +1]."""
        cfg = StrategyConfig()
        gen = SignalGenerator(cfg)
        # Test with extreme values
        for _ in range(10):
            np.random.seed(_)
            closes = list(np.random.normal(100, 10, 50))
            df = _make_df_with_indicators(closes, cfg)
            sig = gen.generate(df)
            assert -1.0 <= sig.composite <= 1.0

    def test_signal_breakdown_fields(self):
        cfg = StrategyConfig()
        closes = list(np.random.RandomState(42).normal(100, 5, 50))
        df = _make_df_with_indicators(closes, cfg)
        gen = SignalGenerator(cfg)
        sig = gen.generate(df)
        assert isinstance(sig, SignalBreakdown)
        assert hasattr(sig, "ema_signal")
        assert hasattr(sig, "rsi_signal")
        assert hasattr(sig, "composite")
