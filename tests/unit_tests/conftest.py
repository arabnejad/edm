from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import Mock

import pytest

from easy_docker_manager.app.container_lifecycle_action_runner import (
    ContainerLifecycleActionRunner,
)
from easy_docker_manager.app.container_list_refresh import ContainerListRefresher
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.app.selected_tab_load import SelectedTabContentLoader
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.containers import (
    ContainerResourceStatsSnapshot,
    ContainerSummary,
)
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.tabs.tab_data_loader import ContainerTabTextLoader


@dataclass
class RecordedBackgroundSubmission:
    """Store one worker request so a test can finish it later."""

    fn: Callable[..., Any]
    arguments: tuple[Any, ...]
    completion_callback: Callable[[Future], bool]
    future: Future


class RecordingBackgroundExecutor:
    """Record submitted work without starting worker threads."""

    def __init__(self) -> None:
        self.requests: list[RecordedBackgroundSubmission] = []

    def submit(
        self,
        fn: Callable[..., Any],
        *arguments: Any,
        on_complete: Callable[[Future], bool],
    ) -> Future:
        future: Future = Future()
        self.requests.append(
            RecordedBackgroundSubmission(
                fn=fn,
                arguments=arguments,
                completion_callback=on_complete,
                future=future,
            )
        )
        return future

    def complete_submission(
        self,
        request_index: int = -1,
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
    ) -> bool:
        request = self.requests[request_index]
        if exception is not None:
            request.future.set_exception(exception)
        else:
            request.future.set_result(result)
        return request.completion_callback(request.future)


@dataclass
class DockerManagerTestSetup:
    docker_manager: DockerManager
    container_list_refresher: ContainerListRefresher
    selected_tab_content_loader: SelectedTabContentLoader
    container_log_updater: ContainerLogUpdater
    container_lifecycle_action_runner: ContainerLifecycleActionRunner
    state: TerminalSessionState
    background_executor: RecordingBackgroundExecutor
    tab_data_loader: Mock
    docker_container_client: Mock


@pytest.fixture
def docker_manager_factory():
    """Create a Docker manager whose background work is completed by the test."""

    def create_docker_manager(
        state: Optional[TerminalSessionState] = None,
        app_config: Optional[AppConfig] = None,
    ) -> DockerManagerTestSetup:
        selected_state = state if state is not None else TerminalSessionState()
        selected_config = app_config if app_config is not None else AppConfig()
        background_executor = RecordingBackgroundExecutor()
        tab_data_loader = Mock(spec=ContainerTabTextLoader)
        docker_container_client = Mock(spec=DockerContainerClient)
        docker_manager = DockerManager(
            selected_state,
            selected_config,
            background_executor,  # type: ignore[arg-type]
            tab_data_loader,
            docker_container_client,
        )
        return DockerManagerTestSetup(
            docker_manager=docker_manager,
            container_list_refresher=docker_manager.container_list_refresher,
            selected_tab_content_loader=docker_manager.selected_tab_content_loader,
            container_log_updater=docker_manager.container_log_updater,
            container_lifecycle_action_runner=(
                docker_manager.container_lifecycle_action_runner
            ),
            state=selected_state,
            background_executor=background_executor,
            tab_data_loader=tab_data_loader,
            docker_container_client=docker_container_client,
        )

    return create_docker_manager


@pytest.fixture
def completed_future_factory() -> Callable[..., Future]:
    """Create completed futures with either a result or an exception."""

    def create_completed_future(
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
    ) -> Future:
        future: Future = Future()
        if exception is not None:
            future.set_exception(exception)
        else:
            future.set_result(result)
        return future

    return create_completed_future


@pytest.fixture
def container_summary_factory() -> Callable[..., ContainerSummary]:
    """Create container summaries with useful defaults for unit tests."""

    def create_container_summary(
        container_id: str = "container-1",
        name: str = "web",
        status: str = "running",
        image_name: str = "python:3.12",
        created_at: str = "2026-01-01T12:00:00Z",
        compose_project_name: Optional[str] = None,
        compose_service_name: Optional[str] = None,
    ) -> ContainerSummary:
        return ContainerSummary(
            container_id=container_id,
            name=name,
            status=status,
            image_name=image_name,
            created_at=created_at,
            compose_project_name=compose_project_name,
            compose_service_name=compose_service_name,
        )

    return create_container_summary


@pytest.fixture
def container_resource_stats_snapshot_factory() -> (
    Callable[..., ContainerResourceStatsSnapshot]
):
    """Create resource-stat snapshots with predictable values for unit tests."""

    def create_container_resource_stats_snapshot(
        **changed_values: Any,
    ) -> ContainerResourceStatsSnapshot:
        values = {
            "collected_at": datetime(2026, 1, 1, 14, 32, 18, tzinfo=timezone.utc),
            "container_uptime_seconds": 188_280.0,
            "container_health_status": "healthy",
            "container_restart_count": 2,
            "cpu_usage_percent": 12.45,
            "cpu_cores_used": 0.1245,
            "cpu_limit_cores": 2.0,
            "cpu_limit_usage_percent": 6.225,
            "cpu_throttled_period_count": 12,
            "cpu_throttled_time_seconds": 1.4,
            "memory_usage_bytes": 256 * 1024**2,
            "memory_cache_bytes": 32 * 1024**2,
            "memory_limit_bytes": 2 * 1024**3,
            "memory_available_bytes": 1792 * 1024**2,
            "memory_usage_percent": 12.5,
            "memory_swap_bytes": 0,
            "network_received_bytes": 916 * 1024**2,
            "network_receive_rate_bytes_per_second": 2.4 * 1024**2,
            "network_sent_bytes": 648 * 1024**2,
            "network_send_rate_bytes_per_second": 420 * 1024,
            "network_received_packet_count": 742_183,
            "network_sent_packet_count": 510_422,
            "block_read_bytes": 147 * 1024**2,
            "block_read_rate_bytes_per_second": 1.2 * 1024**2,
            "block_written_bytes": 86 * 1024**2,
            "block_write_rate_bytes_per_second": 320 * 1024,
            "current_process_and_thread_count": 24,
            "process_and_thread_limit": 512,
        }
        values.update(changed_values)
        return ContainerResourceStatsSnapshot(**values)

    return create_container_resource_stats_snapshot


@pytest.fixture
def session_state_factory(
    container_summary_factory: Callable[..., ContainerSummary],
) -> Callable[..., TerminalSessionState]:
    """Create terminal session state with one selected container and tab."""

    def create_session_state(
        container_id: str = "container-1",
        tab: TabName = TabName.LOGS,
    ) -> TerminalSessionState:
        return TerminalSessionState(
            container_list=ContainerList(
                [container_summary_factory(container_id=container_id)]
            ),
            selected_container_index=0,
            active_detail_tab_name=tab,
        )

    return create_session_state
