# High Frequency Trading Bot

A Binance Futures HFT bot built in Python that uses a momentum/signal-based strategy with weighted composite indicators, 9-layer risk management, and a real-time Rich terminal dashboard. Supports paper trading, testnet, and live execution modes.

## Features

- **5 Technical Indicators** — EMA crossover, RSI, VWAP mean-reversion, Bollinger Bands, and Volume Spike amplifier combined into a single weighted composite signal
- **9-Layer Risk Management** — Daily loss limits, max drawdown breaker, circuit breaker, post-loss cooldown, position sizing caps, rate limiting, and more
- **3 Execution Modes** — Paper trading (simulated fills), Binance testnet (fake money, real infra), and live trading (real capital)
- **Rich Terminal Dashboard** — Live-updating panels for price, signals, position, risk status, order book, and logs
- **State Persistence** — Positions, equity, and trade history saved to disk and restored on restart
- **Async Architecture** — Built on `asyncio` with WebSocket market data streams for low-latency processing

## Architecture

```
Market Data (WebSocket)
  │
  ├─ on_candle_closed ──► Strategy Engine ──► Order Manager ──► Risk Manager
  │                        ├ EMA Crossover      │                  ├ Halt check
  │                        ├ RSI                 │                  ├ Circuit breaker
  │                        ├ VWAP                │                  ├ Cooldown
  │                        ├ Bollinger Bands     │                  ├ Position conflict
  │                        └ Volume Spike        │                  ├ Daily loss (USD)
  │                                              │                  ├ Daily loss (%)
  │                                              │                  ├ Max drawdown
  │                                              │                  ├ Position size cap
  │                                              │                  └ Rate limiter
  │                                              ▼
  │                                   ┌─────────────────────┐
  │                                   │  Executor           │
  │                                   │  Paper / Binance    │
  │                                   └────────┬────────────┘
  │                                            ▼
  └─ on_tick ──► Stop-Loss Check       Position Tracker
                 ├ Hard stop (5%)       ├ PnL calculation
                 └ Trailing stop (3%)   ├ Equity tracking
                                        └ State persistence
```

## Signal Strategy

Indicators are computed on each closed candle and combined into a composite score in **[-1, +1]**:

| Indicator       | Weight | Signal Logic                                              |
|-----------------|--------|-----------------------------------------------------------|
| EMA Crossover   | 0.30   | Fast(9)/Slow(21) crossover: bullish = +1, bearish = -1   |
| RSI             | 0.20   | Period 14; +1 at oversold (<=30), -1 at overbought (>=70) |
| VWAP            | 0.20   | Mean reversion; +1 when price far below VWAP, -1 above   |
| Bollinger Bands | 0.15   | Period 20, 2 std; +1 below lower band, -1 above upper    |
| Volume Spike    | 0.15   | Amplifier; multiplies signal when volume > 2x average     |

**Action thresholds:** composite >= **0.60** &rarr; BUY &nbsp;|&nbsp; composite <= **-0.60** &rarr; SELL &nbsp;|&nbsp; otherwise HOLD

## Risk Management

All 9 safeguards are evaluated before every trade:

| # | Safeguard              | Default              | Behavior                                    |
|---|------------------------|----------------------|---------------------------------------------|
| 1 | Bot Halt State         | —                    | Blocks all trading if a fatal limit was hit |
| 2 | Circuit Breaker        | 3 losses / 30 min    | Trips on consecutive losses                 |
| 3 | Post-Loss Cooldown     | 300 s (5 min)        | Pause after any losing trade                |
| 4 | Position Conflict      | 1 concurrent max     | Prevents opening a second position          |
| 5 | Daily Loss Limit (USD) | $500                 | Halts bot when daily loss exceeds limit     |
| 6 | Daily Loss Limit (%)   | 5% of equity         | Halts bot when daily loss % exceeds limit   |
| 7 | Max Drawdown           | 15% from peak equity | Halts bot when drawdown exceeds threshold   |
| 8 | Position Size Cap      | min(25% balance, $10k) | Caps notional value per trade             |
| 9 | Rate Limiter           | 5 orders/sec         | Token-bucket throttle to prevent spam       |

Additionally, open positions are protected by a **5% hard stop-loss** and a **3% trailing stop** evaluated on every tick.

## Project Structure

```
High Frequency Trading Bot/
├── main.py                     # Entry point, CLI, component wiring
├── requirements.txt
├── .env.example
│
├── config/
│   └── settings.py             # Dataclass-based configuration
│
├── data/
│   ├── models.py               # Candle, Tick, Position data models
│   └── feed.py                 # Async WebSocket market data feed
│
├── strategy/
│   ├── indicators.py           # EMA, RSI, VWAP, BB, Volume, ATR
│   ├── signals.py              # Weighted composite signal generation
│   └── engine.py               # Strategy orchestrator
│
├── execution/
│   ├── paper_engine.py         # Simulated fills (paper mode)
│   ├── binance_executor.py     # Binance Futures REST executor
│   ├── order_manager.py        # Risk check → execute → track
│   └── position_tracker.py     # Position state, PnL, persistence
│
├── risk/
│   ├── manager.py              # 9-layer pre-trade risk checks
│   └── circuit_breaker.py      # Consecutive loss detection
│
├── dashboard/
│   ├── app.py                  # Rich Live terminal dashboard
│   └── panels.py               # UI panels (price, signals, risk, etc.)
│
├── utils/
│   ├── helpers.py              # Async retry & rate limiter
│   └── logging.py              # Rich logging + dashboard buffer
│
└── tests/
    ├── conftest.py
    ├── test_indicators.py
    ├── test_signals.py
    ├── test_paper_engine.py
    └── test_risk.py
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/high-frequency-trading-bot.git
cd high-frequency-trading-bot

# Install dependencies
pip install -r requirements.txt

# Configure environment (required for testnet/live only)
cp .env.example .env
# Edit .env with your Binance API credentials

# Run in paper mode (no API keys needed)
python main.py --mode paper
```

## CLI Usage

```bash
python main.py [--mode {paper,testnet,live}] [--symbol SYMBOL] [--interval INTERVAL]
```

| Flag         | Default    | Description                          |
|--------------|------------|--------------------------------------|
| `--mode`     | `paper`    | Execution mode                       |
| `--symbol`   | `BTCUSDT`  | Binance Futures trading pair         |
| `--interval` | `1m`       | Candle interval (1m, 5m, 15m, 1h)   |

**Examples:**

```bash
# Paper trade ETH with 5-minute candles
python main.py --mode paper --symbol ETHUSDT --interval 5m

# Testnet with default settings
python main.py --mode testnet

# Live trading (requires confirmation prompt)
python main.py --mode live --symbol BTCUSDT
```

## Testing

```bash
pytest tests/ -v
```

Tests cover indicators, signal generation, paper engine execution, and risk management logic.

## Disclaimer

This software is for **educational and research purposes only**. It is **not financial advice**. Trading cryptocurrencies involves substantial risk of loss. Use this bot at your own risk. The authors are not responsible for any financial losses incurred through the use of this software. Always test thoroughly in paper/testnet mode before considering live deployment.
