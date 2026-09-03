from __future__ import annotations

from functools import partial
from unittest.mock import Mock

from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.docker_sdk_container_client import (
    DockerSDKContainerClient,
)


def test_runtime_factory_uses_supplied_config_and_data_source() -> None:
    config = AppConfig(
        tab_content_cache_max_entries=7,
        tab_content_cache_max_bytes=500,
        max_background_worker_threads=2,
    )
    docker_container_client = Mock(spec=DockerContainerClient)
    notify_background_work_ready = Mock()
    app_config_store = Mock(spec=AppConfigStore)
    runtime = EDMRuntimeFactory(
        config,
        docker_container_client,
        app_config_store,
    ).create_runtime(notify_background_work_ready)

    try:
        assert runtime.docker_container_client is docker_container_client
        state = runtime.terminal_controller.state
        assert state.tab_content_cache.max_entries == 7
        assert state.tab_content_cache.max_total_bytes == 500
        docker_manager = runtime.docker_manager
        assert docker_manager.app_config is config
        assert docker_manager.state is state
        assert docker_manager.docker_container_client is docker_container_client
        assert (
            docker_manager.tab_data_loader.docker_container_client
            is docker_container_client
        )
        assert docker_manager.background_executor is runtime.background_executor
        assert (
            runtime.keyboard_controller.terminal_controller
            is runtime.terminal_controller
        )
        tab_export_controller = runtime.keyboard_controller.tab_export_controller
        assert tab_export_controller.state is state
        assert tab_export_controller.background_executor is runtime.background_executor
        diagnostics_controller = runtime.keyboard_controller.diagnostics_controller
        assert diagnostics_controller.state is state
        assert diagnostics_controller.background_executor is runtime.background_executor
        assert diagnostics_controller.docker_container_client is docker_container_client
        settings_controller = runtime.keyboard_controller.settings_controller
        assert settings_controller.state is state
        assert settings_controller.app_config_store is app_config_store
        container_action_controller = (
            runtime.keyboard_controller.container_action_controller
        )
        assert container_action_controller.state is state
        assert container_action_controller.docker_manager is docker_manager
    finally:
        runtime.background_executor.shutdown()


def test_runtime_factory_builds_sdk_client_for_startup_context_and_timeout() -> None:
    runtime_factory = EDMRuntimeFactory(AppConfig(docker_request_timeout=3.5))

    assert isinstance(
        runtime_factory.docker_container_client,
        DockerSDKContainerClient,
    )
    create_docker_client_callback = (
        runtime_factory.docker_container_client._create_docker_client
    )
    assert isinstance(create_docker_client_callback, partial)
    assert create_docker_client_callback.func is create_docker_client
    assert create_docker_client_callback.args == (
        runtime_factory.startup_docker_context,
        3.5,
    )


def test_runtime_factory_uses_default_config_when_none_is_given() -> None:
    runtime_factory = EDMRuntimeFactory(
        docker_container_client=Mock(spec=DockerContainerClient)
    )
    assert runtime_factory.app_config == AppConfig()
