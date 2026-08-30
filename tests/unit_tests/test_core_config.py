from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.containers import ContainerProcessTable, ContainerSummary
from easy_docker_manager.core.log_text import MIN_LOG_LINE_CHARS
from easy_docker_manager.core.tabs import TabName


def test_app_config_uses_expected_defaults() -> None:
    config = AppConfig()

    assert config.container_list_refresh_interval_seconds == 2.0
    assert config.tab_refresh_interval == 2.0
    assert config.initial_log_tail_lines == 100
    assert config.max_log_lines == 2000
    assert config.max_log_line_chars == 4000
    assert config.tab_content_cache_max_entries == 50
    assert config.tab_content_cache_max_bytes == 25_000_000
    assert config.docker_request_timeout == 10.0
    assert config.max_background_worker_threads == 4
    assert config.colors_enabled is True
    assert config.application_log_level == "INFO"
    assert config.application_log_to_stdout is False


@pytest.mark.parametrize(
    "field_name",
    [
        "container_list_refresh_interval_seconds",
        "tab_refresh_interval",
        "initial_log_tail_lines",
        "max_log_lines",
        "tab_content_cache_max_entries",
        "tab_content_cache_max_bytes",
        "docker_request_timeout",
        "max_background_worker_threads",
    ],
)
def test_app_config_rejects_non_positive_values(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be positive"):
        AppConfig(**{field_name: 0})


def test_app_config_is_immutable() -> None:
    config = AppConfig()

    with pytest.raises(FrozenInstanceError):
        config.initial_log_tail_lines = 10  # type: ignore[misc]


def test_app_config_requires_a_practical_log_line_limit() -> None:
    with pytest.raises(
        ValueError,
        match=f"max_log_line_chars must be at least {MIN_LOG_LINE_CHARS}",
    ):
        AppConfig(max_log_line_chars=MIN_LOG_LINE_CHARS - 1)


def test_app_config_rejects_unknown_application_log_level() -> None:
    with pytest.raises(ValueError, match="application_log_level must be one of"):
        AppConfig(application_log_level="TRACE")


def test_container_models_store_summary_and_process_data() -> None:
    container_summary = ContainerSummary(
        container_id="abc",
        name="web",
        status="running",
        image_name="nginx:latest",
        created_at="2026-01-01T12:00:00Z",
    )
    process_list = ContainerProcessTable(
        columns=("PID", "CMD"),
        rows=(("1", "python"),),
    )

    assert container_summary.name == "web"
    assert process_list.columns == ("PID", "CMD")
    assert process_list.rows[0] == ("1", "python")


def test_tab_names_match_the_visible_labels() -> None:
    assert [tab.value for tab in TabName] == [
        "Logs",
        "Env",
        "Config",
        "Stats",
        "Top",
    ]
