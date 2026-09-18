"""Run one container lifecycle action without blocking the terminal UI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future
from functools import partial
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.container_actions import ContainerLifecycleAction
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.compose_service_recreator import (
    DockerComposeServiceRecreator,
)
from easy_docker_manager.docker.container_client import DockerContainerClient

logger = logging.getLogger(__name__)


class ContainerLifecycleActionRunner:
    """Submit container or Compose actions and apply results on the UI thread."""

    def __init__(
        self,
        state: TerminalSessionState,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
        request_container_list_refresh: Callable[[], None],
        docker_compose_service_recreator: Optional[
            DockerComposeServiceRecreator
        ] = None,
    ) -> None:
        self.state = state
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client
        self._request_container_list_refresh = request_container_list_refresh
        self.docker_compose_service_recreator = (
            docker_compose_service_recreator or DockerComposeServiceRecreator()
        )
        self._active_action_future: Optional[Future[None]] = None

    @property
    def is_action_in_progress(self) -> bool:
        """Return whether a container action is already running."""
        return self._active_action_future is not None

    def start_action(
        self,
        action: ContainerLifecycleAction,
        container: ContainerSummary,
    ) -> bool:
        """Submit one action, returning False when another action is active."""
        if self._active_action_future is not None:
            return False

        docker_request, docker_request_arguments = self._get_docker_request_for_action(
            action,
            container,
        )
        self.state.status_message = self._get_action_progress_message(
            action,
            container.name,
        )
        self._active_action_future = self.background_executor.submit(
            docker_request,
            *docker_request_arguments,
            on_complete=partial(
                self._apply_action_result,
                action,
                container.name,
            ),
        )
        return True

    def _get_docker_request_for_action(
        self,
        action: ContainerLifecycleAction,
        container: ContainerSummary,
    ) -> tuple[Callable[..., None], tuple[object, ...]]:
        """Return the worker function and arguments for one supported action."""
        if action == ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE:
            return (
                self.docker_compose_service_recreator.recreate_service,
                (container, self.state.active_docker_context),
            )
        if action == ContainerLifecycleAction.START:
            return self.docker_container_client.start_container, (
                container.container_id,
            )
        if action == ContainerLifecycleAction.STOP:
            return self.docker_container_client.stop_container, (
                container.container_id,
            )
        if action == ContainerLifecycleAction.RESTART:
            return self.docker_container_client.restart_container, (
                container.container_id,
            )
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
            self.state.status_message = self._get_action_error_message(
                action,
                container_name,
                exc,
            )
            return True

        self.state.status_message = self._get_action_completed_message(
            action,
            container_name,
        )
        self._request_container_list_refresh()
        return True

    @staticmethod
    def _get_action_progress_message(
        action: ContainerLifecycleAction,
        container_name: str,
    ) -> str:
        """Return the status shown while one action is running."""
        if action == ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE:
            return f'Recreating Compose service for container "{container_name}"...'
        if action == ContainerLifecycleAction.START:
            return f'Starting container "{container_name}"...'
        if action == ContainerLifecycleAction.STOP:
            return f'Stopping container "{container_name}"...'
        if action == ContainerLifecycleAction.RESTART:
            return f'Restarting container "{container_name}"...'
        raise ValueError(f"Unsupported container action: {action}")

    @staticmethod
    def _get_action_completed_message(
        action: ContainerLifecycleAction,
        container_name: str,
    ) -> str:
        """Return the status shown after one action succeeds."""
        if action == ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE:
            return (
                f'Compose service for container "{container_name}" recreated. '
                "Refreshing containers..."
            )
        if action == ContainerLifecycleAction.START:
            return f'Container "{container_name}" started. Refreshing containers...'
        if action == ContainerLifecycleAction.STOP:
            return f'Container "{container_name}" stopped. Refreshing containers...'
        if action == ContainerLifecycleAction.RESTART:
            return f'Container "{container_name}" restarted. Refreshing containers...'
        raise ValueError(f"Unsupported container action: {action}")

    @staticmethod
    def _get_action_error_message(
        action: ContainerLifecycleAction,
        container_name: str,
        error: Exception,
    ) -> str:
        """Return the status shown after one action fails."""
        if action == ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE:
            return (
                f'Could not recreate Compose service for container "{container_name}": '
                f"{error}"
            )
        return f'Could not {action.value} container "{container_name}": {error}'


__all__ = ["ContainerLifecycleActionRunner"]
