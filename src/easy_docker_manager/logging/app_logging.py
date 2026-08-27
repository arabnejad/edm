"""Configure EDM's rotating application log."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

from easy_docker_manager.constants import APP_NAME

LOG_FILE_NAME = "edm.log"
DEFAULT_LOG_LEVEL = "INFO"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 3


def default_log_file_path() -> Path:
    """Return the edm.log path in the same user directory as config.json."""
    return Path(user_config_dir(appname=APP_NAME, appauthor=False)) / LOG_FILE_NAME


def configure_logging() -> logging.Logger:
    """Configure EDM's rotating log file and optional terminal output.

    main() calls this before loading config or starting the UI. Environment
    variables can change the level, file path, and stdout output. If EDM cannot
    create the log file, warnings go to stderr and startup continues.
    """
    level_name = os.getenv("EDM_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    configured_log_file = os.getenv("EDM_LOG_FILE")
    log_file = (
        Path(configured_log_file).expanduser()
        if configured_log_file
        else default_log_file_path()
    )
    stdout_enabled = os.getenv("EDM_LOG_STDOUT", "0").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    logger = logging.getLogger("easy_docker_manager")
    logger.setLevel(level)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_logging_error: Optional[OSError] = None
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as exc:
        file_logging_error = exc
    else:
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if stdout_enabled:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if file_logging_error is not None:
        if not logger.handlers:
            fallback_handler = logging.StreamHandler(sys.stderr)
            fallback_handler.setLevel(logging.WARNING)
            fallback_handler.setFormatter(formatter)
            logger.addHandler(fallback_handler)
        logger.warning("Unable to create log file %s: %s", log_file, file_logging_error)
    else:
        logger.info(
            "EDM logging initialized: file=%s stdout=%s", log_file, stdout_enabled
        )
    return logger


__all__ = ["configure_logging", "default_log_file_path"]
