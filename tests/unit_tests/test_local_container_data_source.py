from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import DockerException, NotFound

from easy_docker_manager.core import ContainerSummary
from easy_docker_manager.docker.base import (
    ContainerLogFetchError,
    ContainerNotFoundError,
    ContainerRefreshError,
    DockerRequestFailedError,
    LogsUnavailableError,
)
from easy_docker_manager.docker.local import LocalContainerDataSource


@pytest.fixture
def docker_client_factory():
    def create_client(container=None):
        containers = Mock()
        containers.get.return_value = container
        images = Mock()
        return SimpleNamespace(containers=containers, images=images, close=Mock())

    return create_client


@pytest.fixture
def docker_container_factory():
    def create_container(**overrides):
        values = {
            "id": "container-id",
            "short_id": "container-id"[:12],
            "name": "web",
            "status": "running",
            "attrs": {
                "Id": "container-id",
                "Image": "sha256:image",
                "Config": {
                    "Env": ["A=1", "EMPTY=", "INVALID"],
                    "Image": "example:latest",
                },
                "Created": "2026-01-01T12:00:00Z",
                "HostConfig": {"LogConfig": {"Type": "json-file"}},
            },
            "logs": Mock(return_value=b"hello\xff"),
            "top": Mock(
                return_value={
                    "Titles": ["PID", "CMD"],
                    "Processes": [[1, "python"]],
                }
            ),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    return create_container


def test_client_is_created_lazily_and_reused(docker_client_factory) -> None:
    client = docker_client_factory()
    create_client = Mock(return_value=client)
    container_data_source = LocalContainerDataSource(create_client=create_client)

    assert container_data_source._docker_client_instance is None
    assert container_data_source._get_or_create_docker_client() is client
    assert container_data_source._get_or_create_docker_client() is client
    create_client.assert_called_once_with()


def test_docker_connection_error_becomes_refresh_error() -> None:
    container_data_source = LocalContainerDataSource(
        create_client=Mock(side_effect=DockerException("offline"))
    )

    with pytest.raises(ContainerRefreshError, match="offline"):
        container_data_source.list_running_containers()


def test_list_running_containers_filters_and_maps_containers(
    docker_client_factory,
    docker_container_factory,
) -> None:
    first_container = docker_container_factory(id="one", name="one")
    second_container = docker_container_factory(id="two", name="two")
    client = docker_client_factory()
    client.containers.list.return_value = [first_container, second_container]
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    running_containers = container_data_source.list_running_containers()

    client.containers.list.assert_called_once_with(filters={"status": "running"})
    assert running_containers == [
        ContainerSummary(
            "one",
            "one",
            "running",
            "example:latest",
            "2026-01-01T12:00:00Z",
        ),
        ContainerSummary(
            "two",
            "two",
            "running",
            "example:latest",
            "2026-01-01T12:00:00Z",
        ),
    ]


def test_list_running_containers_skips_a_container_that_cannot_be_mapped(
    monkeypatch,
    docker_client_factory,
    docker_container_factory,
) -> None:
    first_container = docker_container_factory(id="one")
    second_container = docker_container_factory(id="two")
    client = docker_client_factory()
    client.containers.list.return_value = [first_container, second_container]
    container_data_source = LocalContainerDataSource(create_client=lambda: client)
    expected_container = ContainerSummary(
        "two",
        "two",
        "up",
        "example:latest",
        "2026-01-01T12:00:00Z",
    )
    calls = iter([ValueError("bad container"), expected_container])

    def map_container(_container):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        "easy_docker_manager.docker.local.to_container_summary", map_container
    )

    assert container_data_source.list_running_containers() == [expected_container]


def test_list_running_containers_wraps_docker_failure(docker_client_factory) -> None:
    client = docker_client_factory()
    client.containers.list.side_effect = RuntimeError("offline")
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    with pytest.raises(ContainerRefreshError, match="offline"):
        container_data_source.list_running_containers()


def test_get_logs_decodes_bad_bytes_and_passes_options(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    client = docker_client_factory(container)
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    log_text = container_data_source.get_logs(
        "container-id",
        tail_lines="all",
        since_timestamp=100,
    )

    assert log_text == "hello�"
    container.logs.assert_called_once_with(tail="all", timestamps=True, since=100)


def test_get_logs_does_not_pass_since_when_it_is_missing(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(logs=Mock(return_value="text"))
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    assert container_data_source.get_logs("container-id", tail_lines=20) == "text"
    container.logs.assert_called_once_with(tail=20, timestamps=True)


def test_get_logs_rejects_none_logging_driver(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(
        attrs={"HostConfig": {"LogConfig": {"Type": "none"}}}
    )
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(LogsUnavailableError) as error:
        container_data_source.get_logs("container-id")
    assert error.value.driver == "none"


def test_get_logs_maps_missing_container(docker_client_factory) -> None:
    client = docker_client_factory()
    client.containers.get.side_effect = NotFound("missing")
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    with pytest.raises(ContainerNotFoundError):
        container_data_source.get_logs("missing")


def test_get_logs_maps_unreadable_driver_response_to_logs_unavailable(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container.logs.side_effect = RuntimeError(
        "configured logging driver does not support reading"
    )
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(LogsUnavailableError) as error:
        container_data_source.get_logs("container-id")
    assert error.value.driver == "json-file"


def test_get_logs_maps_transient_failure(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container.logs.side_effect = RuntimeError("timeout")
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(ContainerLogFetchError, match="timeout"):
        container_data_source.get_logs("container-id")


def test_get_environment_variables_returns_only_valid_name_value_pairs(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    assert container_data_source.get_environment_variables("container-id") == {
        "A": "1",
        "EMPTY": "",
    }


def test_get_environment_variables_maps_docker_failure(docker_client_factory) -> None:
    client = docker_client_factory()
    client.containers.get.side_effect = RuntimeError("denied")
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    with pytest.raises(DockerRequestFailedError, match="Environment load failed"):
        container_data_source.get_environment_variables("container-id")


def test_inspection_data_includes_container_and_image(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    client = docker_client_factory(container)
    client.images.get.return_value = SimpleNamespace(attrs={"RepoTags": ["web:1"]})
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    inspection_data = container_data_source.get_docker_inspection_data("container-id")

    assert inspection_data["container"] is container.attrs
    assert inspection_data["image"] == {"RepoTags": ["web:1"]}
    client.images.get.assert_called_once_with("sha256:image")


def test_missing_image_data_does_not_fail_container_inspection(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    client = docker_client_factory(container)
    client.images.get.side_effect = RuntimeError("image removed")
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    inspection_data = container_data_source.get_docker_inspection_data("container-id")
    assert inspection_data["image"] == {}


def test_process_list_is_converted_to_strings(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    process_list = container_data_source.get_process_list("container-id")

    assert process_list.columns == ("PID", "CMD")
    assert process_list.rows == (("1", "python"),)


def test_process_list_failure_is_mapped(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(top=Mock(side_effect=RuntimeError("stopped")))
    container_data_source = LocalContainerDataSource(
        create_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(DockerRequestFailedError, match="Process list load failed"):
        container_data_source.get_process_list("container-id")


def test_close_releases_only_an_existing_client(docker_client_factory) -> None:
    client = docker_client_factory()
    container_data_source = LocalContainerDataSource(create_client=lambda: client)

    container_data_source.close()
    client.close.assert_not_called()

    assert container_data_source._get_or_create_docker_client() is client
    container_data_source.close()
    client.close.assert_called_once_with()
    assert container_data_source._docker_client_instance is None
