"""Manage the tab export menu and its background file write."""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.tab_export.definitions import (
    TabExportMenuField,
    TabExportMenuState,
    TabExportPhase,
    TabExportRequest,
    TabExportScope,
)
from easy_docker_manager.tab_export.writer import (
    ExportTargetExistsError,
    TabExportError,
    TabExportWriter,
)
from easy_docker_manager.tabs.tab_text_filter import TabTextFilter

logger = logging.getLogger(__name__)


class TabExportController:
    """Handle the complete export workflow for the active container tab.

    KeyboardController calls this object to open the export menu and passes all
    menu keypresses to handle_menu_keypress(). This controller edits the menu,
    copies the requested text from the existing tab cache, and sends only the
    file write to BackgroundExecutor. It updates the menu on the UI thread when
    writing finishes.

    Exporting never starts a new Docker request. It saves the content already
    loaded for the selected container and tab.
    """

    EXPORT_FIELDS = tuple(TabExportMenuField)
    MAX_EXPORT_PATH_CHARACTERS = 4096

    def __init__(
        self,
        state: TerminalSessionState,
        tab_text_filter: TabTextFilter,
        background_executor: BackgroundExecutor,
        tab_export_writer: TabExportWriter,
        launch_directory: Path,
    ) -> None:
        self.state = state
        self.tab_text_filter = tab_text_filter
        self.background_executor = background_executor
        self.tab_export_writer = tab_export_writer
        self.launch_directory = launch_directory.resolve()
        self._active_export_future: Optional[Future[Path]] = None

    def open_tab_export_menu(self) -> bool:
        """Open the export menu for the selected container and active tab.

        KeyboardController calls this when the user presses e in the details
        panel. The menu opens only after the active tab has loaded. Its default
        path starts in the directory where EDM was launched.
        """
        if self.state.tab_export_menu_state is not None:
            return False

        container_tab_key = self.state.selected_container_tab_key
        selected_container = self.state.selected_container_summary
        if container_tab_key is None or selected_container is None:
            self.state.status_message = "Select a container before exporting."
            return True
        if container_tab_key not in self.state.tab_content_cache:
            self.state.status_message = (
                f"Wait for {container_tab_key.tab_name.value} to finish loading "
                "before exporting."
            )
            return True

        file_name = self._build_default_export_file_name(
            selected_container.name,
            container_tab_key.tab_name,
        )
        file_path = str(self.launch_directory / file_name)
        self.state.container_sort_menu_state = None
        self.state.tab_export_menu_state = TabExportMenuState(
            container_tab_key=container_tab_key,
            container_name=selected_container.name,
            file_path=file_path,
            path_cursor_index=len(file_path),
        )
        return True

    def handle_menu_keypress(self, key: str) -> bool:
        """Handle one key while the export menu is open.

        KeyboardController delegates every export-menu keypress here. The
        current menu phase decides whether the key edits the form, answers the
        overwrite question, or is ignored while the file is being written.
        The return value tells EDM whether the visible menu changed.
        """
        menu_state = self.state.tab_export_menu_state
        if menu_state is None or menu_state.phase == TabExportPhase.WRITING:
            return False

        if menu_state.phase == TabExportPhase.CONFIRMING_OVERWRITE:
            if key == "enter":
                return self._submit_tab_export(overwrite=True)
            if key == "esc":
                return self._cancel_export_file_overwrite_confirmation()
            return False

        if key == "esc":
            return self._close_tab_export_menu()
        if key == "enter":
            return self._submit_tab_export()
        if key == "up":
            return self._change_selected_export_field(-1)
        if key in {"down", "tab"}:
            return self._change_selected_export_field(1)
        if menu_state.selected_field == TabExportMenuField.SCOPE:
            if key in {"left", "right", " "}:
                return self._toggle_tab_export_scope()
            return False
        return self._edit_tab_export_path(key)

    def _close_tab_export_menu(self) -> bool:
        """Close the export menu without writing a file."""
        menu_state = self.state.tab_export_menu_state
        if menu_state is None or menu_state.phase == TabExportPhase.WRITING:
            return False
        self.state.tab_export_menu_state = None
        return True

    def _cancel_export_file_overwrite_confirmation(self) -> bool:
        """Return from the overwrite question to the editable export menu."""
        menu_state = self.state.tab_export_menu_state
        if (
            menu_state is None
            or menu_state.phase != TabExportPhase.CONFIRMING_OVERWRITE
        ):
            return False
        menu_state.phase = TabExportPhase.EDITING
        return True

    def _change_selected_export_field(self, field_offset: int) -> bool:
        """Move the selection between the File and Scope fields.

        handle_menu_keypress() passes -1 for Up and 1 for Down or Tab.
        Selection stops at the first and last fields instead of wrapping.
        """
        menu_state = self.state.tab_export_menu_state
        if menu_state is None or not self._menu_fields_can_be_edited(menu_state):
            return False

        previous_field = menu_state.selected_field
        previous_index = self.EXPORT_FIELDS.index(previous_field)
        selected_index = max(
            0,
            min(len(self.EXPORT_FIELDS) - 1, previous_index + field_offset),
        )
        menu_state.selected_field = self.EXPORT_FIELDS[selected_index]
        return menu_state.selected_field != previous_field

    def _toggle_tab_export_scope(self) -> bool:
        """Switch between the current view and all loaded tab content.

        Current view applies the active Logs regex. Searches on Env, Config,
        and Top only highlight text, so those tabs keep all loaded lines in
        either scope.
        """
        menu_state = self.state.tab_export_menu_state
        if (
            menu_state is None
            or menu_state.selected_field != TabExportMenuField.SCOPE
            or not self._menu_fields_can_be_edited(menu_state)
        ):
            return False
        menu_state.scope = (
            TabExportScope.FULL_TAB
            if menu_state.scope == TabExportScope.CURRENT_VIEW
            else TabExportScope.CURRENT_VIEW
        )
        return True

    def _edit_tab_export_path(self, key: str) -> bool:
        """Apply one cursor, deletion, or printable key to the File field.

        Printable keys include q and Q while the File field is selected. They
        edit the path instead of activating normal EDM shortcuts.
        """
        menu_state = self.state.tab_export_menu_state
        if (
            menu_state is None
            or menu_state.selected_field != TabExportMenuField.FILE_PATH
            or not self._menu_fields_can_be_edited(menu_state)
        ):
            return False

        cursor_index = menu_state.path_cursor_index
        if key == "left":
            menu_state.path_cursor_index = max(0, cursor_index - 1)
        elif key == "right":
            menu_state.path_cursor_index = min(
                len(menu_state.file_path), cursor_index + 1
            )
        elif key == "home":
            menu_state.path_cursor_index = 0
        elif key == "end":
            menu_state.path_cursor_index = len(menu_state.file_path)
        elif key == "backspace":
            if cursor_index == 0:
                return False
            menu_state.file_path = (
                menu_state.file_path[: cursor_index - 1]
                + menu_state.file_path[cursor_index:]
            )
            menu_state.path_cursor_index -= 1
        elif key == "delete":
            if cursor_index >= len(menu_state.file_path):
                return False
            menu_state.file_path = (
                menu_state.file_path[:cursor_index]
                + menu_state.file_path[cursor_index + 1 :]
            )
        elif len(key) == 1 and key.isprintable():
            if len(menu_state.file_path) >= self.MAX_EXPORT_PATH_CHARACTERS:
                menu_state.error_message = (
                    "File path cannot exceed "
                    f"{self.MAX_EXPORT_PATH_CHARACTERS} characters."
                )
                return True
            menu_state.file_path = (
                menu_state.file_path[:cursor_index]
                + key
                + menu_state.file_path[cursor_index:]
            )
            menu_state.path_cursor_index += 1
        else:
            return False

        menu_state.error_message = ""
        return True

    def _submit_tab_export(self, *, overwrite: bool = False) -> bool:
        """Validate the menu and start its file write in a worker thread.

        handle_menu_keypress() calls this for Enter. After an existing file is
        found, it calls the method again with overwrite=True when the user
        confirms replacement. The exported text is copied from the cache before
        the worker starts, so later tab updates cannot change the file.
        """
        menu_state = self.state.tab_export_menu_state
        if menu_state is None or menu_state.phase == TabExportPhase.WRITING:
            return False

        raw_file_path = menu_state.file_path.strip()
        if not raw_file_path:
            menu_state.error_message = "Enter a file path before exporting."
            return True

        try:
            target_path = Path(raw_file_path).expanduser()
            if not target_path.is_absolute():
                target_path = self.launch_directory / target_path
            target_path = target_path.resolve()
        except (OSError, RuntimeError) as exc:
            menu_state.error_message = f"Invalid export path: {exc}"
            return True

        full_content = self.state.tab_content_cache.get(menu_state.container_tab_key)
        if full_content is None:
            menu_state.error_message = (
                "This tab is no longer loaded. Close the menu and try again."
            )
            return True
        if self._active_export_future is not None:
            menu_state.error_message = (
                "Another export is still running. Try again shortly."
            )
            return True

        export_content = self._prepare_tab_export_content(menu_state, full_content)
        request = TabExportRequest(
            target_path=target_path,
            content=export_content,
            overwrite=overwrite,
        )

        menu_state.file_path = str(target_path)
        menu_state.path_cursor_index = len(menu_state.file_path)
        menu_state.error_message = ""
        menu_state.phase = TabExportPhase.WRITING
        self.state.status_message = (
            f"Exporting {menu_state.container_tab_key.tab_name.value}..."
        )

        try:
            self._active_export_future = self.background_executor.submit(
                self.tab_export_writer.export_text,
                request,
                on_complete=partial(
                    self._apply_tab_export_result,
                    menu_state.container_tab_key,
                    target_path,
                ),
            )
        except RuntimeError as exc:
            menu_state.phase = TabExportPhase.EDITING
            menu_state.error_message = str(exc)
            self.state.status_message = f"Export failed: {exc}"
        return True

    @staticmethod
    def _menu_fields_can_be_edited(menu_state: TabExportMenuState) -> bool:
        """Return whether the normal File and Scope fields accept input."""
        return menu_state.phase == TabExportPhase.EDITING

    @staticmethod
    def _build_default_export_file_name(
        container_name: str,
        tab_name: TabName,
    ) -> str:
        """Build a portable, timestamped file name for a new export menu."""
        safe_container_name = re.sub(r"[^A-Za-z0-9._-]+", "_", container_name)
        safe_container_name = safe_container_name.strip("._-") or "container"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        extension = ".log" if tab_name == TabName.LOGS else ".txt"
        return f"{safe_container_name}-{tab_name.value.lower()}-{timestamp}{extension}"

    def _prepare_tab_export_content(
        self,
        menu_state: TabExportMenuState,
        full_content: str,
    ) -> str:
        """Return the cached text snapshot selected by the export scope."""
        if menu_state.scope == TabExportScope.FULL_TAB:
            return full_content

        query = self.state.tab_search_queries.get(menu_state.container_tab_key, "")
        visible_lines = self.tab_text_filter.get_visible_lines(
            full_content,
            menu_state.container_tab_key.tab_name,
            query,
        )
        return "\n".join(visible_lines)

    def _apply_tab_export_result(
        self,
        container_tab_key: ContainerTabKey,
        target_path: Path,
        export_future: Future[Path],
    ) -> bool:
        """Update the export menu after its background file write finishes.

        BackgroundExecutor calls this on the UI thread. Success closes the
        matching menu. An existing file asks for confirmation. Other errors
        leave the menu open so its path can be corrected and submitted again.
        """
        if export_future is not self._active_export_future:
            return False
        self._active_export_future = None

        menu_state = self.state.tab_export_menu_state
        is_matching_menu = (
            menu_state is not None
            and menu_state.container_tab_key == container_tab_key
            and Path(menu_state.file_path) == target_path
        )

        try:
            saved_path = export_future.result()
        except ExportTargetExistsError as exc:
            if is_matching_menu and menu_state is not None:
                menu_state.phase = TabExportPhase.CONFIRMING_OVERWRITE
                menu_state.error_message = ""
            self.state.status_message = f"File already exists: {exc.target_path}"
            return True
        except TabExportError as exc:
            logger.warning("Tab export failed for %s: %s", exc.target_path, exc)
            if is_matching_menu and menu_state is not None:
                menu_state.phase = TabExportPhase.EDITING
                menu_state.error_message = str(exc)
            self.state.status_message = f"Export failed: {exc}"
            return True
        except Exception as exc:
            logger.warning("Tab export failed: %s", exc)
            if is_matching_menu and menu_state is not None:
                menu_state.phase = TabExportPhase.EDITING
                menu_state.error_message = str(exc)
            self.state.status_message = f"Export failed: {exc}"
            return True

        if is_matching_menu:
            self.state.tab_export_menu_state = None
        self.state.status_message = f"Exported to {saved_path}"
        return True


__all__ = ["TabExportController"]
