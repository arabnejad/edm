from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from easy_docker_manager.config import app_config_store
from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.core import AppConfig


def test_load_and_sync_writes_default_config(tmp_path: Path) -> None:
    config_path = tmp_path / "EDM" / "config.json"

    loaded_config = AppConfigStore(config_path).load_and_sync()

    assert loaded_config == AppConfig()
    assert json.loads(config_path.read_text(encoding="utf-8")) == asdict(AppConfig())


def test_load_keeps_valid_values_and_removes_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "refresh_interval": 5,
                "log_tail": 25,
                "colors_enabled": False,
                "removed_setting": True,
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert loaded_config.refresh_interval == 5.0
    assert loaded_config.log_tail == 25
    assert loaded_config.colors_enabled is False
    assert saved_config["tab_refresh_interval"] == 2.0
    assert "removed_setting" not in saved_config


def test_invalid_values_use_defaults_and_are_rewritten(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "log_tail": True,
                "max_workers": -2,
                "colors_enabled": "false",
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()

    assert loaded_config.log_tail == AppConfig().log_tail
    assert loaded_config.max_workers == AppConfig().max_workers
    assert loaded_config.colors_enabled is True


def test_invalid_json_and_non_object_json_use_defaults(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{broken", encoding="utf-8")
    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")

    assert AppConfigStore(invalid_path).load_and_sync() == AppConfig()
    assert AppConfigStore(list_path).load_and_sync() == AppConfig()


def test_save_failure_does_not_prevent_config_loading(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    config_path = tmp_path / "config.json"
    config_store = AppConfigStore(config_path)

    def fail_mkdir(*_args, **_kwargs) -> None:
        raise OSError("read only")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    loaded_config = config_store.load_and_sync()

    assert loaded_config == AppConfig()
    assert "Unable to save config file" in caplog.text


def test_default_config_path_uses_the_edm_platform_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        app_config_store,
        "user_config_dir",
        lambda **_kwargs: "/tmp/user-config/EDM",
    )

    assert app_config_store.default_config_path() == Path(
        "/tmp/user-config/EDM/config.json"
    )
