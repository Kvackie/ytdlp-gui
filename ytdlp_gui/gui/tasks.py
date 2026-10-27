"""Run blocking work (network, subprocesses) on a background thread and report back on the GUI thread."""
from __future__ import annotations

import threading
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal

_alive: set[Task] = set()  # keeps running tasks referenced until they report back


class Task(QObject):
    """`fn(report, cancelled)` runs on a worker thread; its result or error arrives via signals.

    `report(text, done, total)` emits `progress`; `cancelled()` returns True once `cancel()` was called.
    """

    progress = Signal(str, int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, fn: Callable[[Callable[[str, int, int], None], Callable[[], bool]], object]):
        super().__init__()
        self._fn = fn
        self._cancel = threading.Event()

    def start(self) -> Task:
        # Connected last so callers' slots run before the task lets go of itself.
        for sig in (self.succeeded, self.failed):
            sig.connect(self._release, Qt.ConnectionType.QueuedConnection)
        _alive.add(self)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _run(self) -> None:
        try:
            result = self._fn(lambda text, done, total: self.progress.emit(text, done, total), self.cancelled)
        except Exception as exc:  # noqa: BLE001 - every failure is reported to the GUI
            traceback.print_exc()
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(result)

    def _release(self, *_):
        self.done.emit()
        _alive.discard(self)


def run_task(fn, on_success=None, on_failure=None, on_progress=None) -> Task:
    task = Task(fn)
    if on_success:
        task.succeeded.connect(on_success)
    if on_failure:
        task.failed.connect(on_failure)
    if on_progress:
        task.progress.connect(on_progress)
    return task.start()
