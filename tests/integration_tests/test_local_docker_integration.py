from __future__ import annotations

import pytest

from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient
from tests.integration_tests.docker_test_setup import DockerIntegrationTestContainer

pytestmark = pytest.mark.integration


def test_running_container_is_returned_by_container_listing(
    docker_test_setup: DockerIntegrationTestContainer,
    local_docker_container_client: LocalDockerContainerClient,
) -> None:
    running_containers = local_docker_container_client.list_running_containers()

    matching_container = None
    for container in running_containers:
        if container.container_id == docker_test_setup.container.id:
            matching_container = container
            break

    assert matching_container is not None
    assert matching_container.name == docker_test_setup.container.name
    assert matching_container.status == "running"


def test_container_logs_are_read_from_docker(
    docker_test_setup: DockerIntegrationTestContainer,
    local_docker_container_client: LocalDockerContainerClient,
) -> None:
    log_text = local_docker_container_client.get_container_logs(
        docker_test_setup.container.id,
        tail_lines=20,
    )

    assert docker_test_setup.log_message in log_text


def test_container_environment_variables_are_read_from_inspection_data(
    docker_test_setup: DockerIntegrationTestContainer,
    local_docker_container_client: LocalDockerContainerClient,
) -> None:
    environment_variables = (
        local_docker_container_client.get_container_environment_variables(
            docker_test_setup.container.id
        )
    )

    for variable_name, expected_value in docker_test_setup.environment.items():
        assert environment_variables[variable_name] == expected_value


def test_container_and_image_inspection_data_are_returned(
    docker_test_setup: DockerIntegrationTestContainer,
    local_docker_container_client: LocalDockerContainerClient,
) -> None:
    inspection_data = local_docker_container_client.get_container_inspection_data(
        docker_test_setup.container.id
    )

    container_data = inspection_data["container"]
    image_data = inspection_data["image"]
    assert container_data["Id"] == docker_test_setup.container.id
    assert container_data["Name"] == f"/{docker_test_setup.container.name}"
    assert container_data["Config"]["Labels"] == docker_test_setup.labels
    assert image_data["Id"] == container_data["Image"]


def test_container_process_information_is_returned(
    docker_test_setup: DockerIntegrationTestContainer,
    local_docker_container_client: LocalDockerContainerClient,
) -> None:
    process_table = local_docker_container_client.get_container_top_process_table(
        docker_test_setup.container.id
    )

    assert process_table.columns
    assert process_table.rows
    assert all(len(row) == len(process_table.columns) for row in process_table.rows)
    assert any("sh" in " ".join(row) for row in process_table.rows)
