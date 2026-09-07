"""Tests for filtering, grouping, and sorting the container list."""

from __future__ import annotations

import pytest

from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.containers import ContainerListViewMode, ContainerSummary


@pytest.fixture
def containers_for_filtering(container_summary_factory) -> list[ContainerSummary]:
    return [
        container_summary_factory(
            "web-id",
            name="web-api",
            image_name="python:3.12",
            status="running",
        ),
        container_summary_factory(
            "cache-id",
            name="cache",
            image_name="redis:7",
            status="running",
        ),
        container_summary_factory(
            "worker-id",
            name="worker",
            image_name="jobs:latest",
            status="restarting",
        ),
    ]


def test_new_list_uses_the_docker_order_for_its_initial_display(
    container_summary_factory,
) -> None:
    first_container = container_summary_factory("first")
    second_container = container_summary_factory("second")

    container_list = ContainerList([first_container, second_container])

    assert container_list.displayed_containers == [
        first_container,
        second_container,
    ]
    assert container_list.all_container_count == 2
    assert container_list.all_container_ids == {"first", "second"}
    assert container_list.running_container_ids == {"first", "second"}


def test_rebuilding_the_display_sorts_then_filters_the_docker_list(
    container_summary_factory,
) -> None:
    container_list = ContainerList(
        [
            container_summary_factory(
                "worker",
                name="Zulu worker",
                image_name="redis:7",
            ),
            container_summary_factory(
                "web",
                name="Alpha web",
                image_name="python:3.12",
            ),
            container_summary_factory(
                "cache",
                name="Beta cache",
                image_name="redis:6",
            ),
        ]
    )

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.NAME,
        False,
        "redis",
    )

    assert [container.container_id for container in displayed_containers] == [
        "cache",
        "worker",
    ]
    assert container_list.all_container_count == 3


def test_clearing_the_filter_restores_containers_without_a_new_docker_list(
    container_summary_factory,
) -> None:
    container_list = ContainerList(
        [
            container_summary_factory("web", image_name="python:3.12"),
            container_summary_factory("cache", image_name="redis:7"),
        ]
    )
    container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.DOCKER_ORDER,
        False,
        "redis",
    )

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )

    assert [container.container_id for container in displayed_containers] == [
        "web",
        "cache",
    ]


def test_replacing_all_containers_updates_count_and_container_ids(
    container_summary_factory,
) -> None:
    container_list = ContainerList([container_summary_factory("old")])

    container_list.replace_all_containers(
        [
            container_summary_factory("new-1"),
            container_summary_factory("new-2"),
        ]
    )
    container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )

    assert container_list.all_container_count == 2
    assert container_list.all_container_ids == {"new-1", "new-2"}


@pytest.mark.parametrize(
    ("filter_query", "expected_container_ids"),
    [
        ("WEB", ["web-id"]),
        ("redis", ["cache-id"]),
        ("START", ["worker-id"]),
        ("running", ["web-id", "cache-id"]),
        ("missing", []),
    ],
)
def test_filter_matches_name_image_and_status_without_case_sensitivity(
    containers_for_filtering: list[ContainerSummary],
    filter_query: str,
    expected_container_ids: list[str],
) -> None:
    container_list = ContainerList(containers_for_filtering)

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        filter_query,
    )

    assert [container.container_id for container in displayed_containers] == (
        expected_container_ids
    )


def test_empty_filter_keeps_the_full_container_list(
    containers_for_filtering: list[ContainerSummary],
) -> None:
    container_list = ContainerList(containers_for_filtering)

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )

    assert displayed_containers == containers_for_filtering
    assert displayed_containers is not containers_for_filtering


def test_compose_projects_are_grouped_and_other_containers_are_kept_at_the_end(
    container_summary_factory,
) -> None:
    container_list = ContainerList(
        [
            container_summary_factory(
                "project-z-worker",
                name="worker",
                compose_project_name="project-z",
                compose_service_name="worker",
            ),
            container_summary_factory("standalone", name="agent"),
            container_summary_factory(
                "project-a-web",
                name="web",
                compose_project_name="project-a",
                compose_service_name="web",
            ),
            container_summary_factory(
                "project-z-api",
                name="api",
                compose_project_name="project-z",
                compose_service_name="api",
            ),
        ]
    )

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.NAME,
        False,
        "",
    )

    assert [container.container_id for container in displayed_containers] == [
        "project-a-web",
        "project-z-api",
        "project-z-worker",
        "standalone",
    ]


@pytest.mark.parametrize("filter_query", ["ACCOUNTS", "web-service"])
def test_filter_matches_compose_project_and_service_names(
    container_summary_factory,
    filter_query: str,
) -> None:
    compose_container = container_summary_factory(
        "compose-web",
        compose_project_name="accounts",
        compose_service_name="web-service",
    )
    container_list = ContainerList(
        [compose_container, container_summary_factory("standalone")]
    )

    displayed_containers = container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.DOCKER_ORDER,
        False,
        filter_query,
    )

    assert displayed_containers == [compose_container]


def test_running_view_hides_stopped_containers(container_summary_factory) -> None:
    running_container = container_summary_factory("running")
    stopped_container = container_summary_factory("stopped", status="exited")
    container_list = ContainerList([running_container, stopped_container])

    running_view = container_list.rebuild_displayed_containers(
        ContainerListViewMode.RUNNING_ONLY,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )

    assert running_view == [running_container]
    assert (
        container_list.get_container_count_for_view(ContainerListViewMode.RUNNING_ONLY)
        == 1
    )
    assert container_list.get_container_count_for_view(ContainerListViewMode.ALL) == 2
