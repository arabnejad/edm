from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker import TLSConfig
from docker.errors import DockerException

from easy_docker_manager.core.docker_connections import (
    DockerConnectionMenuState,
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.docker import docker_contexts
from easy_docker_manager.docker.docker_contexts import DockerContextReader


def _create_tls_config(
    certificate_directory: Path,
    *,
    verify_server_certificate: bool,
) -> TLSConfig:
    ca_certificate = certificate_directory / "ca.pem"
    client_certificate = certificate_directory / "cert.pem"
    client_private_key = certificate_directory / "key.pem"
    for certificate_file in (
        ca_certificate,
        client_certificate,
        client_private_key,
    ):
        certificate_file.write_text("test certificate", encoding="utf-8")
    return TLSConfig(
        client_cert=(str(client_certificate), str(client_private_key)),
        ca_cert=str(ca_certificate),
        verify=verify_server_certificate,
    )


def test_startup_context_uses_docker_context_environment_first(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "staging")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/ignored.sock")
    get_context = Mock(
        return_value=SimpleNamespace(
            name="staging",
            Host="ssh://docker@staging",
        )
    )
    monkeypatch.setattr(docker_contexts.docker.ContextAPI, "get_context", get_context)

    context = DockerContextReader().get_startup_docker_context()

    assert context.context_name == "staging"
    assert context.transport == DockerConnectionTransport.SSH
    assert not context.uses_docker_environment
    get_context.assert_called_once_with("staging")


def test_startup_context_preserves_docker_host_environment(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://docker@staging")

    context = DockerContextReader().get_startup_docker_context()

    assert context.context_name == "DOCKER_HOST"
    assert context.docker_host == "ssh://docker@staging"
    assert context.transport == DockerConnectionTransport.SSH
    assert context.uses_docker_environment


def test_context_list_includes_environment_and_sorts_default_first(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/docker.sock")
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "contexts",
        Mock(
            return_value=[
                SimpleNamespace(name="staging", Host="ssh://docker@staging"),
                SimpleNamespace(
                    name="default",
                    Host="unix:///var/run/docker.sock",
                ),
                SimpleNamespace(
                    name="production",
                    Host="tcp://production:2376",
                ),
            ]
        ),
    )

    contexts = DockerContextReader().list_configured_docker_contexts()

    assert [context.context_name for context in contexts] == [
        "default",
        "DOCKER_HOST",
        "production",
        "staging",
    ]
    assert contexts[0].display_name == "localhost"
    assert contexts[2].transport == DockerConnectionTransport.TCP
    assert not contexts[2].is_supported
    assert "CA certificate" in contexts[2].unsupported_reason


def test_context_list_supports_tcp_context_with_verified_tls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tls_config = _create_tls_config(
        tmp_path,
        verify_server_certificate=True,
    )
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "contexts",
        Mock(
            return_value=[
                SimpleNamespace(
                    name="production",
                    Host="tcp://production.example.com:2376",
                    TLSConfig=tls_config,
                )
            ]
        ),
    )

    context = DockerContextReader().list_configured_docker_contexts()[0]

    assert context.transport == DockerConnectionTransport.TCP
    assert context.has_required_tls_certificate_files
    assert context.verifies_tls_server_certificate
    assert context.uses_verified_tls
    assert context.is_supported
    assert context.transport_label == "TCP + TLS"


def test_context_list_rejects_tcp_context_that_skips_server_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tls_config = _create_tls_config(
        tmp_path,
        verify_server_certificate=False,
    )
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "contexts",
        Mock(
            return_value=[
                SimpleNamespace(
                    name="insecure-production",
                    Host="tcp://production.example.com:2376",
                    TLSConfig=tls_config,
                )
            ]
        ),
    )

    context = DockerContextReader().list_configured_docker_contexts()[0]

    assert context.has_required_tls_certificate_files
    assert not context.verifies_tls_server_certificate
    assert not context.uses_verified_tls
    assert not context.is_supported
    assert "verify the Docker server certificate" in context.unsupported_reason


def test_docker_host_environment_supports_verified_tls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_tls_config(tmp_path, verify_server_certificate=True)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://production.example.com:2376")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path))
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")

    context = DockerContextReader().get_startup_docker_context()

    assert context.uses_docker_environment
    assert context.uses_verified_tls
    assert context.is_supported


def test_docker_host_environment_rejects_disabled_server_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_tls_config(tmp_path, verify_server_certificate=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://production.example.com:2376")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path))
    monkeypatch.delenv("DOCKER_TLS_VERIFY", raising=False)

    context = DockerContextReader().get_startup_docker_context()

    assert context.has_required_tls_certificate_files
    assert not context.verifies_tls_server_certificate
    assert not context.is_supported


def test_docker_host_environment_rejects_missing_certificate_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://production.example.com:2376")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path))
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")

    context = DockerContextReader().get_startup_docker_context()

    assert not context.has_required_tls_certificate_files
    assert not context.uses_verified_tls
    assert not context.is_supported
    assert "CA certificate" in context.unsupported_reason


def test_unknown_context_is_returned_as_unsupported(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "missing")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "get_context",
        Mock(return_value=None),
    )

    context = DockerContextReader().get_startup_docker_context()

    assert context.context_name == "missing"
    assert context.transport == DockerConnectionTransport.UNKNOWN
    assert not context.is_supported
    assert "endpoint type" in context.unsupported_reason


def test_startup_context_uses_current_context_when_environment_is_empty(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "get_current_context",
        Mock(
            return_value=SimpleNamespace(
                name="default",
                Host="npipe:////./pipe/docker_engine",
            )
        ),
    )

    context = DockerContextReader().get_startup_docker_context()

    assert context.display_name == "localhost"
    assert context.transport_label == "Named pipe"


def test_startup_context_fails_when_docker_has_no_current_context(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "get_current_context",
        Mock(return_value=None),
    )

    with pytest.raises(DockerException, match="current context"):
        DockerContextReader().get_startup_docker_context()


@pytest.mark.parametrize(
    ("docker_host", "expected_transport", "expected_label"),
    [
        ("ssh://docker@server", DockerConnectionTransport.SSH, "SSH"),
        ("https://server:2376", DockerConnectionTransport.TCP, "TCP"),
        ("http://server:2375", DockerConnectionTransport.UNKNOWN, "Unsupported"),
        ("invalid-endpoint", DockerConnectionTransport.UNKNOWN, "Unsupported"),
    ],
)
def test_environment_endpoint_is_classified_for_display(
    monkeypatch,
    docker_host: str,
    expected_transport: DockerConnectionTransport,
    expected_label: str,
) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", docker_host)

    context = DockerContextReader().get_startup_docker_context()

    assert context.transport == expected_transport
    assert context.transport_label == expected_label


def test_context_list_does_not_add_docker_host_when_docker_context_is_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "staging")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/ignored.sock")
    monkeypatch.setattr(
        docker_contexts.docker.ContextAPI,
        "contexts",
        Mock(
            return_value=[
                None,
                SimpleNamespace(name="staging", Host="ssh://docker@staging"),
            ]
        ),
    )

    contexts = DockerContextReader().list_configured_docker_contexts()

    assert [context.context_name for context in contexts] == ["staging"]


def test_connection_menu_has_no_selection_when_context_list_is_empty() -> None:
    menu_state = DockerConnectionMenuState([], active_context_name="default")

    assert menu_state.selected_docker_context is None


def test_non_default_local_context_keeps_its_context_name() -> None:
    context = DockerContextDetails(
        "desktop-linux",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )

    assert context.display_name == "desktop-linux"
