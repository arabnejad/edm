"""Build the read-only diagnostics popup."""

from __future__ import annotations

import urwid

from easy_docker_manager.diagnostics import (
    DiagnosticsReport,
    DiagnosticsReportSection,
    build_diagnostics_report_sections,
)

KEYBOARD_HELP_DETAILS = """  Up/Down     Select a container or detail line
  Enter/Esc   Open details or return to the container list
  [ / ]       Switch detail tabs
  /           Search the active tab
  f / s / e   Filter containers, set list options, or export a tab
  a           Open actions for the selected container
  c / p       Change Docker context or open settings
  q           Quit EDM"""


def build_diagnostics_popup(
    diagnostics_report: DiagnosticsReport,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the current diagnostics report above the main terminal layout."""
    diagnostics_report_sections = build_diagnostics_report_sections(diagnostics_report)
    popup_rows: list[urwid.Widget] = [
        urwid.Text(
            [
                ("status_ok", "Keyboard shortcuts"),
                "\n",
                KEYBOARD_HELP_DETAILS,
            ],
            wrap="clip",
        ),
        *_build_diagnostics_report_rows(diagnostics_report_sections),
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
        height=29,
    )


def _build_diagnostics_report_rows(
    diagnostics_report_sections: tuple[DiagnosticsReportSection, ...],
) -> list[urwid.Widget]:
    """Build full-width section dividers and colored report rows."""
    report_rows: list[urwid.Widget] = []
    for section in diagnostics_report_sections:
        report_rows.extend(
            [
                urwid.AttrMap(urwid.Divider("─"), "title_border"),
                urwid.Text(("host", section.title), wrap="clip"),
            ]
        )
        for field in section.fields:
            label_with_colon = f"{field.label}:"
            report_rows.append(
                urwid.Text(
                    [
                        f"  {label_with_colon:<22}",
                        ("diagnostics_value", field.value),
                    ],
                    wrap="any",
                )
            )
    return report_rows


__all__ = ["build_diagnostics_popup"]
