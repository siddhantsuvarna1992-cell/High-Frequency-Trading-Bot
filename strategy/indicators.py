"""Technical indicators: EMA, RSI, VWAP, Bollinger Bands, Volume Spike, ATR."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 (all gains), RSI = 100; when avg_gain is 0, RSI = 0
    result = result.fillna(result.where(avg_loss != 0, 100.0))
    result = result.where(avg_gain != 0, 0.0).where(~((avg_gain == 0) & (avg_loss == 0)), np.nan)
    # Simpler: if avg_loss == 0 and avg_gain > 0, RSI = 100
    mask_all_gain = (avg_loss == 0) & (avg_gain > 0)
    mask_all_loss = (avg_gain == 0) & (avg_loss > 0)
    result[mask_all_gain] = 100.0
    result[mask_all_loss] = 0.0
    return result


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-Weighted Average Price (intraday approximation using cumulative sums)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: (middle, upper, lower)."""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return middle, upper, lower


def volume_spike(volume: pd.Series, period: int = 20, threshold: float = 2.0) -> pd.Series:
    """Returns 1.0 where volume exceeds `threshold` x rolling average, else 0.0."""
    avg_vol = volume.rolling(window=period).mean()
    return (volume > threshold * avg_vol).astype(float)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_all(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Compute all indicators and attach them to the DataFrame.

    Args:
        df: OHLCV DataFrame with columns: open, high, low, close, volume
        cfg: StrategyConfig dataclass

    Returns:
        DataFrame with indicator columns added.
    """
    df = df.copy()

    # EMA
    df["ema_fast"] = ema(df["close"], cfg.ema_fast)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow)

    # RSI
    df["rsi"] = rsi(df["close"], cfg.rsi_period)

    # VWAP
    df["vwap"] = vwap(df)

    # Bollinger Bands
    df["bb_mid"], df["bb_upper"], df["bb_lower"] = bollinger_bands(
        df["close"], cfg.bb_period, cfg.bb_std
    )

    # Volume spike
    df["vol_spike"] = volume_spike(df["volume"], cfg.volume_avg_period, cfg.volume_spike_threshold)

    # ATR
    df["atr"] = atr(df, cfg.atr_period)

    return df
