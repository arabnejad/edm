from __future__ import annotations

import pytest

from easy_docker_manager.core.container_actions import ContainerAction


@pytest.mark.parametrize(
    (
        "action",
        "docker_client_method_name",
        "progress_message",
        "completed_message",
    ),
    [
        (
            ContainerAction.START,
            "start_container",
            'Starting container "web"...',
            'Container "web" started. Refreshing containers...',
        ),
        (
            ContainerAction.STOP,
            "stop_container",
            'Stopping container "web"...',
            'Container "web" stopped. Refreshing containers...',
        ),
        (
            ContainerAction.RESTART,
            "restart_container",
            'Restarting container "web"...',
            'Container "web" restarted. Refreshing containers...',
        ),
    ],
)
def test_container_action_runs_once_and_refreshes_after_success(
    action: ContainerAction,
    docker_client_method_name: str,
    progress_message: str,
    completed_message: str,
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    selected_container = container_summary_factory()

    assert test_setup.docker_manager.start_container_action(
        action,
        selected_container,
    )
    assert not test_setup.docker_manager.start_container_action(
        ContainerAction.STOP,
        selected_container,
    )
    assert test_setup.docker_manager.is_container_action_in_progress
    action_request = test_setup.background_executor.requests[0]
    assert action_request.fn == getattr(
        test_setup.docker_container_client,
        docker_client_method_name,
    )
    assert action_request.arguments == ("container-1",)
    assert test_setup.state.status_message == progress_message

    assert test_setup.background_executor.complete_submission(result=None)
    assert not test_setup.docker_manager.is_container_action_in_progress
    assert test_setup.state.status_message == completed_message
    refresh_request = test_setup.background_executor.requests[1]
    assert refresh_request.fn == (test_setup.docker_container_client.list_containers)


def test_failed_container_action_shows_error_without_refreshing(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_action(
        ContainerAction.STOP,
        container_summary_factory(name="worker"),
    )

    assert test_setup.background_executor.complete_submission(
        exception=RuntimeError("permission denied")
    )
    assert test_setup.state.status_message == (
        'Could not stop container "worker": permission denied'
    )
    assert len(test_setup.background_executor.requests) == 1


def test_compose_recreate_uses_container_metadata_and_active_context(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory="/workspace/example",
        compose_config_file_paths=("/workspace/example/compose.yaml",),
    )

    assert test_setup.docker_manager.start_container_action(
        ContainerAction.RECREATE_COMPOSE_SERVICE,
        container,
    )

    action_request = test_setup.background_executor.requests[0]
    assert action_request.fn == (
        test_setup.container_action_runner.docker_compose_service_recreator.recreate_service
    )
    assert action_request.arguments == (
        container,
        test_setup.state.active_docker_context,
    )
    assert test_setup.state.status_message == (
        'Recreating Compose service for container "web"...'
    )

    assert test_setup.background_executor.complete_submission(result=None)
    assert test_setup.state.status_message == (
        'Compose service for container "web" recreated. Refreshing containers...'
    )


def test_failed_compose_recreate_shows_the_command_error(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory="/workspace/example",
        compose_config_file_paths=("/workspace/example/compose.yaml",),
    )
    test_setup.docker_manager.start_container_action(
        ContainerAction.RECREATE_COMPOSE_SERVICE,
        container,
    )

    assert test_setup.background_executor.complete_submission(
        exception=RuntimeError("compose file is invalid")
    )
    assert test_setup.state.status_message == (
        'Could not recreate Compose service for container "web": '
        "compose file is invalid"
    )
    assert len(test_setup.background_executor.requests) == 1


def test_action_completion_reloads_after_an_older_refresh_finishes(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_list_refresh(force=True)
    test_setup.docker_manager.start_container_action(
        ContainerAction.STOP,
        container_summary_factory(),
    )

    assert test_setup.background_executor.complete_submission(1, result=None)
    assert len(test_setup.background_executor.requests) == 2

    assert test_setup.background_executor.complete_submission(0, result=[])
    assert len(test_setup.background_executor.requests) == 3
    follow_up_refresh = test_setup.background_executor.requests[2]
    assert follow_up_refresh.fn == (test_setup.docker_container_client.list_containers)
