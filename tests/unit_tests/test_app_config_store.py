from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager.config import app_config_store
from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.core.config import AppConfig


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
                "container_list_refresh_interval_seconds": 5,
                "initial_log_tail_lines": 25,
                "colors_enabled": False,
                "removed_setting": True,
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert loaded_config.container_list_refresh_interval_seconds == 5.0
    assert loaded_config.initial_log_tail_lines == 25
    assert loaded_config.colors_enabled is False
    assert saved_config["detail_tab_refresh_interval_seconds"] == 2.0
    assert "removed_setting" not in saved_config


def test_load_migrates_renamed_config_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tab_refresh_interval": 5,
                "docker_request_timeout": 20,
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert loaded_config.detail_tab_refresh_interval_seconds == 5.0
    assert loaded_config.docker_request_timeout_seconds == 20.0
    assert saved_config["detail_tab_refresh_interval_seconds"] == 5.0
    assert saved_config["docker_request_timeout_seconds"] == 20.0
    assert "tab_refresh_interval" not in saved_config
    assert "docker_request_timeout" not in saved_config


def test_current_config_keys_take_priority_over_old_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tab_refresh_interval": 5,
                "detail_tab_refresh_interval_seconds": 7,
                "docker_request_timeout": 20,
                "docker_request_timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()

    assert loaded_config.detail_tab_refresh_interval_seconds == 7.0
    assert loaded_config.docker_request_timeout_seconds == 30.0


def test_invalid_values_use_defaults_and_are_rewritten(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "initial_log_tail_lines": True,
                "max_background_worker_threads": -2,
                "colors_enabled": "false",
            }
        ),
        encoding="utf-8",
    )

    loaded_config = AppConfigStore(config_path).load_and_sync()

    assert loaded_config.initial_log_tail_lines == AppConfig().initial_log_tail_lines
    assert (
        loaded_config.max_background_worker_threads
        == AppConfig().max_background_worker_threads
    )
    assert loaded_config.colors_enabled is True


def test_invalid_json_and_non_object_json_use_defaults(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{broken", encoding="utf-8")
    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")

    assert AppConfigStore(invalid_path).load_and_sync() == AppConfig()
    assert AppConfigStore(list_path).load_and_sync() == AppConfig()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400])
def test_invalid_durations_use_defaults_and_keep_other_settings(
    tmp_path: Path, value: object
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "container_list_refresh_interval_seconds": value,
                "detail_tab_refresh_interval_seconds": value,
                "docker_request_timeout_seconds": value,
                "colors_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    loaded = AppConfigStore(config_path).load_and_sync()

    assert loaded == AppConfig(colors_enabled=False)
    assert json.loads(config_path.read_text(encoding="utf-8")) == asdict(loaded)


@pytest.mark.parametrize("contents", [b"\xff\xfe", b"{broken", b"[]"])
def test_unusable_settings_are_backed_up_before_writing_defaults(
    tmp_path: Path, contents: bytes
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_bytes(contents)

    assert AppConfigStore(config_path).load_and_sync() == AppConfig()

    assert (tmp_path / "config.json.invalid").read_bytes() == contents
    assert json.loads(config_path.read_text(encoding="utf-8")) == asdict(AppConfig())


def test_backing_up_invalid_settings_keeps_previous_backups(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    (tmp_path / "config.json.invalid").write_bytes(b"first bad file")
    (tmp_path / "config.json.invalid.1").write_bytes(b"second bad file")
    config_path.write_bytes(b"\xff")

    assert AppConfigStore(config_path).load_and_sync() == AppConfig()

    assert (tmp_path / "config.json.invalid").read_bytes() == b"first bad file"
    assert (tmp_path / "config.json.invalid.1").read_bytes() == b"second bad file"
    assert (tmp_path / "config.json.invalid.2").read_bytes() == b"\xff"


def test_backup_failure_leaves_invalid_settings_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_bytes(b"\xff")
    monkeypatch.setattr(Path, "rename", Mock(side_effect=OSError("read only")))

    assert AppConfigStore(config_path).load_and_sync() == AppConfig()

    assert config_path.read_bytes() == b"\xff"
    assert "leaving it unchanged" in caplog.text


def test_settings_directory_is_left_untouched(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.mkdir()

    assert AppConfigStore(config_path).load_and_sync() == AppConfig()
    assert config_path.is_dir()


def test_save_rejects_non_finite_json_without_replacing_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"colors_enabled": false}', encoding="utf-8")
    monkeypatch.setattr(
        app_config_store, "asdict", lambda config: {"bad": float("nan")}
    )

    assert AppConfigStore(config_path).save(AppConfig()) is False
    assert config_path.read_text(encoding="utf-8") == '{"colors_enabled": false}'


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


def test_save_reports_success_and_failure(tmp_path: Path, monkeypatch) -> None:
    config_store = AppConfigStore(tmp_path / "config.json")
    assert config_store.save(AppConfig()) is True

    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("read only")))
    assert config_store.save(AppConfig()) is False


def test_default_config_path_uses_the_edm_platform_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        app_config_store,
        "user_config_dir",
        lambda **_kwargs: "/tmp/user-config/EDM",
    )

    assert app_config_store.default_config_path() == Path(
        "/tmp/user-config/EDM/config.json"
    )
