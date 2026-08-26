"""Run the Easy Docker Manager terminal application."""

from __future__ import annotations

import logging
from typing import Any, Optional

import urwid

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.background_notifier import (
    BackgroundNotifier,
    create_background_notifier,
)
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.core import AppConfig
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.ui.keyboard_controller import KeyAction, KeyboardController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView
from easy_docker_manager.ui.ui_controller import UIController

logger = logging.getLogger(__name__)


class _KeyboardRoutingWidget(urwid.WidgetWrap):
    """Keep keyboard input routed to EDMApp for every displayed screen."""

    def __init__(self, app: EDMApp) -> None:
        """Wrap the main layout so EDMApp can handle every keypress."""
        self.app = app
        super().__init__(app.layout)

    def selectable(self) -> bool:
        """Accept keys even when the displayed popup contains only text."""
        return True

    def keypress(self, size: tuple[int, ...], key: str) -> Optional[str]:
        """Pass one Urwid keypress to EDMApp."""
        return self.app.handle_keyboard_input(key, size)


class EDMApp:
    """Run the terminal UI and manage the application lifecycle.

    EDMApp handles keyboard input, processes completed background tasks, redraws
    the screen when data changes, and closes application resources during
    shutdown. The console entry point creates one EDMApp and calls run().
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        docker_container_client: Optional[DockerContainerClient] = None,
        runtime_factory: Optional[EDMRuntimeFactory] = None,
        background_notifier: Optional[BackgroundNotifier] = None,
    ) -> None:
        # Workers need a way to wake EDMApp before the Urwid loop exists. The
        # notifier uses a pipe on Unix-like systems and polling on Windows.
        self.background_notifier = (
            background_notifier
            if background_notifier is not None
            else create_background_notifier()
        )
        self.ui_event_loop: Optional[urwid.MainLoop] = None
        self._pending_docker_data_refresh_timer: Optional[Any] = None

        selected_runtime_factory = (
            runtime_factory
            if runtime_factory is not None
            else EDMRuntimeFactory(
                app_config=app_config,
                docker_container_client=docker_container_client,
            )
        )
        runtime = selected_runtime_factory.create_runtime(
            self._notify_background_task_ready
        )

        # Keep the objects used to run background work, draw the terminal, and
        # close the Docker connection when EDM stops.
        self.docker_container_client: DockerContainerClient = (
            runtime.docker_container_client
        )
        self.background_executor: BackgroundExecutor = runtime.background_executor
        self.terminal_layout_view: TerminalLayoutView = runtime.terminal_layout_view
        self.layout = self.terminal_layout_view.layout

        # DockerManager loads Docker data and saves finished results in the
        # session state.
        # The keyboard controller handles user input, and the UI controller
        # prepares the current state for the terminal view.
        self.docker_manager: DockerManager = runtime.docker_manager
        self.ui_controller: UIController = runtime.ui_controller
        self.keyboard_controller: KeyboardController = runtime.keyboard_controller

    def run(self) -> None:
        """Start the terminal UI, then close its resources when the UI stops."""
        logger.info("Starting EDM app")
        try:
            self.ui_event_loop = urwid.MainLoop(
                _KeyboardRoutingWidget(self),
                palette=self.terminal_layout_view.build_urwid_style_palette(),
                handle_mouse=False,
            )
            self.background_notifier.start(
                self.ui_event_loop,
                self._process_completed_background_tasks,
            )
            self.docker_manager.start_running_container_list_refresh(force=True)
            self.ui_controller.update_terminal_view()
            self._schedule_next_docker_data_refresh_check(delay=0)
            self.ui_event_loop.run()
        finally:
            self.background_notifier.stop()
            self.background_executor.shutdown(wait=True)
            self.docker_container_client.close()
            logger.info("Stopped EDM app")

    def handle_keyboard_input(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> Optional[str]:
        """Handle one keypress, redraw when needed, or exit on Quit."""
        action = self.keyboard_controller.handle_keypress(key, terminal_size)
        if action == KeyAction.QUIT:
            raise urwid.ExitMainLoop()
        if action == KeyAction.RENDER:
            self.ui_controller.update_terminal_view()
            self.docker_manager.refresh_docker_data_if_needed()
            self._schedule_next_docker_data_refresh_check()
        return None

    def _run_scheduled_docker_data_refresh_check(
        self,
        _loop: urwid.MainLoop,
        _data: Any = None,
    ) -> None:
        """Run the Docker refresh check requested by the previous timer.

        Urwid calls this method after the timer created by
        _schedule_next_docker_data_refresh_check() expires. The timer has
        finished at that point, so this method clears its saved reference,
        starts any Docker refresh work that is now due, and schedules the next
        check.

        The next check runs later through Urwid's event loop. Calling the
        scheduling method here therefore creates a repeating timer, not a
        recursive function call.
        """
        self._pending_docker_data_refresh_timer = None
        self.docker_manager.refresh_docker_data_if_needed()
        self._schedule_next_docker_data_refresh_check()

    def _process_completed_background_tasks(self, _data: bytes) -> None:
        """Handle completed background tasks and redraw if the screen changed."""
        should_redraw = False
        for (
            completion_callback
        ) in self.background_executor.get_and_remove_all_ui_completion_callbacks():
            should_redraw = completion_callback() or should_redraw
        self.docker_manager.refresh_docker_data_if_needed()
        self._schedule_next_docker_data_refresh_check()
        if should_redraw:
            self.ui_controller.update_terminal_view()

    def _schedule_next_docker_data_refresh_check(
        self,
        delay: Optional[float] = None,
    ) -> None:
        """Set a timer for the next check for Docker data that needs updating.

        EDM calls this after startup, user input, completed background work,
        and each scheduled refresh check. An existing timer is replaced so
        only one refresh check is waiting at a time. When delay is not given,
        DockerManager calculates how long EDM should wait.
        """
        if self.ui_event_loop is None:
            return
        if self._pending_docker_data_refresh_timer is not None:
            self.ui_event_loop.remove_alarm(self._pending_docker_data_refresh_timer)
        next_delay = (
            self.docker_manager.get_next_docker_data_refresh_delay()
            if delay is None
            else delay
        )
        # Pass the method without parentheses. Urwid stores this function
        # reference and calls it after next_delay instead of calling it now.
        self._pending_docker_data_refresh_timer = self.ui_event_loop.set_alarm_in(
            next_delay,
            self._run_scheduled_docker_data_refresh_check,
        )

    def _notify_background_task_ready(self) -> None:
        """Tell the notifier that a worker result is ready for EDMApp."""
        self.background_notifier.notify()


__all__ = ["EDMApp"]
