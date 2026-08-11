from __future__ import annotations

from functools import partial
from unittest.mock import Mock

from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.core import AppConfig
from easy_docker_manager.docker.base import ContainerDataSource
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.local import LocalContainerDataSource


def test_runtime_factory_uses_supplied_config_and_data_source() -> None:
    config = AppConfig(
        content_cache_size=7,
        content_cache_max_bytes=500,
        max_workers=2,
    )
    container_data_source = Mock(spec=ContainerDataSource)
    notify_background_work_ready = Mock()
    runtime = EDMRuntimeFactory(config, container_data_source).create_runtime(
        notify_background_work_ready
    )

    try:
        assert runtime.container_data_source is container_data_source
        state = runtime.ui_controller.state
        assert state.tab_content_cache.max_entries == 7
        assert state.tab_content_cache.max_total_bytes == 500
        assert all(
            provider.container_data_source is container_data_source
            for provider in runtime.scheduler.tab_data_loader._providers_by_tab.values()
        )
        assert runtime.scheduler.app_config is config
        assert runtime.scheduler.state is state
        assert runtime.scheduler.task_runner is runtime.task_runner
        assert runtime.keyboard_controller.ui_controller is runtime.ui_controller
        assert runtime.background_task_result_handler.scheduler is runtime.scheduler
    finally:
        runtime.task_runner.shutdown()


def test_runtime_factory_builds_local_data_source_with_configured_timeout() -> None:
    runtime_factory = EDMRuntimeFactory(AppConfig(docker_request_timeout=3.5))

    assert isinstance(
        runtime_factory.container_data_source,
        LocalContainerDataSource,
    )
    create_client = runtime_factory.container_data_source._create_docker_client
    assert isinstance(create_client, partial)
    assert create_client.func is create_docker_client
    assert create_client.args == (3.5,)


def test_runtime_factory_uses_default_config_when_none_is_given() -> None:
    runtime_factory = EDMRuntimeFactory(
        container_data_source=Mock(spec=ContainerDataSource)
    )
    assert runtime_factory.app_config == AppConfig()
