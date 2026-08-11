from __future__ import annotations

from unittest.mock import Mock

import pytest

from easy_docker_manager.core import AppConfig, ContainerProcessTable
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.docker.base import ContainerDataSource, LogsUnavailableError
from easy_docker_manager.tabs.tab_data_loader import (
    ConfigTabDataProvider,
    EnvTabDataProvider,
    LogsTabDataProvider,
    TabDataLoader,
    TabDataProvider,
    TopTabDataProvider,
    format_logs_unavailable_message,
)


@pytest.fixture
def container_data_source() -> Mock:
    return Mock(spec=ContainerDataSource)


def test_tab_data_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        TabDataProvider()  # type: ignore[abstract]


def test_logs_provider_applies_fetch_and_display_limits(
    container_data_source: Mock,
) -> None:
    container_data_source.get_logs.return_value = f"old\n{'1' * 50}\nnew"
    config = AppConfig(log_tail=2, max_log_lines=2, max_log_line_chars=32)

    result = LogsTabDataProvider(container_data_source, config).load_text("abc")

    container_data_source.get_logs.assert_called_once_with("abc", 2)
    assert result.splitlines()[-1] == "new"
    assert "old" not in result


def test_env_provider_sorts_and_shows_all_variable_values(
    container_data_source: Mock,
) -> None:
    container_data_source.get_environment_variables.return_value = {
        "Z": "last",
        "API_KEY": "secret",
        "A": "first",
    }

    result = EnvTabDataProvider(container_data_source).load_text("abc")

    assert result.splitlines() == ["A=first", "API_KEY=secret", "Z=last"]


def test_env_provider_handles_empty_data(
    container_data_source: Mock,
) -> None:
    container_data_source.get_environment_variables.return_value = {}
    assert EnvTabDataProvider(container_data_source).load_text("abc") == ""


def test_config_provider_formats_docker_inspection_data(
    container_data_source: Mock,
) -> None:
    container_data_source.get_docker_inspection_data.return_value = {
        "container": {"Name": "/web", "Id": "abcdef"}
    }

    result = ConfigTabDataProvider(container_data_source).load_text("abc")

    assert "== Identity ==" in result
    assert "web" in result


def test_top_provider_formats_process_columns_and_rows(
    container_data_source: Mock,
) -> None:
    container_data_source.get_process_list.return_value = ContainerProcessTable(
        columns=("PID", "CMD"),
        rows=(("1", "python"), ("2", "worker")),
    )

    result = TopTabDataProvider(container_data_source).load_text("abc")

    assert result == "PID CMD\n1 python\n2 worker"


def test_top_provider_returns_empty_text_for_empty_process_list(
    container_data_source: Mock,
) -> None:
    container_data_source.get_process_list.return_value = ContainerProcessTable((), ())
    assert TopTabDataProvider(container_data_source).load_text("abc") == ""


@pytest.mark.parametrize("tab", list(TabName))
def test_tab_data_loader_routes_each_tab_to_its_provider(
    tab: TabName,
    container_data_source: Mock,
) -> None:
    container_data_source.get_logs.return_value = "logs"
    container_data_source.get_environment_variables.return_value = {"A": "1"}
    container_data_source.get_docker_inspection_data.return_value = {"container": {}}
    container_data_source.get_process_list.return_value = ContainerProcessTable((), ())
    tab_data_loader = TabDataLoader(container_data_source, AppConfig())

    result = tab_data_loader.load_tab_text("abc", tab)

    assert isinstance(result, str)


def test_logs_unavailable_message_names_driver_and_solution() -> None:
    message = format_logs_unavailable_message(LogsUnavailableError("none"))
    assert "driver 'none'" in message
    assert "json-file" in message
