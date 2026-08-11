from __future__ import annotations

from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.ui.formatting import (
    MAX_REGEX_QUERY_LENGTH,
    DetailLineRenderer,
    DetailTabTextFormatter,
    LogRegexLineFilter,
    append_markup_piece,
    compile_regex,
    log_markup,
    markup_piece_attr_and_text,
    plain_text_match_ranges,
    regex_match_ranges,
    structured_text_markup,
    token_markup,
)


def flatten_markup_text(markup) -> str:
    return "".join(piece[1] if isinstance(piece, tuple) else piece for piece in markup)


def test_log_filter_applies_case_insensitive_regex_to_logs() -> None:
    line_filter = LogRegexLineFilter()

    assert line_filter.filter_lines(
        "INFO started\nERROR failed",
        TabName.LOGS,
        "error",
    ) == ["ERROR failed"]


def test_log_filter_reports_no_matches() -> None:
    assert LogRegexLineFilter().filter_lines("INFO", TabName.LOGS, "ERROR") == [
        "No log lines match /ERROR/."
    ]


def test_log_filter_leaves_non_log_tabs_and_invalid_regex_unchanged() -> None:
    content = "A=1\nB=2"
    line_filter = LogRegexLineFilter()

    assert line_filter.filter_lines(content, TabName.ENV, "A") == ["A=1", "B=2"]
    assert line_filter.filter_lines(content, TabName.LOGS, "[") == ["A=1", "B=2"]
    assert line_filter.filter_lines("", TabName.LOGS, "A") == []


def test_log_filter_reuses_the_last_result() -> None:
    line_filter = LogRegexLineFilter()
    first_result = line_filter.filter_lines("A\nB", TabName.LOGS, "A")
    repeated_result = line_filter.filter_lines("A\nB", TabName.LOGS, "A")
    assert repeated_result is first_result


def test_compile_regex_handles_valid_invalid_and_long_queries() -> None:
    pattern, error = compile_regex("error")
    assert error is None
    assert pattern.search("ERROR")

    _, error = compile_regex("[")
    assert error

    _, error = compile_regex("a" * (MAX_REGEX_QUERY_LENGTH + 1))
    assert error == "Regex query is too long."


def test_regex_match_ranges_ignore_zero_width_matches() -> None:
    assert regex_match_ranges("error ERROR", "error") == [(0, 5), (6, 11)]
    assert regex_match_ranges("text", "^") == []
    assert regex_match_ranges("text", "[") == []


def test_plain_text_match_ranges_escape_regex_characters() -> None:
    assert plain_text_match_ranges("Value [ABC] and [abc]", "[abc]") == [
        (6, 11),
        (16, 21),
    ]
    assert plain_text_match_ranges("text", "") == []


def test_detail_renderer_marks_errors_explicitly() -> None:
    renderer = DetailLineRenderer()
    assert renderer.render_line("failed", TabName.CONFIG, "", is_error=True) == [
        ("error", "failed")
    ]


def test_detail_renderer_highlights_plain_text_without_losing_text() -> None:
    markup = DetailLineRenderer().render_line("API_KEY=value", TabName.ENV, "key")

    assert flatten_markup_text(markup) == "API_KEY=value"
    assert ("highlight", "KEY") in markup


def test_detail_renderer_highlights_log_regex() -> None:
    markup = DetailLineRenderer().render_line("ERROR failed", TabName.LOGS, "err.*")

    assert flatten_markup_text(markup) == "ERROR failed"
    assert any(piece == ("highlight", "ERROR failed") for piece in markup)


def test_detail_formatter_delegates_filtering_and_rendering() -> None:
    formatter = DetailTabTextFormatter()

    assert formatter.prepare_visible_lines("A\nB", TabName.LOGS, "B") == ["B"]
    assert formatter.format_detail_line("A=1", TabName.ENV, "") == [
        ("accent", "A"),
        ("muted", "="),
        ("value", "1"),
    ]


def test_markup_helpers_split_and_merge_segments() -> None:
    assert markup_piece_attr_and_text("plain") == (None, "plain")
    assert markup_piece_attr_and_text(("value", "text")) == ("value", "text")

    markup_output = []
    append_markup_piece(markup_output, "value", "one")
    append_markup_piece(markup_output, "value", "two")
    append_markup_piece(markup_output, None, "plain")
    append_markup_piece(markup_output, None, "")
    assert markup_output == [("value", "onetwo"), "plain"]


def test_structured_text_markup_colors_environment_key_and_value() -> None:
    assert structured_text_markup("NAME=value=more", TabName.ENV) == [
        ("accent", "NAME"),
        ("muted", "="),
        ("value", "value=more"),
    ]


def test_log_markup_colors_common_log_tokens() -> None:
    markup = log_markup("2026-01-01T10:00:00Z INFO DEBUG WARNING ERROR GET /health 200")
    style_names = [piece[0] for piece in markup if isinstance(piece, tuple)]

    assert style_names == [
        "log_time",
        "log_info",
        "log_debug",
        "log_warning",
        "log_error",
        "log_http",
        "log_http",
        "log_number",
    ]


def test_token_markup_colors_structured_values() -> None:
    markup = token_markup('{"count": 2, "ready": true, "value": null}')
    style_names = [piece[0] for piece in markup if isinstance(piece, tuple)]

    assert "muted" in style_names
    assert "value" in style_names
    assert "log_number" in style_names
    assert "log_warning" in style_names
