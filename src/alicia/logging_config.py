"""Bounded application logs, independent from SDK and network debug logs."""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(directory: Path, debug: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "alicia.log"
    logger = logging.getLogger("alicia")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    for handler in tuple(logger.handlers):
        if getattr(handler, "_alicia_managed", False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler._alicia_managed = True
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return log_path
