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
from easy_docker_manager.core.config import AppConfig

LOG_FILE_NAME = "edm.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 3
PARAMIKO_LOGGER_NAME = "paramiko"


def default_log_file_path() -> Path:
    """Return the edm.log path in the same user directory as config.json."""
    return Path(user_config_dir(appname=APP_NAME, appauthor=False)) / LOG_FILE_NAME


def get_configured_log_file_path() -> Path:
    """Return the log path selected by EDM_LOG_FILE or the platform default."""
    configured_log_file = os.getenv("EDM_LOG_FILE")
    return (
        Path(configured_log_file).expanduser()
        if configured_log_file
        else default_log_file_path()
    )


def configure_logging(app_config: Optional[AppConfig] = None) -> logging.Logger:
    """Configure EDM's rotating log file and optional terminal output.

    main() calls this before loading config.json so file errors can be logged.
    It calls it again when the saved log settings differ from the defaults.
    Environment variables override saved values and can also change the file
    path. If EDM cannot create the log file, warnings go to stderr and startup
    continues.
    """
    selected_config = app_config if app_config is not None else AppConfig()
    level_name = os.getenv(
        "EDM_LOG_LEVEL",
        selected_config.application_log_level,
    ).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = get_configured_log_file_path()
    configured_stdout_value = os.getenv("EDM_LOG_STDOUT")
    if configured_stdout_value is None:
        stdout_enabled = selected_config.application_log_to_stdout
    else:
        stdout_enabled = configured_stdout_value.lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    logger = logging.getLogger("easy_docker_manager")
    paramiko_logger = logging.getLogger(PARAMIKO_LOGGER_NAME)
    logger.setLevel(level)
    paramiko_logger.setLevel(max(level, logging.WARNING))
    logger.propagate = False
    paramiko_logger.propagate = False
    _remove_and_close_handlers(logger, paramiko_logger)

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
        paramiko_logger.addHandler(file_handler)

    if stdout_enabled:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if file_logging_error is not None:
        # Without a handler, Python may print Paramiko errors over the EDM
        # screen. NullHandler keeps them out of the terminal when edm.log is
        # unavailable.
        paramiko_logger.addHandler(logging.NullHandler())
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


def _remove_and_close_handlers(*loggers: logging.Logger) -> None:
    """Remove old handlers before EDM applies a new logging configuration.

    The EDM and Paramiko loggers share the same file handler. Track handlers by
    id so the shared handler is closed only once.
    """
    removed_handlers: dict[int, logging.Handler] = {}
    for logger in loggers:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            removed_handlers[id(handler)] = handler
    for handler in removed_handlers.values():
        handler.close()


__all__ = [
    "configure_logging",
    "default_log_file_path",
    "get_configured_log_file_path",
]
