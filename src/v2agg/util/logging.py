from __future__ import annotations

import logging
import sys
from typing import Any


_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def setup_logging(level: str = "INFO", json_mode: bool = False) -> None:
    lvl = _LEVELS.get((level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(lvl)

    handler = logging.StreamHandler(sys.stdout)
    if json_mode:
        formatter = logging.Formatter(
            '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}'
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_kv(logger: logging.Logger, level: int, msg: str, **kwargs: Any) -> None:
    extras = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
    logger.log(level, f"{msg} {extras}".rstrip())
