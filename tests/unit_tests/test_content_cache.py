from __future__ import annotations

import pytest

from easy_docker_manager.core.content_cache import ContainerTabKey, LRUTabContentCache
from easy_docker_manager.core.tabs import TabName


def container_tab_key(
    container_id: str,
    tab: TabName = TabName.LOGS,
) -> ContainerTabKey:
    return ContainerTabKey(container_id=container_id, tab_name=tab)


@pytest.mark.parametrize(
    ("max_entries", "max_bytes"),
    [(0, 10), (1, 0), (-1, 10), (1, -1)],
)
def test_cache_rejects_invalid_limits(max_entries: int, max_bytes: int) -> None:
    with pytest.raises(ValueError):
        LRUTabContentCache(max_entries=max_entries, max_total_bytes=max_bytes)


def test_cache_removes_the_least_recently_used_entry() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=100)
    first_key = container_tab_key("first")
    second_key = container_tab_key("second")
    third_key = container_tab_key("third")
    cache[first_key] = "one"
    cache[second_key] = "two"

    assert cache[first_key] == "one"
    cache[third_key] = "three"

    assert first_key in cache
    assert second_key not in cache
    assert third_key in cache


def test_cache_tracks_bytes_when_an_entry_is_replaced() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=20)
    cache[container_tab_key("one")] = "abc"
    cache[container_tab_key("one")] = "abcdef"

    assert cache.total_size_bytes == 6
    assert len(cache) == 1


def test_cache_trims_large_logs_from_the_start() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=4)
    cache[container_tab_key("one", TabName.LOGS)] = "abcdef"

    assert cache[container_tab_key("one", TabName.LOGS)] == "cdef"


def test_cache_trims_large_non_log_text_from_the_end() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=4)
    cache[container_tab_key("one", TabName.CONFIG)] = "abcdef"

    assert cache[container_tab_key("one", TabName.CONFIG)] == "abcd"


@pytest.mark.parametrize("tab_name", [TabName.LOGS, TabName.CONFIG])
def test_cache_keeps_trimmed_multibyte_text_within_the_byte_limit(
    tab_name: TabName,
) -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=2)
    key = container_tab_key("one", tab_name)

    # \u00e9 is a Unicode escape for a character that uses two UTF-8 bytes.
    cache[key] = "a\u00e9b"

    assert key in cache
    assert len(cache[key].encode("utf-8")) <= 2
    assert cache.total_size_bytes <= 2


def test_cache_byte_limit_removes_old_entries() -> None:
    cache = LRUTabContentCache(max_entries=5, max_total_bytes=6)
    cache[container_tab_key("one")] = "abc"
    cache[container_tab_key("two")] = "def"
    cache[container_tab_key("three")] = "g"

    assert container_tab_key("one") not in cache
    assert cache.total_size_bytes == 4


def test_cache_get_returns_default_without_adding_an_entry() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=100)

    assert cache.get(container_tab_key("missing"), "fallback") == "fallback"
    assert len(cache) == 0


def test_cache_prunes_stopped_containers_and_can_be_cleared() -> None:
    cache = LRUTabContentCache(max_entries=2, max_total_bytes=100)
    cache[container_tab_key("live")] = "one"
    cache[container_tab_key("stopped")] = "two"

    cache.remove_stopped_container_entries({"live"})

    assert container_tab_key("live") in cache
    assert container_tab_key("stopped") not in cache
    cache.clear()
    assert len(cache) == 0
    assert cache.total_size_bytes == 0
