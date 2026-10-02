"""Filter tab data without adding messages meant only for the screen."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import regex

from easy_docker_manager.core.tabs import TabName

MAX_REGEX_QUERY_LENGTH = 200
LOG_REGEX_TIMEOUT_SECONDS = 0.05


class TabTextFilter:
    """Choose the lines shown on screen or written by a Current view export.

    Logs searches keep only lines that match the regular expression. Env,
    Config, Stats, and Top searches keep every line because those tabs highlight
    matches instead of filtering content. TerminalController and
    TabExportController share this class so the screen and exported Current
    view use the same rules.
    """

    def __init__(self) -> None:
        """Keep the latest Logs result so an unchanged view is quick to reuse."""
        self._last_log_content: Optional[str] = None
        self._last_log_query: Optional[str] = None
        self._last_log_result: Optional[tuple[list[str], Optional[str]]] = None

    def filter_lines(
        self,
        content: str,
        tab_name: TabName,
        query: str,
    ) -> tuple[list[str], Optional[str]]:
        """Return data lines and a separate error message if the search fails."""
        query = query.strip()
        if tab_name != TabName.LOGS or not query:
            return content.splitlines(), None

        if (
            content == self._last_log_content
            and query == self._last_log_query
            and self._last_log_result is not None
        ):
            return self._last_log_result

        matching_lines: list[str] = []
        pattern, error = compile_log_filter_regex(query)
        if error:
            error = f"Invalid log search: {error}"
        else:
            try:
                matching_lines = [
                    line
                    for line in content.splitlines()
                    if pattern.search(line, timeout=LOG_REGEX_TIMEOUT_SECONDS)
                ]
            except TimeoutError:
                error = "Log search took too long. Try a simpler regex."

        result = matching_lines, error
        self._last_log_content = content
        self._last_log_query = query
        self._last_log_result = result
        return result


@lru_cache(maxsize=128)
def compile_log_filter_regex(query: str) -> tuple[regex.Pattern[str], Optional[str]]:
    """Compile a case-insensitive regex, returning its error instead of raising."""
    if len(query) > MAX_REGEX_QUERY_LENGTH:
        return regex.compile(r"$."), "Regex query is too long."
    try:
        return regex.compile(query, regex.IGNORECASE | regex.VERSION0), None
    except (regex.error, ValueError, OverflowError) as exc:
        return regex.compile(r"$."), str(exc)


__all__ = [
    "LOG_REGEX_TIMEOUT_SECONDS",
    "MAX_REGEX_QUERY_LENGTH",
    "TabTextFilter",
    "compile_log_filter_regex",
]
