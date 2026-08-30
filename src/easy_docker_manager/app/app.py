"""Start, run, and stop the Easy Docker Manager terminal application."""

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
from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.ui.keyboard_controller import KeyAction, KeyboardController
from easy_docker_manager.ui.terminal_controller import TerminalController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView

logger = logging.getLogger(__name__)


class _KeyboardRoutingWidget(urwid.WidgetWrap):
    """Send every keypress to EDMApp, including keys pressed in a popup."""

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
    """Run EDM's terminal interface from startup through shutdown.

    The console entry point creates one EDMApp and calls run(). EDMApp starts
    Urwid, routes keyboard input, handles finished background work, redraws the
    screen when needed, and closes the worker pool and Docker connection before
    it exits.
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        docker_container_client: Optional[DockerContainerClient] = None,
        runtime_factory: Optional[EDMRuntimeFactory] = None,
        background_notifier: Optional[BackgroundNotifier] = None,
        app_config_store: Optional[AppConfigStore] = None,
    ) -> None:
        # Create the notifier first because the worker pool needs its callback.
        # The notifier is connected to Urwid later, after MainLoop is created.
        self.background_notifier = (
            background_notifier
            if background_notifier is not None
            else create_background_notifier()
        )
        self.urwid_main_loop: Optional[urwid.MainLoop] = None
        self._pending_docker_data_refresh_timer: Optional[Any] = None

        selected_runtime_factory = (
            runtime_factory
            if runtime_factory is not None
            else EDMRuntimeFactory(
                app_config=app_config,
                docker_container_client=docker_container_client,
                app_config_store=app_config_store,
            )
        )
        runtime = selected_runtime_factory.create_runtime(
            self._notify_background_task_ready
        )

        # EDMApp uses these objects directly while running and during shutdown.
        self.docker_container_client: DockerContainerClient = (
            runtime.docker_container_client
        )
        self.background_executor: BackgroundExecutor = runtime.background_executor
        self.terminal_layout_view: TerminalLayoutView = runtime.terminal_layout_view
        self.layout = self.terminal_layout_view.layout

        # DockerManager loads Docker data. The two controllers turn keyboard
        # input and session data into updates for the terminal screen.
        self.docker_manager: DockerManager = runtime.docker_manager
        self.terminal_controller: TerminalController = runtime.terminal_controller
        self.keyboard_controller: KeyboardController = runtime.keyboard_controller

    def run(self) -> None:
        """Open the terminal interface and clean up after it closes."""
        logger.info("Starting EDM app")
        try:
            self.urwid_main_loop = urwid.MainLoop(
                _KeyboardRoutingWidget(self),
                palette=self.terminal_layout_view.build_urwid_style_palette(),
                handle_mouse=False,
            )
            self.background_notifier.start(
                self.urwid_main_loop,
                self._process_completed_background_tasks,
            )
            self.docker_manager.start_running_container_list_refresh(force=True)
            self.terminal_controller.update_terminal_view()
            self._schedule_next_docker_data_refresh_check(delay=0)
            self.urwid_main_loop.run()
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
        """Process one keypress, then redraw or exit when the action requires it."""
        action = self.keyboard_controller.handle_keypress(key, terminal_size)
        if action == KeyAction.QUIT:
            raise urwid.ExitMainLoop()
        if action == KeyAction.REDRAW:
            self.terminal_controller.update_terminal_view()
            self.docker_manager.refresh_docker_data_if_needed()
            self._schedule_next_docker_data_refresh_check()
        return None

    def _run_scheduled_docker_data_refresh_check(
        self,
        _loop: urwid.MainLoop,
        _data: Any = None,
    ) -> None:
        """Check which Docker requests should start when the timer expires.

        Urwid calls this method after the timer created by
        _schedule_next_docker_data_refresh_check() expires. The timer has
        finished at that point, so this method clears its saved reference,
        starts any scheduled Docker work whose start time has arrived, and
        schedules the next check.

        At the end, this method starts a new timer. Urwid calls this method
        again only after that timer expires. The method does not call itself
        directly.
        """
        self._pending_docker_data_refresh_timer = None
        self.docker_manager.refresh_docker_data_if_needed()
        self._schedule_next_docker_data_refresh_check()

    def _process_completed_background_tasks(self, _data: bytes) -> None:
        """Apply finished worker results and redraw when they change the screen."""
        should_redraw = False
        for (
            completion_callback
        ) in self.background_executor.get_and_remove_all_ui_completion_callbacks():
            should_redraw = completion_callback() or should_redraw
        self.docker_manager.refresh_docker_data_if_needed()
        self._schedule_next_docker_data_refresh_check()
        if should_redraw:
            self.terminal_controller.update_terminal_view()

    def _schedule_next_docker_data_refresh_check(
        self,
        delay: Optional[float] = None,
    ) -> None:
        """Set one timer for the next Docker data refresh check.

        EDM calls this after startup, user input, completed worker tasks, and
        each timed check. It replaces the previous timer so only one check is
        pending. When delay is not provided, DockerManager returns the wait
        time for the next container refresh, tab refresh, or log poll.
        """
        if self.urwid_main_loop is None:
            return
        if self._pending_docker_data_refresh_timer is not None:
            self.urwid_main_loop.remove_alarm(self._pending_docker_data_refresh_timer)
        next_delay = (
            self.docker_manager.get_next_docker_data_refresh_delay()
            if delay is None
            else delay
        )
        # Pass the method itself, not the result of calling it. Urwid calls the
        # method after next_delay has passed.
        self._pending_docker_data_refresh_timer = self.urwid_main_loop.set_alarm_in(
            next_delay,
            self._run_scheduled_docker_data_refresh_check,
        )

    def _notify_background_task_ready(self) -> None:
        """Ask the notifier to wake EDMApp after a worker finishes."""
        self.background_notifier.notify()


__all__ = ["EDMApp"]
