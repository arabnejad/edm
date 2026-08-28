from __future__ import annotations

from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.ui.formatting import (
    DetailLineRenderer,
    DetailTabTextFormatter,
    append_markup_piece,
    format_log_line,
    format_structured_text_line,
    format_structured_tokens,
    markup_piece_attr_and_text,
    plain_text_match_ranges,
    regex_match_ranges,
)


def flatten_markup_text(markup) -> str:
    return "".join(piece[1] if isinstance(piece, tuple) else piece for piece in markup)


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


def test_detail_formatter_delegates_line_rendering() -> None:
    formatter = DetailTabTextFormatter()

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


def test_format_structured_text_line_colors_environment_key_and_value() -> None:
    assert format_structured_text_line("NAME=value=more", TabName.ENV) == [
        ("accent", "NAME"),
        ("muted", "="),
        ("value", "value=more"),
    ]


def test_format_structured_text_line_colors_stats_label_and_value() -> None:
    assert format_structured_text_line("  Usage           : 12.45%", TabName.STATS) == [
        ("accent", "  Usage           "),
        ("muted", ":"),
        ("value", " 12.45%"),
    ]


def test_format_log_line_colors_common_log_tokens() -> None:
    markup = format_log_line(
        "2026-01-01T10:00:00Z INFO DEBUG WARNING ERROR GET /health 200"
    )
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


def test_format_structured_tokens_colors_structured_values() -> None:
    markup = format_structured_tokens('{"count": 2, "ready": true, "value": null}')
    style_names = [piece[0] for piece in markup if isinstance(piece, tuple)]

    assert "muted" in style_names
    assert "value" in style_names
    assert "log_number" in style_names
    assert "log_warning" in style_names
