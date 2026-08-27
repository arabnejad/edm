from __future__ import annotations

from unittest.mock import Mock

import pytest

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.containers import ContainerProcessTable
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.docker.container_client import (
    ContainerLogsUnavailableError,
    DockerContainerClient,
)
from easy_docker_manager.tabs.tab_data_loader import (
    ContainerTabTextLoader,
    build_logs_unavailable_error_message,
)


@pytest.fixture
def docker_container_client() -> Mock:
    return Mock(spec=DockerContainerClient)


@pytest.fixture
def tab_data_loader(docker_container_client: Mock) -> ContainerTabTextLoader:
    return ContainerTabTextLoader(
        docker_container_client,
        AppConfig(initial_log_tail_lines=2, max_log_lines=2, max_log_line_chars=32),
    )


def test_logs_are_loaded_with_the_configured_display_limits(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_logs.return_value = f"old\n{'1' * 50}\nnew"

    result = tab_data_loader.load_tab_text("abc", TabName.LOGS)

    docker_container_client.get_container_logs.assert_called_once_with("abc", 2)
    assert result.splitlines()[-1] == "new"
    assert "old" not in result


def test_environment_variables_are_sorted_and_all_values_are_shown(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_environment_variables.return_value = {
        "Z": "last",
        "API_KEY": "secret",
        "A": "first",
    }

    result = tab_data_loader.load_tab_text("abc", TabName.ENV)

    assert result.splitlines() == ["A=first", "API_KEY=secret", "Z=last"]


def test_empty_environment_returns_empty_text(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_environment_variables.return_value = {}
    assert tab_data_loader.load_tab_text("abc", TabName.ENV) == ""


def test_container_inspection_data_is_formatted_for_the_config_tab(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_inspection_data.return_value = {
        "container": {"Name": "/web", "Id": "abcdef"}
    }

    result = tab_data_loader.load_tab_text("abc", TabName.CONFIG)

    assert "== Identity ==" in result
    assert "web" in result


def test_process_columns_and_rows_are_formatted_for_the_top_tab(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_top_process_table.return_value = (
        ContainerProcessTable(
            columns=("PID", "CMD"),
            rows=(("1", "python"), ("2", "worker")),
        )
    )

    result = tab_data_loader.load_tab_text("abc", TabName.TOP)

    assert result == "PID CMD\n1 python\n2 worker"


def test_empty_process_table_returns_empty_text(
    docker_container_client: Mock,
    tab_data_loader: ContainerTabTextLoader,
) -> None:
    docker_container_client.get_container_top_process_table.return_value = (
        ContainerProcessTable((), ())
    )
    assert tab_data_loader.load_tab_text("abc", TabName.TOP) == ""


def test_unknown_tab_is_rejected(tab_data_loader: ContainerTabTextLoader) -> None:
    with pytest.raises(ValueError, match="Unsupported tab"):
        tab_data_loader.load_tab_text("abc", object())  # type: ignore[arg-type]


def test_logs_unavailable_message_names_driver_and_solution() -> None:
    message = build_logs_unavailable_error_message(
        ContainerLogsUnavailableError("none")
    )
    assert "driver 'none'" in message
    assert "json-file" in message
