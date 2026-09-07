from __future__ import annotations

import pytest

from easy_docker_manager.core.container_actions import ContainerLifecycleAction


@pytest.mark.parametrize(
    (
        "action",
        "docker_client_method_name",
        "progress_message",
        "completed_message",
    ),
    [
        (
            ContainerLifecycleAction.STOP,
            "stop_container",
            'Stopping container "web"...',
            'Container "web" stopped. Refreshing containers...',
        ),
        (
            ContainerLifecycleAction.RESTART,
            "restart_container",
            'Restarting container "web"...',
            'Container "web" restarted. Refreshing containers...',
        ),
    ],
)
def test_container_lifecycle_action_runs_once_and_refreshes_after_success(
    action: ContainerLifecycleAction,
    docker_client_method_name: str,
    progress_message: str,
    completed_message: str,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()

    assert test_setup.docker_manager.start_container_lifecycle_action(
        action,
        "container-1",
        "web",
    )
    assert not test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "web",
    )
    assert test_setup.docker_manager.is_container_lifecycle_action_in_progress
    action_request = test_setup.background_executor.requests[0]
    assert action_request.fn == getattr(
        test_setup.docker_container_client,
        docker_client_method_name,
    )
    assert action_request.arguments == ("container-1",)
    assert test_setup.state.status_message == progress_message

    assert test_setup.background_executor.complete_submission(result=None)
    assert not test_setup.docker_manager.is_container_lifecycle_action_in_progress
    assert test_setup.state.status_message == completed_message
    refresh_request = test_setup.background_executor.requests[1]
    assert refresh_request.fn == (test_setup.docker_container_client.list_containers)


def test_failed_container_lifecycle_action_shows_error_without_refreshing(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "worker",
    )

    assert test_setup.background_executor.complete_submission(
        exception=RuntimeError("permission denied")
    )
    assert test_setup.state.status_message == (
        'Could not stop container "worker": permission denied'
    )
    assert len(test_setup.background_executor.requests) == 1


def test_action_completion_reloads_after_an_older_refresh_finishes(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_list_refresh(force=True)
    test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "web",
    )

    assert test_setup.background_executor.complete_submission(1, result=None)
    assert len(test_setup.background_executor.requests) == 2

    assert test_setup.background_executor.complete_submission(0, result=[])
    assert len(test_setup.background_executor.requests) == 3
    follow_up_refresh = test_setup.background_executor.requests[2]
    assert follow_up_refresh.fn == (test_setup.docker_container_client.list_containers)
