from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pytest

from easy_docker_manager.core.containers import (
    ContainerResourceStatsSnapshot,
    ContainerSummary,
)
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState


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
    ) -> ContainerSummary:
        return ContainerSummary(
            container_id=container_id,
            name=name,
            status=status,
            image_name=image_name,
            created_at=created_at,
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
            running_container_list=RunningContainerList(
                [container_summary_factory(container_id=container_id)]
            ),
            selected_container_index=0,
            active_detail_tab_name=tab,
        )

    return create_session_state
