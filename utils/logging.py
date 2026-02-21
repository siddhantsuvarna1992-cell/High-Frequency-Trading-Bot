"""Structured logging with Rich handler and dashboard integration."""

from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

from rich.logging import RichHandler

if TYPE_CHECKING:
    pass

# In-memory log buffer for dashboard
log_buffer: deque[dict] = deque(maxlen=200)


class DashboardLogHandler(logging.Handler):
    """Pushes log records into a deque for the Rich dashboard to consume."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_buffer.append({
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name.split(".")[-1],
                "message": self.format(record),
            })
        except Exception:
            self.handleError(record)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with Rich console + dashboard buffer handlers."""
    root = logging.getLogger("hft")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return root

    # Rich console handler
    console = RichHandler(
        level=logging.INFO,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    # Dashboard buffer handler
    dash_handler = DashboardLogHandler()
    dash_handler.setLevel(logging.DEBUG)
    dash_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(dash_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hft.{name}")
