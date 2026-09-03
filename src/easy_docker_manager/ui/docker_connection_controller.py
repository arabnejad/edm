"""Handle Docker context selection and connection checks."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from functools import partial
from typing import Optional

from docker import DockerClient

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.docker_connections import (
    DockerConnectionMenuState,
    DockerContextDetails,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.client_factory import (
    create_validated_docker_client_for_context,
)
from easy_docker_manager.docker.docker_contexts import DockerContextReader
from easy_docker_manager.docker.docker_sdk_container_client import (
    DockerSDKContainerClient,
)

ValidatedDockerClientFactory = Callable[[DockerContextDetails, float], DockerClient]


class DockerConnectionController:
    """Handle the connection popup and change EDM's active Docker context.

    KeyboardController forwards the popup's keypresses here. Opening the menu
    only reads Docker's local configuration. After the user presses Enter, the
    selected connection is checked in a worker. A successful check switches
    the Docker client and clears data loaded from the previous daemon.
    """

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        docker_manager: DockerManager,
        docker_context_reader: DockerContextReader,
        docker_sdk_container_client: Optional[DockerSDKContainerClient],
        create_validated_docker_client_for_context: ValidatedDockerClientFactory = (
            create_validated_docker_client_for_context
        ),
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.docker_manager = docker_manager
        self.docker_context_reader = docker_context_reader
        self.docker_sdk_container_client = docker_sdk_container_client
        self._create_validated_docker_client_for_context = (
            create_validated_docker_client_for_context
        )
        self._docker_context_validation_future: Optional[Future[DockerClient]] = None

    def open_docker_connection_menu(self) -> bool:
        """Read configured contexts and open the connection popup."""
        if self.state.docker_connection_menu_state is not None:
            return False

        try:
            docker_contexts = (
                self.docker_context_reader.list_configured_docker_contexts()
            )
            context_discovery_error_message = ""
        except Exception as exc:
            docker_contexts = []
            context_discovery_error_message = f"Could not read Docker contexts: {exc}"

        active_context_name = self.state.active_docker_context.context_name
        selected_context_index = 0
        for index, docker_context in enumerate(docker_contexts):
            if docker_context.context_name == active_context_name:
                selected_context_index = index
                break

        self.state.docker_connection_menu_state = DockerConnectionMenuState(
            docker_contexts=docker_contexts,
            active_context_name=active_context_name,
            selected_context_index=selected_context_index,
            context_discovery_error_message=context_discovery_error_message,
        )
        return True

    def handle_menu_keypress(self, key: str) -> bool:
        """Move, connect, or close the Docker connection menu."""
        menu_state = self.state.docker_connection_menu_state
        if menu_state is None:
            return False
        if menu_state.context_name_being_validated is not None:
            return False
        if key == "up":
            return self._move_selected_context(-1)
        if key == "down":
            return self._move_selected_context(1)
        if key == "enter":
            return self._connect_to_selected_context()
        if key == "esc":
            self.state.docker_connection_menu_state = None
            return True
        return False

    def _move_selected_context(self, offset: int) -> bool:
        """Move the context selection without wrapping around the list."""
        menu_state = self.state.docker_connection_menu_state
        if menu_state is None or not menu_state.docker_contexts:
            return False
        next_index = max(
            0,
            min(
                len(menu_state.docker_contexts) - 1,
                menu_state.selected_context_index + offset,
            ),
        )
        if next_index == menu_state.selected_context_index:
            return False
        menu_state.selected_context_index = next_index
        menu_state.context_discovery_error_message = ""
        return True

    def _connect_to_selected_context(self) -> bool:
        """Start checking the selected context, or close when it is already active."""
        menu_state = self.state.docker_connection_menu_state
        if menu_state is None:
            return False
        selected_context = menu_state.selected_docker_context
        if selected_context is None:
            return False
        if selected_context.context_name == menu_state.active_context_name:
            self.state.docker_connection_menu_state = None
            return True
        if not selected_context.is_supported:
            menu_state.connection_error_messages[selected_context.context_name] = (
                selected_context.unsupported_reason
            )
            return True
        if self.docker_manager.is_container_lifecycle_action_in_progress:
            menu_state.connection_error_messages[selected_context.context_name] = (
                "Wait for the current container action to finish before changing "
                "Docker context."
            )
            return True
        if self.docker_sdk_container_client is None:
            menu_state.connection_error_messages[selected_context.context_name] = (
                "Docker context switching is unavailable for this EDM runtime."
            )
            return True

        menu_state.connection_error_messages.pop(selected_context.context_name, None)
        menu_state.context_name_being_validated = selected_context.context_name
        self._docker_context_validation_future = self.background_executor.submit(
            self._create_validated_docker_client_for_context,
            selected_context,
            self.app_config.docker_request_timeout,
            on_complete=partial(
                self._apply_docker_context_validation_result,
                selected_context,
            ),
        )
        return True

    def _apply_docker_context_validation_result(
        self,
        selected_context: DockerContextDetails,
        docker_context_validation_future: Future[DockerClient],
    ) -> bool:
        """Switch to the checked context or show why the check failed."""
        if (
            docker_context_validation_future
            is not self._docker_context_validation_future
        ):
            return False
        self._docker_context_validation_future = None

        menu_state = self.state.docker_connection_menu_state
        if menu_state is None:
            return False
        menu_state.context_name_being_validated = None

        try:
            validated_docker_client = docker_context_validation_future.result()
        except Exception as exc:
            menu_state.connection_error_messages[selected_context.context_name] = str(
                exc
            )
            return True

        assert self.docker_sdk_container_client is not None
        self.docker_manager.reset_after_docker_context_change()
        self.docker_sdk_container_client.switch_docker_connection(
            validated_docker_client
        )
        self.state.clear_container_data_for_docker_context_change()
        self.state.active_docker_context = selected_context
        self.state.docker_connection_menu_state = None
        self.state.status_message = (
            f'Connecting to Docker context "{selected_context.display_name}"...'
        )
        self.docker_manager.start_running_container_list_refresh(force=True)
        return True


__all__ = ["DockerConnectionController"]
