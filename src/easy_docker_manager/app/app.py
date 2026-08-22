"""Run the Easy Docker Manager terminal application."""

from __future__ import annotations

import logging
from typing import Any, Optional

import urwid

from easy_docker_manager.app.background_notifier import (
    BackgroundNotifier,
    create_background_notifier,
)
from easy_docker_manager.app.background_task_result_handler import (
    BackgroundTaskResultHandler,
)
from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.core import AppConfig
from easy_docker_manager.docker.base import ContainerDataSource
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
        """Accept keys even when the displayed overlay contains only text."""
        return True

    def keypress(self, size: tuple[int, ...], key: str) -> Optional[str]:
        """Pass one Urwid keypress to EDMApp."""
        return self.app.handle_keyboard_input(key, size)


class EDMApp:
    """Run the terminal UI and coordinate the application.

    EDMApp handles keyboard input, processes completed background tasks, redraws
    the screen when data changes, and closes application resources during
    shutdown. The console entry point creates one EDMApp and calls run().
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        container_data_source: Optional[ContainerDataSource] = None,
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
        self._background_check_timer_handle: Optional[Any] = None

        selected_runtime_factory = (
            runtime_factory
            if runtime_factory is not None
            else EDMRuntimeFactory(
                app_config=app_config,
                container_data_source=container_data_source,
            )
        )
        runtime = selected_runtime_factory.create_runtime(
            self._notify_background_task_ready
        )

        # Keep the objects used to run background work, draw the terminal, and
        # close the Docker connection when EDM stops.
        self.container_data_source: ContainerDataSource = runtime.container_data_source
        self.task_runner = runtime.task_runner
        self.terminal_layout_view: TerminalLayoutView = runtime.terminal_layout_view
        self.layout = self.terminal_layout_view.layout

        # Keep the objects that schedule Docker requests, handle keyboard
        # actions, and apply results returned by background workers.
        self.scheduler: BackgroundTaskScheduler = runtime.scheduler
        self.ui_controller: UIController = runtime.ui_controller
        self.keyboard_controller: KeyboardController = runtime.keyboard_controller
        self.background_task_result_handler: BackgroundTaskResultHandler = (
            runtime.background_task_result_handler
        )

    def run(self) -> None:
        """Start the terminal UI, then close its resources when the UI stops."""
        logger.info("Starting EDM app")
        try:
            self.ui_event_loop = urwid.MainLoop(
                _KeyboardRoutingWidget(self),
                palette=self.terminal_layout_view.build_palette(),
                handle_mouse=False,
            )
            self.background_notifier.start(
                self.ui_event_loop,
                self._process_completed_background_tasks,
            )
            self.scheduler.schedule_container_refresh(force=True)
            self.ui_controller.render_current_state()
            self._schedule_next_background_check(delay=0)
            self.ui_event_loop.run()
        finally:
            self.background_notifier.stop()
            self.task_runner.shutdown(wait=True)
            self.container_data_source.close()
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
            self.ui_controller.render_current_state()
            self.scheduler.schedule_next_tasks()
            self._schedule_next_background_check()
        return None

    def _schedule_next_background_tasks(
        self,
        _loop: urwid.MainLoop,
        _data: Any = None,
    ) -> None:
        """Start due background work, then schedule the next check."""
        self._background_check_timer_handle = None
        self.scheduler.schedule_next_tasks()
        self._schedule_next_background_check()

    def _process_completed_background_tasks(self, _data: bytes) -> None:
        """Handle completed background tasks and redraw if the screen changed."""
        should_redraw = False
        for completed_task in self.task_runner.pop_all_completed_tasks():
            should_redraw = (
                self.background_task_result_handler.handle_completed_task(
                    completed_task
                )
                or should_redraw
            )
        self.scheduler.schedule_next_tasks()
        self._schedule_next_background_check()
        if should_redraw:
            self.ui_controller.render_current_state()

    def _schedule_next_background_check(self, delay: Optional[float] = None) -> None:
        """Set a timer for the next container, tab, or log update."""
        if self.ui_event_loop is None:
            return
        if self._background_check_timer_handle is not None:
            self.ui_event_loop.remove_alarm(self._background_check_timer_handle)
        next_delay = (
            self.scheduler.seconds_until_next_task_check() if delay is None else delay
        )
        self._background_check_timer_handle = self.ui_event_loop.set_alarm_in(
            next_delay,
            self._schedule_next_background_tasks,
        )

    def _notify_background_task_ready(self) -> None:
        """Tell the notifier that a worker result is ready for EDMApp."""
        self.background_notifier.notify()


__all__ = ["EDMApp"]
