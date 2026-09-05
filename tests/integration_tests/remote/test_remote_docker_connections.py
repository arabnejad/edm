from __future__ import annotations

import os
import uuid
from contextlib import suppress

import pytest
from docker.errors import NotFound

from easy_docker_manager.core.docker_connections import DockerConnectionTransport
from easy_docker_manager.docker.client_factory import (
    create_validated_docker_client_for_context,
)
from easy_docker_manager.docker.docker_contexts import DockerContextReader
from easy_docker_manager.docker.docker_sdk_container_client import (
    DockerSDKContainerClient,
)

pytestmark = pytest.mark.remote_integration

REMOTE_TEST_CONTAINER_IMAGE = os.getenv(
    "EDM_REMOTE_INTEGRATION_TEST_IMAGE", "alpine:3.20"
)
REMOTE_CONTEXT_TEST_CASES = (
    (
        "EDM_REMOTE_TLS_CONTEXT_NAME",
        DockerConnectionTransport.TCP,
    ),
    (
        "EDM_REMOTE_SSH_CONTEXT_NAME",
        DockerConnectionTransport.SSH,
    ),
)


@pytest.mark.parametrize(
    ("context_name_environment_variable", "expected_transport"),
    REMOTE_CONTEXT_TEST_CASES,
    ids=("tls", "ssh"),
)
def test_remote_context_can_be_discovered_validated_and_used(
    context_name_environment_variable: str,
    expected_transport: DockerConnectionTransport,
) -> None:
    context_name = os.getenv(context_name_environment_variable)
    if not context_name:
        pytest.fail(
            "Run make remote-integration-test to create the remote Docker contexts"
        )

    configured_contexts = DockerContextReader().list_configured_docker_contexts()
    context_by_name = {
        docker_context.context_name: docker_context
        for docker_context in configured_contexts
    }
    assert context_name in context_by_name

    docker_context = context_by_name[context_name]
    assert docker_context.transport == expected_transport
    assert docker_context.is_supported
    if expected_transport == DockerConnectionTransport.TCP:
        assert docker_context.uses_verified_tls

    validated_docker_client = create_validated_docker_client_for_context(
        docker_context,
        request_timeout=60.0,
    )
    docker_container_client = DockerSDKContainerClient(
        create_docker_client=lambda: validated_docker_client
    )
    docker_container_client.switch_docker_connection(validated_docker_client)

    container = None
    container_name = f"edm-remote-test-{uuid.uuid4().hex[:12]}"
    expected_log_message = f"{container_name}-ready"
    try:
        validated_docker_client.images.pull(REMOTE_TEST_CONTAINER_IMAGE)
        container = validated_docker_client.containers.run(
            REMOTE_TEST_CONTAINER_IMAGE,
            [
                "sh",
                "-c",
                f"echo {expected_log_message}; while true; do sleep 1; done",
            ],
            detach=True,
            labels={"edm.remote-integration-test": "true"},
            name=container_name,
        )

        running_containers = docker_container_client.list_running_containers()
        matching_container = next(
            (
                running_container
                for running_container in running_containers
                if running_container.container_id == container.id
            ),
            None,
        )

        assert matching_container is not None
        assert matching_container.name == container_name
        assert matching_container.status == "running"
        assert expected_log_message in docker_container_client.get_container_logs(
            container.id,
            tail_lines=20,
        )

        daemon_details = docker_container_client.get_docker_daemon_details()
        assert daemon_details.daemon_version
        assert daemon_details.api_version
    finally:
        try:
            if container is not None:
                with suppress(NotFound):
                    container.remove(force=True)
        finally:
            docker_container_client.close()
