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

    result = text_filter.get_visible_lines("INFO\nERROR", TabName.LOGS, "error")

    assert result == ["Log search took too long. Try a simpler regex."]
    assert text_filter.get_visible_lines("INFO\nERROR", TabName.LOGS, "error") is result


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
                assert text_filter.get_visible_lines(
                    'a' * 30 + '!', TabName.LOGS, query
                ) == [f'No log lines match /{query}/.']

                content = 'a' * 1000 + '!'
                query = '(a|aa)+$'
                assert text_filter.get_visible_lines(
                    content, TabName.LOGS, query
                ) == ['Log search took too long. Try a simpler regex.']
                assert text_filter.get_visible_lines(
                    content, TabName.LOGS, 'a'
                ) == [content]
                assert regex_match_ranges('ok ' + content, 'ok|' + query) == []
                """),
        ],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )

    assert result.returncode == 0, result.stderr
