from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress

import pytest
from docker import DockerClient
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

from easy_docker_manager.core.docker_connections import DockerConnectionTransport
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.docker_contexts import DockerContextReader
from easy_docker_manager.docker.docker_sdk_container_client import (
    DockerSDKContainerClient,
)
from tests.integration_tests.docker_test_setup import DockerIntegrationTestContainer

CONTAINER_IMAGE = os.getenv("EDM_INTEGRATION_TEST_IMAGE", "alpine:3.20")
CONTAINER_LOG_MESSAGE = "edm-integration-log-ready"
CONTAINER_ENVIRONMENT = {
    "EDM_TEST_VALUE": "visible",
    "EDM_EMPTY_VALUE": "",
}
CONTAINER_LABELS = {
    "edm.integration-test": "true",
    "com.docker.compose.project": "edm-integration",
    "com.docker.compose.service": "test-container",
}
CONTAINER_START_TIMEOUT_SECONDS = 20.0


@pytest.fixture(scope="session")
def docker_client() -> Iterator[DockerClient]:
    """Connect to local Docker or skip the integration suite when unavailable."""
    try:
        docker_context = DockerContextReader().get_startup_docker_context()
        if docker_context.transport != DockerConnectionTransport.LOCAL:
            pytest.skip("Integration tests require a local Docker context")
        client = create_docker_client(docker_context, request_timeout=10.0)
        client.ping()
    except DockerException as exc:
        pytest.skip(f"Local Docker is unavailable: {exc}")

    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def docker_test_setup(
    docker_client: DockerClient,
) -> Iterator[DockerIntegrationTestContainer]:
    """Start one container shared by the Docker integration tests, then remove it."""
    container_name = f"edm-integration-{uuid.uuid4().hex[:12]}"
    docker_client.images.pull(CONTAINER_IMAGE)
    container = docker_client.containers.run(
        CONTAINER_IMAGE,
        [
            "sh",
            "-c",
            (f"echo {CONTAINER_LOG_MESSAGE}; " "while true; do sleep 1; done"),
        ],
        detach=True,
        environment=CONTAINER_ENVIRONMENT,
        labels=CONTAINER_LABELS,
        name=container_name,
    )

    try:
        _wait_for_container(container)
        yield DockerIntegrationTestContainer(
            container=container,
            log_message=CONTAINER_LOG_MESSAGE,
            environment=CONTAINER_ENVIRONMENT,
            labels=CONTAINER_LABELS,
        )
    finally:
        with suppress(NotFound):
            container.remove(force=True)


@pytest.fixture
def local_docker_container_client() -> Iterator[DockerSDKContainerClient]:
    """Create the real container client with a separate Docker connection."""
    docker_context = DockerContextReader().get_startup_docker_context()
    docker_container_client = DockerSDKContainerClient(
        create_docker_client=lambda: create_docker_client(
            docker_context,
            request_timeout=10.0,
        )
    )
    try:
        yield docker_container_client
    finally:
        docker_container_client.close()


def _wait_for_container(container: Container) -> None:
    """Wait until the container is running and its startup message is readable."""
    deadline = time.monotonic() + CONTAINER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        container.reload()
        log_text = container.logs().decode("utf-8", errors="replace")
        if container.status == "running" and CONTAINER_LOG_MESSAGE in log_text:
            return
        time.sleep(0.1)

    pytest.fail(
        f"Container {container.name!r} did not become ready within "
        f"{CONTAINER_START_TIMEOUT_SECONDS:g} seconds"
    )
