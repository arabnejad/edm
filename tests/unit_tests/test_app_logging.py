from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager.logging import app_logging


@pytest.fixture(autouse=True)
def reset_edm_logger_handlers():
    """Close handlers before and after each logging test."""

    logger = logging.getLogger("easy_docker_manager")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    yield
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def test_default_log_path_uses_the_edm_platform_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        app_logging,
        "user_config_dir",
        lambda **_kwargs: "/tmp/user-config/EDM",
    )

    assert app_logging.default_log_file_path() == Path("/tmp/user-config/EDM/edm.log")


def test_configure_logging_creates_a_rotating_file_handler(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "logs" / "edm.log"
    monkeypatch.setenv("EDM_LOG_FILE", str(log_path))
    monkeypatch.setenv("EDM_LOG_LEVEL", "DEBUG")
    monkeypatch.delenv("EDM_LOG_STDOUT", raising=False)

    logger = app_logging.configure_logging()
    logger.debug("written to file")
    for handler in logger.handlers:
        handler.flush()

    assert logger.level == logging.DEBUG
    assert log_path.exists()
    assert "written to file" in log_path.read_text(encoding="utf-8")
    file_handler = logger.handlers[0]
    assert file_handler.maxBytes == app_logging.LOG_FILE_MAX_BYTES
    assert file_handler.backupCount == app_logging.LOG_FILE_BACKUP_COUNT


def test_stdout_logging_can_be_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", str(tmp_path / "edm.log"))
    monkeypatch.setenv("EDM_LOG_STDOUT", "yes")

    logger = app_logging.configure_logging()
    assert len(logger.handlers) == 2
    assert any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    )


def test_invalid_log_level_falls_back_to_info(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", str(tmp_path / "edm.log"))
    monkeypatch.setenv("EDM_LOG_LEVEL", "NOT_A_LEVEL")

    logger = app_logging.configure_logging()
    assert logger.level == logging.INFO


def test_unwritable_log_file_uses_stderr_fallback(monkeypatch) -> None:
    monkeypatch.delenv("EDM_LOG_STDOUT", raising=False)
    monkeypatch.setattr(
        app_logging,
        "RotatingFileHandler",
        Mock(side_effect=OSError("read only")),
    )

    logger = app_logging.configure_logging()
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.StreamHandler)
    assert logger.handlers[0].level == logging.WARNING
