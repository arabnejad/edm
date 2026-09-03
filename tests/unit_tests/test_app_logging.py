from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.logging import app_logging


@pytest.fixture(autouse=True)
def reset_edm_logger_handlers():
    """Close handlers before and after each logging test."""

    edm_logger = logging.getLogger("easy_docker_manager")
    paramiko_logger = logging.getLogger(app_logging.PARAMIKO_LOGGER_NAME)
    app_logging._remove_and_close_handlers(edm_logger, paramiko_logger)
    yield
    app_logging._remove_and_close_handlers(edm_logger, paramiko_logger)
    paramiko_logger.setLevel(logging.NOTSET)
    paramiko_logger.propagate = True


def test_default_log_path_uses_the_edm_platform_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        app_logging,
        "user_config_dir",
        lambda **_kwargs: "/tmp/user-config/EDM",
    )

    assert app_logging.default_log_file_path() == Path("/tmp/user-config/EDM/edm.log")


def test_configured_log_path_uses_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", "~/edm-custom.log")

    assert app_logging.get_configured_log_file_path() == (
        Path.home() / "edm-custom.log"
    )


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


def test_saved_level_and_stdout_settings_are_used_without_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", str(tmp_path / "edm.log"))
    monkeypatch.delenv("EDM_LOG_LEVEL", raising=False)
    monkeypatch.delenv("EDM_LOG_STDOUT", raising=False)

    logger = app_logging.configure_logging(
        AppConfig(
            application_log_level="ERROR",
            application_log_to_stdout=True,
        )
    )

    assert logger.level == logging.ERROR
    assert len(logger.handlers) == 2


def test_logging_environment_variables_override_saved_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", str(tmp_path / "edm.log"))
    monkeypatch.setenv("EDM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("EDM_LOG_STDOUT", "off")

    logger = app_logging.configure_logging(
        AppConfig(
            application_log_level="ERROR",
            application_log_to_stdout=True,
        )
    )

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_invalid_log_level_falls_back_to_info(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EDM_LOG_FILE", str(tmp_path / "edm.log"))
    monkeypatch.setenv("EDM_LOG_LEVEL", "NOT_A_LEVEL")

    logger = app_logging.configure_logging()
    assert logger.level == logging.INFO


def test_paramiko_errors_are_not_written_over_the_terminal(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    log_path = tmp_path / "edm.log"
    monkeypatch.setenv("EDM_LOG_FILE", str(log_path))
    app_logging.configure_logging()
    app_logging.configure_logging()

    logging.getLogger("paramiko.transport").error(
        "Secsh channel 94 open FAILED: open failed: Connect failed"
    )

    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == ""
    paramiko_logger = logging.getLogger(app_logging.PARAMIKO_LOGGER_NAME)
    for handler in paramiko_logger.handlers:
        handler.flush()
    assert "Secsh channel 94 open FAILED" in log_path.read_text(encoding="utf-8")
    assert len(paramiko_logger.handlers) == 1
    assert (
        paramiko_logger.handlers[0] in logging.getLogger("easy_docker_manager").handlers
    )


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
    paramiko_logger = logging.getLogger(app_logging.PARAMIKO_LOGGER_NAME)
    assert len(paramiko_logger.handlers) == 1
    assert isinstance(paramiko_logger.handlers[0], logging.NullHandler)
