from __future__ import annotations

from unittest.mock import Mock

import pytest

from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.container_actions import (
    ContainerLifecycleAction,
    get_available_actions_for_container_status,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.ui.container_action_controller import (
    ContainerActionController,
)


@pytest.mark.parametrize(
    ("container_status", "expected_actions"),
    [
        (
            "running",
            [ContainerLifecycleAction.RESTART, ContainerLifecycleAction.STOP],
        ),
        ("created", []),
        ("exited", []),
        ("paused", []),
        ("restarting", []),
        ("dead", []),
    ],
)
def test_available_actions_follow_container_status(
    container_status: str,
    expected_actions: list[ContainerLifecycleAction],
) -> None:
    assert get_available_actions_for_container_status(container_status) == (
        expected_actions
    )


def test_open_menu_uses_selected_running_container(
    session_state_factory,
) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)

    assert controller.open_container_action_menu()

    menu_state = state.container_action_menu_state
    assert menu_state is not None
    assert menu_state.container_id == "container-1"
    assert menu_state.container_name == "web"
    assert menu_state.available_actions == [
        ContainerLifecycleAction.RESTART,
        ContainerLifecycleAction.STOP,
    ]


def test_unsupported_container_status_shows_why_menu_did_not_open(
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.running_container_list.displayed_containers[0].status = "paused"
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)

    assert controller.open_container_action_menu()

    assert state.container_action_menu_state is None
    assert state.status_message == (
        'No actions are available for container "web" while its status is paused.'
    )


def test_enter_confirms_then_submits_selected_action(session_state_factory) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    docker_manager.start_container_lifecycle_action.return_value = True
    controller = ContainerActionController(state, docker_manager)
    controller.open_container_action_menu()

    assert controller.handle_menu_keypress("down")
    assert controller.handle_menu_keypress("enter")
    assert state.container_action_menu_state is not None
    assert state.container_action_menu_state.is_awaiting_confirmation
    assert controller.handle_menu_keypress("enter")

    assert state.container_action_menu_state is None
    docker_manager.start_container_lifecycle_action.assert_called_once_with(
        ContainerLifecycleAction.STOP,
        "container-1",
        "web",
    )


def test_escape_closes_confirmation_without_submitting(session_state_factory) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)
    controller.open_container_action_menu()
    controller.handle_menu_keypress("enter")

    assert controller.handle_menu_keypress("esc")
    assert state.container_action_menu_state is None
    docker_manager.start_container_lifecycle_action.assert_not_called()


def test_action_menu_does_not_open_while_another_action_runs(
    session_state_factory,
) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = True
    controller = ContainerActionController(state, docker_manager)

    assert controller.open_container_action_menu()
    assert state.container_action_menu_state is None
    assert state.status_message == "A container action is already running."


def test_action_menu_requires_a_selected_container() -> None:
    state = TerminalSessionState()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)

    assert controller.open_container_action_menu()
    assert state.container_action_menu_state is None
    assert state.status_message == "Select a container first."


def test_open_menu_and_unrelated_keys_do_not_change_an_open_menu(
    session_state_factory,
) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)

    assert controller.open_container_action_menu()
    assert not controller.open_container_action_menu()
    assert not controller.handle_menu_keypress("q")
    assert not controller.handle_menu_keypress("up")


def test_failed_submission_closes_menu_and_reports_active_action(
    session_state_factory,
) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    docker_manager.start_container_lifecycle_action.return_value = False
    controller = ContainerActionController(state, docker_manager)
    controller.open_container_action_menu()
    controller.handle_menu_keypress("enter")

    assert controller.handle_menu_keypress("enter")
    assert state.container_action_menu_state is None
    assert state.status_message == "A container action is already running."


def test_confirmation_rejects_an_action_after_container_status_changes(
    session_state_factory,
) -> None:
    state = session_state_factory()
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_lifecycle_action_in_progress = False
    controller = ContainerActionController(state, docker_manager)
    controller.open_container_action_menu()
    controller.handle_menu_keypress("enter")
    state.running_container_list.displayed_containers[0].status = "exited"

    assert controller.handle_menu_keypress("enter")

    assert state.container_action_menu_state is None
    assert state.status_message == (
        "The container status changed. Open Actions to see its current options."
    )
    docker_manager.start_container_lifecycle_action.assert_not_called()
