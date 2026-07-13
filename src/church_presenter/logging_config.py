from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_path


def configure_logging(log_dir: Path | None = None) -> Path:
    """Configure a rotating development log and return its path."""
    directory = log_dir or user_log_path("Church Presenter", "JinsolSeo")
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "church_presenter.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return log_path
