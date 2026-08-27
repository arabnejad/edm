"""Define the menu choices and file-write request used by tab exports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from easy_docker_manager.core.tabs import ContainerTabKey


class TabExportScope(str, Enum):
    """Choose which loaded tab text should be written to the export file."""

    CURRENT_VIEW = "Current view"
    FULL_TAB = "Full loaded tab"


class TabExportMenuField(str, Enum):
    """Name the fields that can be selected in the export menu."""

    FILE_PATH = "File"
    SCOPE = "Scope"


class TabExportPhase(str, Enum):
    """Describe what the export menu is currently waiting for.

    EDITING accepts changes to the file path and scope. WRITING blocks menu
    input while the background file write runs. CONFIRMING_OVERWRITE asks the
    user whether an existing file may be replaced.
    """

    EDITING = "editing"
    WRITING = "writing"
    CONFIRMING_OVERWRITE = "confirming_overwrite"


@dataclass
class TabExportMenuState:
    """Store the values currently shown in the tab export menu.

    TabExportController creates this when the user opens the menu. Keyboard
    input changes the path, selected field, and export scope. The terminal
    view reads the same object when drawing the popup.

    If the file already exists, phase changes to CONFIRMING_OVERWRITE until the
    user confirms or returns to editing.
    """

    container_tab_key: ContainerTabKey
    container_name: str
    file_path: str
    file_path_cursor_index: int
    scope: TabExportScope = TabExportScope.CURRENT_VIEW
    selected_field: TabExportMenuField = TabExportMenuField.FILE_PATH
    phase: TabExportPhase = TabExportPhase.EDITING
    error_message: str = ""


@dataclass(frozen=True)
class TabExportRequest:
    """Carry a fixed text snapshot to the background file writer.

    TabExportController creates this after the user confirms the export. The
    object is frozen so the path, text, and overwrite choice cannot change
    while the worker thread writes the file.
    """

    target_path: Path
    tab_text_snapshot: str
    allow_overwrite: bool = False


__all__ = [
    "TabExportMenuField",
    "TabExportPhase",
    "TabExportMenuState",
    "TabExportRequest",
    "TabExportScope",
]
