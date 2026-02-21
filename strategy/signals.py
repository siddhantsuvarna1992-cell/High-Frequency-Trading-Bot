"""Weighted composite signal generator [-1, +1]."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.settings import StrategyConfig


@dataclass
class SignalBreakdown:
    """Stores individual sub-signals and the composite score."""
    ema_signal: float = 0.0
    rsi_signal: float = 0.0
    vwap_signal: float = 0.0
    volume_signal: float = 0.0
    bb_signal: float = 0.0
    composite: float = 0.0
    timestamp_ms: int = 0


class SignalGenerator:
    """Produces a composite trading signal from indicator values."""

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def generate(self, df: pd.DataFrame) -> SignalBreakdown:
        """Generate a composite signal from the latest row of an indicator-enriched DataFrame.

        Expects columns: ema_fast, ema_slow, rsi, vwap, bb_upper, bb_lower, vol_spike
        """
        if len(df) < 2:
            return SignalBreakdown()

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        sig = SignalBreakdown()
        sig.timestamp_ms = int(curr.get("open_time", 0))

        # 1. EMA Crossover
        sig.ema_signal = self._ema_signal(curr, prev)

        # 2. RSI
        sig.rsi_signal = self._rsi_signal(curr["rsi"])

        # 3. VWAP deviation
        sig.vwap_signal = self._vwap_signal(curr["close"], curr["vwap"])

        # 4. Bollinger Bands
        sig.bb_signal = self._bb_signal(curr["close"], curr["bb_upper"], curr["bb_lower"])

        # 5. Volume spike (amplifier: scales other signals, not directional itself)
        sig.volume_signal = float(curr.get("vol_spike", 0.0))

        # Composite (volume acts as amplifier on directional signals)
        cfg = self.cfg
        base_score = (
            cfg.ema_weight * sig.ema_signal
            + cfg.rsi_weight * sig.rsi_signal
            + cfg.vwap_weight * sig.vwap_signal
            + cfg.bb_weight * sig.bb_signal
        )
        # Volume amplifies: if spike present, boost by volume_weight fraction
        volume_multiplier = 1.0 + cfg.volume_weight * sig.volume_signal
        sig.composite = float(np.clip(base_score * volume_multiplier, -1.0, 1.0))

        return sig

    def _ema_signal(self, curr: pd.Series, prev: pd.Series) -> float:
        """EMA crossover: +1 on bullish cross, -1 on bearish cross, 0 otherwise."""
        fast_now, slow_now = curr["ema_fast"], curr["ema_slow"]
        fast_prev, slow_prev = prev["ema_fast"], prev["ema_slow"]

        if pd.isna(fast_now) or pd.isna(slow_now) or pd.isna(fast_prev) or pd.isna(slow_prev):
            return 0.0

        bullish_cross = fast_prev <= slow_prev and fast_now > slow_now
        bearish_cross = fast_prev >= slow_prev and fast_now < slow_now

        if bullish_cross:
            return 1.0
        elif bearish_cross:
            return -1.0

        # Continuous signal based on separation
        gap_pct = (fast_now - slow_now) / slow_now if slow_now != 0 else 0.0
        return float(np.clip(gap_pct * 100, -1.0, 1.0))

    def _rsi_signal(self, rsi_val: float) -> float:
        """RSI: +1 when oversold, -1 when overbought, linear interpolation in between."""
        if pd.isna(rsi_val):
            return 0.0
        if rsi_val <= self.cfg.rsi_oversold:
            return 1.0
        elif rsi_val >= self.cfg.rsi_overbought:
            return -1.0
        # Linear interpolation: 50 -> 0, 30 -> +1, 70 -> -1
        return float(np.clip((50.0 - rsi_val) / 20.0, -1.0, 1.0))

    def _vwap_signal(self, price: float, vwap_val: float) -> float:
        """VWAP deviation: +1 when price far below VWAP, -1 when far above."""
        if pd.isna(vwap_val) or vwap_val == 0:
            return 0.0
        dev_pct = ((price - vwap_val) / vwap_val) * 100.0
        threshold = self.cfg.vwap_deviation_pct
        # Below VWAP is bullish (mean reversion), above is bearish
        return float(np.clip(-dev_pct / threshold, -1.0, 1.0))

    def _bb_signal(self, price: float, upper: float, lower: float) -> float:
        """Bollinger Bands: +1 below lower, -1 above upper."""
        if pd.isna(upper) or pd.isna(lower):
            return 0.0
        mid = (upper + lower) / 2.0
        half_width = (upper - lower) / 2.0
        if half_width == 0:
            return 0.0
        # Normalize distance from middle band
        deviation = (price - mid) / half_width
        return float(np.clip(-deviation, -1.0, 1.0))
