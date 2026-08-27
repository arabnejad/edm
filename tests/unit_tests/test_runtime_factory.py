from __future__ import annotations

from functools import partial
from unittest.mock import Mock

from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.core import AppConfig
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient


def test_runtime_factory_uses_supplied_config_and_data_source() -> None:
    config = AppConfig(
        content_cache_size=7,
        content_cache_max_bytes=500,
        max_workers=2,
    )
    docker_container_client = Mock(spec=DockerContainerClient)
    notify_background_work_ready = Mock()
    runtime = EDMRuntimeFactory(config, docker_container_client).create_runtime(
        notify_background_work_ready
    )

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
    finally:
        runtime.background_executor.shutdown()


def test_runtime_factory_builds_local_data_source_with_configured_timeout() -> None:
    runtime_factory = EDMRuntimeFactory(AppConfig(docker_request_timeout=3.5))

    assert isinstance(
        runtime_factory.docker_container_client,
        LocalDockerContainerClient,
    )
    create_client = runtime_factory.docker_container_client._create_docker_client
    assert isinstance(create_client, partial)
    assert create_client.func is create_docker_client
    assert create_client.args == (3.5,)


def test_runtime_factory_uses_default_config_when_none_is_given() -> None:
    runtime_factory = EDMRuntimeFactory(
        docker_container_client=Mock(spec=DockerContainerClient)
    )
    assert runtime_factory.app_config == AppConfig()
