from __future__ import annotations

import pytest

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    get_container_list_in_requested_order,
)
from easy_docker_manager.core.containers import ContainerSummary


@pytest.fixture
def containers_for_sorting() -> list[ContainerSummary]:
    return [
        ContainerSummary(
            container_id="container-b",
            name="bravo",
            status="paused",
            image_name="redis:7",
            created_at="2026-02-01T10:00:00Z",
        ),
        ContainerSummary(
            container_id="container-a",
            name="Alpha",
            status="running",
            image_name="nginx:latest",
            created_at="2026-01-01T10:00:00Z",
        ),
        ContainerSummary(
            container_id="container-c",
            name="charlie",
            status="exited",
            image_name="",
            created_at="",
        ),
    ]


@pytest.mark.parametrize(
    ("sort_field", "descending", "expected_ids"),
    [
        (ContainerSortField.NAME, False, ["container-a", "container-b", "container-c"]),
        (ContainerSortField.NAME, True, ["container-c", "container-b", "container-a"]),
        (
            ContainerSortField.IMAGE,
            False,
            ["container-a", "container-b", "container-c"],
        ),
        (ContainerSortField.IMAGE, True, ["container-b", "container-a", "container-c"]),
        (
            ContainerSortField.STATUS,
            False,
            ["container-c", "container-b", "container-a"],
        ),
        (
            ContainerSortField.STATUS,
            True,
            ["container-a", "container-b", "container-c"],
        ),
        (
            ContainerSortField.CREATED_AT,
            False,
            ["container-a", "container-b", "container-c"],
        ),
        (
            ContainerSortField.CREATED_AT,
            True,
            ["container-b", "container-a", "container-c"],
        ),
    ],
)
def test_container_sorting_orders_each_field_in_both_directions(
    containers_for_sorting: list[ContainerSummary],
    sort_field: ContainerSortField,
    descending: bool,
    expected_ids: list[str],
) -> None:
    sorted_containers = get_container_list_in_requested_order(
        containers_for_sorting,
        sort_field,
        descending,
    )

    assert [container.container_id for container in sorted_containers] == expected_ids


def test_docker_order_returns_a_copy_without_reordering(
    containers_for_sorting: list[ContainerSummary],
) -> None:
    sorted_containers = get_container_list_in_requested_order(
        containers_for_sorting,
        ContainerSortField.DOCKER_ORDER,
        descending=True,
    )

    assert sorted_containers == containers_for_sorting
    assert sorted_containers is not containers_for_sorting
