from __future__ import annotations

from unittest.mock import Mock

from easy_docker_manager import main as main_module
from easy_docker_manager.core import AppConfig


def test_main_configures_logging_loads_config_and_runs_app(monkeypatch) -> None:
    configure_logging = Mock()
    config_store = Mock()
    app_config = AppConfig(refresh_interval=5)
    config_store.load_and_sync.return_value = app_config
    config_store_class = Mock(return_value=config_store)
    edm_app = Mock()
    edm_app_class = Mock(return_value=edm_app)
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "AppConfigStore", config_store_class)
    monkeypatch.setattr(main_module, "EDMApp", edm_app_class)

    assert main_module.main() == 0

    configure_logging.assert_called_once_with()
    config_store_class.assert_called_once_with()
    config_store.load_and_sync.assert_called_once_with()
    edm_app_class.assert_called_once_with(app_config=app_config)
    edm_app.run.assert_called_once_with()
