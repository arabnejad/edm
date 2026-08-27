from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable, Optional

import pytest

from easy_docker_manager.core import ContainerSummary
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
def session_state_factory(
    container_summary_factory: Callable[..., ContainerSummary],
) -> Callable[..., TerminalSessionState]:
    """Create UI state with one selected container and detail tab."""

    def create_session_state(
        container_id: str = "container-1",
        tab: TabName = TabName.LOGS,
    ) -> TerminalSessionState:
        return TerminalSessionState(
            running_containers=[container_summary_factory(container_id=container_id)],
            selected_container_index=0,
            active_detail_tab_name=tab,
        )

    return create_session_state
