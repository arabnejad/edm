from __future__ import annotations

from pathlib import Path

from easy_docker_manager import diagnostics
from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.diagnostics import (
    DiagnosticsReport,
    DockerConnectionStatus,
    build_edm_title,
    build_edm_version_label,
    create_initial_diagnostics_report,
    format_diagnostics_report,
)
from easy_docker_manager.docker.container_client import DockerDaemonDetails


def test_initial_report_collects_installed_versions_and_file_paths(
    monkeypatch,
) -> None:
    installed_versions = {
        "easy-docker-manager": "1.2.0",
        "docker": "7.1.0",
    }
    monkeypatch.setattr(
        diagnostics,
        "distribution_version",
        lambda distribution_name: installed_versions[distribution_name],
    )
    monkeypatch.setattr(diagnostics.platform, "python_version", lambda: "3.12.3")
    monkeypatch.setattr(
        diagnostics,
        "default_config_path",
        lambda: Path("/tmp/EDM/config.json"),
    )
    monkeypatch.setattr(
        diagnostics,
        "get_configured_log_file_path",
        lambda: Path("/tmp/EDM/edm.log"),
    )

    report = create_initial_diagnostics_report()

    assert report.edm_version == "1.2.0"
    assert report.python_version == "3.12.3"
    assert report.docker_sdk_version == "7.1.0"
    assert report.docker_context_name == "localhost"
    assert report.config_file_path == Path("/tmp/EDM/config.json")
    assert report.application_log_file_path == Path("/tmp/EDM/edm.log")
    assert report.docker_connection_status == DockerConnectionStatus.CHECKING


def test_missing_distribution_metadata_is_reported_as_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics,
        "distribution_version",
        lambda distribution_name: (_ for _ in ()).throw(
            diagnostics.PackageNotFoundError(distribution_name)
        ),
    )

    assert diagnostics.get_installed_edm_version() == "unknown"


def test_report_formats_connected_docker_details_and_shortens_home_paths() -> None:
    report = DiagnosticsReport(
        edm_version="1.2.0",
        python_version="3.12.3",
        docker_sdk_version="7.1.0",
        config_file_path=Path.home() / ".config" / "EDM" / "config.json",
        application_log_file_path=Path.home() / ".config" / "EDM" / "edm.log",
    )
    report.record_successful_docker_connection(
        DockerDaemonDetails(
            daemon_version="28.3.3",
            api_version="1.51",
            operating_system="linux",
            architecture="amd64",
        )
    )

    formatted_report = format_diagnostics_report(report)

    assert formatted_report.startswith("Easy Docker Manager Diagnostics\n")
    assert "EDM version:          1.2.0" in formatted_report
    assert "Config file:          ~/.config/EDM/config.json" in formatted_report
    assert "Connection:           Connected" in formatted_report
    assert "Context:              localhost" in formatted_report
    assert "Daemon version:       28.3.3" in formatted_report
    assert "Platform:             Linux amd64" in formatted_report


def test_report_formats_docker_failure_on_one_line() -> None:
    report = DiagnosticsReport(
        edm_version="1.2.0",
        python_version="3.12.3",
        docker_sdk_version="7.1.0",
        config_file_path=Path("config.json"),
        application_log_file_path=Path("edm.log"),
    )
    report.record_failed_docker_connection(RuntimeError("daemon\nnot available"))

    formatted_report = format_diagnostics_report(report, include_heading=False)

    assert "Connection:           Failed" in formatted_report
    assert "Daemon version:       N/A" in formatted_report
    assert "Error:                daemon not available" in formatted_report


def test_initial_report_uses_selected_docker_context_name() -> None:
    report = create_initial_diagnostics_report(
        DockerContextDetails(
            "staging",
            "ssh://docker@staging",
            DockerConnectionTransport.SSH,
        )
    )

    assert report.docker_context_name == "staging"


def test_application_title_hides_local_build_suffix() -> None:
    assert build_edm_title("1.2.0") == "Easy Docker Manager (v1.2.0)"
    assert build_edm_title("1.3.0.dev4+g123abc") == (
        "Easy Docker Manager (v1.3.0.dev4)"
    )
    assert build_edm_title("unknown") == "Easy Docker Manager"


def test_application_version_label_hides_local_build_suffix() -> None:
    assert build_edm_version_label("1.2.0") == "v1.2.0"
    assert build_edm_version_label("1.3.0.dev4+g123abc") == "v1.3.0.dev4"
    assert build_edm_version_label("unknown") == ""
