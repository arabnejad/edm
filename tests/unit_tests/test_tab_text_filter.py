from __future__ import annotations

from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.tabs.tab_text_filter import (
    MAX_REGEX_QUERY_LENGTH,
    TabTextFilter,
    compile_regex,
)


def test_tab_text_filter_applies_case_insensitive_regex_to_logs() -> None:
    tab_text_filter = TabTextFilter()

    assert tab_text_filter.get_visible_lines(
        "INFO started\nERROR failed",
        TabName.LOGS,
        "error",
    ) == ["ERROR failed"]


def test_tab_text_filter_reports_when_no_log_lines_match() -> None:
    visible_lines = TabTextFilter().get_visible_lines(
        "INFO",
        TabName.LOGS,
        "ERROR",
    )

    assert visible_lines == ["No log lines match /ERROR/."]


def test_tab_text_filter_keeps_non_log_tabs_and_invalid_regex_unchanged() -> None:
    content = "A=1\nB=2"
    tab_text_filter = TabTextFilter()

    assert tab_text_filter.get_visible_lines(content, TabName.ENV, "A") == [
        "A=1",
        "B=2",
    ]
    assert tab_text_filter.get_visible_lines(content, TabName.LOGS, "[") == [
        "A=1",
        "B=2",
    ]
    assert tab_text_filter.get_visible_lines("", TabName.LOGS, "A") == []


def test_tab_text_filter_reuses_the_latest_log_result() -> None:
    tab_text_filter = TabTextFilter()
    first_result = tab_text_filter.get_visible_lines("A\nB", TabName.LOGS, "A")
    repeated_result = tab_text_filter.get_visible_lines("A\nB", TabName.LOGS, "A")

    assert repeated_result is first_result


def test_compile_regex_handles_valid_invalid_and_long_queries() -> None:
    pattern, error = compile_regex("error")
    assert error is None
    assert pattern.search("ERROR")

    _, error = compile_regex("[")
    assert error

    _, error = compile_regex("a" * (MAX_REGEX_QUERY_LENGTH + 1))
    assert error == "Regex query is too long."
