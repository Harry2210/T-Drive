"""
Telegram Cloud Drive — Logging System
Provides a centralized, dual-output (file + console) logger with
coloured console output and automatic log rotation.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ANSI colour codes for console output
_COLOURS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",
}


class _ColouredFormatter(logging.Formatter):
    """Formatter that injects ANSI colour codes based on log level."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelname, "")
        reset = _COLOURS["RESET"]
        record.levelname = f"{colour}{record.levelname}{reset}"
        return super().format(record)


def setup_logger(
    log_file: str = "log.txt",
    level: int = logging.DEBUG,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
) -> logging.Logger:
    """
    Configure and return the application-wide logger.

    Parameters
    ----------
    log_file : str
        Path to the log file.
    level : int
        Minimum logging level.
    max_bytes : int
        Maximum size of a single log file before rotation.
    backup_count : int
        Number of rotated log files to keep.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger("TelegramDrive")
    if logger.handlers:
        # Already configured — return the existing instance
        return logger

    logger.setLevel(level)

    # ---------- File handler (plain text, rotating) ----------
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    file_handler.setLevel(level)

    # ---------- Console handler (coloured) ----------
    console_handler = logging.StreamHandler(sys.stdout)
    console_fmt = _ColouredFormatter(
        "[%(asctime)s] %(levelname)-18s  %(message)s",  # extra width for ANSI codes
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    console_handler.setLevel(level)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_logger() -> logging.Logger:
    """Return the shared application logger (must be set up first)."""
    return logging.getLogger("TelegramDrive")
