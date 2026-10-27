"""Checks for and installs new versions of the managed tools, without disturbing running downloads."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from ..components import Components, Release
from ..settings import Settings
from .queue import QueueManager
from .tasks import Task, run_task

AUTO_UPDATE_KEYS = ("yt-dlp", "deno")  # FFmpeg is big and rarely matters, so it is only offered


class UpdateService(QObject):
    checked = Signal()
    check_started = Signal()
    progress = Signal(str, str, int, int)  # component key, phase, done, total
    installed = Signal(str, bool)  # component key, was an automatic update
    install_failed = Signal(str, str)
    busy_changed = Signal()

    def __init__(self, components: Components, settings: Settings, queue: QueueManager):
        super().__init__()
        self.components = components
        self.settings = settings
        self.queue = queue
        self.latest: dict[str, Release] = {}
        self.errors: dict[str, str] = {}
        self.checking = False
        self._installing: dict[str, Task] = {}
        self._auto: set[str] = set()
        self._pending: list[str] = []
        queue.activity_changed.connect(self._run_pending)

    # --- state -----------------------------------------------------------------------------------
    def installing(self, key: str | None = None) -> bool:
        return bool(self._installing) if key is None else key in self._installing

    def update_available(self, key: str) -> bool:
        release = self.latest.get(key)
        return release is not None and self.components.get(key).update_available(release)

    def updates_available(self) -> list[str]:
        return [c.key for c in self.components.all() if self.update_available(c.key)]

    def set_channel(self, channel: str) -> None:
        if channel != self.components.ytdlp.channel:
            self.components.ytdlp.channel = channel
            self.latest.pop("yt-dlp", None)

    # --- checking --------------------------------------------------------------------------------
    def check(self, auto: bool = False) -> None:
        if self.checking:
            return
        self.checking = True
        self.check_started.emit()
        components = [c for c in self.components.all() if c.supported()]

        def work(_report, _cancelled):
            found, errors = {}, {}
            for comp in components:
                try:
                    found[comp.key] = comp.latest()
                except Exception as exc:  # noqa: BLE001 - shown per component
                    errors[comp.key] = str(exc) or type(exc).__name__
            return found, errors

        run_task(work, lambda result: self._on_checked(result, auto),
                 lambda err: self._on_checked(({}, {"*": err}), auto))

    def _on_checked(self, result, auto: bool) -> None:
        found, errors = result
        self.checking = False
        self.latest.update(found)
        self.errors = errors
        if found:
            self.settings.last_update_check = time.time()
        if auto and self.settings.auto_update:
            for key in AUTO_UPDATE_KEYS:
                if self.update_available(key):
                    self.install_when_idle(key)
        self.checked.emit()

    # --- installing ------------------------------------------------------------------------------
    def install_when_idle(self, key: str) -> None:
        """Install as soon as no download is running (yt-dlp can't be replaced while in use on Windows)."""
        self._auto.add(key)
        if key not in self._pending:
            self._pending.append(key)
        self._run_pending()

    def _run_pending(self) -> None:
        while self._pending and self.queue.running == 0:
            key = self._pending.pop(0)
            if not self.installing(key):
                self.install(key)

    def install(self, key: str) -> bool:
        """Download and install the latest build of a component. False if downloads are running."""
        if self.installing(key):
            return True
        if self.queue.running:
            return False
        comp = self.components.get(key)

        def work(report, cancelled):
            release = comp.latest()
            comp.install(release, report, cancelled)
            return release

        task = Task(work)
        task.progress.connect(lambda text, done, total: self.progress.emit(key, text, done, total))
        task.succeeded.connect(lambda release: self._on_installed(key, release))
        task.failed.connect(lambda err: self._on_install_failed(key, err))
        self._installing[key] = task
        self.queue.set_blocked(True)
        self.busy_changed.emit()
        task.start()
        return True

    def cancel_install(self, key: str) -> None:
        task = self._installing.get(key)
        if task:
            task.cancel()

    def _finish(self, key: str) -> bool:
        self._installing.pop(key, None)
        auto = key in self._auto
        self._auto.discard(key)
        if not self._installing:
            self.queue.set_blocked(False)
        self.busy_changed.emit()
        return auto

    def _on_installed(self, key: str, release: Release) -> None:
        self.latest[key] = release
        self.errors.pop(key, None)
        auto = self._finish(key)
        self.installed.emit(key, auto)

    def _on_install_failed(self, key: str, error: str) -> None:
        self._finish(key)
        if error == "Cancelled":
            error = "Cancelled."
        self.install_failed.emit(key, error)

    def remove(self, key: str) -> bool:
        if self.queue.running or self.installing(key):
            return False
        self.components.get(key).remove()
        self.busy_changed.emit()
        return True
