"""Handle the container action menu and submit confirmed actions."""

from __future__ import annotations

from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.container_actions import (
    ContainerActionMenuState,
    get_available_actions_for_container_status,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState


class ContainerActionController:
    """Open, navigate, confirm, and close the selected container's action menu."""

    def __init__(
        self,
        state: TerminalSessionState,
        docker_manager: DockerManager,
    ) -> None:
        self.state = state
        self.docker_manager = docker_manager

    def open_container_action_menu(self) -> bool:
        """Open the actions supported by the selected container's status."""
        if self.state.container_action_menu_state is not None:
            return False
        if self.docker_manager.is_container_lifecycle_action_in_progress:
            self.state.status_message = "A container action is already running."
            return True

        selected_container = self.state.selected_container_summary
        if selected_container is None:
            self.state.status_message = "Select a container first."
            return True

        available_actions = get_available_actions_for_container_status(
            selected_container.status
        )
        if not available_actions:
            self.state.status_message = (
                f'No actions are available for container "{selected_container.name}" '
                f"while its status is {selected_container.status}."
            )
            return True

        self.state.container_action_menu_state = ContainerActionMenuState(
            container_id=selected_container.container_id,
            container_name=selected_container.name,
            available_actions=available_actions,
        )
        return True

    def handle_menu_keypress(self, key: str) -> bool:
        """Handle navigation, confirmation, or cancellation inside the menu."""
        menu_state = self.state.container_action_menu_state
        if menu_state is None:
            return False
        if key == "esc":
            self.state.container_action_menu_state = None
            return True
        if menu_state.is_awaiting_confirmation:
            return self._handle_confirmation_keypress(key, menu_state)
        if key == "up":
            return self._move_selected_action(-1)
        if key == "down":
            return self._move_selected_action(1)
        if key == "enter":
            menu_state.is_awaiting_confirmation = True
            return True
        return False

    def _move_selected_action(self, selection_offset: int) -> bool:
        """Move the highlight without passing the first or last action."""
        menu_state = self.state.container_action_menu_state
        if menu_state is None:
            return False
        previous_index = menu_state.selected_action_index
        menu_state.selected_action_index = max(
            0,
            min(
                len(menu_state.available_actions) - 1,
                previous_index + selection_offset,
            ),
        )
        return menu_state.selected_action_index != previous_index

    def _handle_confirmation_keypress(
        self,
        key: str,
        menu_state: ContainerActionMenuState,
    ) -> bool:
        """Submit the selected action when the user confirms it with Enter."""
        if key != "enter":
            return False

        selected_action = menu_state.selected_action
        if not self._selected_action_is_still_available_for_target_container(
            menu_state
        ):
            self.state.container_action_menu_state = None
            self.state.status_message = (
                "The container status changed. Open Actions to see its current options."
            )
            return True

        container_id = menu_state.container_id
        container_name = menu_state.container_name
        self.state.container_action_menu_state = None
        if self.docker_manager.start_container_lifecycle_action(
            selected_action,
            container_id,
            container_name,
        ):
            return True

        self.state.status_message = "A container action is already running."
        return True

    def _selected_action_is_still_available_for_target_container(
        self,
        menu_state: ContainerActionMenuState,
    ) -> bool:
        """Check the latest loaded status before submitting the chosen action."""
        for container in self.state.running_container_list.displayed_containers:
            if container.container_id != menu_state.container_id:
                continue
            return (
                menu_state.selected_action
                in get_available_actions_for_container_status(container.status)
            )
        return False


__all__ = ["ContainerActionController"]
