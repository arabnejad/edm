from __future__ import annotations

import runpy
from unittest.mock import Mock

import pytest

from easy_docker_manager import main as main_module
from easy_docker_manager.core.config import AppConfig


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
    edm_app_class.assert_called_once_with(app_config=app_config)
    edm_app.run.assert_called_once_with()


def test_no_color_option_disables_colors_for_the_application_run(monkeypatch) -> None:
    config_store = Mock()
    config_store.load_and_sync.return_value = AppConfig(colors_enabled=True)
    edm_app = Mock()
    monkeypatch.setattr(main_module, "configure_logging", Mock())
    monkeypatch.setattr(main_module, "AppConfigStore", Mock(return_value=config_store))
    edm_app_class = Mock(return_value=edm_app)
    monkeypatch.setattr(main_module, "EDMApp", edm_app_class)

    assert main_module.main(["--no-color"]) == 0

    edm_app_class.assert_called_once_with(app_config=AppConfig(colors_enabled=False))
    edm_app.run.assert_called_once_with()


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
    assert "usage: edm [-h] [--version] [--no-color]" in output
    assert "Run without options to start EDM." in single_line_output
    assert "--no-color" in output
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
    package_not_found = main_module.PackageNotFoundError("easy-docker-manager")
    monkeypatch.setattr(
        main_module,
        "distribution_version",
        Mock(side_effect=package_not_found),
    )

    assert main_module._installed_version() == "unknown"


def test_package_module_calls_main(monkeypatch) -> None:
    main = Mock(return_value=7)
    monkeypatch.setattr(main_module, "main", main)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("easy_docker_manager", run_name="__main__")

    assert exit_info.value.code == 7
    main.assert_called_once_with()
