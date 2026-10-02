from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.tabs.tab_text_filter import (
    MAX_REGEX_QUERY_LENGTH,
    TabTextFilter,
    compile_log_filter_regex,
)


def test_tab_text_filter_applies_case_insensitive_regex_to_logs() -> None:
    tab_text_filter = TabTextFilter()

    assert tab_text_filter.filter_lines(
        "INFO started\nERROR failed",
        TabName.LOGS,
        "error",
    ) == (["ERROR failed"], None)


def test_tab_text_filter_returns_empty_data_when_no_log_lines_match() -> None:
    lines, error = TabTextFilter().filter_lines(
        "INFO",
        TabName.LOGS,
        "ERROR",
    )

    assert lines == []
    assert error is None


def test_tab_text_filter_keeps_non_log_tabs_unchanged() -> None:
    content = "A=1\nB=2"
    tab_text_filter = TabTextFilter()

    assert tab_text_filter.filter_lines(content, TabName.ENV, "[") == (
        ["A=1", "B=2"],
        None,
    )
    assert tab_text_filter.filter_lines("", TabName.LOGS, "A") == ([], None)
    assert tab_text_filter.filter_lines(content, TabName.LOGS, " ") == (
        ["A=1", "B=2"],
        None,
    )


def test_tab_text_filter_reuses_the_latest_log_result() -> None:
    tab_text_filter = TabTextFilter()
    first_result = tab_text_filter.filter_lines("A\nB", TabName.LOGS, "A")
    repeated_result = tab_text_filter.filter_lines("A\nB", TabName.LOGS, "A")

    assert repeated_result is first_result


@pytest.mark.parametrize("query", ["[", "a" * (MAX_REGEX_QUERY_LENGTH + 1)])
@pytest.mark.parametrize("content", ["", "INFO\nERROR"])
def test_invalid_log_search_returns_an_error_without_data(
    query: str, content: str
) -> None:
    text_filter = TabTextFilter()

    lines, error = text_filter.filter_lines(content, TabName.LOGS, query)

    assert lines == []
    assert error is not None
    assert error.startswith("Invalid log search:")


def test_compile_log_filter_regex_handles_valid_invalid_and_long_queries() -> None:
    pattern, error = compile_log_filter_regex("error")
    assert error is None
    assert pattern.search("ERROR")

    _, error = compile_log_filter_regex("[")
    assert error

    _, error = compile_log_filter_regex("a" * (MAX_REGEX_QUERY_LENGTH + 1))
    assert error == "Regex query is too long."


def test_log_filter_shows_and_caches_a_timeout_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pattern = Mock()
    pattern.search.side_effect = TimeoutError
    monkeypatch.setattr(
        "easy_docker_manager.tabs.tab_text_filter.compile_log_filter_regex",
        lambda query: (pattern, None),
    )
    text_filter = TabTextFilter()

    result = text_filter.filter_lines("INFO\nERROR", TabName.LOGS, "error")

    assert result == ([], "Log search took too long. Try a simpler regex.")
    assert text_filter.filter_lines("INFO\nERROR", TabName.LOGS, "error") is result
    pattern.search.assert_called_once()


def test_expensive_regex_cannot_hang_filtering_or_highlighting() -> None:
    # A separate process lets the test fail safely if the timeout is removed.
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            dedent("""
                from easy_docker_manager.core.tabs import TabName
                from easy_docker_manager.tabs.tab_text_filter import TabTextFilter
                from easy_docker_manager.ui.formatting import regex_match_ranges

                text_filter = TabTextFilter()
                query = '(a+)+$'
                assert text_filter.filter_lines(
                    'a' * 30 + '!', TabName.LOGS, query
                ) == ([], None)

                content = 'a' * 1000 + '!'
                query = '(a|aa)+$'
                assert text_filter.filter_lines(
                    content, TabName.LOGS, query
                ) == ([], 'Log search took too long. Try a simpler regex.')
                assert text_filter.filter_lines(
                    content, TabName.LOGS, 'a'
                ) == ([content], None)
                assert regex_match_ranges('ok ' + content, 'ok|' + query) == []
                """),
        ],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )

    assert result.returncode == 0, result.stderr
