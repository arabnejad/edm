from __future__ import annotations

import os
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager import main as main_module
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.diagnostics import DiagnosticsReport
from easy_docker_manager.docker.container_client import DockerDaemonDetails


@pytest.fixture(autouse=True)
def terminal_is_large_enough_for_edm(monkeypatch) -> None:
    """Give command tests EDM's minimum supported terminal size."""
    monkeypatch.setattr(
        main_module,
        "get_terminal_size",
        Mock(return_value=os.terminal_size((120, 30))),
    )


def test_main_configures_logging_loads_config_and_runs_app(monkeypatch) -> None:
    configure_logging = Mock()
    config_store = Mock()
    app_config = AppConfig(container_list_refresh_interval_seconds=5)
    config_store.load_and_sync.return_value = app_config
    config_store_class = Mock(return_value=config_store)
    edm_app = Mock()
    edm_app_class = Mock(return_value=edm_app)
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "AppConfigStore", config_store_class)
    monkeypatch.setattr(main_module, "EDMApp", edm_app_class)

    assert main_module.main([]) == 0

    configure_logging.assert_called_once_with()
    config_store_class.assert_called_once_with()
    config_store.load_and_sync.assert_called_once_with()
    edm_app_class.assert_called_once_with(
        app_config=app_config,
        app_config_store=config_store,
    )
    edm_app.run.assert_called_once_with()


@pytest.mark.parametrize("terminal_dimensions", [(119, 30), (120, 29), (80, 24)])
def test_main_exits_before_startup_when_terminal_is_too_small(
    monkeypatch,
    capsys,
    terminal_dimensions: tuple[int, int],
) -> None:
    configure_logging = Mock()
    config_store_class = Mock()
    edm_app_class = Mock()
    monkeypatch.setattr(
        main_module,
        "get_terminal_size",
        Mock(return_value=os.terminal_size(terminal_dimensions)),
    )
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "AppConfigStore", config_store_class)
    monkeypatch.setattr(main_module, "EDMApp", edm_app_class)

    assert main_module.main([]) == 1

    assert capsys.readouterr().err == (
        "Error: EDM requires a terminal size of at least 120 columns by 30 rows.\n"
        f"Current terminal size: {terminal_dimensions[0]} columns by "
        f"{terminal_dimensions[1]} rows.\n"
        "Resize the terminal and run EDM again.\n"
    )
    configure_logging.assert_not_called()
    config_store_class.assert_not_called()
    edm_app_class.assert_not_called()


def test_no_color_option_disables_colors_for_the_application_run(monkeypatch) -> None:
    config_store = Mock()
    config_store.load_and_sync.return_value = AppConfig(colors_enabled=True)
    edm_app = Mock()
    monkeypatch.setattr(main_module, "configure_logging", Mock())
    monkeypatch.setattr(main_module, "AppConfigStore", Mock(return_value=config_store))
    edm_app_class = Mock(return_value=edm_app)
    monkeypatch.setattr(main_module, "EDMApp", edm_app_class)

    assert main_module.main(["--no-color"]) == 0

    edm_app_class.assert_called_once_with(
        app_config=AppConfig(colors_enabled=False),
        app_config_store=config_store,
    )
    edm_app.run.assert_called_once_with()


def test_saved_logging_settings_are_applied_after_config_loading(monkeypatch) -> None:
    configure_logging = Mock()
    config_store = Mock()
    app_config = AppConfig(
        application_log_level="DEBUG",
        application_log_to_stdout=True,
    )
    config_store.load_and_sync.return_value = app_config
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "AppConfigStore", Mock(return_value=config_store))
    edm_app = Mock()
    monkeypatch.setattr(main_module, "EDMApp", Mock(return_value=edm_app))

    assert main_module.main([]) == 0

    assert configure_logging.call_args_list[0].args == ()
    assert configure_logging.call_args_list[1].args == (app_config,)


def test_help_prints_usage_without_starting_the_application(
    monkeypatch, capsys
) -> None:
    configure_logging = Mock()
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)

    with pytest.raises(SystemExit) as exit_info:
        main_module.main(["--help"])

    output = capsys.readouterr().out
    single_line_output = " ".join(output.split())
    assert exit_info.value.code == 0
    assert "usage: edm [-h] [--version] [--no-color] [--diagnostics]" in output
    assert "Run without options to start EDM." in single_line_output
    assert "--no-color" in output
    assert "--diagnostics" in output
    configure_logging.assert_not_called()


def test_version_prints_installed_version_without_starting_the_application(
    monkeypatch, capsys
) -> None:
    configure_logging = Mock()
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "_installed_version", lambda: "1.2.3")

    with pytest.raises(SystemExit) as exit_info:
        main_module.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "edm 1.2.3\n"
    configure_logging.assert_not_called()


def test_installed_version_returns_unknown_without_package_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_installed_edm_version",
        Mock(return_value="unknown"),
    )

    assert main_module._installed_version() == "unknown"


def test_diagnostics_option_exits_without_starting_the_terminal(monkeypatch) -> None:
    print_diagnostics = Mock(return_value=0)
    configure_logging = Mock()
    monkeypatch.setattr(main_module, "_print_diagnostics", print_diagnostics)
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)

    assert main_module.main(["--diagnostics"]) == 0

    print_diagnostics.assert_called_once_with()
    configure_logging.assert_not_called()


def test_print_diagnostics_closes_client_and_returns_success(
    monkeypatch, capsys
) -> None:
    report = DiagnosticsReport(
        edm_version="1.2.0",
        python_version="3.12.3",
        docker_sdk_version="7.1.0",
        config_file_path=Path("/tmp/EDM/config.json"),
        application_log_file_path=Path("/tmp/EDM/edm.log"),
    )
    docker_daemon_details = DockerDaemonDetails("28.3.3", "1.51", "linux", "amd64")
    docker_container_client = Mock()
    docker_container_client.get_docker_daemon_details.return_value = (
        docker_daemon_details
    )
    monkeypatch.setattr(
        main_module,
        "create_initial_diagnostics_report",
        lambda: report,
    )
    monkeypatch.setattr(
        main_module,
        "LocalDockerContainerClient",
        Mock(return_value=docker_container_client),
    )

    assert main_module._print_diagnostics() == 0

    docker_container_client.close.assert_called_once_with()
    assert "Connection:           Connected" in capsys.readouterr().out


def test_print_diagnostics_returns_failure_when_docker_is_unavailable(
    monkeypatch,
    capsys,
) -> None:
    report = DiagnosticsReport(
        edm_version="1.2.0",
        python_version="3.12.3",
        docker_sdk_version="7.1.0",
        config_file_path=Path("/tmp/EDM/config.json"),
        application_log_file_path=Path("/tmp/EDM/edm.log"),
    )
    docker_container_client = Mock()
    docker_container_client.get_docker_daemon_details.side_effect = RuntimeError(
        "Docker is unavailable"
    )
    monkeypatch.setattr(
        main_module,
        "create_initial_diagnostics_report",
        lambda: report,
    )
    monkeypatch.setattr(
        main_module,
        "LocalDockerContainerClient",
        Mock(return_value=docker_container_client),
    )

    assert main_module._print_diagnostics() == 1

    docker_container_client.close.assert_called_once_with()
    output = capsys.readouterr().out
    assert "Connection:           Failed" in output
    assert "Error:                Docker is unavailable" in output


def test_package_module_calls_main(monkeypatch) -> None:
    main = Mock(return_value=7)
    monkeypatch.setattr(main_module, "main", main)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("easy_docker_manager", run_name="__main__")

    assert exit_info.value.code == 7
    main.assert_called_once_with()
