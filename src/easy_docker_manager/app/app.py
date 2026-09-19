"""Start, run, and stop the Easy Docker Manager terminal application."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import Future
from functools import partial
from typing import Any, Optional, cast

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
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.docker_connections import DockerContextDetails
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.container_shell_launcher import (
    ContainerShellLauncher,
)
from easy_docker_manager.ui.keyboard_controller import (
    KeyboardController,
    KeypressResult,
)
from easy_docker_manager.ui.terminal_controller import TerminalController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView

logger = logging.getLogger(__name__)

# urwid.Terminal expects an escape key name. This is not a real Urwid key, so
# every key pressed in the shell is sent to the container.
_DISABLED_SHELL_ESCAPE_SEQUENCE = "__edm_shell_escape_disabled__"


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
        container_shell_launcher: Optional[ContainerShellLauncher] = None,
        container_terminal_factory: Optional[Callable[..., urwid.Terminal]] = None,
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
        self.container_shell_launcher = (
            container_shell_launcher or ContainerShellLauncher()
        )
        self._container_terminal_factory = container_terminal_factory or urwid.Terminal
        self._shell_detection_future: Optional[Future[str]] = None
        self._active_shell_terminal: Optional[urwid.Terminal] = None
        self._active_shell_container: Optional[ContainerSummary] = None

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
            self._notify_background_task_ready,
            self._request_interactive_container_shell,
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
            self.docker_manager.start_container_list_refresh(force=True)
            self.terminal_controller.update_terminal_view()
            self._schedule_next_docker_data_refresh_check(delay=0)
            self.urwid_main_loop.run()
        finally:
            self._terminate_active_shell()
            self.background_notifier.stop()
            self.background_executor.shutdown(wait=True)
            self.docker_container_client.close()
            logger.info("Stopped EDM app")

    def handle_keyboard_input(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> Optional[str]:
        """Process one keypress, then redraw or exit when its result requires it."""
        if self._active_shell_terminal is not None:
            if terminal_size is None:
                return key
            return cast(
                Optional[str],
                self.layout.keypress(
                    cast(tuple[int, int], terminal_size),
                    key,
                ),
            )

        keypress_result = self.keyboard_controller.handle_keypress(key, terminal_size)
        if keypress_result == KeypressResult.QUIT:
            raise urwid.ExitMainLoop()
        if keypress_result == KeypressResult.REDRAW:
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

    def _request_interactive_container_shell(
        self,
        container: ContainerSummary,
    ) -> Optional[str]:
        """Find a supported shell without blocking the terminal interface."""
        if self.urwid_main_loop is None:
            return "Could not open the container shell before EDM started."
        if self._shell_detection_future is not None:
            return "EDM is already looking for a container shell."
        if self._active_shell_terminal is not None:
            return "Close the current container shell before opening another one."

        docker_context = self.terminal_controller.state.active_docker_context
        self.terminal_controller.state.status_message = (
            f'Looking for a shell in container "{container.name}"...'
        )
        self._shell_detection_future = self.background_executor.submit(
            self.container_shell_launcher.find_available_shell_executable,
            container.container_id,
            docker_context,
            on_complete=partial(
                self._handle_detected_container_shell,
                container,
                docker_context,
            ),
        )
        return None

    def _handle_detected_container_shell(
        self,
        container: ContainerSummary,
        docker_context: DockerContextDetails,
        shell_detection_future: Future[str],
    ) -> bool:
        """Open the shell workspace after the background check finishes."""
        if shell_detection_future is not self._shell_detection_future:
            return False
        self._shell_detection_future = None

        try:
            shell_executable = shell_detection_future.result()
        except Exception as exc:
            logger.exception(
                "Could not find a shell in container %s",
                container.container_id,
            )
            self.terminal_controller.state.status_message = (
                f'Could not open shell for container "{container.name}": {exc}'
            )
            return True

        if docker_context != self.terminal_controller.state.active_docker_context:
            self.terminal_controller.state.status_message = (
                "The Docker connection changed before the shell could open."
            )
            return True

        if os.name == "nt":
            self._open_shell_using_current_terminal(
                container,
                shell_executable,
                docker_context,
            )
            return True

        try:
            command = self.container_shell_launcher.build_interactive_shell_command(
                container.container_id,
                shell_executable,
                docker_context,
            )
            terminal = self._container_terminal_factory(
                command,
                main_loop=self.urwid_main_loop,
                escape_sequence=_DISABLED_SHELL_ESCAPE_SEQUENCE,
            )
            # The shell owns keyboard input until its process exits.
            terminal.keygrab = True
            urwid.connect_signal(
                terminal,
                "closed",
                self._handle_container_shell_closed,
            )
        except Exception as exc:
            logger.exception(
                "Could not create a shell workspace for container %s",
                container.container_id,
            )
            self.terminal_controller.state.status_message = (
                f'Could not open shell for container "{container.name}": {exc}'
            )
            return True

        self._active_shell_terminal = terminal
        self._active_shell_container = container
        self.terminal_layout_view.show_container_shell(
            terminal,
            container.name,
            shell_executable,
        )
        return True

    def _open_shell_using_current_terminal(
        self,
        container: ContainerSummary,
        shell_executable: str,
        docker_context: DockerContextDetails,
    ) -> None:
        """Use the old terminal handoff on systems without Urwid's PTY widget."""
        if self.urwid_main_loop is None:
            return

        screen = self.urwid_main_loop.screen
        exit_code: Optional[int] = None
        screen.stop()
        try:
            exit_code = self.container_shell_launcher.open_shell(
                container.container_id,
                shell_executable,
                docker_context,
            )
        except Exception as exc:
            logger.exception(
                "Could not open a shell in container %s",
                container.container_id,
            )
            self.terminal_controller.state.status_message = (
                f'Could not open shell for container "{container.name}": {exc}'
            )
        finally:
            screen.start()
            screen.clear()

        if exit_code is not None and exit_code != 0:
            self.terminal_controller.state.status_message = (
                f'Shell for container "{container.name}" exited with status '
                f"{exit_code}."
            )
        elif exit_code is not None:
            self.terminal_controller.state.status_message = (
                f'Shell for container "{container.name}" closed.'
            )
        self.docker_manager.refresh_after_interactive_shell(container.container_id)

    def _handle_container_shell_closed(self, _terminal: urwid.Terminal) -> None:
        """Return to the container view when the shell process exits."""
        self._finish_interactive_container_shell()

    def _finish_interactive_container_shell(self) -> None:
        """Restore the container view and reload data changed by the shell."""
        container = self._active_shell_container
        if self._active_shell_terminal is None or container is None:
            return

        self._active_shell_terminal = None
        self._active_shell_container = None
        self.terminal_layout_view.show_main_workspace()
        self.terminal_controller.state.status_message = (
            f'Shell for container "{container.name}" closed.'
        )
        self.docker_manager.refresh_after_interactive_shell(container.container_id)
        self.terminal_controller.update_terminal_view()

    def _terminate_active_shell(self) -> None:
        """Stop a shell process that is still open while EDM shuts down."""
        terminal = self._active_shell_terminal
        self._active_shell_terminal = None
        self._active_shell_container = None
        if terminal is not None and terminal.pid is not None:
            terminal.terminate()


__all__ = ["EDMApp"]
