"""Rich panels for the terminal dashboard."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from data.models import OrderBookSnapshot, Position
from strategy.signals import SignalBreakdown
from utils.logging import log_buffer


def price_panel(symbol: str, price: float, change_24h: float = 0.0) -> Panel:
    """Current price display."""
    color = "green" if change_24h >= 0 else "red"
    content = Table.grid(padding=(0, 2))
    content.add_column(justify="right")
    content.add_column(justify="left")
    content.add_row("Symbol:", f"[bold]{symbol}[/bold]")
    content.add_row("Price:", f"[bold {color}]${price:,.2f}[/bold {color}]")
    return Panel(content, title="Market", border_style="blue")


def signal_panel(signal: SignalBreakdown) -> Panel:
    """Current signal breakdown."""
    table = Table.grid(padding=(0, 1))
    table.add_column("Indicator", justify="left", min_width=12)
    table.add_column("Signal", justify="right", min_width=8)
    table.add_column("Bar", justify="left", min_width=12)

    components = [
        ("EMA Cross", signal.ema_signal),
        ("RSI", signal.rsi_signal),
        ("VWAP", signal.vwap_signal),
        ("Boll. Bands", signal.bb_signal),
        ("Volume", signal.volume_signal),
    ]
    for name, val in components:
        color = "green" if val > 0 else ("red" if val < 0 else "dim")
        bar = _signal_bar(val)
        table.add_row(name, f"[{color}]{val:+.3f}[/{color}]", bar)

    # Composite
    comp = signal.composite
    comp_color = "bold green" if comp > 0.3 else ("bold red" if comp < -0.3 else "yellow")
    table.add_row("", "", "")
    table.add_row("[bold]COMPOSITE[/bold]", f"[{comp_color}]{comp:+.3f}[/{comp_color}]", _signal_bar(comp))

    return Panel(table, title="Signals", border_style="magenta")


def _signal_bar(value: float, width: int = 10) -> str:
    """Render a mini bar chart for a signal value."""
    half = width // 2
    pos = int(abs(value) * half)
    if value >= 0:
        bar = " " * half + "|" + "#" * pos + " " * (half - pos)
        return f"[green]{bar}[/green]"
    else:
        bar = " " * (half - pos) + "#" * pos + "|" + " " * half
        return f"[red]{bar}[/red]"


def position_panel(pos: Position, daily_pnl: float, equity: float, win_rate: float) -> Panel:
    """Position and PnL display."""
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", min_width=14)
    table.add_column(justify="left", min_width=16)

    if pos.is_open:
        side_color = "green" if pos.side and pos.side.value == "BUY" else "red"
        table.add_row("Status:", f"[bold {side_color}]{pos.side.value if pos.side else 'N/A'}[/bold {side_color}]")
        table.add_row("Entry:", f"${pos.entry_price:,.2f}")
        table.add_row("Size:", f"{pos.quantity:.6f}")
        pnl_color = "green" if pos.unrealized_pnl >= 0 else "red"
        table.add_row("Unrealized PnL:", f"[{pnl_color}]${pos.unrealized_pnl:+,.2f}[/{pnl_color}]")
        table.add_row("Highest:", f"${pos.highest_price:,.2f}")
    else:
        table.add_row("Status:", "[dim]No Position[/dim]")

    table.add_row("", "")
    dpnl_color = "green" if daily_pnl >= 0 else "red"
    table.add_row("Daily PnL:", f"[{dpnl_color}]${daily_pnl:+,.2f}[/{dpnl_color}]")
    table.add_row("Equity:", f"${equity:,.2f}")
    table.add_row("Win Rate:", f"{win_rate * 100:.1f}%")

    return Panel(table, title="Position", border_style="green")


def risk_panel(risk_status: dict) -> Panel:
    """Risk management status display."""
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", min_width=16)
    table.add_column(justify="left")

    halted = risk_status.get("halted", False)
    status_text = "[bold red]HALTED[/bold red]" if halted else "[bold green]ACTIVE[/bold green]"
    table.add_row("Status:", status_text)

    if halted:
        table.add_row("Reason:", f"[red]{risk_status.get('halt_reason', '')}[/red]")

    cb_tripped = risk_status.get("circuit_breaker_tripped", False)
    cb_text = "[red]TRIPPED[/red]" if cb_tripped else "[green]OK[/green]"
    table.add_row("Circuit Breaker:", cb_text)

    cooldown = risk_status.get("in_cooldown", False)
    if cooldown:
        remaining = risk_status.get("cooldown_remaining", 0)
        table.add_row("Cooldown:", f"[yellow]{remaining:.0f}s[/yellow]")
    else:
        table.add_row("Cooldown:", "[dim]None[/dim]")

    consec = risk_status.get("consecutive_losses", 0)
    consec_color = "red" if consec >= 2 else ("yellow" if consec >= 1 else "green")
    table.add_row("Consec. Losses:", f"[{consec_color}]{consec}[/{consec_color}]")

    return Panel(table, title="Risk", border_style="red")


def orderbook_panel(ob: OrderBookSnapshot) -> Panel:
    """Orderbook depth display (top 5 bids/asks)."""
    table = Table(show_header=True, header_style="bold", padding=(0, 1), expand=True)
    table.add_column("Bid Qty", justify="right", style="green")
    table.add_column("Bid Price", justify="right", style="green")
    table.add_column("Ask Price", justify="left", style="red")
    table.add_column("Ask Qty", justify="left", style="red")

    asks_display = list(reversed(ob.asks[:5])) if ob.asks else []
    bids_display = ob.bids[:5] if ob.bids else []

    max_rows = max(len(asks_display), len(bids_display), 1)

    for i in range(max_rows):
        bid_p = f"{bids_display[i][0]:,.2f}" if i < len(bids_display) else ""
        bid_q = f"{bids_display[i][1]:.4f}" if i < len(bids_display) else ""
        ask_p = f"{asks_display[i][0]:,.2f}" if i < len(asks_display) else ""
        ask_q = f"{asks_display[i][1]:.4f}" if i < len(asks_display) else ""
        table.add_row(bid_q, bid_p, ask_p, ask_q)

    spread = ob.spread
    spread_text = f"Spread: ${spread:.2f}" if spread else "Spread: N/A"

    return Panel(table, title=f"Order Book ({spread_text})", border_style="cyan")


def log_panel(max_lines: int = 15) -> Panel:
    """Recent log entries."""
    lines = []
    recent = list(log_buffer)[-max_lines:]
    for entry in recent:
        level = entry["level"]
        color = {
            "DEBUG": "dim",
            "INFO": "white",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red",
        }.get(level, "white")
        lines.append(f"[dim]{entry['time']}[/dim] [{color}]{entry['message']}[/{color}]")

    content = "\n".join(lines) if lines else "[dim]No log entries yet[/dim]"
    return Panel(Text.from_markup(content), title="Log", border_style="yellow")
