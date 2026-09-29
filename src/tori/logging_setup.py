"""Minimal logging setup for Tori."""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """Configure concise console logging without recording conversation text."""

    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
