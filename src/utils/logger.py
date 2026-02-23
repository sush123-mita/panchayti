"""
logger.py — Centralised logging setup.

All modules use:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
"""

import logging
import sys
from pathlib import Path

_INITIALISED = False


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """
    Call once at startup.  Adds a console handler and a rotating file handler.
    """
    global _INITIALISED
    if _INITIALISED:
        return get_logger()

    root = logging.getLogger("localdiscord")
    root.setLevel(logging.DEBUG)        # capture everything; handlers filter

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console — INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File — DEBUG and above
    log_dir = Path.home() / ".localdiscord"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "localdiscord.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    _INITIALISED = True
    return root


def get_logger(name: str = "localdiscord") -> logging.Logger:
    """Return a child logger under the 'localdiscord' namespace."""
    if not name.startswith("localdiscord"):
        name = f"localdiscord.{name}"
    return logging.getLogger(name)
