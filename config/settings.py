"""Dataclass-based configuration for the HFT bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ExchangeConfig:
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    testnet: bool = False
    base_url: str = "https://fapi.binance.com"
    ws_url: str = "wss://fstream.binance.com"
    testnet_base_url: str = "https://testnet.binancefuture.com"
    testnet_ws_url: str = "wss://stream.binancefuture.com"

    @property
    def active_base_url(self) -> str:
        return self.testnet_base_url if self.testnet else self.base_url

    @property
    def active_ws_url(self) -> str:
        return self.testnet_ws_url if self.testnet else self.ws_url


@dataclass
class SymbolConfig:
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    warmup_candles: int = 100


@dataclass
class StrategyConfig:
    # EMA crossover
    ema_fast: int = 9
    ema_slow: int = 21
    ema_weight: float = 0.30

    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    rsi_weight: float = 0.20

    # VWAP
    vwap_deviation_pct: float = 2.0
    vwap_weight: float = 0.20

    # Volume spike
    volume_avg_period: int = 20
    volume_spike_threshold: float = 2.0
    volume_weight: float = 0.15

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0
    bb_weight: float = 0.15

    # ATR (for stop-loss sizing)
    atr_period: int = 14

    # Signal thresholds
    buy_threshold: float = 0.60
    sell_threshold: float = -0.60


@dataclass
class RiskConfig:
    max_position_usd: float = 10_000.0
    max_position_pct: float = 0.25  # 25% of account
    hard_stop_loss_pct: float = 0.05  # 5%
    trailing_stop_pct: float = 0.03  # 3%
    daily_loss_limit_usd: float = 500.0
    daily_loss_limit_pct: float = 0.05  # 5%
    max_drawdown_pct: float = 0.15  # 15%
    post_loss_cooldown_sec: int = 300  # 5 minutes
    consecutive_loss_limit: int = 3
    consecutive_loss_window_sec: int = 1800  # 30 minutes
    max_orders_per_second: int = 5


@dataclass
class PaperConfig:
    initial_balance: float = 100_000.0
    fee_rate: float = 0.0004  # 0.04% taker fee
    slippage_bps: float = 1.0  # 1 basis point


@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    symbol: SymbolConfig = field(default_factory=SymbolConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    mode: str = "paper"  # "paper", "testnet", "live"
    state_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "state")
    state_save_interval_sec: int = 30
    stop_check_tick_interval: int = 10  # Check stops every N-th tick

    def __post_init__(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.mode == "testnet":
            self.exchange.testnet = True


# Singleton
settings = Settings()
