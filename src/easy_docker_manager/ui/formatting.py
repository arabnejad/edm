"""Add terminal colors and search highlights to detail text."""

from __future__ import annotations

import re
from collections.abc import Hashable
from functools import lru_cache
from typing import Optional, Union

from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.tabs.tab_text_filter import compile_regex

MarkupSegment = Union[str, tuple[Hashable, str]]


class DetailLineRenderer:
    """Add search highlights and simple tab-specific colors."""

    def render_line(
        self,
        line: str,
        tab: TabName,
        query: str,
        *,
        is_error: bool = False,
    ) -> Union[str, list[MarkupSegment]]:
        """Return display markup for one line in the detail panel.

        The formatter calls this while rendering a tab. Error lines use the
        error style; other lines use tab colors and search highlighting.
        """
        if is_error:
            return [("error", line)]

        query = query.strip()
        if not query:
            return self.base_line_markup(line, tab)

        if tab != TabName.LOGS:
            return self.plain_text_highlighted_markup(line, tab, query)
        return self.regex_highlighted_markup(line, tab, query)

    def regex_highlighted_markup(
        self,
        line: str,
        tab: TabName,
        query: str,
    ) -> list[MarkupSegment]:
        """Highlight every regex match in a Logs line."""
        match_ranges = regex_match_ranges(line, query)
        return self.highlighted_markup(line, tab, match_ranges)

    def plain_text_highlighted_markup(
        self,
        line: str,
        tab: TabName,
        query: str,
    ) -> list[MarkupSegment]:
        """Highlight plain-text matches in Env, Config, or Top text."""
        match_ranges = plain_text_match_ranges(line, query)
        return self.highlighted_markup(line, tab, match_ranges)

    def highlighted_markup(
        self,
        line: str,
        tab: TabName,
        match_ranges: list[tuple[int, int]],
    ) -> list[MarkupSegment]:
        """Add search highlights while keeping the line's normal colors."""
        if not match_ranges:
            return self.base_line_markup(line, tab)

        base_markup = self.base_line_markup(line, tab)
        output: list[MarkupSegment] = []
        match_range_index = 0
        text_position = 0

        for piece in base_markup:
            attr, text = markup_piece_attr_and_text(piece)
            piece_start = text_position
            piece_end = piece_start + len(text)
            local_position = 0

            while (
                match_range_index < len(match_ranges)
                and match_ranges[match_range_index][1] <= piece_start
            ):
                match_range_index += 1

            while (
                match_range_index < len(match_ranges)
                and match_ranges[match_range_index][0] < piece_end
            ):
                match_start, match_end = match_ranges[match_range_index]
                highlight_start = max(match_start, piece_start)
                highlight_end = min(match_end, piece_end)

                if highlight_start > piece_start + local_position:
                    normal_end = highlight_start - piece_start
                    append_markup_piece(
                        output,
                        attr,
                        text[local_position:normal_end],
                    )
                    local_position = normal_end

                append_markup_piece(
                    output,
                    "highlight",
                    text[highlight_start - piece_start : highlight_end - piece_start],
                )
                local_position = highlight_end - piece_start

                if match_end <= piece_end:
                    match_range_index += 1
                else:
                    break

            append_markup_piece(output, attr, text[local_position:])
            text_position = piece_end

        return output

    def base_line_markup(self, line: str, tab: TabName) -> list[MarkupSegment]:
        """Return the line's normal tab-specific colors."""
        if not line:
            return [""]
        if tab != TabName.LOGS:
            return structured_text_markup(line, tab)
        return log_markup(line)


class DetailTabTextFormatter:
    """Add colors and search highlights to detail-tab lines.

    TerminalController uses this before drawing each visible line. Logs use
    regex highlights. Env, Config, and Top highlight plain-text matches.
    TabTextFilter decides which lines are visible before this formatter runs.
    """

    def __init__(self) -> None:
        self.line_renderer = DetailLineRenderer()

    def format_detail_line(
        self,
        line: str,
        tab: TabName,
        query: str,
        *,
        is_error: bool = False,
    ) -> Union[str, list[MarkupSegment]]:
        """Return the line's colors, using the error color when is_error is True."""
        return self.line_renderer.render_line(line, tab, query, is_error=is_error)


def regex_match_ranges(line: str, query: str) -> list[tuple[int, int]]:
    """Return the start and end positions of regex matches in one log line.

    For example, regex_match_ranges("ERROR 500", "error|500") returns
    [(0, 5), (6, 9)]. The search is case-insensitive.
    """
    pattern, error = compile_regex(query)
    if error:
        return []
    return [
        (match.start(), match.end())
        for match in pattern.finditer(line)
        if match.start() != match.end()
    ]


def plain_text_match_ranges(line: str, query: str) -> list[tuple[int, int]]:
    """Return plain-text match positions without treating query as a regex.

    For example, plain_text_match_ranges("A[B [b", "[B") returns
    [(1, 3), (4, 6)]. The opening bracket is matched as normal text rather than
    being interpreted as regex syntax.
    """
    if not query:
        return []
    pattern = _compile_plain_text_pattern(query)
    return [(match.start(), match.end()) for match in pattern.finditer(line)]


@lru_cache(maxsize=128)
def _compile_plain_text_pattern(query: str) -> re.Pattern[str]:
    """Compile and cache a case-insensitive plain-text search pattern."""
    return re.compile(re.escape(query), re.IGNORECASE)


def markup_piece_attr_and_text(
    piece: MarkupSegment,
) -> tuple[Optional[Hashable], str]:
    """Return a markup segment's color name and text."""
    if isinstance(piece, tuple):
        return piece[0], piece[1]
    return None, piece


def append_markup_piece(
    output: list[MarkupSegment],
    attr: Optional[Hashable],
    text: str,
) -> None:
    """Append markup and join it to the previous segment when colors match."""
    if not text:
        return

    if not output:
        output.append((attr, text) if attr is not None else text)
        return

    previous = output[-1]
    previous_attr, previous_text = markup_piece_attr_and_text(previous)
    if previous_attr != attr:
        output.append((attr, text) if attr is not None else text)
        return

    combined_text = f"{previous_text}{text}"
    output[-1] = (attr, combined_text) if attr is not None else combined_text


def structured_text_markup(line: str, tab: TabName) -> list[MarkupSegment]:
    """Return simple token markup for Env, Config, and Top lines."""
    if "=" in line and tab == TabName.ENV:
        key, value = line.split("=", 1)
        return [("accent", key), ("muted", "="), ("value", value)]
    return token_markup(line)


def log_markup(line: str) -> list[MarkupSegment]:
    """Return color markup for common timestamps, levels, URLs, and numbers."""
    parts: list[MarkupSegment] = []
    for token in re.split(r"(\s+)", line):
        if not token:
            continue
        if token.isspace():
            parts.append(token)
        elif re.match(r"\d{4}-\d{2}-\d{2}T|\d{4}-\d{2}-\d{2}$", token):
            parts.append(("log_time", token))
        elif token in {"INFO", "INFO-"}:
            parts.append(("log_info", token))
        elif token in {"DEBUG", "DEBUG-"}:
            parts.append(("log_debug", token))
        elif token.startswith("WARN"):
            parts.append(("log_warning", token))
        elif token.startswith("ERROR") or token.startswith("FATAL"):
            parts.append(("log_error", token))
        elif (
            token.startswith("GET") or token.startswith("POST") or token.startswith("/")
        ):
            parts.append(("log_http", token))
        elif re.fullmatch(r"[0-9]+", token):
            parts.append(("log_number", token))
        else:
            parts.append(token)
    return parts


def token_markup(line: str) -> list[MarkupSegment]:
    """Add terminal colors to Config and Top values.

    Punctuation, numbers, booleans, null values, and quoted text receive
    separate colors so these tabs are easier to scan.
    """
    parts: list[MarkupSegment] = []
    for part in re.split(r"([{}\[\]:,=]|\s+)", line):
        if not part:
            continue
        if part.isspace():
            parts.append(part)
        elif part in "{}[]:,=":
            parts.append(("muted", part))
        elif re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", part):
            parts.append(("log_number", part))
        elif part.lower() in {"true", "false", "null"}:
            parts.append(("log_warning", part))
        elif part.startswith('"') and part.endswith('"'):
            parts.append(("value", part))
        else:
            parts.append(part)
    return parts


__all__ = [
    "DetailLineRenderer",
    "DetailTabTextFormatter",
    "MarkupSegment",
    "append_markup_piece",
    "plain_text_match_ranges",
    "log_markup",
    "markup_piece_attr_and_text",
    "regex_match_ranges",
    "structured_text_markup",
    "token_markup",
]
