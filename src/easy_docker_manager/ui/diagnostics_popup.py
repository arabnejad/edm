"""Build the read-only diagnostics popup."""

from __future__ import annotations

import urwid

from easy_docker_manager.diagnostics import DiagnosticsReport, format_diagnostics_report

KEYBOARD_HELP_DETAILS = """  Up/Down     Select a container or detail line
  Enter/Esc   Open details or return to the container list
  [ / ]       Switch detail tabs
  /           Search the active tab
  f / s / e   Filter containers, sort containers, or export a tab
  a           Open actions for the selected container
  p           Open settings
  q           Quit EDM"""


def build_diagnostics_popup(
    diagnostics_report: DiagnosticsReport,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the current diagnostics report above the main terminal layout."""
    report_text = format_diagnostics_report(
        diagnostics_report,
        include_heading=False,
    )
    popup_rows: list[urwid.Widget] = [
        urwid.Text(
            [
                ("status_ok", "Keyboard shortcuts"),
                "\n",
                KEYBOARD_HELP_DETAILS,
            ],
            wrap="clip",
        ),
        *_build_diagnostics_report_rows(report_text),
        urwid.AttrMap(urwid.Divider("─"), "title_border"),
        urwid.Text("Esc Close", wrap="clip"),
    ]
    popup_content = urwid.AttrMap(
        urwid.Filler(urwid.Pile(popup_rows), valign="top"),
        "diagnostics_popup",
    )
    popup = urwid.AttrMap(
        urwid.LineBox(
            popup_content,
            title="Help & Diagnostics",
            title_attr="app_title",
        ),
        "title_border",
    )
    return urwid.Overlay(
        popup,
        background_widget,
        align="center",
        width=88,
        valign="middle",
        height=28,
    )


def _build_diagnostics_report_rows(report_text: str) -> list[urwid.Widget]:
    """Build full-width section dividers and colored report rows."""
    report_rows: list[urwid.Widget] = []
    for line in report_text.splitlines():
        if ":" in line:
            label, value = line.split(":", 1)
            report_rows.append(
                urwid.Text(
                    [
                        f"{label}:",
                        ("diagnostics_value", value),
                    ],
                    wrap="any",
                )
            )
        elif line:
            report_rows.extend(
                [
                    urwid.AttrMap(urwid.Divider("─"), "title_border"),
                    urwid.Text(("host", line), wrap="clip"),
                ]
            )
    return report_rows


__all__ = ["build_diagnostics_popup"]
