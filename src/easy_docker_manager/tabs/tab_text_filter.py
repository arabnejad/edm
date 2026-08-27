"""Choose which tab lines remain visible after a search."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from easy_docker_manager.core.tabs import TabName

MAX_REGEX_QUERY_LENGTH = 200


class TabTextFilter:
    """Choose the lines shown on screen or written by a Current view export.

    Logs searches keep only lines that match the regular expression. Env,
    Config, and Top searches keep every line because those tabs highlight
    matches instead of filtering content. TerminalController and
    TabExportController share this class so the screen and exported Current
    view use the same rules.
    """

    def __init__(self) -> None:
        """Keep the latest Logs result so an unchanged view is quick to reuse."""
        self._last_log_content: Optional[str] = None
        self._last_log_query: Optional[str] = None
        self._last_visible_log_lines: Optional[list[str]] = None

    def get_visible_lines(
        self,
        content: str,
        tab_name: TabName,
        query: str,
    ) -> list[str]:
        """Return the lines that should remain visible for this tab and query."""
        if not content:
            return []

        query = query.strip()
        if tab_name != TabName.LOGS or not query:
            return content.splitlines()

        if (
            content == self._last_log_content
            and query == self._last_log_query
            and self._last_visible_log_lines is not None
        ):
            return self._last_visible_log_lines

        pattern, error = compile_log_filter_regex(query)
        if error:
            return content.splitlines()

        matching_lines = [line for line in content.splitlines() if pattern.search(line)]
        visible_lines = matching_lines or [f"No log lines match /{query}/."]
        self._last_log_content = content
        self._last_log_query = query
        self._last_visible_log_lines = visible_lines
        return visible_lines


@lru_cache(maxsize=128)
def compile_log_filter_regex(query: str) -> tuple[re.Pattern[str], Optional[str]]:
    """Compile a case-insensitive regex, returning its error instead of raising."""
    if len(query) > MAX_REGEX_QUERY_LENGTH:
        return re.compile(r"$."), "Regex query is too long."
    try:
        return re.compile(query, re.IGNORECASE), None
    except re.error as exc:
        return re.compile(r"$."), str(exc)


__all__ = ["MAX_REGEX_QUERY_LENGTH", "TabTextFilter", "compile_log_filter_regex"]
