from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from docker.errors import DockerException, NotFound

from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerDaemonDetails,
    DockerRequestFailedError,
    RunningContainerListRefreshError,
)
from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient


@pytest.fixture
def docker_client_factory():
    def create_docker_client(container=None):
        containers = Mock()
        containers.get.return_value = container
        images = Mock()
        return SimpleNamespace(
            containers=containers,
            images=images,
            version=Mock(
                return_value={
                    "Version": "28.3.3",
                    "ApiVersion": "1.51",
                    "Os": "linux",
                    "Arch": "amd64",
                }
            ),
            close=Mock(),
        )

    return create_docker_client


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
            "stats": Mock(return_value={"read": "2026-01-01T14:32:18Z"}),
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
    create_docker_client = Mock(return_value=client)
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=create_docker_client
    )

    assert docker_container_client._docker_client is None
    assert docker_container_client._get_or_create_docker_client() is client
    assert docker_container_client._get_or_create_docker_client() is client
    create_docker_client.assert_called_once_with()


def test_docker_connection_error_becomes_refresh_error() -> None:
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=Mock(side_effect=DockerException("offline"))
    )

    with pytest.raises(RunningContainerListRefreshError, match="offline"):
        docker_container_client.list_running_containers()


def test_list_running_containers_filters_and_maps_containers(
    docker_client_factory,
    docker_container_factory,
) -> None:
    first_container = docker_container_factory(id="one", name="one")
    second_container = docker_container_factory(id="two", name="two")
    client = docker_client_factory()
    client.containers.list.return_value = [first_container, second_container]
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    running_containers = docker_container_client.list_running_containers()

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
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )
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
        "easy_docker_manager.docker.local_container_client.to_container_summary",
        map_container,
    )

    assert docker_container_client.list_running_containers() == [expected_container]


def test_list_running_containers_wraps_docker_failure(docker_client_factory) -> None:
    client = docker_client_factory()
    client.containers.list.side_effect = RuntimeError("offline")
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    with pytest.raises(RunningContainerListRefreshError, match="offline"):
        docker_container_client.list_running_containers()


def test_get_container_logs_decodes_bad_bytes_and_passes_options(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    client = docker_client_factory(container)
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    log_text = docker_container_client.get_container_logs(
        "container-id",
        tail_lines="all",
        since_timestamp=100,
    )

    assert log_text == "hello�"
    container.logs.assert_called_once_with(tail="all", timestamps=True, since=100)


def test_get_container_logs_does_not_pass_since_when_it_is_missing(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(logs=Mock(return_value="text"))
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    assert (
        docker_container_client.get_container_logs("container-id", tail_lines=20)
        == "text"
    )
    container.logs.assert_called_once_with(tail=20, timestamps=True)


def test_get_container_logs_rejects_none_logging_driver(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(
        attrs={"HostConfig": {"LogConfig": {"Type": "none"}}}
    )
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(ContainerLogsUnavailableError) as error:
        docker_container_client.get_container_logs("container-id")
    assert error.value.logging_driver_name == "none"


def test_get_container_logs_maps_missing_container(docker_client_factory) -> None:
    client = docker_client_factory()
    client.containers.get.side_effect = NotFound("missing")
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    with pytest.raises(ContainerNotFoundError):
        docker_container_client.get_container_logs("missing")


def test_get_container_logs_maps_unreadable_driver_response_to_logs_unavailable(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container.logs.side_effect = RuntimeError(
        "configured logging driver does not support reading"
    )
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(ContainerLogsUnavailableError) as error:
        docker_container_client.get_container_logs("container-id")
    assert error.value.logging_driver_name == "json-file"


def test_get_container_logs_maps_transient_failure(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container.logs.side_effect = RuntimeError("timeout")
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(ContainerLogFetchError, match="timeout"):
        docker_container_client.get_container_logs("container-id")


def test_get_container_environment_variables_returns_valid_name_value_pairs(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    assert docker_container_client.get_container_environment_variables(
        "container-id"
    ) == {"A": "1", "EMPTY": ""}


def test_get_container_environment_variables_maps_docker_failure(
    docker_client_factory,
) -> None:
    client = docker_client_factory()
    client.containers.get.side_effect = RuntimeError("denied")
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    with pytest.raises(DockerRequestFailedError, match="Environment load failed"):
        docker_container_client.get_container_environment_variables("container-id")


def test_inspection_data_includes_container_and_image(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    client = docker_client_factory(container)
    client.images.get.return_value = SimpleNamespace(attrs={"RepoTags": ["web:1"]})
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    inspection_data = docker_container_client.get_container_inspection_data(
        "container-id"
    )

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
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    inspection_data = docker_container_client.get_container_inspection_data(
        "container-id"
    )
    assert inspection_data["image"] == {}


def test_container_top_process_table_is_converted_to_strings(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    process_table = docker_container_client.get_container_top_process_table(
        "container-id"
    )

    assert process_table.columns == ("PID", "CMD")
    assert process_table.rows == (("1", "python"),)


def test_container_top_process_table_failure_is_mapped(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(top=Mock(side_effect=RuntimeError("stopped")))
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(DockerRequestFailedError, match="Process list load failed"):
        docker_container_client.get_container_top_process_table("container-id")


def test_container_resource_stats_use_the_last_sample_for_transfer_rates(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory()
    container.stats.side_effect = [
        {
            "read": "2026-01-01T14:32:16Z",
            "networks": {
                "eth0": {
                    "rx_bytes": 100,
                    "tx_bytes": 200,
                    "rx_packets": 1,
                    "tx_packets": 2,
                }
            },
        },
        {
            "read": "2026-01-01T14:32:18Z",
            "networks": {
                "eth0": {
                    "rx_bytes": 500,
                    "tx_bytes": 800,
                    "rx_packets": 3,
                    "tx_packets": 4,
                }
            },
        },
    ]
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    first_snapshot = docker_container_client.get_container_resource_stats(
        "container-id"
    )
    second_snapshot = docker_container_client.get_container_resource_stats(
        "container-id"
    )

    assert first_snapshot.network_receive_rate_bytes_per_second is None
    assert second_snapshot.network_receive_rate_bytes_per_second == 200
    assert second_snapshot.network_send_rate_bytes_per_second == 300
    assert container.stats.call_args_list == [
        call(stream=False),
        call(stream=False),
    ]


def test_container_resource_stats_failure_is_mapped(
    docker_client_factory,
    docker_container_factory,
) -> None:
    container = docker_container_factory(
        stats=Mock(side_effect=RuntimeError("stats unavailable"))
    )
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: docker_client_factory(container)
    )

    with pytest.raises(
        DockerRequestFailedError,
        match="Resource statistics load failed",
    ):
        docker_container_client.get_container_resource_stats("container-id")


def test_close_releases_only_an_existing_client(docker_client_factory) -> None:
    client = docker_client_factory()
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    docker_container_client.close()
    client.close.assert_not_called()

    assert docker_container_client._get_or_create_docker_client() is client
    docker_container_client._last_resource_stats_snapshot_by_container_id[
        "container-id"
    ] = Mock()
    docker_container_client.close()
    client.close.assert_called_once_with()
    assert docker_container_client._docker_client is None
    assert docker_container_client._last_resource_stats_snapshot_by_container_id == {}


def test_docker_daemon_details_are_read_from_the_version_response(
    docker_client_factory,
) -> None:
    client = docker_client_factory()
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    assert docker_container_client.get_docker_daemon_details() == DockerDaemonDetails(
        daemon_version="28.3.3",
        api_version="1.51",
        operating_system="linux",
        architecture="amd64",
    )
    client.version.assert_called_once_with()


def test_docker_daemon_details_reject_an_unknown_response_format(
    docker_client_factory,
) -> None:
    client = docker_client_factory()
    client.version.return_value = "unexpected"
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=lambda: client
    )

    with pytest.raises(TypeError, match="unknown format"):
        docker_container_client.get_docker_daemon_details()
