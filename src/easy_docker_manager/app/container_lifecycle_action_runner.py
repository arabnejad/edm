"""Run one container lifecycle action without blocking the terminal UI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future
from functools import partial
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.container_actions import ContainerLifecycleAction
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient

logger = logging.getLogger(__name__)


class ContainerLifecycleActionRunner:
    """Submit Stop or Restart and apply its result on the UI thread."""

    def __init__(
        self,
        state: TerminalSessionState,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
        request_container_list_refresh: Callable[[], None],
    ) -> None:
        self.state = state
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client
        self._request_container_list_refresh = request_container_list_refresh
        self._active_action_future: Optional[Future[None]] = None

    @property
    def is_action_in_progress(self) -> bool:
        """Return whether a container action is already running."""
        return self._active_action_future is not None

    def start_action(
        self,
        action: ContainerLifecycleAction,
        container_id: str,
        container_name: str,
    ) -> bool:
        """Submit one action, returning False when another action is active."""
        if self._active_action_future is not None:
            return False

        docker_request = self._get_docker_request_for_action(action)
        self.state.status_message = (
            f"{self._get_action_progress_word(action)} container "
            f'"{container_name}"...'
        )
        self._active_action_future = self.background_executor.submit(
            docker_request,
            container_id,
            on_complete=partial(
                self._apply_action_result,
                action,
                container_name,
            ),
        )
        return True

    def _get_docker_request_for_action(
        self,
        action: ContainerLifecycleAction,
    ) -> Callable[[str], None]:
        """Return the explicit Docker client method for one supported action."""
        if action == ContainerLifecycleAction.STOP:
            return self.docker_container_client.stop_container
        if action == ContainerLifecycleAction.RESTART:
            return self.docker_container_client.restart_container
        raise ValueError(f"Unsupported container action: {action}")

    def _apply_action_result(
        self,
        action: ContainerLifecycleAction,
        container_name: str,
        action_future: Future[None],
    ) -> bool:
        """Show the result and refresh the container list after success."""
        if action_future is not self._active_action_future:
            return False
        self._active_action_future = None

        try:
            action_future.result()
        except Exception as exc:
            logger.warning(
                "Container %s failed for %s: %s",
                action.value,
                container_name,
                exc,
            )
            self.state.status_message = (
                f'Could not {action.value} container "{container_name}": {exc}'
            )
            return True

        self.state.status_message = (
            f'Container "{container_name}" '
            f"{self._get_completed_action_word(action)}. Refreshing containers..."
        )
        self._request_container_list_refresh()
        return True

    @staticmethod
    def _get_action_progress_word(action: ContainerLifecycleAction) -> str:
        """Return the verb used while an action is running."""
        if action == ContainerLifecycleAction.STOP:
            return "Stopping"
        if action == ContainerLifecycleAction.RESTART:
            return "Restarting"
        raise ValueError(f"Unsupported container action: {action}")

    @staticmethod
    def _get_completed_action_word(action: ContainerLifecycleAction) -> str:
        """Return the verb used after an action succeeds."""
        if action == ContainerLifecycleAction.STOP:
            return "stopped"
        if action == ContainerLifecycleAction.RESTART:
            return "restarted"
        raise ValueError(f"Unsupported container action: {action}")


__all__ = ["ContainerLifecycleActionRunner"]
